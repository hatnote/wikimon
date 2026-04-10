import time

from wikimon.monitor import (
    MultiLangWikimonServer,
    LangChannel,
    _resolve_server_name,
    DEFAULT_LANGUAGES,
    transform_event,
    SSE_READ_TIMEOUT_SECONDS,
    EN_STALE_THRESHOLD_SECONDS,
    STALE_STREAM_THRESHOLD_SECONDS,
)


def make_test_server(languages):
    server = object.__new__(MultiLangWikimonServer)
    server.port = 9500
    server.geoip = None
    server.channels = {}
    server.path_to_channel = {}
    server.msg_count = 0
    server.start_time = 0
    server._last_event_id = None
    server._last_event_time = time.time()
    server._reconnect_count = 0
    for lang, project, ws_path in languages:
        server_name = _resolve_server_name(lang, project)
        channel = LangChannel(lang=lang, project=project, ws_path=ws_path, ns_map={})
        server.channels[server_name] = channel
        server.path_to_channel[ws_path] = channel
        bare = ws_path.rstrip("/")
        if bare:
            server.path_to_channel[bare] = channel
    return server


class TestLangChannelRouting:
    def test_path_routing_with_slash(self):
        server = make_test_server([("en", "wikipedia", "/en/")])
        assert "/en/" in server.path_to_channel

    def test_path_routing_without_slash(self):
        server = make_test_server([("en", "wikipedia", "/en/")])
        assert "/en" in server.path_to_channel

    def test_root_path_maps_to_en(self):
        server = make_test_server(DEFAULT_LANGUAGES)
        ch = server.path_to_channel.get("/en")
        assert ch is not None
        assert ch.lang == "en"

    def test_unknown_path_returns_none(self):
        server = make_test_server([("en", "wikipedia", "/en/")])
        assert server.path_to_channel.get("/xx") is None

    def test_wikidata_routing(self):
        server = make_test_server([("wikidata", "wikidata", "/wikidata/")])
        ch = server.path_to_channel.get("/wikidata")
        assert ch is not None
        assert ch.project == "wikidata"

    def test_multiple_languages(self):
        server = make_test_server([
            ("en", "wikipedia", "/en/"),
            ("de", "wikipedia", "/de/"),
        ])
        assert "/en" in server.path_to_channel
        assert "/de" in server.path_to_channel


class TestServerNameDispatch:
    def test_en_wikipedia(self):
        assert _resolve_server_name("en", "wikipedia") == "en.wikipedia.org"

    def test_wikidata(self):
        assert _resolve_server_name("wikidata", "wikidata") == "www.wikidata.org"

    def test_channel_keyed_by_server_name(self):
        server = make_test_server([("de", "wikipedia", "/de/")])
        assert "de.wikipedia.org" in server.channels

    def test_all_default_languages_have_channels(self):
        server = make_test_server(DEFAULT_LANGUAGES)
        assert len(server.channels) == len(DEFAULT_LANGUAGES)


class TestLangChannel:
    def test_default_clients_empty(self):
        ch = LangChannel(lang="en", project="wikipedia", ws_path="/en/", ns_map={})
        assert ch.clients == set()

    def test_clients_independent(self):
        ch1 = LangChannel(lang="en", project="wikipedia", ws_path="/en/", ns_map={})
        ch2 = LangChannel(lang="de", project="wikipedia", ws_path="/de/", ns_map={})
        ch1.clients.add("fake_client")
        assert len(ch2.clients) == 0



# A realistic EventStreams edit event (same as test_monitor.py)
SAMPLE_EDIT_EVENT = {
    'type': 'edit',
    'title': 'Main Page',
    'user': 'ExampleUser',
    'bot': False,
    'minor': False,
    'patrolled': True,
    'comment': 'fixed typo',
    'namespace': 0,
    'server_name': 'en.wikipedia.org',
    'server_url': 'https://en.wikipedia.org',
    'server_script_path': '/w',
    'length': {'new': 5200, 'old': 5100},
    'revision': {'new': 560171723, 'old': 558167099},
}

NS_MAP = {0: 'Main', 1: 'Talk'}


class TestLangChannelLastEventTime:
    def test_default_last_event_time(self):
        before = time.time()
        ch = LangChannel(lang='en', project='wikipedia', ws_path='/en/', ns_map={})
        after = time.time()
        assert before <= ch.last_event_time <= after

    def test_last_event_time_independent(self):
        ch1 = LangChannel(lang='en', project='wikipedia', ws_path='/en/', ns_map={})
        ch2 = LangChannel(lang='de', project='wikipedia', ws_path='/de/', ns_map={})
        ch1.last_event_time = 0.0
        assert ch2.last_event_time > 0.0


class TestServerStalenessTracking:
    def test_init_has_reconnect_count(self):
        server = make_test_server([('en', 'wikipedia', '/en/')])
        assert server._reconnect_count == 0

    def test_init_has_last_event_time(self):
        before = time.time()
        server = make_test_server([('en', 'wikipedia', '/en/')])
        assert server._last_event_time <= time.time()
        assert server._last_event_time >= before - 1  # small tolerance


class TestProcessEventTimestamps:
    """Verify _process_event updates both channel and server timestamps."""

    import pytest

    @pytest.mark.asyncio
    async def test_process_event_updates_timestamps(self):
        server = make_test_server([('en', 'wikipedia', '/en/')])
        channel = server.channels['en.wikipedia.org']
        # Set timestamps to the past
        old_time = time.time() - 600
        channel.last_event_time = old_time
        server._last_event_time = old_time

        before = time.time()
        await server._process_event(SAMPLE_EDIT_EVENT, channel)
        after = time.time()

        assert channel.last_event_time >= before
        assert channel.last_event_time <= after
        assert server._last_event_time >= before
        assert server._last_event_time <= after
        assert server.msg_count == 1

    @pytest.mark.asyncio
    async def test_process_event_increments_msg_count(self):
        server = make_test_server([('en', 'wikipedia', '/en/')])
        channel = server.channels['en.wikipedia.org']
        assert server.msg_count == 0
        await server._process_event(SAMPLE_EDIT_EVENT, channel)
        await server._process_event(SAMPLE_EDIT_EVENT, channel)
        assert server.msg_count == 2


class TestConstants:
    def test_sse_read_timeout_positive(self):
        assert SSE_READ_TIMEOUT_SECONDS > 0

    def test_en_stale_threshold_positive(self):
        assert EN_STALE_THRESHOLD_SECONDS > 0

    def test_stale_stream_threshold_gt_en(self):
        assert STALE_STREAM_THRESHOLD_SECONDS > EN_STALE_THRESHOLD_SECONDS
