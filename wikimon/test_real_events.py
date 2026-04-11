# -*- coding: utf-8 -*-
"""Tests using real EventStreams data captured from production.

The fixture file (test_fixtures.json) contains a sample of every event
type wikimon encounters: edit, new, log/newusers, log/other, categorize.
These tests verify that transform_event produces correct output for real
data shapes, catching field renames or missing keys that hand-crafted
fixtures miss.
"""

import json
import os

import pytest

from wikimon.monitor import transform_event, MultiLangWikimonServer, LangChannel, _resolve_server_name

FIXTURES_PATH = os.path.join(os.path.dirname(__file__), 'test_fixtures.json')
NS_MAP = {0: 'Main', 1: 'Talk', 2: 'User'}

EXPECTED_KEYS = {
    'page_title', 'user', 'is_anon', 'is_bot', 'is_new', 'is_minor',
    'is_unpatrolled', 'change_size', 'url', 'ns', 'summary', 'action',
    'hashtags', 'mentions', 'section', 'parsed_summary', 'rev_id',
    'parent_rev_id',
}


@pytest.fixture(scope='module')
def fixtures():
    with open(FIXTURES_PATH) as f:
        return json.load(f)


def _events_by_type(fixtures, event_type, log_type=None):
    """Filter fixture events by type (and optionally log_type)."""
    for e in fixtures:
        if e.get('type') != event_type:
            continue
        if log_type is not None and e.get('log_type') != log_type:
            continue
        yield e


class TestRealEdits:
    """Every real edit event must produce a complete, well-typed message."""

    def test_all_keys_present(self, fixtures):
        for event in _events_by_type(fixtures, 'edit'):
            msg = transform_event(event, NS_MAP)
            assert set(msg.keys()) == EXPECTED_KEYS, f"missing keys for {event.get('title')}"

    def test_change_size_is_int(self, fixtures):
        for event in _events_by_type(fixtures, 'edit'):
            msg = transform_event(event, NS_MAP)
            assert isinstance(msg['change_size'], int)

    def test_url_is_diff_link(self, fixtures):
        for event in _events_by_type(fixtures, 'edit'):
            msg = transform_event(event, NS_MAP)
            assert 'diff=' in msg['url']
            assert 'oldid=' in msg['url']

    def test_action_is_edit(self, fixtures):
        for event in _events_by_type(fixtures, 'edit'):
            msg = transform_event(event, NS_MAP)
            assert msg['action'] == 'edit'

    def test_is_new_false(self, fixtures):
        for event in _events_by_type(fixtures, 'edit'):
            msg = transform_event(event, NS_MAP)
            assert msg['is_new'] is False


class TestRealNewPages:
    """New page events must have positive change_size and a valid URL."""

    def test_all_keys_present(self, fixtures):
        for event in _events_by_type(fixtures, 'new'):
            msg = transform_event(event, NS_MAP)
            assert set(msg.keys()) == EXPECTED_KEYS

    def test_change_size_is_positive_int(self, fixtures):
        for event in _events_by_type(fixtures, 'new'):
            msg = transform_event(event, NS_MAP)
            assert isinstance(msg['change_size'], int), \
                f"change_size should be int, got {type(msg['change_size'])}"
            assert msg['change_size'] > 0, \
                f"new page should have positive change_size, got {msg['change_size']}"

    def test_url_not_empty(self, fixtures):
        for event in _events_by_type(fixtures, 'new'):
            msg = transform_event(event, NS_MAP)
            assert msg['url'] != '', "new page URL should not be empty"
            assert 'oldid=' in msg['url']

    def test_is_new_true(self, fixtures):
        for event in _events_by_type(fixtures, 'new'):
            msg = transform_event(event, NS_MAP)
            assert msg['is_new'] is True
            assert msg['action'] == 'new'

    def test_parent_rev_id_is_none(self, fixtures):
        for event in _events_by_type(fixtures, 'new'):
            msg = transform_event(event, NS_MAP)
            assert msg['parent_rev_id'] is None


