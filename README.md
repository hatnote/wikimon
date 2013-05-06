# WikiMon

Watch the [RecentChanges IRC
feed](http://meta.wikimedia.org/wiki/Research:Data#IRC_Feeds) with
Python. Support for various WikiMedia projects and languages.

## Requirements

 - Twisted==13.0.0
 - autobahn==0.5.14
 - [wapiti](https://github.com/mahmoud/wapiti)

## Usage

At the moment, WikiMon's primary usage pattern is broadcasting changes
over WebSocket. To do that, simply run `monitor_websocket.py`:

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


## See also

* [wikimon](https://github.com/hatnote/wikimon)
* [hatnote](https://github.com/hatnote)
* [Stephen LaPorte](https://github.com/slaporte)
* [Mahmoud Hashemi](https://github.com/mahmoud).
