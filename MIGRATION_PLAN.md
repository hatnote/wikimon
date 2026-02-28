# Wikimon: Single-Process Refactor and Parallel Deployment Plan

## Context and Current State

### Architecture Overview

Wikimon broadcasts real-time Wikimedia edits over WebSockets. The system has two codepaths in the repo:

| Component | File | Stack | Status |
|---|---|---|---|
| Legacy monitor | `monitor_websocket.py` | Twisted + IRC + Autobahn (Python 2 syntax) | Dead code, never runs |
| Legacy GeoIP | `monitor_geolite2.py` | Twisted LoopingCall + `geoip` library | Dead code |
| Modern monitor | `monitor.py` | asyncio + aiohttp + websockets + maxminddb | **Active**, deployed |
| Parsers | `parsers.py` | Pure Python 3 | Shared, stable |

### Current Deployment (Production Server)

**37 separate supervisor processes**, one per language, each running:

```
/home/hatnote/virtualenvs/wikimon/bin/python -m wikimon.monitor \
    --project wikipedia --lang <LANG> --port <PORT> --loglevel INFO \
    --geoip-db /home/hatnote/wikimon/geodb/GeoLite2-City.mmdb
```

Languages and ports (from `conf/supervisord.conf`):

| Lang | Port | Lang | Port | Lang | Port | Lang | Port |
|---|---|---|---|---|---|---|---|
| en | 9000 | fr | 9050 | ta | 9110 | sa | 9190 |
| de | 9010 | nl | 9060 | pa | 9120 | gu | 9200 |
| ru | 9020 | it | 9070 | mr | 9130 | fa | 9210 |
| ja | 9030 | sv | 9080 | hi | 9140 | wikidata | 9220 |
| es | 9040 | ar | 9090 | as | 9150 | he | 9230 |
| | | id | 9100 | bn | 9160 | zh | 9240 |
| | | | | te | 9165 | ml | 9250 |
| | | | | kn | 9170 | pl | 9260 |
| | | | | or | 9180 | mk | 9270 |

Plus: be (9280), sr (9290), bg (9300), uk (9310), hu (9320), fi (9330), no (9340), el (9350), eo (9360), pt (9370), et (9380), ur (9390), ro (9400), hy (9410).

### Nginx (from `conf/wikimon.nginx.conf`)

Each language has a dedicated `location` block proxying to its individual port:

```nginx
location /       { proxy_pass http://127.0.0.1:9000; }   # en (default)
location /en/    { proxy_pass http://127.0.0.1:9000; }
location /de/    { proxy_pass http://127.0.0.1:9010; }
# ... 35 more entries
```

### Problems with Current Architecture

1. **37 processes** each open their own EventStreams SSE connection, GeoIP database handle, and asyncio event loop
2. **37 SSE connections** to `stream.wikimedia.org` for what is a single shared stream
3. **37 GeoIP database handles** to the same `.mmdb` file
4. Adding a new language requires: new supervisor entry, new nginx location, port allocation, restart
5. Memory footprint: ~37 Python interpreters resident
6. Operational complexity: `supervisorctl status` shows 37 entries; failures hide in noise

---

## Phase 1: Single-Process Refactor (Local Development)

### 1.1 Language Registry

Define the supported languages as a data structure in `monitor.py` rather than requiring one process per language:

```python
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
```

### 1.2 Multi-Language WikimonServer

Replace the current single-lang `WikimonServer` with a `MultiLangWikimonServer` that:

- Maintains a `dict[str, LangChannel]` keyed by `server_name` (e.g., `en.wikipedia.org`)
- Each `LangChannel` holds: `lang`, `project`, `ws_path`, `ns_map`, `clients: set[websocket]`
- Opens **one** EventStreams SSE connection (the stream already carries all wikis)
- Dispatches each event to the correct `LangChannel` by matching `event['server_name']`

