import pytest
import wikimon.monitor_websocket as MW


class FakeInfobj(object):
    def __init__(self, result):
        self.result = result

    def get_info_dict(self):
        return self.result


class FakeGeolite2(object):
    def __init__(self, result, should_raise=False):
        self.result = FakeInfobj(result)
        self.should_raise = should_raise

    def lookup(self, ip):
        if self.should_raise:
            raise ValueError
        return self.result


def test_geolocate_anonymous_user():
    parsed_message = {"is_anon": True,
                      "user": "192.168.1.1"}

    COUNTRY, LAT, LONG, REGION, CITY = range(5)
    expected = {'country_name': COUNTRY,
                'latitude': LAT,
                'longitude': LONG,
                'region_name': REGION,
                'city': CITY}

    result = {'city': {'names': {'en': CITY}},
              'country': {'names': {'en': COUNTRY}},
              'location': {'latitude': LAT,
                           'longitude': LONG},
              'subdivisions': [{'names': {'en': REGION}}]}

    geo = MW.geolocated_anonymous_user(FakeGeolite2(result),
                                       parsed_message)

    assert geo == expected


@pytest.mark.parametrize('parsed_message',
                         [{},
                          {'is_anon': False, 'user': '192.168.1.1'},
                          {'is_anon': True, 'user': 'bad ip'}])
def test_geolocate_anonymouse_irrelevant_messages(parsed_message):
    geoip_db = FakeGeolite2({}, should_raise=True)
    assert not MW.geolocated_anonymous_user(geoip_db, parsed_message)
