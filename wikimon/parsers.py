# -*- coding: utf-8 -*-

import re
import socket
from urlparse import parse_qsl


COLOR_RE = re.compile(r"\x03(?:\d{1,2}(?:,\d{1,2})?)?",
                      re.UNICODE)  # remove IRC color codes
PARSE_EDIT_RE = re.compile(r'(\[\[(?P<page_title>.*?)\]\])'
                           r' +((?P<flags>[A-Z\!]+) )?'
                           r'(?P<url>\S*)'
                           r' +\* (?P<user>.*?)'
                           r' \* (\((?P<change_size>[\+\-][0-9]+)\))?'
                           r' ?(?P<summary>.+)?')
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
               'Special',
               'Media']


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


def clean_irc_markup(message):
    message = message.replace('\x02', '')
    no_color = COLOR_RE.sub('', message)
    no_color = no_color.strip()
    return no_color


def parse_irc_message(message, non_main_ns=NON_MAIN_NS):
    clean_message = clean_irc_markup(message)
    ret = PARSE_EDIT_RE.match(clean_message)
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
    ns, _, title = top_level_title.rpartition(':')
    if ns not in non_main_ns:
        msg_dict['ns'] = 'Main'
    else:
        msg_dict['ns'] = ns

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

    return msg_dict
