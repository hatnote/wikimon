# some code from Twisted Matrix's irc_test.py
from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
from autobahn.websocket import (WebSocketServerFactory,
                                WebSocketServerProtocol,
                                listenWS)
import re
from json import dumps

DEBUG = False

import logging
bcast_log = logging.getLogger('bcast_log')


CHANNEL = 'en.wikipedia'  # use language.project
COLOR_RE = re.compile(r"\x03(?:\d{1,2}(?:,\d{1,2})?)?",
                      re.UNICODE)  # remove IRC color codes
PARSE_EDIT_RE = re.compile(r'(\[\[(?P<page_title>.*?)\]\])'
                           r' +((?P<flags>[A-Z\!]+) )?'
                           r'(?P<url>\S*)'
                           r' +\* (?P<user>.*?)'
                           r' \* (\((?P<change_size>[\+\-][0-9]+)\))?'
                           r' ?(?P<summary>.+)?')
NON_MAIN_NS = ['Talk',
               'User',
               'User talk',
               'Wikipedia',
               'Wikipedia talk',
               'File',
               'File talk',
               'MediaWiki',
               'MediaWiki talk',
               'Template',
               'Template talk',
               'Help',
               'Help talk',
               'Category',
               'Category talk',
               'Portal',
               'Portal talk',
               'Book',
               'Book talk',
               'Education Program',
               'Education Program talk',
               'TimedText',
               'TimedText talk',
               'Module',
               'Module talk',
               'Special',
               'Media']


def process_message(message):
    no_color = COLOR_RE.sub('', message)
    ret = PARSE_EDIT_RE.match(no_color)
    if ret:
        return ret.groupdict()
    return {}


class Monitor(irc.IRCClient):
    def __init__(self, bsf):
        self.broadcaster = bsf
        bcast_log.info('created IRC ...')

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        bcast_log.info('connected to IRC server...')

    def signedOn(self):
        self.join(self.factory.channel)
        bcast_log.info('joined %s ...', self.factory.channel)

    def privmsg(self, user, channel, msg):
        rc = process_message(msg)
        rc['is_new'] = False
        rc['is_bot'] = False
        rc['is_minor'] = False
        rc['is_unpatrolled'] = False
        rc['is_anon'] = False
        '''
        Special logs:
            - Special:Log/abusefilter
            - Special:Log/block
            - Special:Log/newusers
            - Special:Log/move
            - Special:Log/pagetriage-curation
            - Special:Log/delete
            - Special:Log/upload
            - Special:Log/patrol
        '''
        ns, _, title = rc['page_title'].partition(':')
        if not title or ns not in NON_MAIN_NS:
            rc['ns'] = 'Main'
        else:
            rc['ns'] = ns
        if rc['flags'] and 'N' in rc['flags']:
            rc['is_new'] = True
        if rc['flags'] and 'B' in rc['flags']:
            rc['is_bot'] = True
        if rc['flags'] and 'M' in rc['flags']:
            rc['is_minor'] = True
        if rc['flags'] and '!' in rc['flags']:
            rc['is_unpatrolled'] = True
        if rc['user'] and sum([a.isdigit() for a in rc['user'].split('.')]) == 4:
            rc['is_anon'] = True
        # Which revisions to broadcast?
        if rc['is_anon'] and rc['ns'] == 'Main':
            self.broadcaster.broadcast(dumps(rc))


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
    def __init__(self, url, debug=False, debugCodePaths=False):
        WebSocketServerFactory.__init__(self,
                                        url,
                                        debug=debug,
                                        debugCodePaths=debugCodePaths)
        self.clients = []
        self.tickcount = 0
        start_monitor(self)

    def tick(self):
        self.tickcount += 1
        self.broadcast("'tick %d' from server" % self.tickcount)
        reactor.callLater(1, self.tick)

    def register(self, client):
        if not client in self.clients:
            bcast_log.info("registered client %s", client.peerstr)
        self.clients.append(client)

    def unregister(self, client):
        if client in self.clients:
            bcast_log.info("unregistered client %s", client.peerstr)
            self.clients.remove(client)

    def broadcast(self, msg):
        bcast_log.info("broadcasting message %r", msg)
        for c in self.clients:
            c.sendMessage(msg)
            bcast_log.info("message sent to %s", c.peerstr)


class BroadcastPreparedServerFactory(BroadcastServerFactory):
    def broadcast(self, msg):
        # print "broadcasting prepared message '%s' .." % msg
        preparedMsg = self.prepareMessage(msg)
        for c in self.clients:
            c.sendPreparedMessage(preparedMsg)
            bcast_log.info("prepared message sent to %s", c.peerstr)


def start_monitor(bsf):
    f = MonitorFactory(CHANNEL, bsf)
    reactor.connectTCP("irc.wikimedia.org", 6667, f)


if __name__ == '__main__':
    # start_monitor()
    ServerFactory = BroadcastServerFactory
    factory = ServerFactory("ws://localhost:9000",
                            debug=DEBUG,
                            debugCodePaths=DEBUG)

    factory.protocol = BroadcastServerProtocol
    factory.setProtocolOptions(allowHixie76=True)
    listenWS(factory)
    reactor.run()
