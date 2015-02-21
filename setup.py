# -*- coding: utf-8 -*-

"""
    wikimon
    ~~~~~~~

    A WebSocket-oriented monitor for streaming live changes to
    Wikipedia. (also, wikimon, wikital monsters)

    :copyright: (c) 2013-2015 by Mahmoud Hashemi and Stephen LaPorte
    :license: GPLv3, see LICENSE for more details.

"""

import sys
from setuptools import setup


__author__ = 'Mahmoud Hashemi and Stephen LaPorte'
__version__ = '0.6.2'
__contact__ = 'mahmoudrhashemi@gmail.com'
__url__ = 'https://github.com/hatnote/wikimon'
__license__ = 'GPLv3'

desc = ('A WebSocket-oriented monitor for streaming live changes to'
        'Wikipedia. (also, wikimon, wikital monsters)')


if sys.version_info < (2,6):
    raise NotImplementedError("Sorry, wikimon only supports Python >=2.6")


if sys.version_info >= (3,):
    raise NotImplementedError("Wikimon doesn't support Python 3 (yet!)")


setup(name='wikimon',
      version=__version__,
      description=desc,
      long_description=__doc__,
      author=__author__,
      author_email=__contact__,
      url=__url__,
      packages=['wikimon'],
      include_package_data=True,
      zip_safe=False,
      install_requires=['wapiti',
                        'Twisted==13.0.0',
                        'autobahn==0.5.14',
                        'python-geoip==1.2',
                        'python-geoip-geolite2==2014.207'],
      license=__license__,
      platforms='any',
      classifiers=[
          'Programming Language :: Python :: 2.6',
          'Programming Language :: Python :: 2.7', ]
      )
