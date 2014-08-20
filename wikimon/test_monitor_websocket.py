import pytest
import wikimon.monitor_websocket as MW


class fake_infobj(object):
    def __init__(self, result):
        self.result = result

    def get_info_dict(self):
        return self.result


class fake_geolite2(object):
    def __init__(self, result):
        self.result = fake_infobj(result)

    def lookup(self, ip):
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

    geo = MW.geolocated_anonymous_user(parsed_message,
                                       _geolite2=fake_geolite2(result))

    assert geo == expected


@pytest.mark.parametrize('parsed_message',
                         [{},
                          {'is_anon': False, 'user': '192.168.1.1'},
                          {'is_anon': True, 'user': 'bad ip'}])
def test_geolocate_anonymouse_irrelevant_messages(parsed_message):
    assert not MW.geolocated_anonymous_user(parsed_message)
