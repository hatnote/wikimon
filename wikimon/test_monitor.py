# -*- coding: utf-8 -*-

import pytest

from wikimon.monitor import transform_event


# Expected keys in every transform_event output
EXPECTED_KEYS = {
    'page_title', 'user', 'is_anon', 'is_bot', 'is_new', 'is_minor',
    'is_unpatrolled', 'change_size', 'url', 'ns', 'summary', 'action',
    'hashtags', 'mentions', 'section', 'parsed_summary', 'rev_id',
    'parent_rev_id',
}

# A realistic EventStreams edit event
SAMPLE_EDIT_EVENT = {
    'type': 'edit',
    'title': 'Main Page',
    'user': 'ExampleUser',
    'bot': False,
    'minor': False,
    'patrolled': True,
    'comment': '/* Introduction */ fixed #typo @Reviewer',
    'namespace': 0,
    'server_name': 'en.wikipedia.org',
    'server_url': 'https://en.wikipedia.org',
    'server_script_path': '/w',
    'length': {'new': 5200, 'old': 5100},
    'revision': {'new': 560171723, 'old': 558167099},
}

NS_MAP = {0: 'Main', 1: 'Talk', 2: 'User'}


class TestTransformEvent:
    def test_standard_edit(self):
        msg = transform_event(SAMPLE_EDIT_EVENT, NS_MAP)
        assert msg['page_title'] == 'Main Page'
        assert msg['user'] == 'ExampleUser'
        assert msg['is_anon'] is False
        assert msg['is_bot'] is False
        assert msg['is_new'] is False
        assert msg['is_minor'] is False
        assert msg['is_unpatrolled'] is False
        assert msg['change_size'] == 100
        assert 'diff=560171723' in msg['url']
        assert 'oldid=558167099' in msg['url']
        assert msg['ns'] == 'Main'
        assert msg['action'] == 'edit'
        assert 'typo' in msg['hashtags']
        assert 'Reviewer' in msg['mentions']
        assert msg['section'] == 'Introduction'
        assert msg['rev_id'] == '560171723'
        assert msg['parent_rev_id'] == '558167099'

    def test_all_expected_keys_present(self):
        msg = transform_event(SAMPLE_EDIT_EVENT, NS_MAP)
        assert set(msg.keys()) == EXPECTED_KEYS

    def test_new_page(self):
        event = dict(SAMPLE_EDIT_EVENT)
        event['type'] = 'new'
        msg = transform_event(event, NS_MAP)
        assert msg['is_new'] is True
        assert msg['action'] == 'new'

    def test_bot_edit(self):
        event = dict(SAMPLE_EDIT_EVENT)
        event['bot'] = True
        msg = transform_event(event, NS_MAP)
        assert msg['is_bot'] is True

    def test_minor_edit(self):
        event = dict(SAMPLE_EDIT_EVENT)
        event['minor'] = True
        msg = transform_event(event, NS_MAP)
        assert msg['is_minor'] is True

    def test_anonymous_edit_ip(self):
        event = dict(SAMPLE_EDIT_EVENT)
        event['user'] = '192.168.1.1'
        msg = transform_event(event, NS_MAP)
        assert msg['is_anon'] is True
        assert msg['user'] == '192.168.1.1'

    def test_anonymous_ipv6(self):
        event = dict(SAMPLE_EDIT_EVENT)
        event['user'] = '2001:558:6033:77:453B:B384:FEF:E2D9'
        msg = transform_event(event, NS_MAP)
        assert msg['is_anon'] is True

    def test_anonymous_temp_account(self):
        event = dict(SAMPLE_EDIT_EVENT)
        event['user'] = '~2026-93757-24'
        msg = transform_event(event, NS_MAP)
        assert msg['is_anon'] is True
        assert msg['user'] == '~2026-93757-24'

    def test_missing_length(self):
        event = dict(SAMPLE_EDIT_EVENT)
        del event['length']
        msg = transform_event(event, NS_MAP)
        assert msg['change_size'] is None

    def test_missing_revision(self):
        event = dict(SAMPLE_EDIT_EVENT)
        del event['revision']
        msg = transform_event(event, NS_MAP)
        assert msg['rev_id'] is None
        assert msg['parent_rev_id'] is None
        assert msg['url'] == ''

    def test_non_main_namespace(self):
        event = dict(SAMPLE_EDIT_EVENT)
        event['namespace'] = 1
        msg = transform_event(event, NS_MAP)
        assert msg['ns'] == 'Talk'

    def test_unknown_namespace_id(self):
        event = dict(SAMPLE_EDIT_EVENT)
        event['namespace'] = 999
        msg = transform_event(event, NS_MAP)
        # Falls back to string representation
        assert msg['ns'] == '999'

    def test_change_size_negative(self):
        event = dict(SAMPLE_EDIT_EVENT)
        event['length'] = {'new': 100, 'old': 200}
        msg = transform_event(event, NS_MAP)
        assert msg['change_size'] == -100

    def test_change_size_zero(self):
        event = dict(SAMPLE_EDIT_EVENT)
        event['length'] = {'new': 100, 'old': 100}
        msg = transform_event(event, NS_MAP)
        assert msg['change_size'] == 0

    def test_rev_ids_are_strings(self):
        msg = transform_event(SAMPLE_EDIT_EVENT, NS_MAP)
        assert isinstance(msg['rev_id'], str)
        assert isinstance(msg['parent_rev_id'], str)

    def test_url_format(self):
        msg = transform_event(SAMPLE_EDIT_EVENT, NS_MAP)
        assert msg['url'] == 'https://en.wikipedia.org/w/index.php?diff=560171723&oldid=558167099'

    def test_empty_comment(self):
        event = dict(SAMPLE_EDIT_EVENT)
        event['comment'] = ''
        msg = transform_event(event, NS_MAP)
        assert msg['summary'] == ''
        assert msg['hashtags'] == []
        assert msg['mentions'] == []
        assert msg['section'] == ''

    def test_unpatrolled_edit(self):
        event = dict(SAMPLE_EDIT_EVENT)
        event['patrolled'] = False
        msg = transform_event(event, NS_MAP)
        assert msg['is_unpatrolled'] is True