```python
@dataclasses.dataclass
class LangChannel:
    lang: str
    project: str
    ws_path: str          # e.g. "/en/"
    ns_map: dict
    clients: set = dataclasses.field(default_factory=set)

class MultiLangWikimonServer:
    def __init__(self, languages, port, geoip_manager):
        self.port = port
        self.geoip = geoip_manager
        self.channels: dict[str, LangChannel] = {}  # server_name -> LangChannel
        self.path_to_channel: dict[str, LangChannel] = {}  # ws_path -> LangChannel

        for lang, project, ws_path in languages:
            server_name = _resolve_server_name(lang, project)
            ns_map = fetch_namespace_map(lang, project)
            channel = LangChannel(lang, project, ws_path, ns_map)
            self.channels[server_name] = channel
            self.path_to_channel[ws_path] = channel
            # Also register bare path without trailing slash
            self.path_to_channel[ws_path.rstrip('/')] = channel
```

### 1.3 Path-Based WebSocket Routing

Clients connect to `wss://wikimon.hatnote.com/en/`, `wss://wikimon.hatnote.com/de/`, etc. The server routes by the request path:

```python
async def ws_handler(self, websocket):
    path = websocket.request.path  # e.g. "/en/" or "/en"
    # Normalize: strip trailing slash, default "/" to "/en/"
    normalized = path.rstrip('/') or '/en'
    channel = self.path_to_channel.get(normalized)
    if channel is None:
        # Also try with trailing slash
        channel = self.path_to_channel.get(normalized + '/')
    if channel is None:
        await websocket.close(4004, f'Unknown language path: {path}')
        return

    channel.clients.add(websocket)
    logger.info('Client connected to %s: %s (total: %d)',
                channel.lang, websocket.remote_address, len(channel.clients))
    try:
        async for _ in websocket:
            pass
    except websockets.ConnectionClosed:
        pass
    finally:
        channel.clients.discard(websocket)
        logger.info('Client disconnected from %s (total: %d)',
                    channel.lang, len(channel.clients))
```

The root path `/` should map to English for backwards compatibility (existing clients connecting without a language path).

### 1.4 Single EventStreams Consumer with Event Dispatch

One SSE connection, no `server_name` filter — process all events, dispatch by `server_name`:

```python
async def consume_eventstream(self):
    backoff = 1
    max_backoff = 60

    while True:
        try:
            headers = {'User-Agent': USER_AGENT}
            if self._last_event_id:
                headers['Last-Event-ID'] = self._last_event_id

            logger.info('Connecting to EventStreams (all languages, %d channels)',
                        len(self.channels))
            async with aiohttp.ClientSession() as session:
                async with session.get(EVENTSTREAMS_URL, headers=headers,
                                       timeout=None) as resp:
                    if resp.status != 200:
                        logger.error('EventStreams HTTP %d, retry in %ds',
                                     resp.status, backoff)
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, max_backoff)
                        continue
                    backoff = 1
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
                            if event_id:
                                self._last_event_id = event_id
                            try:
                                data = json.loads(event_data)
                            except json.JSONDecodeError:
                                event_data = None
                                continue
                            event_data = None

                            # Dispatch to the correct channel
                            server_name = data.get('server_name')
                            channel = self.channels.get(server_name)
                            if channel is None:
                                continue  # Not a language we serve

                            await self._process_event(data, channel)

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('EventStreams error, reconnecting in %ds', backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
```

### 1.5 Event Processing and Broadcast

```python
async def _process_event(self, event, channel):
    msg = transform_event(event, channel.ns_map)

    if msg['is_anon'] and msg['user']:
        loop = asyncio.get_running_loop()
        geo = await loop.run_in_executor(None, self.geoip.lookup, msg['user'])
        msg['geo_ip'] = geo
    else:
        msg['geo_ip'] = {}

    json_str = dumps(msg, sort_keys=True)
    self.msg_count += 1

    if not channel.clients:
        return
    stale = set()
    for ws in channel.clients:
        try:
            await ws.send(json_str)
        except websockets.ConnectionClosed:
            stale.add(ws)
        except Exception:
            logger.debug('Send error', exc_info=True)
            stale.add(ws)
    channel.clients -= stale
```

### 1.6 Namespace Map Fetching

