# -*- coding: utf-8 -*-

from json import dumps

from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
from twisted.internet.protocol import ReconnectingClientFactory
from autobahn.websocket import (WebSocketServerFactory,
                                WebSocketServerProtocol,
                                listenWS)

import wapiti
from parsers import parse_irc_message
import monitor_geolite2


DEBUG = False

import logging
from twisted.python.log import PythonLoggingObserver
observer = PythonLoggingObserver()
observer.start()

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


def strip_colors(msg):
    def _extract(formatted):
        if not hasattr(formatted, 'children'):
            return formatted
        return ''.join(map(_extract, formatted.children))

    return _extract(irc.parseFormattedText(msg))


def geolocated_anonymous_user(geoip_db, parsed, lang='en'):
    geo_loc = {}

    localized = ['names', lang]
    info_to_geoloc = {'country_name': ['country'] + localized,
                      'latitude': ['location', 'latitude'],
                      'longitude': ['location', 'longitude'],
                      'region_name': ['subdivisions', 0] + localized,
                      'city': ['city'] + localized}

    if not parsed.get('is_anon'):
        return geo_loc
    ip = parsed['user']
    try:
        result = geoip_db.lookup(ip)
        if not result:
            return geo_loc
    except Exception:
        bcast_log.exception('geoip lookup failed for %r', ip)
        return geo_loc

    info = result.get_info_dict()

    for dst, src_items in info_to_geoloc.items():
        cursor = info
        for src in src_items:
            try:
                cursor = cursor[src]
            except (KeyError, IndexError):
                cursor = None
                break
        geo_loc[dst] = cursor

    return geo_loc


class Monitor(irc.IRCClient):
    GEO_IP_KEY = 'geo_ip'

    def __init__(self, geoip_db_monitor, bsf, nmns, factory):
        self.geoip_db_monitor = geoip_db_monitor
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
        msg = strip_colors(msg)

        try:
            msg = msg.decode('utf-8')
        except UnicodeError as ue:
            bcast_log.warn('UnicodeError: %r on IRC message %r', ue, msg)
            return

        parsed = parse_irc_message(msg, NON_MAIN_NS)
        bcast_log.info(self.geoip_db_monitor.geoip_db)
        geo_loc = geolocated_anonymous_user(self.geoip_db_monitor.geoip_db,
                                            parsed)
        if geo_loc:
            parsed[self.GEO_IP_KEY] = geo_loc
            # Which revisions to broadcast?
        self.broadcaster.broadcast(dumps(parsed, sort_keys=True))


class MonitorFactory(ReconnectingClientFactory):
    def __init__(self, geoip_db_monitor, channel, bsf, nmns=NON_MAIN_NS):
        self.geoip_db_monitor = geoip_db_monitor
        self.channel = channel
        self.bsf = bsf
        self.nmns = nmns

    def buildProtocol(self, addr):
        irc_log.info('monitor IRC connected to %s', self.channel)
        self.resetDelay()
        return Monitor(self.geoip_db_monitor, self.bsf, self.nmns, self)

    def startConnecting(self, connector):
        irc_log.info('monitor IRC starting connection to %s', self.channel)
        protocol.startConnecting(self, connector)

    def clientConnectionLost(self, connector, reason):
        irc_log.error('lost monitor IRC connection: %s', reason)
        ReconnectingClientFactory.clientConnectionLost(self, connector, reason)

    def clientConnectionFailed(self, connector, reason):
        irc_log.error('failed monitor IRC connection: %s', reason)
        ReconnectingClientFactory.clientConnectionFailed(self, connector,
                                                         reason)


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
    def __init__(self, url, geoip_db, geoip_update_interval,
                 lang, project, *a, **kw):
        WebSocketServerFactory.__init__(self, url, *a, **kw)
        self.clients = set()
        self.tickcount = 0

        start_monitor(self, geoip_db, geoip_update_interval,
                      lang, project)  # blargh

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


def start_monitor(broadcaster, geoip_db, geoip_update_interval,
                  lang=DEFAULT_LANG, project=DEFAULT_PROJECT):
    channel = '%s.%s' % (lang, project)
    api_url = 'http://%s.%s.org/w/api.php' % (lang, project)
    api_log.info('fetching namespaces from %r', api_url)
    wc = wapiti.WapitiClient('wikimon@hatnote.com', api_url=api_url)
    api_log.info('successfully fetched namespaces from %r', api_url)
    page_info = wc.get_source_info()
    nmns = [ns.title for ns in page_info[0].namespace_map if ns.title]
    irc_log.info('connecting to %s...', channel)
    geoip_db_monitor = monitor_geolite2.begin(geoip_db,
                                              geoip_update_interval)
    f = MonitorFactory(geoip_db_monitor, channel, broadcaster, nmns)
    reactor.connectTCP("irc.wikimedia.org", 6667, f)


def get_argparser():
    from argparse import ArgumentParser
    desc = "broadcast realtime edits to a Mediawiki project over websockets"
    prs = ArgumentParser(description=desc)
    prs.add_argument('geoip_db', help='path to the GeoLite2 database')
    prs.add_argument('--geoip-update-interval',
                     default=monitor_geolite2.DEFAULT_INTERVAL,
                     type=int,
                     help='how often (in seconds) to check'
                     ' for updates in the GeoIP db')
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
                            geoip_db=args.geoip_db,
                            geoip_update_interval=args.geoip_update_interval,
                            debug=DEBUG,
                            debugCodePaths=DEBUG)
    factory.protocol = BroadcastServerProtocol
    factory.setProtocolOptions(allowHixie76=True)
    listenWS(factory)
    reactor.run()

if __name__ == '__main__':
    main()
