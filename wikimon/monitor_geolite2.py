import time
from twisted.python import log, filepath
from twisted.internet.threads import deferToThread
from twisted.internet.task import LoopingCall
import geoip

observer = log.PythonLoggingObserver()
observer.start()

import logging

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s\t%(name)s\t %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)


DEFAULT_INTERVAL = 30


class MonitorGeoLite2(object):
    geoip_db = None

    def __init__(self, path):
        self.last_modified = time.time()
        self.fp = filepath.FilePath(path)

    def log_error(self, failure):
        logger.error(str(failure))

    def load_if_new(self, force=False):
        self.fp.restat()
        modified = self.fp.getModificationTime()
        if not force and modified <= self.last_modified:
            return
        logger.info('%r modified: %s > %s', self.fp,
                    modified, self.last_modified)
        self.last_modified = modified
        return geoip.open_database(self.fp.realpath().path)

    def store(self, new_geoip_db):
        if new_geoip_db:
            # atomic
            self.geoip_db = new_geoip_db
            logger.info('swapped geoips')

    def update(self):
        self.store(self.load_if_new(True))

    def check_and_update(self):
        d = deferToThread(self.load_if_new)
        d.addCallbacks(self.store, self.log_error)
        return d


def begin(path, interval):
    monitor = MonitorGeoLite2(path)
    monitor.update()
    LoopingCall(monitor.check_and_update).start(interval)
    return monitor
