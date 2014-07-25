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

{"is_minor": false,
 "page_title": "Template:Citation needed/testcases",
 "url": "http://en.wikipedia.org/w/index.php?diff=553804313&oldid=479472901",
 "is_unpatrolled": false,
 "is_bot": false,
 "is_new": false,
 "summary": null,
 "flags": null,
 "user": "98.172.160.184",
 "is_anon": true,
 "ns": "Template",
 "change_size": "+42"}

{"is_minor": true,
 "page_title": "Generalized anxiety disorder",
 "url": "http://en.wikipedia.org/w/index.php?diff=553804315&oldid=553370901",
 "is_unpatrolled": false,
 "is_bot": false,
 "is_new": false,
 "summary": "minor editing in sentences.",
 "flags": "M",
 "user": "BriannaMaxim",
 "is_anon": false,
 "ns": "Main",
 "change_size": "+1"}
```

As you can see, the set of keys sent is always the same. Note that the
`flags` key is redundant, as it is parsed out into `is_minor`,
`is_bot`, `is_unpatrolled`, and `is_new`.

## Geolocation

Geolocation is currently done through a local FreeGeoIP
instance. FreeGeoIP requires Go and several Go libraries. It also
requires memcached to be running on port 11211.

The command used to run FreeGeoIP at the moment:

```
GOPATH=/home/hatnote/gopkg/ GOROOT=/home/hatnote/go nohup /home/hatnote/go/bin/go run freegeoip.go &
```


## See also

* [wikimon](https://github.com/hatnote/wikimon)
* [hatnote](https://github.com/hatnote)
* [Stephen LaPorte](https://github.com/slaporte)
* [Mahmoud Hashemi](https://github.com/mahmoud).