At startup, fetch namespace maps for all languages. This is a blocking synchronous call per language (using `requests`). With 37 languages, this takes ~15-30 seconds sequentially. To speed it up, use `concurrent.futures.ThreadPoolExecutor`:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def fetch_all_namespace_maps(languages):
    """Fetch namespace maps for all languages in parallel."""
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
```

### 1.7 CLI Changes

Update `get_argparser()` and `main()`:

```python
def get_argparser():
    desc = "Broadcast realtime Wikimedia edits over WebSockets (multi-language)"
    prs = ArgumentParser(description=desc)
    prs.add_argument('--geoip-db', default=None,
                     help='path to the GeoLite2 database')
    prs.add_argument('--geoip-update-interval',
                     default=DEFAULT_GEOIP_UPDATE_INTERVAL, type=int,
                     help='seconds between GeoIP db mtime checks')
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

    # Logging setup (unchanged)
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

    # GeoIP
    geoip_db_path = args.geoip_db or DEFAULT_GEOIP_DB
    geoip = GeoIPManager(geoip_db_path, args.geoip_update_interval)

    # Language selection
    if args.lang:
        languages = [(args.lang, args.project, f'/{args.lang}/')]
    else:
        languages = DEFAULT_LANGUAGES

    # Run
    server = MultiLangWikimonServer(
        languages=languages,
        port=args.port,
        geoip_manager=geoip,
    )

    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logger.info('Shutting down')
    finally:
        geoip.close()
```

### 1.8 Periodic Stats (Aggregate)

```python
async def _periodic_stats(self):
    while True:
        await asyncio.sleep(STATS_LOG_INTERVAL)
        uptime_hours = (time.time() - self.start_time) / 3600
        total_clients = sum(len(ch.clients) for ch in self.channels.values())
        per_lang = {ch.lang: len(ch.clients) for ch in self.channels.values()
                    if ch.clients}
        stats = {
            'msgs': self.msg_count,
            'total_clients': total_clients,
            'active_langs': per_lang,
            'num_channels': len(self.channels),
            'uptime_hours': round(uptime_hours, 2),
        }
        logger.info('stats: %s', dumps(stats))
```

### 1.9 Server `run()` Method

```python
async def run(self):
    logger.info('Starting multi-lang wikimon: %d channels, port=%d',
                len(self.channels), self.port)

    async with websockets.serve(self.ws_handler, '0.0.0.0', self.port):
        logger.info('WebSocket server listening on 0.0.0.0:%d', self.port)
        await asyncio.gather(
            self.consume_eventstream(),
            self._periodic_geoip_check(),
            self._periodic_stats(),
        )
```

### 1.10 Tests

Existing `test_monitor.py` tests for `transform_event` and `GeoIPManager` remain valid and unchanged. Add new tests:

**`test_multi_lang_server.py`** — unit tests for the new server:

```python
import pytest
from wikimon.monitor import (
    MultiLangWikimonServer, LangChannel,
    _resolve_server_name, DEFAULT_LANGUAGES,
)

class TestLangChannelRouting:
    def test_path_routing_basic(self):
        server = make_test_server([('en', 'wikipedia', '/en/')])
        assert '/en/' in server.path_to_channel
        assert '/en' in server.path_to_channel

    def test_root_path_maps_to_en(self):
        server = make_test_server(DEFAULT_LANGUAGES)
        # "/" should resolve to en channel
        ch = server.path_to_channel.get('/en')
        assert ch is not None
        assert ch.lang == 'en'

    def test_unknown_path_returns_none(self):
        server = make_test_server([('en', 'wikipedia', '/en/')])
        assert server.path_to_channel.get('/xx') is None

    def test_wikidata_routing(self):
        server = make_test_server([('wikidata', 'wikidata', '/wikidata/')])
        ch = server.path_to_channel.get('/wikidata')
        assert ch is not None
        assert ch.project == 'wikidata'

