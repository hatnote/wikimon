# -*- coding: utf-8 -*-

import pytest

from wikimon.monitor import transform_event, GeoIPManager


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

    def test_anonymous_edit(self):
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

    def test_log_event_newusers(self):
        event = {
            'type': 'log',
            'title': 'Special:Log/newusers',
            'user': 'NewUser123',
            'bot': False,
            'minor': False,
            'comment': '',
            'namespace': 0,
            'server_name': 'en.wikipedia.org',
            'server_url': 'https://en.wikipedia.org',
            'server_script_path': '/w',
            'log_type': 'newusers',
            'log_action': 'create',
        }
        msg = transform_event(event, NS_MAP)
        assert msg['action'] == 'Special:Log/newusers'
        assert msg['page_title'] == 'Special:Log/newusers'

    def test_log_event_other(self):
        event = {
            'type': 'log',
            'title': 'Some page',
            'user': 'Admin',
            'bot': False,
            'minor': False,
            'comment': '',
            'namespace': 0,
            'server_name': 'en.wikipedia.org',
            'server_url': 'https://en.wikipedia.org',
            'server_script_path': '/w',
            'log_type': 'block',
            'log_action': 'block',
        }
        msg = transform_event(event, NS_MAP)
        assert msg['action'] == 'Special:Log/block'
        # Non-newusers log should not override title
        assert msg['page_title'] == 'Some page'

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


# ---- GeoIPManager ----

class FakeMaxmindReader:
    """Mock maxminddb reader for testing."""

    def __init__(self, result):
        self.result = result

    def get(self, ip):
        return self.result

    def close(self):
        pass


def _make_geoip_manager(reader):
    """Create a GeoIPManager without opening a real database file."""
    mgr = object.__new__(GeoIPManager)
    mgr.db_path = '/nonexistent'
    mgr.check_interval = 30
    mgr.last_mtime = 0
    mgr.reader = reader
    return mgr


class TestGeoIPManager:
    def test_lookup_success(self):
        result = {
            'city': {'names': {'en': 'San Francisco'}},
            'country': {'names': {'en': 'United States'}},
            'location': {'latitude': 37.7749, 'longitude': -122.4194},
            'subdivisions': [{'names': {'en': 'California'}}],
        }
        mgr = _make_geoip_manager(FakeMaxmindReader(result))
        geo = mgr.lookup('8.8.8.8')
        assert geo['country_name'] == 'United States'
        assert geo['city'] == 'San Francisco'
        assert geo['latitude'] == 37.7749
        assert geo['longitude'] == -122.4194
        assert geo['region_name'] == 'California'

    def test_lookup_unknown_ip(self):
        mgr = _make_geoip_manager(FakeMaxmindReader(None))
        geo = mgr.lookup('10.0.0.1')
        assert geo == {}

    def test_lookup_no_reader(self):
        mgr = _make_geoip_manager(None)
        geo = mgr.lookup('8.8.8.8')
        assert geo == {}

    def test_lookup_partial_data(self):
        # Only country, no city/subdivisions
        result = {
            'country': {'names': {'en': 'Germany'}},
            'location': {'latitude': 51.0, 'longitude': 9.0},
        }
        mgr = _make_geoip_manager(FakeMaxmindReader(result))
        geo = mgr.lookup('1.2.3.4')
        assert geo['country_name'] == 'Germany'
        assert geo['latitude'] == 51.0
        assert geo['city'] is None
        assert geo['region_name'] is None

    def test_lookup_exception(self):
        class RaisingReader:
            def get(self, ip):
                raise ValueError('bad ip')
            def close(self):
                pass

        mgr = _make_geoip_manager(RaisingReader())
        geo = mgr.lookup('bad')
        assert geo == {}
