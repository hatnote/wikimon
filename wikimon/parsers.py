# -*- coding: utf-8 -*-

import re
import socket
from urlparse import parse_qsl


PARSE_EDIT_RE = re.compile(r'(\[\[(?P<page_title>.*?)\]\])'
                           r' +((?P<flags>[A-Z\!]+) )?'
                           r'(?P<url>\S*)'
                           r' +\* (?P<user>.*?)'
                           r' \* (\((?P<change_size>[\+\-][0-9]+)\))?'
                           r' ?(?P<summary>.+)?')

# see https://gist.github.com/mahmoud/237eb20108b5805aed5f
HASHTAG_RE = re.compile("(?:^|\s)[＃#]{1}(\w+)", re.UNICODE)
MENTION_RE = re.compile("(?:^|\s)[＠ @]{1}([^\s#<>[\]|{}]+)", re.UNICODE)

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
DEFAULT_NS_MAP = dict([(ns, ns) for ns in NON_MAIN_NS])
DEFAULT_NS_MAP[''] = 'Main'


def is_ip(addr):
    """
    >>> is_ip('::1')
    True
    >>> is_ip('192.168.1.1')
    True
    >>> is_ip('unacceptabllllle')
    False
    """
    ret = True
    try:
        socket.inet_pton(socket.AF_INET, addr)
    except socket.error:
        try:
            socket.inet_pton(socket.AF_INET6, addr)
        except socket.error:
            ret = False
    except UnicodeError:
        # IPs are always ASCII-only, no explicit encode/decode necessary
        ret = False
    return ret


def parse_revs_from_url(url):
    """
    Parse and return parent_rev_id, rev_id (old, new) from a URL such as:

    http://en.wikipedia.org/w/index.php?diff=560171723&oldid=558167099

    Raises a ValueError on any exception encountered in the process.
    """
    try:
        _, _, query_str = url.partition('?')
        qdict = dict(parse_qsl(query_str))
        # confusingly, I think oldid is actually the current rev id
        return qdict.get('diff'), qdict['oldid']
    except:
        raise ValueError('unparsable url: %r' % (url,))


def parse_irc_message(message, ns_map=DEFAULT_NS_MAP):
    ret = PARSE_EDIT_RE.match(message)
    msg_dict = {'is_new': False,
                'is_bot': False,
                'is_unpatrolled': False,
                'is_anon': False}
    if ret:
        msg_dict.update(ret.groupdict())
    else:
        msg_dict = {}
    '''
    Special logs:
    - Special:Log/abusefilter
    - Special:Log/block
    - Special:Log/newusers
    - Special:Log/move
    - Special:Log/pagetriage-curation
    - Special:Log/delete
    - Special:Log/upload
    - Special:Log/patrol
    '''
    top_level_title, _, _ = msg_dict['page_title'].partition('/')
    ns, _, title_rem = top_level_title.partition(':')
    try:
        msg_dict['ns'] = ns_map[ns]
        #msg_dict['local_ns'] = ns
    except KeyError:
        msg_dict['ns'] = 'Main'
        #msg_dict['local_ns'] = 'Main'

    try:
        msg_dict['change_size'] = int(msg_dict['change_size'])
    except:
        msg_dict['change_size'] = None

    msg_dict['action'] = 'edit'
    try:
        p_rev_id, rev_id = parse_revs_from_url(msg_dict['url'])
        msg_dict['parent_rev_id'], msg_dict['rev_id'] = p_rev_id, rev_id
    except ValueError:
        msg_dict['action'] = msg_dict.pop('url', None)

    flags = msg_dict.get('flags') or ''
    msg_dict['is_new'] = 'N' in flags
    msg_dict['is_bot'] = 'B' in flags
    msg_dict['is_minor'] = 'M' in flags
    msg_dict['is_unpatrolled'] = '!' in flags

    msg_dict.setdefault('user', None)
    msg_dict['is_anon'] = is_ip(msg_dict['user'])

    if msg_dict['summary']:
        msg_dict['hashtags'] = HASHTAG_RE.findall(msg_dict['summary'])
        msg_dict['mentions'] = MENTION_RE.findall(msg_dict['summary'])
    else:
        msg_dict['hashtags'] = []
        msg_dict['mentions'] = []

    return msg_dict
