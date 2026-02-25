# -*- coding: utf-8 -*-

import re
import socket
from urllib.parse import parse_qsl


HASHTAG_RE = re.compile(r"(?:^|\s)[＃#]{1}(\w+)", re.UNICODE)
MENTION_RE = re.compile(r"(?:^|\s)[＠ @]{1}([^\s#<>[\]|{}]+)", re.UNICODE)

_SECTION_TITLE_RE = re.compile(r"\/\*\s*(?P<section_title>.+)\s*\*\/"
                               r"(?P<real_summary>.*)", re.UNICODE)

NON_MAIN_NS = ['Talk',
               'User',
               'User talk',
               'Wikipedia',
               'Wikipedia talk',
               'File',
               'File talk',
               'MediaWiki',
               'MediaWiki talk',
               'Template',
               'Template talk',
               'Help',
               'Help talk',
               'Category',
               'Category talk',
               'Portal',
               'Portal talk',
               'Book',
               'Book talk',
               'Education Program',
               'Education Program talk',
               'TimedText',
               'TimedText talk',
               'Module',
               'Module talk',
               'Draft',
               'Draft talk',
               'Special',
               'Media']
DEFAULT_NS_MAP = {ns: ns for ns in NON_MAIN_NS}
DEFAULT_NS_MAP[''] = 'Main'


def is_ip(addr):
    """
    Check whether addr is an IPv4 or IPv6 address.

    >>> is_ip('::1')
    True
    >>> is_ip('192.168.1.1')
    True
    >>> is_ip('unacceptabllllle')
    False
    """
    if not addr:
        return False
    try:
        socket.inet_pton(socket.AF_INET, addr)
    except (socket.error, OSError):
        try:
            socket.inet_pton(socket.AF_INET6, addr)
        except (socket.error, OSError):
            return False
    return True


def parse_revs_from_url(url):
    """
    Parse and return parent_rev_id, rev_id (old, new) from a URL such as:

    http://en.wikipedia.org/w/index.php?diff=560171723&oldid=558167099

    Raises a ValueError on any exception encountered in the process.
    """
    try:
        _, _, query_str = url.partition('?')
        qdict = dict(parse_qsl(query_str))
        return qdict.get('diff'), qdict['oldid']
    except Exception:
        raise ValueError('unparsable url: %r' % (url,))


def parse_section_title(summary):
    """Extract the section title from a MediaWiki edit summary.

    Returns a tuple of (section_title, real_summary) where section_title
    is the section name extracted from the /* Section */ prefix and
    real_summary is the remainder of the summary.
    """
    match = _SECTION_TITLE_RE.match(summary)
    if not match:
        return '', summary.strip()
    match_map = match.groupdict()
    section_title = match_map['section_title']
    real_summary = match_map['real_summary']
    section_title = section_title.strip() if section_title else ''
    real_summary = real_summary.strip() if real_summary else ''
    return section_title, real_summary


def parse_comment(comment):
    """Parse an edit comment/summary into structured fields.

    Returns a dict with keys: section, parsed_summary, hashtags, mentions.
    Works with both IRC-sourced summaries and EventStreams comment fields.
    """
    if not comment:
        return {
            'section': '',
            'parsed_summary': comment or '',
            'hashtags': [],
            'mentions': [],
        }
    section, parsed_summary = parse_section_title(comment)
    hashtags = HASHTAG_RE.findall(comment)
    mentions = MENTION_RE.findall(comment)
    return {
        'section': section,
        'parsed_summary': parsed_summary,
        'hashtags': hashtags,
        'mentions': mentions,
    }
