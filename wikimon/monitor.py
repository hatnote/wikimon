# -*- coding: utf-8 -*-

"""
wikimon.monitor
~~~~~~~~~~~~~~~

Asyncio-based monitor that consumes Wikimedia EventStreams (SSE)
and broadcasts edits to WebSocket clients.

Replaces the old Twisted/IRC-based monitor_websocket.py.
"""

import asyncio
import dataclasses
import json
import logging
import time
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from json import dumps

import aiohttp
import websockets

from wikimon.parsers import (
    is_anon,
    parse_comment,
    DEFAULT_NS_MAP,
)

logger = logging.getLogger('wikimon')

DEFAULT_LANG = 'en'
DEFAULT_PROJECT = 'wikipedia'
DEFAULT_BCAST_PORT = 9000

EVENTSTREAMS_URL = 'https://stream.wikimedia.org/v2/stream/recentchange'
USER_AGENT = 'wikimon/0.7.0 (https://github.com/hatnote/wikimon; wikimon@hatnote.com)'

# Stats logging interval in seconds
STATS_LOG_INTERVAL = 120


# Read timeout for SSE stream. EventStreams sends heartbeat `:` comments
# every ~15s. If no bytes arrive within this window, the connection is dead.
SSE_READ_TIMEOUT_SECONDS = 30

# If no en.wikipedia event has arrived in this many seconds, warn.
# en.wiki averages ~2 edits/sec; 60s silence is suspicious.
EN_STALE_THRESHOLD_SECONDS = 60

# If no event on ANY channel has arrived in this many seconds, warn.
STALE_STREAM_THRESHOLD_SECONDS = 120

# Default language configurations
# Each entry: (lang, project, ws_path)
DEFAULT_LANGUAGES = [
    ('en', 'wikipedia', '/en/'),
    ('de', 'wikipedia', '/de/'),
    ('ru', 'wikipedia', '/ru/'),
    ('ja', 'wikipedia', '/ja/'),
    ('es', 'wikipedia', '/es/'),
    ('fr', 'wikipedia', '/fr/'),
    ('nl', 'wikipedia', '/nl/'),
    ('it', 'wikipedia', '/it/'),
    ('sv', 'wikipedia', '/sv/'),
    ('ar', 'wikipedia', '/ar/'),
    ('id', 'wikipedia', '/id/'),
    ('ta', 'wikipedia', '/ta/'),
    ('pa', 'wikipedia', '/pa/'),
    ('mr', 'wikipedia', '/mr/'),
    ('hi', 'wikipedia', '/hi/'),
    ('as', 'wikipedia', '/as/'),
    ('bn', 'wikipedia', '/bn/'),
    ('te', 'wikipedia', '/te/'),
    ('kn', 'wikipedia', '/kn/'),
    ('or', 'wikipedia', '/or/'),
    ('sa', 'wikipedia', '/sa/'),
    ('gu', 'wikipedia', '/gu/'),
    ('fa', 'wikipedia', '/fa/'),
    ('wikidata', 'wikidata', '/wikidata/'),
    ('he', 'wikipedia', '/he/'),
    ('zh', 'wikipedia', '/zh/'),
    ('ml', 'wikipedia', '/ml/'),
    ('pl', 'wikipedia', '/pl/'),
    ('mk', 'wikipedia', '/mk/'),
    ('be', 'wikipedia', '/be/'),
    ('sr', 'wikipedia', '/sr/'),
    ('bg', 'wikipedia', '/bg/'),
    ('uk', 'wikipedia', '/uk/'),
    ('hu', 'wikipedia', '/hu/'),
    ('fi', 'wikipedia', '/fi/'),
    ('no', 'wikipedia', '/no/'),
    ('el', 'wikipedia', '/el/'),
    ('eo', 'wikipedia', '/eo/'),
    ('pt', 'wikipedia', '/pt/'),
    ('et', 'wikipedia', '/et/'),
    ('ur', 'wikipedia', '/ur/'),
    ('ro', 'wikipedia', '/ro/'),
    ('hy', 'wikipedia', '/hy/'),
]


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


