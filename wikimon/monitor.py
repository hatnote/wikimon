# -*- coding: utf-8 -*-

"""
wikimon.monitor
~~~~~~~~~~~~~~~

Asyncio-based monitor that consumes Wikimedia EventStreams (SSE)
and broadcasts edits to WebSocket clients.

Replaces the old Twisted/IRC-based monitor_websocket.py.
"""

import asyncio
import json
import logging
import os
import time
from argparse import ArgumentParser
from json import dumps
from os.path import dirname, abspath

import aiohttp
import websockets
import maxminddb

from wikimon.parsers import (
    is_ip,
    parse_comment,
    DEFAULT_NS_MAP,
)

logger = logging.getLogger('wikimon')

DEFAULT_LANG = 'en'
DEFAULT_PROJECT = 'wikipedia'
DEFAULT_BCAST_PORT = 9000
DEFAULT_GEOIP_DB = os.path.join(
    dirname(dirname(abspath(__file__))), 'geodb', 'GeoLite2-City.mmdb'
)
DEFAULT_GEOIP_UPDATE_INTERVAL = 30  # seconds

EVENTSTREAMS_URL = 'https://stream.wikimedia.org/v2/stream/recentchange'
USER_AGENT = 'wikimon/0.7.0 (https://github.com/hatnote/wikimon; wikimon@hatnote.com)'

# Stats logging interval in seconds
STATS_LOG_INTERVAL = 120