class TestServerNameDispatch:
    def test_en_wikipedia(self):
        assert _resolve_server_name('en', 'wikipedia') == 'en.wikipedia.org'

    def test_wikidata(self):
        assert _resolve_server_name('wikidata', 'wikidata') == 'www.wikidata.org'

    def test_channel_keyed_by_server_name(self):
        server = make_test_server([('de', 'wikipedia', '/de/')])
        assert 'de.wikipedia.org' in server.channels
```

### 1.11 Config Updates

**New `conf/supervisord.conf`** (single entry):

```ini
[program:wikimon]
command=/home/hatnote/wikimon-v2/venv/bin/python -m wikimon.monitor --port 9500 --loglevel INFO --geoip-db /home/hatnote/wikimon/geodb/GeoLite2-City.mmdb
directory=/home/hatnote/wikimon-v2
user=hatnote
autostart=true
autorestart=true
stderr_logfile=/home/hatnote/wikimon-v2/logs/wikimon.err.log
stdout_logfile=/home/hatnote/wikimon-v2/logs/wikimon.out.log
```

**New `conf/wikimon.nginx.conf`**:

```nginx
server {
    server_name  wikimon.hatnote.com;
    listen 443 ssl;

    ssl_certificate /etc/letsencrypt/live/hatnote.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/hatnote.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    access_log  /home/hatnote/wikimon-v2/logs/access.log combined buffer=128k flush=10s;
    error_log   /home/hatnote/wikimon-v2/logs/error.log;

    proxy_http_version 1.1;
    proxy_set_header   Upgrade $http_upgrade;
    proxy_set_header   Connection "Upgrade";
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_read_timeout 86400s;
    proxy_send_timeout 86400s;

    # Single upstream — the multi-lang server handles path routing internally
    location / {
        proxy_pass http://127.0.0.1:9500;
    }
}

server {
    server_name  wikimon.hatnote.com;
    listen 80;
    return 301 https://$host$request_uri;
}
```

---

## Phase 2: Server Preparation

### 2.1 Python 3.10+ Virtual Environment

```bash
# On the production server as hatnote user
python3.10 -m venv /home/hatnote/wikimon-v2/venv
source /home/hatnote/wikimon-v2/venv/bin/activate
```

### 2.2 Deploy to `/home/hatnote/wikimon-v2/`

```bash
# Clone or copy the refactored code
cd /home/hatnote
git clone https://github.com/hatnote/wikimon.git wikimon-v2
cd wikimon-v2
git checkout <refactored-branch>

# Install
/home/hatnote/wikimon-v2/venv/bin/pip install -e .

# Create log directory
mkdir -p /home/hatnote/wikimon-v2/logs
```

### 2.3 GeoIP Database

The GeoIP database lives at `/home/hatnote/wikimon/geodb/GeoLite2-City.mmdb`. The new server can reference it at the same path. No copy needed — the `--geoip-db` flag points to the existing file. The existing crontab (`conf/wikimon_crontab`) continues to update it in place.

### 2.4 Smoke Test (Local)

```bash
# Test with a single language first
/home/hatnote/wikimon-v2/venv/bin/python -m wikimon.monitor \
    --lang en --port 9500 --loglevel DEBUG \
    --geoip-db /home/hatnote/wikimon/geodb/GeoLite2-City.mmdb

# In another terminal, connect a test client
python3 -c "
import asyncio, websockets
async def test():
    async with websockets.connect('ws://localhost:9500/en/') as ws:
        msg = await asyncio.wait_for(ws.recv(), timeout=30)
        print('Received:', msg[:200])
asyncio.run(test())
"
```

---

## Phase 3: Parallel Deployment

### 3.1 Start New Stack on Port 9500

The new multi-lang server runs on port 9500, which is unused. The old per-language servers remain running on ports 9000-9410. Both stacks operate simultaneously — no conflict.

```bash
# Add the new supervisor entry (does NOT replace old ones yet)
sudo supervisorctl reread
sudo supervisorctl add wikimon
sudo supervisorctl start wikimon

# Verify it started
sudo supervisorctl status wikimon
# Should show RUNNING

