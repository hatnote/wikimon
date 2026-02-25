# -*- coding: utf-8 -*-

"""
    wikimon
    ~~~~~~~

    A WebSocket-oriented monitor for streaming live changes to
    Wikipedia. (also, wikimon, wikital monsters)

    :copyright: (c) 2013-2025 by Mahmoud Hashemi and Stephen LaPorte
    :license: GPLv3, see LICENSE for more details.

"""

from setuptools import setup


__author__ = 'Mahmoud Hashemi and Stephen LaPorte'
__version__ = '0.7.0'
__contact__ = 'mahmoudrhashemi@gmail.com'
__url__ = 'https://github.com/hatnote/wikimon'
__license__ = 'GPLv3'

desc = ('A WebSocket-oriented monitor for streaming live changes to '
        'Wikipedia. (also, wikimon, wikital monsters)')


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
      python_requires='>=3.10',
      install_requires=['aiohttp>=3.9,<4',
                        'websockets>=12.0,<14',
                        'maxminddb>=2.4,<3',
                        'requests>=2.31,<3'],
      license=__license__,
      platforms='any',
      classifiers=[
          'Programming Language :: Python :: 3.10',
          'Programming Language :: Python :: 3.11',
          'Programming Language :: Python :: 3.12',
      ]
      )