def fetch_all_namespace_maps(languages):
    """Fetch namespace maps for all languages in parallel.

    Returns a dict keyed by (lang, project) tuples.
    """
    results = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(fetch_namespace_map, lang, project): (lang, project)
            for lang, project, _ in languages
        }
        for future in as_completed(futures):
            lang, project = futures[future]
            try:
                results[(lang, project)] = future.result()
            except Exception:
                logger.exception('Failed to fetch ns map for %s.%s', lang, project)
                results[(lang, project)] = dict(DEFAULT_NS_MAP)
    return results


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
    parsed_summary, rev_id, parent_rev_id.
    """
    # Newusers log events need special handling to match the format
    # the frontend (app.js) expects from the legacy v1 IRC feed.
    if event.get('type') == 'log' and event.get('log_type') == 'newusers':
        user = event.get('user', '')
        return {
            'page_title': 'Special:Log/newusers',
            'user': user,
            'is_anon': False,
            'is_bot': bool(event.get('bot', False)),
            'is_new': False,
            'is_minor': False,
            'is_unpatrolled': False,
            'change_size': 0,
            'url': event.get('log_action', 'create'),  # 'create' or 'byemail'
            'ns': 'Special',
            'summary': event.get('log_action_comment', ''),
            'action': 'newusers',
            'hashtags': [],
            'mentions': [],
            'section': None,
            'parsed_summary': event.get('log_action_comment', ''),
            'rev_id': None,
            'parent_rev_id': None,
        }

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
    elif length_new is not None and event_type == 'new':
        # New pages have no old length; all content is new
        change_size = length_new
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
    elif rev_new:
        # New pages have no old revision; link to the page directly
        url = f'{server_url}{server_script_path}/index.php?oldid={rev_new}'
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
    if event_type == 'new':
        action = 'new'
    else:
        action = 'edit'

    # Flags
    anon_flag = is_anon(user)
    is_bot = bool(event.get('bot', False))
    is_new = event_type == 'new'
    is_minor = bool(event.get('minor', False))
    is_unpatrolled = not bool(event.get('patrolled', True))

    msg = {
        'page_title': title,
        'user': user,
        'is_anon': anon_flag,
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


@dataclasses.dataclass
class LangChannel:
    """A single language channel: holds its config and connected clients."""
    lang: str
    project: str
    ws_path: str       # e.g. "/en/"
    ns_map: dict
    clients: set = dataclasses.field(default_factory=set)
    last_event_time: float = dataclasses.field(default_factory=time.time)


class MultiLangWikimonServer:
    """Multi-language server: one EventStreams consumer, per-language WebSocket channels."""

    def __init__(self, languages, port):
        self.port = port
        self.channels = {}          # server_name -> LangChannel
        self.path_to_channel = {}   # ws_path -> LangChannel
        self.msg_count = 0
        self.start_time = time.time()
        self._last_event_id = None
        self._last_event_time = time.time()
        self._reconnect_count = 0

        # Fetch all namespace maps in parallel
        ns_maps = fetch_all_namespace_maps(languages)
        logger.info('Fetched namespace maps for %d languages', len(ns_maps))

        for lang, project, ws_path in languages:
            server_name = _resolve_server_name(lang, project)
            ns_map = ns_maps.get((lang, project), dict(DEFAULT_NS_MAP))
            channel = LangChannel(lang, project, ws_path, ns_map)
            self.channels[server_name] = channel
            self.path_to_channel[ws_path] = channel
            # Also register bare path without trailing slash
            bare = ws_path.rstrip('/')
            if bare:
                self.path_to_channel[bare] = channel

    async def ws_handler(self, websocket, path=None):
        """Handle an individual WebSocket client connection.

        Compatible with websockets 9.x (websocket.path) through 13.x
        (websocket.request.path).
        """
        if path is None:
            try:
                path = websocket.path             # websockets 9.x-11.x
            except AttributeError:
                path = websocket.request.path      # websockets 12+
        # Normalize: strip trailing slash; bare "/" becomes "" then defaults to "/en"
        normalized = path.rstrip('/') or '/en'
        channel = self.path_to_channel.get(normalized)
        if channel is None:
            # Try with trailing slash as fallback
            channel = self.path_to_channel.get(normalized + '/')
        if channel is None:
            await websocket.close(4004, f'Unknown language path: {path}')
            return

        channel.clients.add(websocket)
        remote = websocket.remote_address
        logger.info('Client connected to %s: %s (total: %d)',
                    channel.lang, remote, len(channel.clients))
        try:
            # Keep connection open; we only send, never receive meaningful data
            async for _ in websocket:
                pass
        except websockets.ConnectionClosed:
            pass
        finally:
            channel.clients.discard(websocket)
            logger.info('Client disconnected from %s (total: %d)',
                        channel.lang, len(channel.clients))

    async def broadcast(self, channel, message):
        """Send a message string to all connected clients on a channel."""
        if not channel.clients:
            return
        stale = set()
        for ws in channel.clients:
            try:
                await ws.send(message)
            except websockets.ConnectionClosed:
                stale.add(ws)
            except Exception:
                logger.debug('Error sending to client', exc_info=True)
                stale.add(ws)
        channel.clients -= stale

    async def consume_eventstream(self):
        """Connect to EventStreams SSE and process events for all languages.

        Auto-reconnects with exponential backoff on failure.
        """
        backoff = 1
        max_backoff = 60

        while True:
            try:
                headers = {'User-Agent': USER_AGENT}
                if self._last_event_id:
                    headers['Last-Event-ID'] = self._last_event_id

                logger.info('Connecting to EventStreams (all languages, %d channels)',
                            len(self.channels))
                sse_timeout = aiohttp.ClientTimeout(total=None, sock_read=SSE_READ_TIMEOUT_SECONDS)
                async with aiohttp.ClientSession(timeout=sse_timeout) as session:
                    async with session.get(EVENTSTREAMS_URL, headers=headers) as resp:
                        if resp.status != 200:
                            logger.error('EventStreams HTTP %d, retry in %ds',
                                         resp.status, backoff)
                            await asyncio.sleep(backoff)
                            backoff = min(backoff * 2, max_backoff)
                            continue
                        backoff = 1  # Reset on successful connection
                        if self._reconnect_count > 0:
                            logger.info('EventStreams reconnected after %d retries', self._reconnect_count)
                        self._reconnect_count = 0
                        logger.info('Connected to EventStreams')

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

                                # Skip non-content events (but keep newusers log
                                # events — the frontend plays string swells for them)
                                evt_type = data.get('type')
                                if evt_type == 'categorize':
                                    continue
                                if evt_type == 'log' and data.get('log_type') != 'newusers':
                                    continue

                                # Dispatch to the correct channel.
                                # Newusers log events come from auth.wikimedia.org
                                # with a 'wiki' field like 'enwiki'; map to channel.
                                server_name = data.get('server_name')
                                channel = self.channels.get(server_name)
                                if channel is None and data.get('log_type') == 'newusers':
                                    channel = self._resolve_newuser_channel(data)
                                if channel is None:
                                    continue  # Not a language we serve

                                await self._process_event(data, channel)

            except asyncio.CancelledError:
                raise
            except Exception:
                self._reconnect_count += 1
                logger.warning('EventStreams error (#%d), reconnecting in %ds',
                               self._reconnect_count, backoff, exc_info=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    def _resolve_newuser_channel(self, data):
        """Map a newusers log event to the correct language channel.

        Newusers events have server_name='auth.wikimedia.org' and a
        'wiki' field like 'enwiki', 'dewiki', etc.  Extract the language
        code and look up the channel by constructed server_name.
        """
        wiki = data.get('wiki', '')
        # 'enwiki' -> 'en', 'dewiki' -> 'de', 'wikidatawiki' -> skip
        if wiki.endswith('wiki') and wiki != 'wikidatawiki':
            lang = wiki[:-4]  # strip 'wiki'
            if lang:
                server_name = f'{lang}.wikipedia.org'
                return self.channels.get(server_name)
        return None

    async def _process_event(self, event, channel):
        """Transform an event and broadcast it to the channel."""
        msg = transform_event(event, channel.ns_map)
        json_str = dumps(msg, sort_keys=True)
        self.msg_count += 1
        now = time.time()
        channel.last_event_time = now
        self._last_event_time = now
        logger.debug('Broadcasting to %s: %s', channel.lang, json_str[:200])
        await self.broadcast(channel, json_str)

    async def _periodic_stats(self):
        """Periodically log server stats."""
        while True:
            await asyncio.sleep(STATS_LOG_INTERVAL)
            uptime_hours = (time.time() - self.start_time) / 3600
            total_clients = sum(len(ch.clients) for ch in self.channels.values())
            per_lang = {ch.lang: len(ch.clients) for ch in self.channels.values()
                        if ch.clients}
            now = time.time()
            stats = {
                'msgs': self.msg_count,
                'total_clients': total_clients,
                'active_langs': per_lang,
                'num_channels': len(self.channels),
                'uptime_hours': round(uptime_hours, 2),
                'secs_since_last_event': round(now - self._last_event_time, 1),
                'reconnect_count': self._reconnect_count,
            }
            en_channel = self.path_to_channel.get('/en')
            if en_channel:
                stats['secs_since_last_en_event'] = round(now - en_channel.last_event_time, 1)
            else:
                stats['secs_since_last_en_event'] = None
            logger.info('stats: %s', dumps(stats))

            # Canary: English Wikipedia silence is the strongest signal
            if en_channel:
                en_silence = now - en_channel.last_event_time
                if en_silence > EN_STALE_THRESHOLD_SECONDS:
                    logger.warning(
                        'No en.wikipedia events in %.0fs -- stream likely dead', en_silence)

            # General staleness across all channels
            since_last = now - self._last_event_time
            if since_last > STALE_STREAM_THRESHOLD_SECONDS:
                logger.warning('No events processed in %.0fs -- stream may be stale', since_last)

    async def run(self):
        """Start the WebSocket server and EventStreams consumer."""
        logger.info('Starting multi-lang wikimon: %d channels, port=%d',
                    len(self.channels), self.port)

        async with websockets.serve(self.ws_handler, '0.0.0.0', self.port):
            logger.info('WebSocket server listening on 0.0.0.0:%d', self.port)
            await asyncio.gather(
                self.consume_eventstream(),
                self._periodic_stats(),
            )


def get_argparser():
    desc = "Broadcast realtime Wikimedia edits over WebSockets (multi-language)"
    prs = ArgumentParser(description=desc)
    prs.add_argument('--port', default=DEFAULT_BCAST_PORT, type=int,
                     help='single listen port for all WebSocket connections')
    prs.add_argument('--lang', default=None,
                     help='run a single language only (for testing); omit for all')
    prs.add_argument('--project', default=DEFAULT_PROJECT,
                     help='project (used with --lang)')
    prs.add_argument('--debug', default=False, action='store_true')
    prs.add_argument('--loglevel', default='WARN',
                     help='e.g., DEBUG, INFO, WARN')
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

    # Language selection
    if args.lang:
        languages = [(args.lang, args.project, f'/{args.lang}/')]
    else:
        languages = DEFAULT_LANGUAGES

    # Run
    server = MultiLangWikimonServer(
        languages=languages,
        port=args.port,
    )

    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logger.info('Shutting down')


if __name__ == '__main__':
    main()