# Check logs
tail -f /home/hatnote/wikimon-v2/logs/wikimon.out.log
# Should see: "Connected to EventStreams" and periodic stats
```

### 3.2 Nginx `/v2/` Test Route

Add a temporary test route in nginx to validate the new stack without touching production traffic:

```nginx
# Add inside the existing server{} block, BEFORE the existing location blocks
location /v2/ {
    # Strip /v2 prefix, forward the rest to the new server
    rewrite ^/v2/(.*) /$1 break;
    proxy_pass http://127.0.0.1:9500;
}
```

```bash
sudo nginx -t && sudo nginx -s reload
```

Now test:
- `wss://wikimon.hatnote.com/v2/en/` → new stack, English
- `wss://wikimon.hatnote.com/v2/de/` → new stack, German
- `wss://wikimon.hatnote.com/en/` → old stack (unchanged)

### 3.3 Validation Checklist

Run these checks against the `/v2/` endpoint:

| Check | Command | Expected |
|---|---|---|
| EN connects | `wscat -c wss://wikimon.hatnote.com/v2/en/` | Receives JSON edits |
| DE connects | `wscat -c wss://wikimon.hatnote.com/v2/de/` | Receives JSON edits |
| Wikidata connects | `wscat -c wss://wikimon.hatnote.com/v2/wikidata/` | Receives JSON edits |
| Root path | `wscat -c wss://wikimon.hatnote.com/v2/` | Connects (routes to EN) |
| Unknown lang | `wscat -c wss://wikimon.hatnote.com/v2/xx/` | Close frame 4004 |
| JSON shape | Parse first message | Has all EXPECTED_KEYS + `geo_ip` |
| `geo_ip` for anon | Wait for anonymous edit | `geo_ip` dict has lat/lon |
| `ns` field | Wait for Talk/User edit | Namespace name, not numeric ID |
| Stats logging | `grep 'stats:' wikimon.out.log` | Logs every 2 minutes |
| Memory | `ps aux \| grep wikimon` | Single process, ~50-100 MB |

### 3.4 Burn-In Period

Run both stacks in parallel for **at least 48 hours**. Monitor:

```bash
# Compare message rates (old vs new)
# Old stack stats are in individual log files:
grep 'stats:' /home/hatnote/wikimon/logs/wikimon_en.out.log | tail -1

# New stack stats (aggregate):
grep 'stats:' /home/hatnote/wikimon-v2/logs/wikimon.out.log | tail -1

# Watch for reconnections in new stack:
grep -c 'reconnecting' /home/hatnote/wikimon-v2/logs/wikimon.out.log
```

Success criteria:
- Zero crashes in 48 hours
- Message rate parity with old stack (within 5%)
- No memory growth (check RSS at start and after 48h)
- All 37 language channels producing events

---

## Phase 4: Cutover

### 4.1 Nginx Swap

Replace all 37 location blocks with a single proxy to port 9500.

**Before** (37 entries):
```nginx
location /       { proxy_pass http://127.0.0.1:9000; }
location /en/    { proxy_pass http://127.0.0.1:9000; }
location /de/    { proxy_pass http://127.0.0.1:9010; }
# ... 34 more
```

**After** (1 entry):
```nginx
location / {
    proxy_pass http://127.0.0.1:9500;
}
```

Also remove the temporary `/v2/` route.

```bash
# Backup current nginx config
sudo cp /etc/nginx/sites-enabled/wikimon.conf /etc/nginx/sites-enabled/wikimon.conf.bak

# Deploy new config
sudo cp /home/hatnote/wikimon-v2/conf/wikimon.nginx.conf /etc/nginx/sites-enabled/wikimon.conf

# Test and reload
sudo nginx -t && sudo nginx -s reload
```

### 4.2 Verify Production

Immediately after the nginx swap:

```bash
# Quick smoke test — should connect to new stack now
wscat -c wss://wikimon.hatnote.com/en/

# Test a few languages
for lang in en de ru ja es fr wikidata; do
    echo "Testing $lang..."
    timeout 10 wscat -c "wss://wikimon.hatnote.com/$lang/" --no-color | head -1
done
```