class TestRealNewuserEvents:
    """Newuser log events must produce the format the frontend expects."""

    def test_all_keys_present(self, fixtures):
        for event in _events_by_type(fixtures, 'log', log_type='newusers'):
            msg = transform_event(event, NS_MAP)
            assert set(msg.keys()) == EXPECTED_KEYS

    def test_page_title_is_special_log(self, fixtures):
        for event in _events_by_type(fixtures, 'log', log_type='newusers'):
            msg = transform_event(event, NS_MAP)
            assert msg['page_title'] == 'Special:Log/newusers'

    def test_url_is_log_action(self, fixtures):
        for event in _events_by_type(fixtures, 'log', log_type='newusers'):
            msg = transform_event(event, NS_MAP)
            assert msg['url'] in ('create', 'byemail', 'create2', 'autocreate')

    def test_user_is_nonempty(self, fixtures):
        for event in _events_by_type(fixtures, 'log', log_type='newusers'):
            msg = transform_event(event, NS_MAP)
            assert msg['user'] != ''

    def test_action_is_newusers(self, fixtures):
        for event in _events_by_type(fixtures, 'log', log_type='newusers'):
            msg = transform_event(event, NS_MAP)
            assert msg['action'] == 'newusers'


class TestNewuserChannelRouting:
    """Newuser events from auth.wikimedia.org must route to the right channel."""

    @staticmethod
    def _make_server(lang_specs):
        """Build a server without network calls (same as test_multi_lang_server)."""
        server = object.__new__(MultiLangWikimonServer)
        server.port = 0
        server.channels = {}
        server.path_to_channel = {}
        server.msg_count = 0
        server.start_time = 0
        server._last_event_id = None
        server._last_event_time = 0
        server._reconnect_count = 0
        for lang, project, ws_path in lang_specs:
            sn = _resolve_server_name(lang, project)
            server.channels[sn] = LangChannel(lang=lang, project=project, ws_path=ws_path, ns_map={})
            server.path_to_channel[ws_path] = server.channels[sn]
        return server

    def test_enwiki_routes_to_en_channel(self):
        server = self._make_server([('en', 'wikipedia', '/en/')])
        data = {'wiki': 'enwiki', 'server_name': 'auth.wikimedia.org'}
        channel = server._resolve_newuser_channel(data)
        assert channel is not None
        assert channel.lang == 'en'

    def test_dewiki_routes_to_de_channel(self):
        server = self._make_server([('en', 'wikipedia', '/en/'), ('de', 'wikipedia', '/de/')])
        data = {'wiki': 'dewiki', 'server_name': 'auth.wikimedia.org'}
        channel = server._resolve_newuser_channel(data)
        assert channel is not None
        assert channel.lang == 'de'

    def test_unknown_wiki_returns_none(self):
        server = self._make_server([('en', 'wikipedia', '/en/')])
        data = {'wiki': 'frwiki', 'server_name': 'auth.wikimedia.org'}
        channel = server._resolve_newuser_channel(data)
        assert channel is None

    def test_wikidatawiki_skipped(self):
        server = self._make_server([('en', 'wikipedia', '/en/')])
        data = {'wiki': 'wikidatawiki', 'server_name': 'auth.wikimedia.org'}
        channel = server._resolve_newuser_channel(data)
        assert channel is None


class TestEventFiltering:
    """Verify which event types should be filtered vs passed through."""

    def test_categorize_events_are_noise(self, fixtures):
        """Categorize events should not produce meaningful output."""
        for event in _events_by_type(fixtures, 'categorize'):
            # These would be filtered in the SSE loop; transform_event
            # would still work but they're not useful content
            msg = transform_event(event, NS_MAP)
            assert msg['action'] == 'edit'  # categorize has no special handling

    def test_non_newuser_log_events_exist(self, fixtures):
        """Confirm we captured log events that aren't newusers (they get filtered)."""
        others = list(_events_by_type(fixtures, 'log'))
        non_newuser = [e for e in others if e.get('log_type') != 'newusers']
        assert len(non_newuser) > 0, "fixture should contain non-newuser log events"