def fetch_namespace_map(lang, project):
    """Fetch namespace mapping from MediaWiki API.

    Makes a synchronous request at startup. Returns a dict mapping
    namespace numeric ID to canonical name.
    """
    if project == 'wikidata':
        api_url = 'https://www.wikidata.org/w/api.php'
    else:
        api_url = f'https://{lang}.{project}.org/w/api.php'

    import requests
    try:
        resp = requests.get(api_url, params={
            'action': 'query',
            'meta': 'siteinfo',
            'siprop': 'namespaces',
            'format': 'json',
        }, headers={'User-Agent': USER_AGENT}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        ns_map = {}
        for ns_id, ns_info in data['query']['namespaces'].items():
            ns_id_int = int(ns_id)
            canonical = ns_info.get('canonical', ns_info.get('*', ''))
            local_name = ns_info.get('*', '')
            if ns_id_int == 0:
                ns_map[0] = 'Main'
            else:
                # Map both numeric ID and local name to canonical
                ns_map[ns_id_int] = canonical or local_name
                if local_name:
                    ns_map[local_name] = canonical or local_name
        return ns_map
    except Exception:
        logger.exception('Failed to fetch namespace map from %s, using defaults', api_url)
        return dict(DEFAULT_NS_MAP)


def _resolve_server_name(lang, project):
    """Return the server_name to filter EventStreams events on."""
    if project == 'wikidata':
        return 'www.wikidata.org'
    return f'{lang}.{project}.org'


def transform_event(event, ns_map):
    """Transform an EventStreams recentchange event into wikimon output format.

    The output dict MUST match the fields the frontend (app.js) consumes:
    page_title, user, is_anon, is_bot, is_new, is_minor, is_unpatrolled,
    change_size, url, ns, summary, action, hashtags, mentions, section,
    parsed_summary, rev_id, parent_rev_id, geo_ip (added separately).
    """
    title = event.get('title', '')
    user = event.get('user', '')
    comment = event.get('comment', '')
    event_type = event.get('type', 'edit')

    # Compute change_size
    length = event.get('length') or {}
    length_new = length.get('new')
    length_old = length.get('old')
    if length_new is not None and length_old is not None:
        change_size = length_new - length_old
    else:
        change_size = None

    # Build diff URL
    revision = event.get('revision') or {}
    rev_new = revision.get('new')
    rev_old = revision.get('old')
    server_url = event.get('server_url', '')
    server_script_path = event.get('server_script_path', '/w')

    if rev_new and rev_old:
        url = f'{server_url}{server_script_path}/index.php?diff={rev_new}&oldid={rev_old}'
    elif event_type == 'log':
        # Log events: action field is the log type/action
        log_type = event.get('log_type', '')
        log_action = event.get('log_action', '')
        url = f'{log_type}/{log_action}' if log_type else ''
    else:
        url = ''

    # Determine namespace
    ns_id = event.get('namespace', 0)
    if ns_id == 0:
        ns = 'Main'
    else:
        ns = ns_map.get(ns_id, ns_map.get(ns_id, str(ns_id)))

    # Parse comment for section, hashtags, mentions
    comment_data = parse_comment(comment)

    # Determine action
    if event_type == 'log':
        # For log events, set page_title to Special:Log/<log_type>
        log_type = event.get('log_type', '')
        action = f'Special:Log/{log_type}' if log_type else 'log'
        # Override title for new user logs to match old wikimon format
        if log_type == 'newusers':
            title = 'Special:Log/newusers'
    elif event_type == 'new':
        action = 'new'
    else:
        action = 'edit'

    # Flags
    is_anon = is_ip(user)
    is_bot = bool(event.get('bot', False))
    is_new = event_type == 'new'
    is_minor = bool(event.get('minor', False))
    is_unpatrolled = not bool(event.get('patrolled', True))

    msg = {
        'page_title': title,
        'user': user,
        'is_anon': is_anon,
        'is_bot': is_bot,
        'is_new': is_new,
        'is_minor': is_minor,
        'is_unpatrolled': is_unpatrolled,
        'change_size': change_size,
        'url': url,
        'ns': ns,
        'summary': comment,
        'action': action,
        'hashtags': comment_data['hashtags'],
        'mentions': comment_data['mentions'],
        'section': comment_data['section'],
        'parsed_summary': comment_data['parsed_summary'],
        'rev_id': str(rev_new) if rev_new is not None else None,
        'parent_rev_id': str(rev_old) if rev_old is not None else None,
    }

    return msg


class GeoIPManager:
    """Manages the MaxMind GeoLite2 database with periodic reload on mtime change."""

    def __init__(self, db_path, check_interval=DEFAULT_GEOIP_UPDATE_INTERVAL):
        self.db_path = db_path
        self.check_interval = check_interval
        self.reader = None
        self.last_mtime = 0
        self._load()

    def _load(self):
        try:
            mtime = os.path.getmtime(self.db_path)
            self.reader = maxminddb.open_database(self.db_path)
            self.last_mtime = mtime
            logger.info('Loaded GeoIP database from %s (mtime=%s)', self.db_path, mtime)
        except Exception:
            logger.exception('Failed to load GeoIP database from %s', self.db_path)
            self.reader = None

    def check_reload(self):
        """Reload the database if the file has been modified."""
        try:
            mtime = os.path.getmtime(self.db_path)
            if mtime > self.last_mtime:
                logger.info('GeoIP database modified, reloading...')
                old_reader = self.reader
                self._load()
                if old_reader:
                    old_reader.close()
        except Exception:
            logger.exception('Error checking GeoIP database mtime')

    def lookup(self, ip, lang='en'):
        """Look up geographic info for an IP address.

        Returns a dict with keys: country_name, latitude, longitude,
        region_name, city. All values may be None.
        """
        geo_loc = {}
        if not self.reader:
            return geo_loc

        info_to_geoloc = {
            'country_name': ['country', 'names', lang],
            'latitude': ['location', 'latitude'],
            'longitude': ['location', 'longitude'],
            'region_name': ['subdivisions', 0, 'names', lang],
            'city': ['city', 'names', lang],
        }
        try:
            result = self.reader.get(ip)
            if not result:
                return geo_loc
        except Exception:
            logger.debug('GeoIP lookup failed for %r', ip)
            return geo_loc

        for dst, src_path in info_to_geoloc.items():
            cursor = result
            for key in src_path:
                try:
                    cursor = cursor[key]
                except (KeyError, IndexError, TypeError):
                    cursor = None
                    break
            geo_loc[dst] = cursor

        return geo_loc

    def close(self):
        if self.reader:
            self.reader.close()
            self.reader = None


class WikimonServer:
    """Main server: consumes EventStreams, broadcasts via WebSocket."""

    def __init__(self, lang, project, port, geoip_manager, ns_map):
        self.lang = lang
        self.project = project
        self.port = port
        self.geoip = geoip_manager
        self.ns_map = ns_map
        self.server_name = _resolve_server_name(lang, project)
        self.clients = set()
        self.msg_count = 0
        self.start_time = time.time()
        self._last_event_id = None

    async def ws_handler(self, websocket):
        """Handle an individual WebSocket client connection."""
        self.clients.add(websocket)
        remote = websocket.remote_address
        logger.info('Client connected: %s (total: %d)', remote, len(self.clients))
        try:
            # Keep connection open; we only send, never receive meaningful data
            async for _ in websocket:
                pass
        except websockets.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            logger.info('Client disconnected: %s (total: %d)', remote, len(self.clients))

    async def broadcast(self, message):
        """Send a message string to all connected WebSocket clients."""
        if not self.clients:
            return
        stale = set()
        for ws in self.clients:
            try:
                await ws.send(message)
            except websockets.ConnectionClosed:
                stale.add(ws)
            except Exception:
                logger.debug('Error sending to client', exc_info=True)
                stale.add(ws)
        self.clients -= stale

    async def consume_eventstream(self):
        """Connect to EventStreams SSE and process events.

        Auto-reconnects with exponential backoff on failure.
        """
        backoff = 1
        max_backoff = 60

        while True:
            try:
                headers = {'User-Agent': USER_AGENT}
                url = EVENTSTREAMS_URL
                if self._last_event_id:
                    # Resume from last known event ID
                    headers['Last-Event-ID'] = self._last_event_id

                logger.info('Connecting to EventStreams for %s (server_name=%s)',
                            self.lang, self.server_name)
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers, timeout=None) as resp:
                        if resp.status != 200:
                            logger.error('EventStreams returned HTTP %d, retrying in %ds',
                                         resp.status, backoff)
                            await asyncio.sleep(backoff)
                            backoff = min(backoff * 2, max_backoff)
                            continue
                        backoff = 1  # Reset on successful connection
                        logger.info('Connected to EventStreams (status=%s)', resp.status)

                        event_id = None
                        event_data = None

                        async for line_bytes in resp.content:
                            line = line_bytes.decode('utf-8', errors='replace').rstrip('\n')

                            if line.startswith('id:'):
                                event_id = line[3:].strip()
                                continue
                            if line.startswith('data:'):
                                event_data = line[5:].strip()
                                continue
                            if line == '' and event_data:
                                # End of SSE event
                                if event_id:
                                    self._last_event_id = event_id
                                try:
                                    data = json.loads(event_data)
                                except json.JSONDecodeError:
                                    event_data = None
                                    continue

                                event_data = None

                                # Filter for our server_name
                                if data.get('server_name') != self.server_name:
                                    continue

                                await self._process_event(data)

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('EventStreams connection error, reconnecting in %ds', backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def _process_event(self, event):
        """Transform an event and broadcast it."""
        msg = transform_event(event, self.ns_map)

        # GeoIP lookup for anonymous users
        if msg['is_anon'] and msg['user']:
            loop = asyncio.get_running_loop()
            geo = await loop.run_in_executor(None, self.geoip.lookup, msg['user'])
            msg['geo_ip'] = geo
        else:
            msg['geo_ip'] = {}

        json_str = dumps(msg, sort_keys=True)
        self.msg_count += 1
        logger.debug('Broadcasting: %s', json_str[:200])
        await self.broadcast(json_str)

    async def _periodic_geoip_check(self):
        """Periodically check if the GeoIP database needs reloading."""
        while True:
            await asyncio.sleep(self.geoip.check_interval)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.geoip.check_reload)

    async def _periodic_stats(self):
        """Periodically log server stats."""
        while True:
            await asyncio.sleep(STATS_LOG_INTERVAL)
            uptime_hours = (time.time() - self.start_time) / 3600
            stats = {
                'msgs': self.msg_count,
                'clients': len(self.clients),
                'lang': self.lang,
                'project': self.project,
                'uptime_hours': round(uptime_hours, 2),
            }
            logger.info('stats: %s', dumps(stats))

    async def run(self):
        """Start the WebSocket server and EventStreams consumer."""
        logger.info('Starting wikimon server: lang=%s project=%s port=%d',
                    self.lang, self.project, self.port)

        async with websockets.serve(self.ws_handler, '0.0.0.0', self.port):
            logger.info('WebSocket server listening on 0.0.0.0:%d', self.port)
            await asyncio.gather(
                self.consume_eventstream(),
                self._periodic_geoip_check(),
                self._periodic_stats(),
            )


