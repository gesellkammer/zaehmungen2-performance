#!/usr/bin/env python
import subprocess
import sys
import os

def get_csound_version():
    if sys.platform == 'darwin':
        possible_paths = ['/usr/local/bin/csound']
    else:
        print "Platform not supported!"
        return None, None
    for path in possible_paths:
        try:
            s = subprocess.Popen([path, '--help', '2>&1', '|grep "Csound version"'.format(path=path), stdout=subprocess.PIPE)
            line = s.stdout.readline()
            break
        except OSError:
            pass
    else:
        return None, None
    l = s.stdout.readline()
    version = l.split()[2]
    major, minor = map(int, version.split('.')[:2])
    return major, minor

def notify(msg):
    print "---", msg

def check():
    csound_major, csound_minor = get_csound_version()
    if csound_major is None:
        return (False, "Csound could not be found. Download it from http://sourceforge.net/projects/csound/files/csound6/Csound6.00.1/")
    if not (csound_major >= 5 and csound_minor >= 12):
        return (False, "The version of Csound is too old. Csound >= 5.12 is needed. Please update and try again")
    return True, ""

if __name__ == '__main__':
    ok, errmsg = check()
    if not ok:
        print errmsg
        sys.exit(0)
    print "CHECK OK!"
