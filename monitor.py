# some code from Twisted Matrix's irc_test.py
from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
import time, sys, re, datetime

DEBUG = False

import logging
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s\t%(name)s\t %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

logger_name = __name__
if __name__ == '__main__':
    logger_name = 'monitor'

mon_log = logging.getLogger(logger_name)
mon_log.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO) 
mon_log.addHandler(console_handler)

CHANNEL = 'en.wikipedia' # use language.project

PARSE_EDIT_RE = re.compile(r'(\[\[(?P<page_title>.*?)\]\])'
                           r' +((?P<flags>[A-Z\!]+) )?'
                           r'(?P<url>\S*)'
                           r' +\* (?P<user>.*?)'
                           r' \* (\((?P<change_size>[\+\-][0-9]+)\))?'
                           r' ?(?P<summary>.+)?')
COLOR_RE = re.compile("\x03(?:\d{1,2}(?:,\d{1,2})?)?", re.UNICODE) # remove IRC color codes


def process_message(message):
    no_color = COLOR_RE.sub('', message)
    ret = PARSE_EDIT_RE.match(no_color)
    if ret:
        return ret.groupdict()
    return {}


class Monitor(irc.IRCClient): 
    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
 
    def signedOn(self):
        self.join(self.factory.channel)
 
    def privmsg(self, user, channel, msg):
        processed = process_message(msg)
        mon_log.info('%r', processed)

 
class MonitorFactory(protocol.ClientFactory):
    def __init__(self, channel):
        self.channel = channel
 
    def buildProtocol(self, addr):
        p = Monitor()
        p.factory = self
        return p

if __name__ == '__main__':
    f = MonitorFactory(CHANNEL)
    reactor.connectTCP("irc.wikimedia.org", 6667, f)
    reactor.run()
