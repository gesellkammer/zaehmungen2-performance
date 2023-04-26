#!/usr/bin/env python3
import time
import os
import sys
import shutil
import subprocess
from zaehmungen import core
import zaehmungen


# Default configuration, it will be overridden by config.txt
# if it exists (in the same directory as this file)

SR = 44100
KSMPS = 64

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

# check installation

def exists_in_path(binary):
    return shutil.which(binary) is not None

if not exists_in_path("csound"):
    print("csound was not found")
    sys.exit(-1)

if not exists_in_path("pd"):
    print("puredata was not found")
    sys.exit(-1)

# setup

def is_jack_running():
    if exists_in_path("jack_control"):
        status = subprocess.call(['jack_control', 'status'])
        if status == 0:
            return True
    else:
        print("jack_control was not found. This doesn't look right")
        if not exists_in_path("qjackctl"):
            print("qjackctl was also not found. Please install that in order")
            print("to control jack via dbus")
            return False
    try:
        procs = subprocess.check_output(["pgrep", "-x", "jackd"]).splitlines()
        return len(procs) > 0
    except subprocess.CalledProcessError:
        return False

if not is_jack_running():
    print("Jack is not running. Please start it, then run this script again")
    sys.exit(-1)

configfile = "config.txt"
if os.path.exists(configfile):
    print("reading configuration")
    exec(open(configfile).read())

def killmatching(pattern):
    os.system(f'killall -9 "{pattern}"')
    timeout = 1
    while timeout > 0:
        procs = procsmatching(pattern)
        if not procs:
            return True
        time.sleep(0.1)
        timeout -= 0.1
    raise RuntimeError(f"could not kill {pattern}")

def procsmatching(pattern):
    try:
        out = subprocess.check_output(["pgrep", "-f", pattern])
        return [int(pid) for pid in out.splitlines()]
    except subprocess.CalledProcessError:
        return None

killmatching("csound")

# puredata gui

pdpatch = os.path.abspath("assets/zaehmungen.pd")
assert os.path.exists(pdpatch)
pdproc = subprocess.Popen(['pd', '-noaudio', '-nomidi', pdpatch])

csoundpatch = os.path.abspath("assets/midikeyb.csd")
assert os.path.exists(csoundpatch)
csoundargs = [
    "csound",
    "-+rtaudio=jack",
    "-odac",
    f"--sample-rate={SR}",
    f"--ksmps={KSMPS}",
    "-m", "0",
    csoundpatch
]

# csound engine

print(csoundargs)
csoundproc = subprocess.Popen(csoundargs)

# controler

keyb = core.MidiKeyb()

try:
    keyb.start()
except KeyboardInterrupt:
    print("Keyboard interrupt: exiting")
except zaehmungen.error.GuiConnectionError:
    print("GuiConnectionError")

print("exiting")
time.sleep(2)

print("killing subprocesses")
csoundproc.kill()
pdproc.kill()