### 4.3 Stop Legacy Processes

Once production is confirmed working on the new stack:

```bash
# Stop all old wikimon processes
sudo supervisorctl stop wikimon_en wikimon_de wikimon_ru wikimon_ja wikimon_es \
    wikimon_fr wikimon_nl wikimon_it wikimon_sv wikimon_ar wikimon_id wikimon_ta \
    wikimon_pa wikimon_mr wikimon_hi wikimon_as wikimon_bn wikimon_te wikimon_kn \
    wikimon_or wikimon_sa wikimon_gu wikimon_fa wikimon_wikidata wikimon_he \
    wikimon_zh wikimon_ml wikimon_pl wikimon_mk wikimon_be wikimon_sr wikimon_bg \
    wikimon_uk wikimon_hu wikimon_fi wikimon_no wikimon_el wikimon_eo wikimon_pt \
    wikimon_et wikimon_ur wikimon_ro wikimon_hy

# Verify they're stopped
sudo supervisorctl status | grep wikimon_
# All should show STOPPED
```

### 4.4 Fix `listen.hatnote.com` Config

If `listen.hatnote.com` (the frontend) connects directly to per-language wikimon ports (bypassing nginx), update its config to use the new single endpoint. The frontend JavaScript (`app.js`) likely opens a WebSocket to `wss://wikimon.hatnote.com/<lang>/` — this continues to work after the nginx swap with no change needed.

If any backend-to-backend connections exist that bypass nginx and hit `localhost:9000` directly, they must be updated to `localhost:9500/<lang>/`.

---

## Phase 5: Cleanup

### 5.1 Remove Legacy Supervisor Entries

```bash
# Remove old supervisor config entries
# Either edit the supervisord conf to remove all wikimon_* entries,
# or remove the old config file entirely and replace with the single-entry version
sudo supervisorctl remove wikimon_en wikimon_de wikimon_ru wikimon_ja wikimon_es \
    wikimon_fr wikimon_nl wikimon_it wikimon_sv wikimon_ar wikimon_id wikimon_ta \
    wikimon_pa wikimon_mr wikimon_hi wikimon_as wikimon_bn wikimon_te wikimon_kn \
    wikimon_or wikimon_sa wikimon_gu wikimon_fa wikimon_wikidata wikimon_he \
    wikimon_zh wikimon_ml wikimon_pl wikimon_mk wikimon_be wikimon_sr wikimon_bg \
    wikimon_uk wikimon_hu wikimon_fi wikimon_no wikimon_el wikimon_eo wikimon_pt \
    wikimon_et wikimon_ur wikimon_ro wikimon_hy

sudo supervisorctl reread
sudo supervisorctl update
```

### 5.2 Remove Dead Code from Repo

Delete legacy files that are no longer referenced:

- `wikimon/monitor_websocket.py` — Twisted/IRC monitor (Python 2, dead code)
- `wikimon/monitor_geolite2.py` — Twisted GeoIP monitor (dead code)
- `wikimon/test_monitor_websocket.py` — Tests for dead code

These files import modules that are not in `requirements.txt` (`twisted`, `autobahn`, `wapiti`, `geoip`) and contain Python 2 syntax (`print` statements without parens). They cannot run and serve no purpose.

### 5.3 Decommission Old Virtual Environment

```bash
# After confirming everything works for at least 1 week on the new stack
# Keep the old venv for 30 days as insurance, then remove
rm -rf /home/hatnote/virtualenvs/wikimon
```

### 5.4 Update Crontab (If Needed)

The GeoIP crontab (`conf/wikimon_crontab`) updates the database at `/home/hatnote/wikimon/geodb/`. If the new server's `--geoip-db` flag points to this same path, no crontab change is needed. The `GeoIPManager` detects mtime changes and reloads automatically.

If the deployment is fully moved to `/home/hatnote/wikimon-v2/`, update the crontab path:

```cron
GEODB_DIR=/home/hatnote/wikimon-v2/geodb/
```

Or symlink: `ln -s /home/hatnote/wikimon/geodb /home/hatnote/wikimon-v2/geodb`

