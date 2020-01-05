# WikiMon

Watch the [RecentChanges IRC
feed](http://meta.wikimedia.org/wiki/Research:Data#IRC_Feeds) with
Python. Support for various WikiMedia projects and languages.


## Usage

At the moment, WikiMon's primary usage pattern is broadcasting changes
over WebSocket. If you'd simply like to consume these messages, feel
free to point a WebSocket client (such as your browser or Autobahn) at
`http://wikimon.hatnote.com/en/`.

If you'd like to run your own copy of WikiMon, install the
requirements below, and run the `monitor_websocket.py` command as
follows:

```
usage: monitor_websocket.py [-h] [--project PROJECT] [--lang LANG]
                            [--port PORT] [--debug] [--loglevel LOGLEVEL]

broadcast realtime edits to a Mediawiki project over websockets

optional arguments:
    -h, --help           show this help message and exit
    --project PROJECT
    --lang LANG
    --port PORT          listen port for websocket connections
    --debug
    --loglevel LOGLEVEL
```

### Requirements

 - Twisted==13.0.0
 - autobahn==0.5.14
 - [wapiti](https://github.com/mahmoud/wapiti)


## Format

Here are a couple example messages, as broadcast over WebSocket:

```json
{
  "action": "edit",
  "change_size": 19,
  "flags": "M",
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
  "flags": null,
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

As you can see, the set of keys sent is always the same. Note that the
`flags` key is redundant, as it is parsed out into `is_minor`,
`is_bot`, `is_unpatrolled`, and `is_new`.

## Geolocation

Geolocation is done in process, using maxmind's free dataset. See the GeoDB directory for more info.

## See also

* [wikimon](https://github.com/hatnote/wikimon)
* [hatnote](https://github.com/hatnote)
* [Stephen LaPorte](https://github.com/slaporte)
* [Mahmoud Hashemi](https://github.com/mahmoud).
