# -*- coding: utf-8 -*-

import pytest

from wikimon.parsers import (
    is_ip,
    parse_comment,
    parse_revs_from_url,
    parse_section_title,
    DEFAULT_NS_MAP,
)


# ---- is_ip ----

class TestIsIP:
    def test_ipv4(self):
        assert is_ip('192.168.1.1') is True

    def test_ipv4_loopback(self):
        assert is_ip('127.0.0.1') is True

    def test_ipv6_full(self):
        assert is_ip('2001:558:6033:77:453B:B384:FEF:E2D9') is True

    def test_ipv6_loopback(self):
        assert is_ip('::1') is True

    def test_username(self):
        assert is_ip('Slaporte') is False

    def test_unicode_username(self):
        assert is_ip('Édouard') is False

    def test_empty_string(self):
        assert is_ip('') is False

    def test_none_like(self):
        # is_ip should handle falsy input without crashing
        assert is_ip('') is False

    def test_hostname(self):
        assert is_ip('en.wikipedia.org') is False


# ---- parse_section_title ----

class TestParseSectionTitle:
    def test_standard_section(self):
        assert parse_section_title('/* History */ fixed typo') == ('History', 'fixed typo')

    def test_no_section(self):
        assert parse_section_title('fixed typo') == ('', 'fixed typo')

    def test_section_only(self):
        assert parse_section_title('/* History */') == ('History', '')

    def test_section_with_trailing_space(self):
        section, summary = parse_section_title('/* History */  ')
        assert section == 'History'
        assert summary == ''

    def test_empty_string(self):
        assert parse_section_title('') == ('', '')

    def test_section_with_special_chars(self):
        section, summary = parse_section_title('/* External links */ added ref')
        assert section == 'External links'
        assert summary == 'added ref'


# ---- parse_comment ----

class TestParseComment:
    def test_single_hashtag(self):
        result = parse_comment('fixed #typo in article')
        assert result['hashtags'] == ['typo']

    def test_multiple_hashtags(self):
        result = parse_comment('#edit #wikipedia')
        assert result['hashtags'] == ['edit', 'wikipedia']

    def test_fullwidth_hash(self):
        result = parse_comment('＃hashtag')
        assert result['hashtags'] == ['hashtag']

    def test_mention(self):
        result = parse_comment('@AdminUser fixed it')
        assert result['mentions'] == ['AdminUser']

    def test_section_and_hashtag(self):
        result = parse_comment('/* History */ fixed #typo')
        assert result['section'] == 'History'
        assert result['hashtags'] == ['typo']

    def test_empty_string(self):
        result = parse_comment('')
        assert result['section'] == ''
        assert result['parsed_summary'] == ''
        assert result['hashtags'] == []
        assert result['mentions'] == []

    def test_none(self):
        result = parse_comment(None)
        assert result['section'] == ''
        assert result['parsed_summary'] == ''
        assert result['hashtags'] == []
        assert result['mentions'] == []

    def test_unicode_summary(self):
        # Japanese text should not crash
        result = parse_comment('記事を編集しました')
        assert result['section'] == ''
        assert result['parsed_summary'] == '記事を編集しました'

    def test_arabic_text(self):
        result = parse_comment('تعديل المقالة')
        assert result['section'] == ''
        assert result['parsed_summary'] == 'تعديل المقالة'

    def test_all_fields_present(self):
        result = parse_comment('/* Refs */ added link #citation @Editor')
        assert set(result.keys()) == {'section', 'parsed_summary', 'hashtags', 'mentions'}
        assert result['section'] == 'Refs'
        assert result['parsed_summary'] == 'added link #citation @Editor'
        assert 'citation' in result['hashtags']
        assert 'Editor' in result['mentions']


# ---- parse_revs_from_url ----

class TestParseRevsFromUrl:
    def test_standard_url(self):
        url = 'http://en.wikipedia.org/w/index.php?diff=560171723&oldid=558167099'
        diff, oldid = parse_revs_from_url(url)
        assert diff == '560171723'
        assert oldid == '558167099'

    def test_malformed_url(self):
        with pytest.raises(ValueError):
            parse_revs_from_url('not-a-url')

    def test_missing_oldid(self):
        with pytest.raises(ValueError):
            parse_revs_from_url('http://example.com/?diff=123')


# ---- DEFAULT_NS_MAP ----

class TestDefaultNsMap:
    def test_main_namespace(self):
        assert DEFAULT_NS_MAP[''] == 'Main'

    def test_talk_namespace(self):
        assert DEFAULT_NS_MAP['Talk'] == 'Talk'

    def test_user_namespace(self):
        assert DEFAULT_NS_MAP['User'] == 'User'

    def test_special_namespace(self):
        assert DEFAULT_NS_MAP['Special'] == 'Special'
