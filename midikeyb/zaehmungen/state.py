from __future__ import print_function, division
import sys
import os
import logging
import logging.handlers
import shutil
import json

from .utils import *

CONFIGFILE_USER = 'userconfig.json'
CONFIGFILE_DEFAULT = 'defaultconfig.json'
CONFIGFILE_LASTSTATE = 'laststate.json'

# This is used for the situation where the installation has been
# messed up with. 
FALLBACK_CONFIG = {
    "midichannel": "ALL",
    "CC_gainchange": 7,
    "CC_sensibility": 93,
    "CC_ratefactor": 91,
    "CC_compressor": 81,
    "CC_randomness": 82,
    "CC_sustain": 64,
    "ratefactor_max": 5,
    "rategactor_min": 0.5,
    "mingain_db": -80,
    "maxgain_db": 0,
    "noteon_max_db": 0,
    "noteon_min_db": -30,
    "default_midichannel": 0,
    "allow_kbd_rate_factor_change": False,
    "save_last_state": True,
    "compression": 0.2,
    "randomness": 0.35,
    "volpedal_curve": 0.4
}

STATE_KEYS = "compression randomness noteon_max_db noteon_min_db gain speed rate".split()

USERFOLDER = os.path.expanduser("~/.zaehmungen")

LOGPATH = os.path.join(USERFOLDER, 'zaehmungen.log')
LOGGERS = {}
env = {'prepared': False}


def prepare():
    """
    prepares the user environment

    Returns True if succesful, False if failed
    """
    if env['prepared']:
        print("environment already prepared!")
        return True
    userpath = USERFOLDER
    if not os.path.exists(userpath):
        print("prepare: creating userpath at %s" % userpath)
        os.mkdir(userpath)
    if not os.path.exists(os.path.join(userpath, CONFIGFILE_USER)):
        print("prepare: creating empty userconfig")
        shutil.copy(os.path.join("assets", CONFIGFILE_USER), os.path.join(userpath, CONFIGFILE_USER))
    env['prepared'] = True
    return True
    

def new_logger():
    if not env['prepared']:
        prepare()
    logger = logging.getLogger('zaehmungen')
    logger.setLevel(logging.DEBUG)
    basepath = os.path.split(LOGPATH)[0]
    if not os.path.exists(basepath):
        print("base path for logfile does not exist, creating")
        os.mkdir(basepath)
    try:
        handler = logging.handlers.RotatingFileHandler(LOGPATH, maxBytes=80*2000, backupCount=1)
    except IOError:
        handler = logging.handlers.SysLogHandler()
    handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    logger.addHandler(handler)
    return logger


def get_logger():
    logger = LOGGERS.get('CORE')
    if logger is None:
        logger = new_logger()
        LOGGERS['CORE'] = logger
    return logger


def _debug(msg):
    logger = get_logger()
    logger.debug(msg)


def config_load():
    defaultconfig = os.path.join("assets", CONFIGFILE_DEFAULT)
    error = None
    if os.path.exists(defaultconfig):
        try:
            _debug(f"loading default config: {defaultconfig}")
            config = json_load(defaultconfig)
        except ValueError:
            _debug("config_load: could not parse default config! using builtin config")
            error = "ParseError:Default"
    else:
        config = FALLBACK_CONFIG
    userconfig = os.path.join(USERFOLDER, CONFIGFILE_USER)
    if os.path.exists(userconfig):
        try:
            _debug(f"loading user config: {userconfig}")
            user = json_load(userconfig)
            print(user)
            config.update(user)
        except ValueError:
            _debug("config_load: could not parse user config! using default")
            _debug(sys.exc_info())
            error = "ParseError:User"
    else:
        prepare()
        if not os.path.exists(userconfig):
            _debug("WTF?!")
            sys.exit(0)
    last_state = state_load()
    if last_state:
        config.update(last_state)
    for key, value in sorted(config.items()):
        _debug("{key} : {value}".format(key=key.ljust(16), value=value))
    return {'config': config, 'defaultconfig': defaultconfig, 'userconfig': userconfig, 'error':error}


def state_load():
    _debug("state_load: loading")
    path = os.path.join(USERFOLDER, CONFIGFILE_LASTSTATE)
    laststate = {}
    if os.path.exists(path):
        try:
            laststate = json.load(open(path))
            _debug("state_load: configfile loaded from: %s" % path)
        except IOError:
            _debug("state_load: configfile not found, laststate is %s" % str(laststate))
            pass
    return laststate


def state_save(config):
    path = os.path.join(USERFOLDER, CONFIGFILE_LASTSTATE)
    _debug("state_save: saving to %s" % path)
    state = {key:config[key] for key in STATE_KEYS if config.get(key) is not None}
    json.dump(state, open(path, 'w'))
