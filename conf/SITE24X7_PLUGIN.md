# wikimon_plugin (Site24x7)

Custom Site24x7 monitoring plugin for wikimon v2. Reads the last `stats:` line from the wikimon stderr log and reports metrics to Site24x7.

## Metrics reported

- `msgs` -- total events processed since start
- `total_clients` -- connected WebSocket clients
- `uptime_hours` -- process uptime
- `secs_since_last_event` -- seconds since any event (stream health)
- `secs_since_last_en_event` -- seconds since an en.wiki event
- `reconnect_count` -- SSE reconnections since start
- `secs_since_log` -- seconds since last stats line was written
- `open_files` / `total_files` -- system file descriptor usage

## Installation

Copy the plugin to the Site24x7 agent plugins directory:

```
sudo mkdir -p /opt/site24x7/monagent/plugins/wikimon_plugin
sudo cp conf/wikimon_plugin.py /opt/site24x7/monagent/plugins/wikimon_plugin/
sudo chown -R site24x7-agent:site24x7-group /opt/site24x7/monagent/plugins/wikimon_plugin
sudo chmod 700 /opt/site24x7/monagent/plugins/wikimon_plugin/wikimon_plugin.py
```

The agent picks up the plugin automatically within a few minutes. No restart needed.

## Testing locally

```
python3 conf/wikimon_plugin.py
```
