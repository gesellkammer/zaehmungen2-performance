from __future__ import division, print_function
"""
helper functions to work with csound
"""

from math import ceil, log
import os
import sys
import subprocess 
import re
from collections import namedtuple
import shutil

class PlatformNotSupported(BaseException): pass
class CsoundVersionError(BaseException): pass

def find_csound():
    path = shutil.which("csound")
    if os.path.exists(path):
        return path
    return None
  

def get_version():
    """
    Returns the csound version as tuple (major, minor, patch) so that '6.03.0' is (6, 3, 0)

    Raises IOError if either csound is not present or its version 
    can't be parsed
    """
    csound = find_csound()
    if not csound:
        raise IOError("Csound not found")
    cmd = '{csound} --help'.format(csound=csound).split()
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE)
    proc.wait()
    lines = proc.stderr.readlines()
    if not lines:
        raise IOError("Could not read csounds output")
    for line in lines:
        if line.startswith("Csound version"):
            matches = re.findall("\d.\d+.\d+", line)
            if matches:
                version = matches[0]
                try:
                    major, minor, patch = map(int, version.split("."))
                    return (major, minor, patch)
                except ValueError:
                    raise ValueError("Csound version malformed: %s" % version)
    raise IOError("Did not found a csound version")

OPCODES = None

def call_csound(*args, **kws):
    """
    call csound with the given arguments in a subprocess

    kws
    ---

    pipe_stderr --> call subproc with stderr=PIPE

    Returns -> a subprocess
    """
    csound = find_csound()
    if not csound:
        return
    cmd = [csound] + list(args)
    print("calling csound with cmd: %s" % " ".join(cmd))
    pipestderr = kws.get("pipe_stderr", False)
    if pipestderr:
        proc = subprocess.Popen(cmd, stderr=subprocess.PIPE)
    else:
        proc = subprocess.Popen(cmd)
    return proc


_audiodevice = namedtuple("Dev", "index label name")

def get_audiodevices(backend=None):
    """
    backend: specify a backend supported by your installation of csound
             None to use a default for you OS

    Returns (indevices, outdevices), where each of these lists 
    is a tuple (index, label, name)

    IMPORTANT: This functionality is only present starting with
               version 6.03.0. This function will raise an 
               exception CsoundVersionError if this is not 
               the case

    label: is something like 'adc0', 'dac1' and is what you
           need to pass to csound to its -i or -o methods. 
    name:  the name of the device. Something like "Built-in Input"

    Backends:

            OSX   Linux   Multiple-Devices    Description
    jack     x      x          -                 Jack
    auhal    x      -          x                 CoreAudio
    pa_cb    x      x          x                 PortAudio (Callback)
    pa_bl    x      x          x                 PortAudio (blocking)
    """
    if get_version() < (6, 3, 0):
        raise CsoundVersionError("This query is only supported in csound >= 6.03.0")

    if backend is None:
        if sys.platform == 'darwin':
            backends = ["pa_cb", "auhal"]
        elif sys.platform == 'linux2':
            backends = ["pa_cb"]
        else:
            raise PlatformNotSupported
    else:
        backends = [backend]
    def parse_device_line(line):
        line = line.strip()
        index, rst = [_.strip() for _ in line.split(":", 1)]
        index = int(index)
        devlabel, devname = rst.strip().split(" ", 1)
        devname = devname[1:-1]
        return _audiodevice(index, devlabel, devname)
    indevices, outdevices = None, None
    for backend in backends:
        proc = call_csound('-+rtaudio=%s'%backend, '--devices', pipe_stderr=True)
        proc.wait()
        lines = proc.stderr.readlines()
        for i, line in enumerate(lines):
            if 'audio input devices' in line:
                matches = re.findall("\d+(?=\saudio)", line)
                if matches:
                    numin = int(matches[0])
                    indevices = map(parse_device_line, lines[i+1:i+1+numin])
                    lines = lines[i:]
                break 
        for i, line in enumerate(lines):
            if 'audio output devices' in line:
                matches = re.findall("\d+(?=\saudio)", line)
                if matches:
                    numout = int(matches[0])
                    outdevices = map(parse_device_line, lines[i+1:i+1+numin])
                break
        if numin and numout:
            break
    return indevices, outdevices


def detect_jack():
    raise RuntimeError("Use jack_control status")
    proc = call_csound('-+rtaudio=jack', '--devices', pipe_stderr=True)
    return 'JACK module enabled' in proc.stderr.read()


def get_system_samplerate(device=None, backend=None):
    """
    audiodevice: a number
    """
    args = []
    if device is None:
        device = ''
    args.append('-odac%s' % str(device))
    if backend is None:
        if detect_jack():
            # Jack is present, assume the user wants to use it
            return _jack_get_samplerate()
    args.appeng('--get-system-sr')
    proc = call_csound(*args, pipe_stderr=True)
    proc.wait()
    for line in proc.stderr.readlines():
        if 'system sr:' in line:
            sr = float(line.split(":")[1].strip())
            print("got samplerate: %d" % int(sr))
            return sr
    return None


def _jack_get_samplerate():
    raise RuntimeError("Use jack_samplerate")
    proc = call_csound('-odac', '-+rtaudio=jack', '--get-system-sr', pipe_stderr=True)
    proc.wait()
    for line in proc.stderr.readlines():
        if '*** rtjack' in line and 'does not match' in line:
            words = line.split()
            sr = float(words[-1])
            return sr
        elif 'system sr:' in line:
            sr = float(line.split(":")[1].strip())
            return sr








