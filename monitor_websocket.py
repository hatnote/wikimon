# some code from Twisted Matrix's irc_test.py
from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
from autobahn.websocket import (WebSocketServerFactory,
                                WebSocketServerProtocol,
                                listenWS)
import re
import wapiti
from json import dumps

DEBUG = False

import logging
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s\t%(name)s\t %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
bcast_log = logging.getLogger('bcast_log')


DEFAULT_LANG = 'fr'
DEFAULT_PROJECT = 'wikipedia'
DEFAULT_BCAST_PORT = 9000

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
    def __init__(self, bsf, nmns):
        self.broadcaster = bsf
        self.non_main_ns = nmns
        bcast_log.info('created IRC monitor...')

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        bcast_log.info('connected to IRC server...')

    def signedOn(self):
        self.join(self.factory.channel)
        bcast_log.info('joined %s ...', self.factory.channel)

    def privmsg(self, user, channel, msg):
        try:
            msg = msg.decode('utf-8')
        except UnicodeError as ue:
            bcast_log.warn('UnicodeError: %r on IRC message %r', (ue, msg))
            return
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
        ns, _, title = rc['page_title'].rpartition(':')
        if ns not in self.non_main_ns:
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
        self.broadcaster.broadcast(dumps(rc))


class MonitorFactory(protocol.ClientFactory):
    def __init__(self, channel, bsf, nmns=NON_MAIN_NS):
        self.channel = channel
        self.bsf = bsf
        self.nmns = nmns

    def buildProtocol(self, addr):
        p = Monitor(self.bsf, self.nmns)
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
    def __init__(self, url, lang, project, *a, **kw):
        WebSocketServerFactory.__init__(self, url, *a, **kw)
        self.clients = set()
        self.tickcount = 0

        start_monitor(self, lang, project)  # blargh

    def tick(self):
        self.tickcount += 1
        self.broadcast("'tick %d' from server" % self.tickcount)
        reactor.callLater(1, self.tick)

    def register(self, client):
        if not client in self.clients:
            bcast_log.info("registered client %s", client.peerstr)
        self.clients.add(client)

    def unregister(self, client):
        try:
            self.clients.remove(client)
            bcast_log.info("unregistered client %s", client.peerstr)
        except KeyError:
            pass

    def broadcast(self, msg):
        bcast_log.info("broadcasting message %r", msg)
        for c in self.clients:
            c.sendMessage(msg)
            bcast_log.debug("message sent to %s", c.peerstr)


class BroadcastPreparedServerFactory(BroadcastServerFactory):
    def broadcast(self, msg):
        preparedMsg = self.prepareMessage(msg)
        for c in self.clients:
            c.sendPreparedMessage(preparedMsg)
            bcast_log.info("prepared message sent to %s", c.peerstr)


def start_monitor(broadcaster, lang=DEFAULT_LANG, project=DEFAULT_PROJECT):
    channel = '%s.%s' % (lang, project)
    api_url = 'http://%s.%s.org/w/api.php' % (lang, project)
    bcast_log.info('fetching namespaces from %r', api_url)
    wc = wapiti.WapitiClient('wikimon@hatnote.com', api_url=api_url)
    page_info = wc.get_source_info()
    nmns = [ns.title for ns in page_info[0].namespace_map if ns.title]
    bcast_log.info('connecting to %s...' % channel)
    f = MonitorFactory(channel, broadcaster, nmns)
    reactor.connectTCP("irc.wikimedia.org", 6667, f)


def create_parser():
    from argparse import ArgumentParser
    desc = "broadcast realtime edits to a Mediawiki project over websockets"
    prs = ArgumentParser(description=desc)
    prs.add_argument('--project', default=DEFAULT_PROJECT)
    prs.add_argument('--lang', default=DEFAULT_LANG)
    prs.add_argument('--port', default=DEFAULT_BCAST_PORT, type=int,
                     help='listen port for websocket connections')
    prs.add_argument('--debug', default=DEBUG, action='store_true')
    prs.add_argument('--loglevel', default='WARN')
    return prs


def main():
    parser = create_parser()
    args = parser.parse_args()
    try:
        bcast_log.setLevel(getattr(logging, args.loglevel))
    except:
        print 'warning: invalid log level'
        bcast_log.setLevel(logging.WARN)
    ws_listen_addr = 'ws://localhost:%d' % (args.port,)
    ServerFactory = BroadcastServerFactory
    factory = ServerFactory(ws_listen_addr,
                            project=args.project,
                            lang=args.lang,
                            debug=DEBUG,
                            debugCodePaths=DEBUG)
    factory.protocol = BroadcastServerProtocol
    factory.setProtocolOptions(allowHixie76=True)
    listenWS(factory)
    reactor.run()

if __name__ == '__main__':
    main()
