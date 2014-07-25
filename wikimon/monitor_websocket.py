# -*- coding: utf-8 -*-


from json import dumps, loads

from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.web.client import getPage
from autobahn.websocket import (WebSocketServerFactory,
                                WebSocketServerProtocol,
                                listenWS)

import wapiti

from parsers import parse_irc_message


DEBUG = False

LOCAL_GEOIP = 'http://localhost:7999'

import logging
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s\t%(name)s\t %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
bcast_log = logging.getLogger('bcast_log')
irc_log = logging.getLogger('irc_log')
api_log = logging.getLogger('api_log')


DEFAULT_LANG = 'en'
DEFAULT_PROJECT = 'wikipedia'
DEFAULT_BCAST_PORT = 9000

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


def process_message(message, non_main_ns=NON_MAIN_NS, bcast_callback=None):
    msg_dict = parse_irc_message(message, non_main_ns)

    def broadcast(geo_json=None):
        if geo_json is not None:
            geo_dict = loads(geo_json)
            msg_dict['geo_ip'] = geo_dict
        bcast_callback(msg_dict)

    def report_failure_broadcast(error):
        bcast_log.debug("could not fetch from local geoip: %s", error)
        broadcast()

    if msg_dict['is_anon']:
        if bcast_callback:
            try:
                geo_url = str(LOCAL_GEOIP + '/json/' + msg_dict['user'])
            except UnicodeError:
                pass
            else:
                getPage(geo_url).addCallbacks(callback=broadcast,
                                              errback=report_failure_broadcast)
    elif bcast_callback:
        broadcast()
    return msg_dict


class Monitor(irc.IRCClient):
    def __init__(self, bsf, nmns, factory):
        self.broadcaster = bsf
        self.non_main_ns = nmns
        self.factory = factory
        irc_log.info('created IRC monitor...')

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        irc_log.info('connected to IRC server...')

    def signedOn(self):
        self.join(self.factory.channel)
        irc_log.info('joined %s ...', self.factory.channel)

    def privmsg(self, user, channel, msg):
        try:
            msg = msg.decode('utf-8')
        except UnicodeError as ue:
            bcast_log.warn('UnicodeError: %r on IRC message %r', ue, msg)
            return
        process_message(msg, self.non_main_ns, self._bc_callback)

    def _bc_callback(self, msg_dict):
        # Which revisions to broadcast?
        json_msg_dict = dumps(msg_dict, sort_keys=True)
        self.broadcaster.broadcast(json_msg_dict)


class MonitorFactory(ReconnectingClientFactory):
    def __init__(self, channel, bsf, nmns=NON_MAIN_NS):
        self.channel = channel
        self.bsf = bsf
        self.nmns = nmns

    def buildProtocol(self, addr):
        irc_log.info('monitor IRC connected to %s', self.channel)
        self.resetDelay()
        return Monitor(self.bsf, self.nmns, self)

    def startConnecting(self, connector):
        irc_log.info('monitor IRC starting connection to %s', self.channel)
        protocol.startConnecting(self, connector)

    def clientConnectionLost(self, connector, reason):
        irc_log.error('lost monitor IRC connection: %s', reason)
        ReconnectingClientFactory.clientConnectionLost(self, connector, reason)

    def clientConnectionFailed(self, connector, reason):
        irc_log.error('failed monitor IRC connection: %s', reason)
        ReconnectingClientFactory.clientConnectionFailed(self, connector, reason)


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
    api_log.info('fetching namespaces from %r', api_url)
    wc = wapiti.WapitiClient('wikimon@hatnote.com', api_url=api_url)
    api_log.info('successfully fetched namespaces from %r', api_url)
    page_info = wc.get_source_info()
    nmns = [ns.title for ns in page_info[0].namespace_map if ns.title]
    irc_log.info('connecting to %s...', channel)
    f = MonitorFactory(channel, broadcaster, nmns)
    reactor.connectTCP("irc.wikimedia.org", 6667, f)


def get_argparser():
    from argparse import ArgumentParser
    desc = "broadcast realtime edits to a Mediawiki project over websockets"
    prs = ArgumentParser(description=desc)
    prs.add_argument('--project', default=DEFAULT_PROJECT)
    prs.add_argument('--lang', default=DEFAULT_LANG)
    prs.add_argument('--port', default=DEFAULT_BCAST_PORT, type=int,
                     help='listen port for websocket connections')
    prs.add_argument('--debug', default=DEBUG, action='store_true')
    prs.add_argument('--loglevel', default='WARN',
                     help='e.g., DEBUG, INFO, WARN, etc.')
    return prs


def main():
    parser = get_argparser()
    args = parser.parse_args()
    try:
        bcast_log.setLevel(getattr(logging, args.loglevel.upper()))
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
