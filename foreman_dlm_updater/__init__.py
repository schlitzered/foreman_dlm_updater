import argparse
import configparser
import subprocess
import logging
import os
import sys
import time
from logging.handlers import TimedRotatingFileHandler

from pep3143daemon import PidFile
import requests


def main():
    parser = argparse.ArgumentParser(description="Foreman DLM Updater")

    parser.add_argument("--cfg", dest="cfg", action="store",
                        default="/etc/foreman_dlm_updater/config.ini",
                        help="Full path to configuration")

    parsed_args = parser.parse_args()

    instance = ForemanDlmUpdater(cfg=parsed_args.cfg)
    instance.work()


class ForemanDlmLock(object):
    def __init__(self, log, lock_name, ca, client_crt, client_key, foreman_url):
        self._ca = ca
        self._client_crt = client_crt
        self._client_key = client_key
        self._foreman_url = foreman_url
        self._lock_name = lock_name
        self.log = log

    @property
    def ca(self):
        return self._ca

    @property
    def client_crt(self):
        return self._client_crt

    @property
    def client_key(self):
        return self._client_key

    @property
    def foreman_lock_url(self):
        return "{0}/api/dlmlocks/{1}/lock".format(self._foreman_url, self._lock_name)

    def acquire(self):
        self.log.info("trying to acquire: {0}".format(self.foreman_lock_url))
        while True:
            resp = requests.put(
                url=self.foreman_lock_url,
                cert=(self.client_crt, self.client_key),
                headers={
                    "Content-Type": "application/json"
                },
                verify=self.ca
            )
            self.log.debug("http status_code is: {0}".format(resp.status_code))
            self.log.debug("http_response is {0}".format(resp.json()))
            if resp.status_code == 200:
                self.log.info("success acquiring lock")
                return
            elif resp.status_code == 412:
                self.log.error(" could not acquire lock, sleeping for 60 seconds")
                time.sleep(60)
            else:
                self.log.fatal("could not acquire lock: {0}".format(resp.json()))
                sys.exit(1)

    def release(self):
        self.log.info("trying to release: {0}".format(self.foreman_lock_url))
        resp = requests.delete(
            url=self.foreman_lock_url,
            cert=(self.client_crt, self.client_key),
            headers={
                "Content-Type": "application/json"
            },
            verify=self.ca
        )
        self.log.debug("http status_code is: {0}".format(resp.status_code))
        self.log.debug("http_response is {0}".format(resp.json()))
        if resp.status_code == 200:
            self.log.info("success releasing lock")
            return
        elif resp.status_code == 412:
            self.log.fatal("could not release lock, how did we managed to here?")
            sys.exit(1)
        else:
            self.log.fatal("could not release lock: {0}".format(resp.json()))
            sys.exit(1)


