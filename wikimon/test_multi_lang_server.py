from wikimon.monitor import (
    MultiLangWikimonServer,
    LangChannel,
    _resolve_server_name,
    DEFAULT_LANGUAGES,
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
