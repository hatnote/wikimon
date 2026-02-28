# WikiMon

Watch the [Wikimedia EventStreams](https://stream.wikimedia.org/?doc)
feed with Python. Support for various Wikimedia projects and languages.


## Usage

WikiMon broadcasts real-time Wikimedia edits over WebSocket. Point a
WebSocket client at `wss://wikimon.hatnote.com/en/` (or any supported
language path like `/de/`, `/ja/`, `/wikidata/`, etc.).

To run your own instance:

```
usage: python -m wikimon.monitor [-h] [--port PORT] [--lang LANG]
                                 [--project PROJECT] [--geoip-db GEOIP_DB]
                                 [--debug] [--loglevel LOGLEVEL]

Broadcast realtime Wikimedia edits over WebSockets (multi-language)

optional arguments:
    -h, --help           show this help message and exit
    --port PORT          listen port for WebSocket connections
    --lang LANG          run a single language only (for testing); omit for all
    --project PROJECT    project (used with --lang)
    --geoip-db GEOIP_DB  path to the GeoLite2 database
    --debug
    --loglevel LOGLEVEL  e.g., DEBUG, INFO, WARN
```

By default (no `--lang`), the server handles all 43 supported languages
on a single port, routing by WebSocket path.

### Requirements

 - Python 3.10+
 - aiohttp
 - websockets
 - maxminddb
 - requests


## Format

Here are a couple example messages, as broadcast over WebSocket:

```json
{
  "action": "edit",
  "change_size": 19,
  "hashtags": [],
  "is_anon": false,
  "is_bot": false,
  "is_minor": true,
  "is_new": false,
  "is_unpatrolled": false,
  "mentions": [],
  "ns": "User talk",
  "page_title": "User talk:Manxruler",
  "parent_rev_id": "775894803",
  "rev_id": "775894650",
  "summary": "/* The battle of Kristiansand (1940) */",
  "url": "https://en.wikipedia.org/w/index.php?diff=775894803&oldid=775894650",
  "user": "Carsten R D"
}

{
  "action": "edit",
  "change_size": -12,
  "geo_ip": {
    "city": "Salisbury",
    "country_name": "United States",
    "latitude": 38.3761,
    "longitude": -75.6086,
    "region_name": "Maryland"
  },
  "hashtags": [],
  "is_anon": true,
  "is_bot": false,
  "is_minor": false,
  "is_new": false,
  "is_unpatrolled": false,
  "mentions": [],
  "ns": "Main",
  "page_title": "Evanescence (Evanescence album)",
  "parent_rev_id": "775894800",
  "rev_id": "774995266",
  "summary": "/* Credits and personnel */ \"Personnel\" is sufficient",
  "url": "https://en.wikipedia.org/w/index.php?diff=775894800&oldid=774995266",
  "user": "71.200.123.192"
}
```

The set of keys is always the same. Anonymous edits include a `geo_ip`
dict with geographic information; registered user edits have an empty
`geo_ip` dict.

## Geolocation

Geolocation is done in-process using MaxMind's GeoLite2-City database.
See the `geodb/` directory for more info. The `GeoIPManager` checks for
database file updates periodically and reloads automatically.

## See also

* [listen-to-wikipedia](https://github.com/hatnote/listen-to-wikipedia)
* [hatnote](https://github.com/hatnote)
* [Stephen LaPorte](https://github.com/slaporte)
* [Mahmoud Hashemi](https://github.com/mahmoud)