class ForemanDlmUpdater(object):
    def __init__(self, cfg):
        self._config_file = cfg
        self._config = configparser.ConfigParser()
        self._config_dict = None
        self.log = logging.getLogger('application')
        self.config.read_file(open(self._config_file))
        self._logging()
        self._lock = PidFile(self.config.get('main', 'lock'))
        self._foreman_lock = ForemanDlmLock(
            log=self.log,
            ca=self.config.get('main', 'ca', fallback=None),
            client_crt=self.config.get('main', 'client_crt'),
            client_key=self.config.get('main', 'client_key'),
            foreman_url=self.config.get('main', 'foreman_url'),
            lock_name=self.config.get('main', 'lock_name',),
        )

    @property
    def config(self):
        return self._config

    @property
    def foreman_lock(self):
        return self._foreman_lock

    @property
    def lock(self):
        return self._lock

    def _logging(self):
        logfmt = logging.Formatter('%(asctime)sUTC - %(levelname)s - %(threadName)s - %(message)s')
        logfmt.converter = time.gmtime
        handlers = []
        aap_level = self.config.get('main', 'loglevel')
        log = self.config.get('main', 'log')
        retention = self.config.getint('main', 'logretention')
        handlers.append(TimedRotatingFileHandler(log, 'd', 1, retention))

        for handler in handlers:
            handler.setFormatter(logfmt)
            self.log.addHandler(handler)
        self.log.setLevel(aap_level)
        self.log.debug("logger is up")

    def execute_shell(self, args):
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        for line in p.stdout:
            self.log.info(line.rstrip())
        p.stdout.close()
        return p.wait()

    @property
    def task(self):
        try:
            with open(self.config.get('main', 'state'), 'r') as state:
                return state.readline().rstrip("\n")
        except FileNotFoundError:
            return 'check_update'

    @task.setter
    def task(self, task):
        try:
            with open(self.config.get('main', 'state'), 'w') as state:
                state.write("{0}\n".format(task))
        except OSError as err:
            self.log.fatal("could not set state: {0}".format(err))
            sys.exit(1)

    @task.deleter
    def task(self):
        try:
            os.remove(self.config.get('main', 'state'))
        except OSError as err:
            self.log.error("could not remove state file: {0}".format(err))

    def check_update(self):
        do_update = False
        self.log.info("checking if updates are available")
        _path = self.config.get('main', 'needs_update.d')
        files = [f for f in os.listdir(_path) if os.path.isfile(os.path.join(_path, f))]
        for _file in files:
            _file = os.path.join(_path, _file)
            if not os.access(_file, os.X_OK):
                continue
            self.log.info("running: {0}".format(_file))
            if self.execute_shell([_file]) != 0:
                self.log.info("updates are available")
                do_update = True
            self.log.info("running: {0} done".format(_file))
        if do_update:
            self.log.debug("setting task to lock_get")
            self.task = "lock_get"
        else:
            self.log.info("no updates available")
            sys.exit(0)

    def lock_get(self):
        self.foreman_lock.acquire()
        self.task = "pre_update"

    def lock_release(self):
        self.log.info("releasing lock")
        self.foreman_lock.release()
        del self.task
        sys.exit(0)

    def do_update(self):
        self.log.info("running_update scripts")
        _path = self.config.get('main', 'update.d')
        files = [f for f in os.listdir(_path) if os.path.isfile(os.path.join(_path, f))]
        for _file in files:
            _file = os.path.join(_path, _file)
            if not os.access(_file, os.X_OK):
                continue
            self.log.info("running: {0}".format(_file))
            if self.execute_shell([_file]) != 0:
                self.log.info("script failed, stopping, keeping lock")
                sys.exit(1)
            self.log.info("running: {0} done".format(_file))
        self.log.info("setting task to needs_reboot")
        self.task = "needs_reboot"

    def post_update(self):
        self.log.info("running post_update scripts")
        _path = self.config.get('main', 'post_update.d')
        files = [f for f in os.listdir(_path) if os.path.isfile(os.path.join(_path, f))]
        for _file in files:
            _file = os.path.join(_path, _file)
            if not os.access(_file, os.X_OK):
                continue
            self.log.info("running: {0}".format(_file))
            if self.execute_shell([_file]) != 0:
                self.log.info("script failed, stopping, keeping lock")
                sys.exit(1)
            self.log.info("running: {0} done".format(_file))
        self.log.info("setting task to lock_release")
        self.task = "lock_release"

    def pre_update(self):
        self.log.info("running pre_update scripts")
        _path = self.config.get('main', 'pre_update.d')
        files = [f for f in os.listdir(_path) if os.path.isfile(os.path.join(_path, f))]
        for _file in files:
            _file = os.path.join(_path, _file)
            if not os.access(_file, os.X_OK):
                continue
            self.log.info("running: {0}".format(_file))
            if self.execute_shell([_file]) != 0:
                self.log.info("script failed, stopping, keeping lock")
                sys.exit(1)
            self.log.info("running: {0} done".format(_file))
        self.log.info("setting task to do_update")
        self.task = "do_update"

    def reboot(self):
        self.log.info("rebooting, and setting task to post_update")
        self.task = "post_update"
        sys.exit(self.execute_shell([self.config.get('main', 'reboot_cmd')]))

    def needs_reboot(self):
        reboot = True
        _path = self.config.get('main', 'needs_reboot.d')
        self.log.info("running needs reboot scripts")
        files = [f for f in os.listdir(_path) if os.path.isfile(os.path.join(_path, f))]
        for _file in files:
            _file = os.path.join(_path, _file)
            if not os.access(_file, os.X_OK):
                continue
            self.log.info("running: {0}".format(_file))
            if self.execute_shell([_file]) != 0:
                self.log.info("running: {0} done".format(_file))
                reboot = True
                break
            else:
                reboot = False
            self.log.info("running: {0} done".format(_file))
        if reboot:
            self.log.info("setting task to reboot")
            self.task = "reboot"
        else:
            self.log.info("setting task to post_update")
            self.task = "post_update"

    def work(self):
        self.lock.acquire()
        while True:
            task = self.task
            if task not in [
                "check_update",
                "lock_get",
                "pre_update",
                "do_update",
                "needs_reboot",
                "reboot",
                "post_update",
                "lock_release"
            ]:
                self.log.fatal("found garbage in status file")
                sys.exit(1)
            if task == "check_update":
                self.check_update()
            elif task == "lock_get":
                self.lock_get()
            elif task == "lock_release":
                self.lock_release()
            elif task == "pre_update":
                self.pre_update()
            elif task == "do_update":
                self.do_update()
            elif task == "needs_reboot":
                self.needs_reboot()
            elif task == "reboot":
                self.reboot()
            elif task == "post_update":
                self.post_update()
            else:
                break
