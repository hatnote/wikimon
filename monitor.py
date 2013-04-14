# some code from Twisted Matrix's irc_test.py
from twisted.words.protocols import irc
from twisted.internet import reactor, protocol

from twisted.web.server import Site
from twisted.web.static import File

from autobahn.websocket import WebSocketServerFactory, \
                               WebSocketServerProtocol, \
                               listenWS
import time, sys, re, datetime
from json import dumps
CHANNEL = 'en.wikipedia'  # use language.project
NAME_RE = re.compile('\[\[(.*?)\]\]')
URL_RE = re.compile(' http(.*?) ')
SUM_RE = re.compile('\([\-\+][0-9]+\) (.*)')
USER_RE = re.compile('\* (.*?) \*')
SIZE_RE = re.compile('\* \(([-\+]+)([0-9]+)\) ')
REV_RE = re.compile('oldid=([0-9]+)')
NEW_RE = re.compile('\] (N)')

def process_message(message):
    color_re = re.compile("\x03(?:\d{1,2}(?:,\d{1,2})?)?",
                          re.UNICODE)  # remove IRC color codes
    return color_re.sub('', message)


def split_chat(chat):
    ret = {}
    try:
        ret['summary'] = SUM_RE.search(chat).group(1)
    except:
        pass
    try:
        ret['url'] = URL_RE.search(chat).group(1)
    except:
        pass
    try:
        ret['name'] = NAME_RE.search(chat).group(1)
    except:
        pass
    try:
        ret['user'] = USER_RE.search(chat).group(1)
    except:
        pass
    try:
        ret['revid'] = REV_RE.search(chat).group(1)
    except:
        pass
    try:
        ret['size'] = SIZE_RE.search(chat).group(2)
        ret['action'] = SIZE_RE.search(chat).group(1)
    except:
        pass
    try:
        new = NEW_RE.search(chat).group(1)
        if new == 'N':
            ret['new'] = True
        else:
            ret['new'] = False
    except:
        ret['new'] = False
    return ret


class Monitor(irc.IRCClient):
    def __init__(self, bsf):
        self.broadcaster = bsf
        print 'created'

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        print 'connected'

    def signedOn(self):
        self.join(self.factory.channel)
        print 'joined'

    def privmsg(self, user, channel, msg):
        m = process_message(msg)
        m = split_chat(m)
        if m.get('name') and not m['name'].startswith('Talk:') and not m['name'].startswith('User:') and not m['name'].startswith('Wikipedia:') and not m['name'].startswith('Wikipedia talk:') and not m['name'].startswith('User talk:') and not m['name'].startswith('Template:') and not m['name'].startswith('Template talk:'):
            self.broadcaster.broadcast(dumps(m))


class MonitorFactory(protocol.ClientFactory):
    def __init__(self, channel, bsf):
        self.channel = channel
        self.bsf = bsf

    def buildProtocol(self, addr):
        p = Monitor(self.bsf)
        p.factory = self
        return p


class BroadcastServerProtocol(WebSocketServerProtocol):

   def onOpen(self):
      self.factory.register(self)

   def onMessage(self, msg, binary):
      if not binary:
         self.factory.broadcast("'%s' from %s" % (msg, self.peerstr))

   def connectionLost(self, reason):
      WebSocketServerProtocol.connectionLost(self, reason)
      self.factory.unregister(self)


class BroadcastServerFactory(WebSocketServerFactory):
   """
   Simple broadcast server broadcasting any message it receives to all
   currently connected clients.
   """

   def __init__(self, url, debug = False, debugCodePaths = False):
      WebSocketServerFactory.__init__(self, url, debug = debug, debugCodePaths = debugCodePaths)
      self.clients = []
      self.tickcount = 0
      start_monitor(self)

   def tick(self):
      self.tickcount += 1
      self.broadcast("'tick %d' from server" % self.tickcount)
      reactor.callLater(1, self.tick)

   def register(self, client):
      if not client in self.clients:
         print "registered client " + client.peerstr
         self.clients.append(client)

   def unregister(self, client):
      if client in self.clients:
         print "unregistered client " + client.peerstr
         self.clients.remove(client)

   def broadcast(self, msg):
      print "broadcasting message '%s' .." % msg
      for c in self.clients:
         c.sendMessage(msg)
         print "message sent to " + c.peerstr


class BroadcastPreparedServerFactory(BroadcastServerFactory):
   """
   Functionally same as above, but optimized broadcast using
   prepareMessage and sendPreparedMessage.
   """

   def broadcast(self, msg):
      print "broadcasting prepared message '%s' .." % msg
      preparedMsg = self.prepareMessage(msg)
      for c in self.clients:
         c.sendPreparedMessage(preparedMsg)
         print "prepared message sent to " + c.peerstr


def start_monitor(bsf):
    f = MonitorFactory(CHANNEL, bsf)
    reactor.connectTCP("irc.wikimedia.org", 6667, f)


if __name__ == '__main__':
    debug = False
    # start_monitor()
    ServerFactory = BroadcastServerFactory
    factory = ServerFactory("ws://localhost:9000",
                           debug = debug,
                           debugCodePaths = debug)

    factory.protocol = BroadcastServerProtocol
    factory.setProtocolOptions(allowHixie76 = True)
    listenWS(factory)
    reactor.run()
