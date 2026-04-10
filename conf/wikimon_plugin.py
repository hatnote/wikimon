#!/usr/bin/python3
"""Site24x7 plugin for wikimon v2.

Reads the last stats line from the wikimon v2 stderr log and reports
key metrics: message count, client count, stream staleness, reconnects,
uptime, and system-level open file descriptors.
"""

import io
import os
import re
import json
from datetime import datetime

PLUGIN_VERSION = "2"
HEARTBEAT = "true"

PROC_FILE = "/proc/sys/fs/file-nr"

WIKIMON_LOGFILE = '/home/hatnote/wikimon_v2/logs/wikimon.err.log'

# V2 stats format: "<timestamp>\twikimon\tstats: <json>"
STATS_RE = re.compile(r'(?P<timestamp>[^\t]+)\twikimon\tstats: (?P<data>\{.*\})')

METRIC_UNITS = {
    'msgs': 'units',
    'total_clients': 'units',
    'num_channels': 'units',
    'uptime_hours': 'h',
    'secs_since_last_event': 's',
    'secs_since_last_en_event': 's',
    'secs_since_log': 's',
    'reconnect_count': 'units',
    'open_files': 'units',
    'total_files': 'units',
}


def main():
    result = get_metrics()
    print(json.dumps(result, indent=4, sort_keys=True))


def get_metrics():
    data = get_last_stats()

    data['plugin_version'] = PLUGIN_VERSION
    data['heartbeat_required'] = HEARTBEAT
    try:
        open_nr, free_nr, max_nr = open(PROC_FILE).readline().split("\t")
        data["open_files"] = int(open_nr) - int(free_nr)
        data["total_files"] = int(max_nr)
    except Exception as e:
        data["status"] = 0
        data["msg"] = str(e)

    data["units"] = METRIC_UNITS
    return data


def get_last_stats():
    """Parse the most recent stats JSON from the wikimon v2 log."""
    default = {'secs_since_log': 3600, 'total_clients': 0, 'msgs': 0}
    try:
        logfile = open(WIKIMON_LOGFILE, 'r')
    except OSError:
        return default

    for line in reverse_iter_lines(logfile):
        if 'stats:' not in line:
            continue
        match = STATS_RE.match(line)
        if not match:
            continue
        dt_str = match.group('timestamp')
        data = json.loads(match.group('data'))
        dt = _parse_log_timestamp(dt_str)
        data['secs_since_log'] = int((datetime.now() - dt).total_seconds())
        return data

    return default


_NONDIGIT_RE = re.compile(r'\D')


def _parse_log_timestamp(ts_str):
    """Parse 'YYYY-MM-DD HH:MM:SS' timestamps from the log."""
    parts = [int(p) for p in _NONDIGIT_RE.split(ts_str) if p]
    return datetime(*parts)


DEFAULT_BLOCKSIZE = 4096


def reverse_iter_lines(file_obj, blocksize=DEFAULT_BLOCKSIZE, preseek=True):
    """Iterate lines of a file in reverse order (last line first).

    Uses file.seek so it works efficiently on large log files without
    reading the entire file into memory.
    """
    try:
        file_obj = file_obj.detach()
    except (AttributeError, io.UnsupportedOperation):
        pass

    if preseek:
        file_obj.seek(0, os.SEEK_END)
    buff = b''
    cur_pos = file_obj.tell()
    while 0 < cur_pos:
        read_size = min(blocksize, cur_pos)
        cur_pos -= read_size
        file_obj.seek(cur_pos, os.SEEK_SET)
        buff = file_obj.read(read_size) + buff
        lines = buff.splitlines()

        if len(lines) < 2 or lines[0] == b'':
            continue
        if buff[-1:] == b'\n':
            yield ''
        for line in lines[:0:-1]:
            yield line.decode('utf-8', errors='replace')
        buff = lines[0]
    if buff:
        yield buff.decode('utf-8', errors='replace')


if __name__ == "__main__":
    main()
