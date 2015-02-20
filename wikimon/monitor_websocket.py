# -*- coding: utf-8 -*-

from json import dumps
from os.path import dirname, abspath

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
DEFAULT_GEOIP_DB = dirname(dirname(abspath(__file__))) + '/geodb/GeoLite2-City.mmdb'

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
IRC_SERVER_HOST = 'irc.wikimedia.org'
IRC_SERVER_PORT = 6667


def strip_colors(msg):
    def _extract(formatted):
        if not hasattr(formatted, 'children'):
            return formatted
        return ''.join(map(_extract, formatted.children))

    return _extract(irc.parseFormattedText(msg))


def geolocate_anonymous_user(geoip_db, ip, lang='en'):
    geo_loc = {}

    localized = ['names', lang]
    info_to_geoloc = {'country_name': ['country'] + localized,
                      'latitude': ['location', 'latitude'],
                      'longitude': ['location', 'longitude'],
                      'region_name': ['subdivisions', 0] + localized,
                      'city': ['city'] + localized}
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
    # without the `nickname` attribute, the nickname defaults to 'irc'
    # which conflicts with a lot of other clients out there and
    # sometimes prevents joining rooms.

    nickname = 'wikimon'
    GEO_IP_KEY = 'geo_ip'

    def __init__(self, geoip_db_monitor, bsf, ns_map, factory):
        self.geoip_db_monitor = geoip_db_monitor
        self.broadcaster = bsf
        self.ns_map = ns_map
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

        msg_dict = parse_irc_message(msg, self.ns_map)
        if msg_dict.get('is_anon'):
            ip = msg_dict['user']
            geo_loc = geolocate_anonymous_user(self.geoip_db_monitor.geoip_db,
                                               ip)
            msg_dict[self.GEO_IP_KEY] = geo_loc

        self.broadcaster.broadcast(dumps(msg_dict, sort_keys=True))


class MonitorFactory(ReconnectingClientFactory):
    def __init__(self, geoip_db_monitor, channel, bsf, ns_map):
        self.geoip_db_monitor = geoip_db_monitor
        self.channel = channel
        self.bsf = bsf
        self.ns_map = ns_map

    def buildProtocol(self, addr):
        irc_log.info('monitor IRC connected to %s', self.channel)
        self.resetDelay()
        return Monitor(self.geoip_db_monitor, self.bsf, self.ns_map, self)

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
        if client not in self.clients:
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
    ns_map = dict([(ns.title, ns.canonical)
                   for ns in page_info[0].namespace_map if ns.title])
    irc_log.info('connecting to %s...', channel)
    geoip_db_monitor = monitor_geolite2.begin(geoip_db,
                                              geoip_update_interval)
    f = MonitorFactory(geoip_db_monitor, channel, broadcaster, ns_map)
    reactor.connectTCP(IRC_SERVER_HOST, IRC_SERVER_PORT, f)


def get_argparser():
    from argparse import ArgumentParser
    desc = "broadcast realtime edits to a Mediawiki project over websockets"
    prs = ArgumentParser(description=desc)
    prs.add_argument('--geoip_db', default=None,
                     help='path to the GeoLite2 database')
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

    geoip_db_path = args.geoip_db
    if not geoip_db_path:
        print "geoip_db not set, defaulting to %r" % DEFAULT_GEOIP_DB
        geoip_db_path = DEFAULT_GEOIP_DB
    open(geoip_db_path).close()  # basic readability check
    try:
        bcast_log.setLevel(getattr(logging, args.loglevel.upper()))
    except:
        print 'warning: invalid log level'
        bcast_log.setLevel(logging.WARN)
    if args.debug:
        bcast_log.setLevel(logging.DEBUG)
    ws_listen_addr = 'ws://localhost:%d' % (args.port,)
    ServerFactory = BroadcastServerFactory
    factory = ServerFactory(ws_listen_addr,
                            project=args.project,
                            lang=args.lang,
                            geoip_db=geoip_db_path,
                            geoip_update_interval=args.geoip_update_interval,
                            debug=DEBUG or args.debug,
                            debugCodePaths=DEBUG)
    factory.protocol = BroadcastServerProtocol
    factory.setProtocolOptions(allowHixie76=True)
    listenWS(factory)
    reactor.run()

if __name__ == '__main__':
    main()
