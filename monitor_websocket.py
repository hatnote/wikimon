# some code from Twisted Matrix's irc_test.py
from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
from twisted.web.client import getPage
from autobahn.websocket import (WebSocketServerFactory,
                                WebSocketServerProtocol,
                                listenWS)
import re
import socket

import wapiti
from json import dumps, loads

DEBUG = False

LOCAL_GEOIP = 'http://localhost:7999'

import logging
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s\t%(name)s\t %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
bcast_log = logging.getLogger('bcast_log')


DEFAULT_LANG = 'en'
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


def is_ip(addr):
    try:
        socket.inet_aton(addr)
    except Exception:
        return False
    return True


def process_message(message, non_main_ns=NON_MAIN_NS, bcast_callback=None):
    no_color = COLOR_RE.sub('', message)
    ret = PARSE_EDIT_RE.match(no_color)
    msg_dict = {'is_new': False,
                'is_bot': False,
                'is_unpatrolled': False,
                'is_anon': False}
    if ret:
        msg_dict.update(ret.groupdict())
    else:
        msg_dict = {}
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
    ns, _, title = msg_dict['page_title'].rpartition(':')
    if ns not in non_main_ns:
        msg_dict['ns'] = 'Main'
    else:
        msg_dict['ns'] = ns
    flags = msg_dict.get('flags') or ''

    msg_dict['is_new'] = 'N' in flags
    msg_dict['is_bot'] = 'B' in flags
    msg_dict['is_minor'] = 'M' in flags
    msg_dict['is_unpatrolled'] = '!' in flags

    username = msg_dict.get('user')
    is_anon = is_ip(username)

    def report_failure_broadcast(error):
        bcast_log.debug("could not fetch from local geoip: %s", error)
        broadcast('null')

    def broadcast(geo_json):
        geo_dict = loads(geo_json)
        msg_dict['geo_ip'] = geo_dict
        bcast_callback(msg_dict)

    if is_anon:
        msg_dict['is_anon'] = True

        if bcast_callback:
            try:
                geo_url = str(LOCAL_GEOIP + '/json/' + username)
            except UnicodeError:
                pass
            else:
                getPage(geo_url).addCallbacks(
                    callback=broadcast,
                    errback=report_failure_broadcast)
    return msg_dict


class Monitor(irc.IRCClient):
    def __init__(self, bsf, nmns, factory):
        self.broadcaster = bsf
        self.non_main_ns = nmns
        self.factory = factory
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
            bcast_log.warn('UnicodeError: %r on IRC message %r', ue, msg)
            return
        process_message(msg, self.non_main_ns, self._bc_callback)

    def _bc_callback(self, msg_dict):
        # Which revisions to broadcast?
        json_msg_dict = dumps(msg_dict)
        self.broadcaster.broadcast(json_msg_dict)



class MonitorFactory(protocol.ReconnectingClientFactory):
    def __init__(self, channel, bsf, nmns=NON_MAIN_NS):
        self.channel = channel
        self.bsf = bsf
        self.nmns = nmns

    def buildProtocol(self, addr):
        bcast_log.debug('Monitor IRC connected')
        self.resetDelay()
        return Monitor(self.bsf, self.nmns, self)

    def startConnecting(self, connector):
        bcast_log.debug('Monitor IRC starting connection')
        protocol.startConnecting(self, connector)

    def clientConnectionLost(self, connector, reason):
        bcast_log.debug('Lost Monitor IRC connection: %s', reason)
        protocol.ReconnectingClientFactory.clientConnectionLost(self, connector, reason)

    def clientConnectionFailed(self, connector, reason):
        bcast_log.error('Failed Monitor IRC connection: %s', reason)
        protocol.ReconnectingClientFactory.clientConnectionFailed(self, connector, reason)


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
    bcast_log.info('connecting to %s...', channel)
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
    prs.add_argument('--loglevel', default='WARN',
                     help='e.g., DEBUG, INFO, WARN, etc.')
    return prs


def main():
    parser = create_parser()
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