def get_argparser():
    desc = "Broadcast realtime Wikimedia edits over WebSockets (EventStreams-based)"
    prs = ArgumentParser(description=desc)
    prs.add_argument('--geoip-db', default=None,
                     help='path to the GeoLite2 database')
    prs.add_argument('--geoip-update-interval',
                     default=DEFAULT_GEOIP_UPDATE_INTERVAL,
                     type=int,
                     help='how often (in seconds) to check for GeoIP db updates')
    prs.add_argument('--project', default=DEFAULT_PROJECT)
    prs.add_argument('--lang', default=DEFAULT_LANG)
    prs.add_argument('--port', default=DEFAULT_BCAST_PORT, type=int,
                     help='listen port for WebSocket connections')
    prs.add_argument('--debug', default=False, action='store_true')
    prs.add_argument('--loglevel', default='WARN',
                     help='e.g., DEBUG, INFO, WARN, etc.')
    return prs


def main():
    parser = get_argparser()
    args = parser.parse_args()

    # Configure logging
    log_level = logging.WARN
    try:
        log_level = getattr(logging, args.loglevel.upper())
    except AttributeError:
        print(f'warning: invalid log level {args.loglevel!r}')
    if args.debug:
        log_level = logging.DEBUG

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s\t%(name)s\t%(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    # GeoIP setup
    geoip_db_path = args.geoip_db
    if not geoip_db_path:
        logger.info('geoip_db not set, defaulting to %r', DEFAULT_GEOIP_DB)
        geoip_db_path = DEFAULT_GEOIP_DB

    geoip = GeoIPManager(geoip_db_path, args.geoip_update_interval)

    # Namespace map
    ns_map = fetch_namespace_map(args.lang, args.project)
    logger.info('Fetched namespace map with %d entries', len(ns_map))

    # Run
    server = WikimonServer(
        lang=args.lang,
        project=args.project,
        port=args.port,
        geoip_manager=geoip,
        ns_map=ns_map,
    )

    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logger.info('Shutting down')
    finally:
        geoip.close()


if __name__ == '__main__':
    main()