---

## Rollback Plan

At every phase, rollback is a simple config swap:

| Phase | Rollback |
|---|---|
| Phase 1 (code) | `git revert` or `git checkout main` |
| Phase 2 (deploy) | Don't start supervisor entry |
| Phase 3 (parallel) | Remove `/v2/` nginx route, stop new supervisor entry |
| Phase 4 (cutover) | Restore `wikimon.conf.bak`, `sudo nginx -s reload`, restart old supervisor entries |
| Phase 5 (cleanup) | If old entries are removed, re-add them from git history |

**Critical rollback scenario** — if Phase 4 cutover fails:

```bash
# 1. Restore nginx
sudo cp /etc/nginx/sites-enabled/wikimon.conf.bak /etc/nginx/sites-enabled/wikimon.conf
sudo nginx -t && sudo nginx -s reload

# 2. Restart old processes (if stopped)
sudo supervisorctl start wikimon_en wikimon_de wikimon_ru wikimon_ja wikimon_es \
    wikimon_fr wikimon_nl wikimon_it wikimon_sv wikimon_ar wikimon_id wikimon_ta \
    wikimon_pa wikimon_mr wikimon_hi wikimon_as wikimon_bn wikimon_te wikimon_kn \
    wikimon_or wikimon_sa wikimon_gu wikimon_fa wikimon_wikidata wikimon_he \
    wikimon_zh wikimon_ml wikimon_pl wikimon_mk wikimon_be wikimon_sr wikimon_bg \
    wikimon_uk wikimon_hu wikimon_fi wikimon_no wikimon_el wikimon_eo wikimon_pt \
    wikimon_et wikimon_ur wikimon_ro wikimon_hy

# 3. Stop new process
sudo supervisorctl stop wikimon
```

Time to full rollback: **< 60 seconds**.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Single process crash kills all languages | Low | High | Supervisor `autorestart=true`; the same EventStreams SSE reconnect logic with exponential backoff exists in the new code. Process restarts in ~2s. |
| Memory pressure from 37 channel client sets in one process | Low | Medium | Each client set is just a `set()` of lightweight WebSocket references. ~37 sets vs. 37 processes is a net reduction. Monitor RSS during burn-in. |
| EventStreams SSE volume overwhelms single consumer | Low | Low | EventStreams delivers ~50-200 events/sec across all wikis. The current code already parses JSON and broadcasts per event. Single-threaded async handles this easily. |
| Namespace map fetch at startup takes too long (37 API calls) | Medium | Low | Mitigated by `ThreadPoolExecutor(max_workers=10)`. Total time: ~5-10s instead of ~30-60s sequential. Failure falls back to `DEFAULT_NS_MAP`. |
| `listen.hatnote.com` breaks due to changed port | Medium | High | Investigate `listen.hatnote.com` config before cutover. If it connects via nginx (likely), no change needed. If it connects to `localhost:9000` directly, update to `localhost:9500/en/`. |
| WebSocket path routing rejects clients using bare `/` | Low | Medium | Root path `/` maps to English channel for backwards compatibility. Tested in validation checklist. |
| GeoIP database path mismatch after deployment | Low | Low | `--geoip-db` flag explicitly set in supervisor config. Verified during smoke test. |
| Old supervisor entries auto-restart after stop | None | None | Use `supervisorctl remove` (Phase 5), not just `stop`, to prevent restart. |

---

## Summary

| Metric | Before | After |
|---|---|---|
| Processes | 37 | 1 |
| Ports | 37 (9000-9410) | 1 (9500) |
| SSE connections to Wikimedia | 37 | 1 |
| GeoIP database handles | 37 | 1 |
| Nginx location blocks | 37 | 1 |
| Supervisor entries | 37 | 1 |
| Memory (estimated) | ~1.5-2 GB (37 x ~40-50 MB) | ~50-100 MB |
| Adding a new language | 3 config files + restart | 1 line in `DEFAULT_LANGUAGES` + restart |
| Rollback time | N/A | < 60 seconds |
