import argparse
import configparser
import subprocess
import logging
import os
import stat
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

    parser.add_argument("--after_reboot", dest="rbt", action="store_true",
                        default=False,
                        help="has to be used from init systems, to indicated that the script was calle:w"
                             "d while booting.")

    parsed_args = parser.parse_args()

    instance = ForemanDlmUpdater(
        cfg=parsed_args.cfg,
        rbt=parsed_args.rbt,
    )
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
    def __init__(self, cfg, rbt):
        self._config_file = cfg
        self._config = configparser.ConfigParser()
        self._config_dict = None
        self._rbt = rbt
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

    @property
    def rbt(self):
        return self._rbt

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
            return 'needs_update'

    @task.setter
    def task(self, task):
        self.log.info("setting task to {0}".format(task))
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

    def check_rbt(self):
        if self._rbt:
            if self.task != 'post_update':
                self.log.info("reboot was not triggered by foreman_dlm_updater, exiting")
                sys.exit(0)
            else:
                self.log.info("reboot was triggered by foreman_dlm_updater, picking up remaining tasks")

    def lock_get(self):
        self.foreman_lock.acquire()
        self.task = "pre_update"

    def lock_release(self):
        self.log.info("releasing lock")
        self.foreman_lock.release()
        del self.task
        sys.exit(0)

    def get_scripts(self, path):
        _path = self.config.get('main', path)
        files = list()
        for _file in os.listdir(_path):
            _file = os.path.join(_path, _file)
            self.log.debug("found the file: {0}".format(_file))
            if not os.path.isfile(_file):
                continue
            if not os.stat(_file).st_uid == 0:
                self.log.warning("file not owned by root")
                continue
            if os.stat(_file).st_mode & stat.S_IXUSR != 64:
                self.log.warning("file not executable by root")
                continue
            if os.stat(_file).st_mode & stat.S_IWOTH == 2:
                self.log.warning("file group writeable")
                continue
            if os.stat(_file).st_mode & stat.S_IWGRP == 16:
                self.log.warning("file world writeable")
                continue
            files.append(_file)
        return files

    def needs_update(self):
        update = False
        self.log.info("checking if updates are available")
        files = self.get_scripts('needs_update.d')
        for _file in files:
            self.log.info("running: {0}".format(_file))
            if self.execute_shell([_file]) != 0:
                self.log.info("updates are available")
                update = True
            self.log.info("running: {0} done".format(_file))
        if update:
            self.task = "lock_get"
        else:
            self.log.info("no updates available")
            sys.exit(0)

    def update(self):
        self.log.info("running_update scripts")
        files = self.get_scripts('update.d')
        for _file in files:
            self.log.info("running: {0}".format(_file))
            if self.execute_shell([_file]) != 0:
                self.log.info("script failed, stopping, keeping lock")
                sys.exit(1)
            self.log.info("running: {0} done".format(_file))
        self.task = "needs_reboot"

    def post_update(self):
        self.log.info("running post_update scripts")
        files = self.get_scripts('post_update.d')
        for _file in files:
            self.log.info("running: {0}".format(_file))
            if self.execute_shell([_file]) != 0:
                self.log.info("script failed, stopping, keeping lock")
                sys.exit(1)
            self.log.info("running: {0} done".format(_file))
        self.task = "lock_release"

    def pre_update(self):
        self.log.info("running pre_update scripts")
        files = self.get_scripts('pre_update.d')
        for _file in files:
            self.log.info("running: {0}".format(_file))
            if self.execute_shell([_file]) != 0:
                self.log.info("script failed, stopping, keeping lock")
                sys.exit(1)
            self.log.info("running: {0} done".format(_file))
        self.task = "update"

    def reboot(self):
        self.log.info("rebooting")
        self.task = "post_update"
        sys.exit(self.execute_shell([self.config.get('main', 'reboot_cmd')]))

    def needs_reboot(self):
        self.log.info("running needs reboot scripts")
        reboot = True
        files = self.get_scripts('needs_reboot.d')
        for _file in files:
            self.log.info("running: {0}".format(_file))
            if self.execute_shell([_file]) != 0:
                self.log.info("running: {0} done".format(_file))
                reboot = True
                break
            else:
                reboot = False
            self.log.info("running: {0} done".format(_file))
        if reboot:
            self.task = "reboot"
        else:
            self.task = "post_update"

    def work(self):
        self.lock.acquire()
        self.check_rbt()
        while True:
            task = self.task
            if task not in [
                "needs_update",
                "lock_get",
                "pre_update",
                "update",
                "needs_reboot",
                "reboot",
                "post_update",
                "lock_release"
            ]:
                self.log.fatal("found garbage in status file: {0}".format(self.task))
                del self.task
                sys.exit(1)
            if task == "needs_update":
                self.needs_update()
            elif task == "lock_get":
                self.lock_get()
            elif task == "lock_release":
                self.lock_release()
            elif task == "pre_update":
                self.pre_update()
            elif task == "update":
                self.update()
            elif task == "needs_reboot":
                self.needs_reboot()
            elif task == "reboot":
                self.reboot()
            elif task == "post_update":
                self.post_update()
