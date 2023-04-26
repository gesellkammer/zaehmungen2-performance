import sys
import os

import operator
import time
from numbers import Number
import liblo
import rtmidi2
import timer3
from queue import Queue

from .utils import *
from .state import *
from .error import *

logger = get_logger()

DEBUG_TO_CONSOLE = True

# Internal Constants
# OSC port where Csound is listening, this must match the port given in the CSD file
CSD_OSCPORT = 7770      
CORE_OSCPORT = 7771
INFO_OSCPORT = 7772

# these should match the order in gi_sndfiles in midikeyb.csd
TABLE_VL = 0       
TABLE_VLA = 1
TABLE_VC = 2

INSTRS = {
    TABLE_VC: 'VC',
    TABLE_VLA: 'VLA',
    TABLE_VL: 'VL'
}

# some notes to make code readable
C4 =  60
C7 =  C4 + 3 * 12
C2 =  C4 - 24
C3 =  C4 - 12
Cx2 = C2 + 1
D2 =  C2 + 2
E2 =  C2 + 4
Eb2 = E2 - 1
F2 =  C2 + 5
Fx2 = F2 + 1
B2 =  F2 + 6

SPEEDVALUES = [
    0.10000000000000001, 0.12583426132260583,  0.15358983848622454, 0.183772233983162,  0.21715728752538094,
    0.2550510257216822,  0.29999999999999999,  0.35857864376269044, 0.5,                0.71875,
    0.875,               0.96875,              1.0,                 1.2599210498948732, 1.5874010519681994,
    1.9999999999999998,  2.5198420997897459,   3.1748021039363983,  3.9999999999999991, 5.039684199579491,
    6.3496042078727957,  7.9999999999999973,   10.079368399158982,  12.699208415745593, 15.999999999999993
]

class FileModificationWatcher(object):
    def __init__(self, path, callback, time_threshold=0.5):
        """
        time_threshold: the difference in time that will trigger a callback
        """
        self.path = path
        self.callback = callback
        self.last_modified = os.stat(path).st_mtime
        self.threshold = time_threshold
        
    def tick(self):
        mtime = os.stat(self.path).st_mtime
        if mtime - self.last_modified > self.threshold:
            self.callback()
            self.last_modified = mtime


class MidiKeyb:
    def __init__(self):
        self.debug("-" * 20)
        self.debug('STARTING MidiKeyb'.center(20))
        self.debug("-" * 20)
        
        self._running = False
        self._paused = False
        self._midiin = None
        self._midi_enabled_channels = [1 for i in range(16)]
        self._midi_inports = []
        self._csd_connected = False
        self._gui_connected = False
        self._csound_addr = liblo.Address("127.0.0.1", CSD_OSCPORT)

        # Support for running funtions on the main thread
        self._tasks = Queue()
        self._tasks_lastcheck = 0
        self.background_task_lasttime = 0
        self._background_tast_enabled = True
        self._lastheartbeat = 0
        self._gui_lastheartbeat = 0
        self._scheduler = timer3.Timer(precision=0.05)

        result = config_load()
        if result['error']:
            self.error("Error loading configfile: %s" % result['error'])
        self.config = result['config']
        
        self._userconfig_path = result['userconfig']
        self.userconfig_watcher = FileModificationWatcher(self._userconfig_path, self.reload)

        self.reset()
        self._create_oscserver()
        
        time.sleep(0.5)
        self.midi_restart()
        self.debug("setting up tasks")
        scheduler = self._scheduler
        scheduler.apply_after(3100, self.dump_state)
        time.sleep(0.1)
        scheduler.apply_interval(1000, self.background_task)
        time.sleep(0.1)
        scheduler.apply_interval(1700, self.userconfig_watcher.tick)
        time.sleep(0.1)
        scheduler.apply_interval(3700, self.state_save)
        # this needs to be run in the main thread to detect new devices
        scheduler.apply_interval(1900, lambda:self.run_in_mainthread(self.midi_check_new_ports))
        # scheduler.apply_after(500, self.midi_restart)
        self.debug("finished setting tasks")

    def reset(self):
        self.last_octave = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        self.notesdown = 0
        self.sustainpedal = False
        self.notesheld = [False for i in range(127)]
        self.notesheld_by_pedal = set()
        self.speed_values = SPEEDVALUES
        self.ratefactors = linspace(1, 2.5, C3 - Eb2)
        self.ratefactor = 1
        self.rate = 12
        self.speed = 1
        self.gain = 1
        self.table = "VL"
        self.tableindex = 0  
        self.midichannel = 'ALL'
        self.midiports = ['*']
        self.num_speed_values = len(self.speed_values)
        self.graindur = 100
        self.graindurs = (10, 20, 50, 100, 200, 500)    # ms
        self.graindurindex = self.graindurs.index(self.graindur)
        self.num_graindurs = len(self.graindurs)
        assert len(self.last_octave) == 12
        self.grainrate_mask = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        
        self._csd_connected = False
        self.background_task_lasttime = self._lastheartbeat = time.time()
        self._setup_config_dependencies()

    def reload(self):
        if not self._running or self._paused:
            return
        self.debug("RELOADING")
        self._paused = True
        config = config_load()
        if config['error']:
            self.error(f"Error loading configfile: {config['error']}. Using last version")
        newconfig = config['config']
        oldconfig = self.config
        for key, newvalue in newconfig.items():
            oldvalue = oldconfig.get(key)
            if newvalue != oldvalue:
                self.debug(f"{key}: {oldvalue} -> {newvalue}")
        self.config = newconfig
        self._setup_config_dependencies()
        self.dump_state()
        self._paused = False

    def debug(self, msg):
        if DEBUG_TO_CONSOLE:
            print(msg)
        logger.debug(msg)

    def error(self, msg):
        logger.error(msg)

    def info(self, label, msg=""):
        if isinstance(msg, float):
            msg = ('f', msg)
        if label.startswith("/"):
            self._oscserver.send(INFO_OSCPORT, label, msg)
        else:
            self._oscserver.send(INFO_OSCPORT, '/print', "%s %s" % (label, msg))

    def midi_restart(self, ports=None):
        """
        ports: a list of patterns
        """
        if ports is None:
            ports = self.config['midiports']
        self.debug("midi_openports: %s" % str(ports))
        assert isinstance(ports, list)
        if self._midiin is not None:
            self._midiin.close_ports()
        self._midiin = rtmidi2.MidiInMulti()
        self._midiin.callback = self.midi_callback
        self._midiin.open_ports(*ports)
        self._midi_connected_ports = [self._midiin.get_port_name(i) for i in self._midiin.get_open_ports()]
        self._midi_available_ports = set(self._midiin.ports)
        self.debug(f"************** taking input from MIDI ports: {self._midi_connected_ports}")
        self.info("/connectedports", ":".join(self._midi_connected_ports))

    def midi_check_new_ports(self):
        ports_now = set(self._midiin.ports)
        if ports_now != self._midi_available_ports:
            self.debug("midi devices changed")
            self.midi_restart()

    def update_state(self, state):
        for key, value in state.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def _setup_config_dependencies(self):
        self.midi_channel_set(self.config['midichannel'])
        self.compression = self.config['compression']
        self.randomness = self.config['randomness']
        self.noteon_min_db = self.config['noteon_min_db']
        self.noteon_max_db = self.config['noteon_max_db']
        self.allow_kbd_rate_factor_change = self.config['allow_kbd_rate_factor_change']
        self.controllers = {
            self.config['CC_gainchange']: self.cc_gainchange,
            self.config['CC_ratefactor']: self.cc_ratefactor_set,
            self.config['CC_sensibility']: self.cc_sensibility_change,
            self.config['CC_compressor']: self.cc_compress_change,
            self.config['CC_randomness']: self.cc_randomness_change,
            self.config['CC_sustain']: self.sustainpedal_handler
        }
        self.debug("registered CC: %s" % str(list(self.controllers.keys())))

    def midi_channel_set(self, channel):
        if isinstance(channel, int):
            if channel < 1 or channel > 16:
                self.error("midichannel should be in the range 1-16 or the string ALL")
                return False
            channel -= 1
        if channel == 'ALL':
            for i in range(16):
                self._midi_enabled_channels[i] = 1
        else:
            for i in range(16):
                self._midi_enabled_channels[i] = 0
            self._midi_enabled_channels[channel] = 1
        self.midichannel = channel
        return True

    def _create_oscserver(self):
        try:
            s = liblo.Server(CORE_OSCPORT)
        except liblo.ServerError:
            raise OscError
        self.debug("creating server on port: " + str(s.port))
        
        def parse_reply_addr(args, src):
            if not args:
                return src
            addr = args[0]
            if isinstance(addr, str):
                hostname, port = addr.split(":")
            elif isinstance(addr, Number):
                hostname = "localhost"
                port = int(addr)
            else:
                self.error("could not parse address: %s", str(addr))
                return None
            return liblo.Address(hostname, port)

        self._oscapi = set()

        def midichannel_set_int(path, args, types, src, self):
            midich = args[0]
            if midich < 1 or midich > 16:
                self.error("midichannel should be an int 1-16 or the string ALL")
                return
            self.midi_channel_set(midich)

        def midichannel_get(path, args, types, src, self):
            addr = parse_reply_addr(args, src) 
            channels = [channel for channel in range(0, 15) if self._midi_enabled_channels[channel]]
            self._oscserver.send(addr, '/midichannel', *channels)

        def connectedports_get(path, args, types, src, self):
            addr = parse_reply_addr(args, src)
            ports = ":".join(self._midi_connected_ports)
            self._oscserver.send(addr, '/connectedports', ports)

        def stop(path, args, types, src, self):
            self.stop()

        def heart(path, args, types, src, self):
            self._lastheartbeat = time.time()
            self._csd_connected = True
            if not self._csd_connected:
                self.debug("csd connected!")
                self.info("/status", 'connected')

        def status_get(path, args, types, src, self):
            # addr = parse_reply_addr(args, src)
            self.info("/status", ["offline", "connected"][self._csd_connected])

        def test_noteon(path, args, types, src, self):
            try:
                midinote, velocity = args
            except IndexError:
                self.debug("test_noteon: index error, got " + str(args))
                return
            if velocity > 0:
                self.debug("noteon")
                self.noteon(midinote, velocity)
            else:
                self.debug("noteoff")
                self.noteoff(midinote)

        def rate_set(path, args, types, src, self):
            self.grainrate_change(args[0])

        def add_method(path, types, func, extra=None):
            s.add_method(path, types, func, extra)

        # called by csound to broadcast information
        def info(path, args, types, sr, self):
            rms, peak = args
            self._oscserver.send(INFO_OSCPORT, '/soundlevel', ('f', rms), ('f', peak))
            
        def ping(path, args, types, src, self):
            try:
                port = int(args[0])
            except TypeError:
                raise TypeError("ping: malformed message")    
            self._oscserver.send(port, '/pingback')

        def gui_heart(path, args, types, src, self):
            self._gui_lastheartbeat = time.time()
            if not self._gui_connected:
                self._gui_connected = True
                self.run_in_background(self.dump_state)
                
        # Sound Engine API
        add_method('/heart', None, heart, self)
        add_method('/info', None, info, self)

        # GUI API
        add_method('/connectedports/get', None, connectedports_get, self)
        add_method('/midichannel/set', 'i', midichannel_set_int, self)
        add_method('/stop', None, stop, self)
        add_method('/midichannel/get', None, midichannel_get, self)
        add_method('/status/get', None, status_get, self)
        add_method('/test/noteon', None, test_noteon, self)
        add_method('/openlog', None, self.openlog)
        add_method('/openconfig', None, lambda *args, **kws: self.openconfig())
        add_method('/dumpstate', None, lambda *args, **kws: self.dump_state())
        add_method('/rate/set', None, rate_set, self)
        add_method('/ping', None, ping, self)
        add_method('/gui/heart', None, gui_heart, self)
        add_method("/restartaudio", None, extra=self, func=self._csound_restart)
        add_method('/graindur/set', None, extra=self, 
                   func=lambda path, args, types, src, self:self.graindur_change(args[0]))
        add_method('/gain/set', None, extra=self, func=
                   lambda path, args, types, src, self: self.gain_set(clip(args[0], 0, 1)))
        add_method('/random/set', None, extra=self, 
                   func=lambda path, args, types, src, self: 
                   self.randomness_set(clip(args[0], 0, 1)))
        add_method('/compress/set', None, extra=self, 
                   func=lambda path, args, types, src, self: 
                   self.compress_change(clip(args[0], 0, 1)))
        add_method('/mindb/set', None, extra=self, func=
                   lambda path, args, types, src, self: 
                   self.sensibility_change(clip(args[0], -120, 12), self.noteon_max_db))
        add_method('/maxdb/set', None, extra=self, func=
                   lambda path, args, types, src, self: 
                   self.sensibility_change(self.noteon_min_db, clip(args[0], -120, 12)))
        self._oscserver = s

    def dump_state(self):
        print("dump_state")
        self.gain_set(self.gain)
        self.speed_set(self.speed)
        self.table_change_raw(self.tableindex)
        self.graindur_change_index(self.graindurindex)
        self.grainrate_change(self.rate)  
        self.compress_change()
        self.randomness_set()
        self.info("/mindb", self.noteon_min_db)
        self.info("/maxdb", self.noteon_max_db)
        self.info("/status", ("offline", "connected")[self._csd_connected])
        
    def noteon(self, midinote, velocity):
        if self.notesheld[midinote]:
            return
        if midinote < C2:
            return
        self.notesheld[midinote] = True
        if self.sustainpedal:
            self.notesheld_by_pedal.add(midinote)
            print("holding notes: %d" % len(self.notesheld_by_pedal))
        if midinote >= C3:
            # check if Cx2 is beeing held down. if it is, it is a change of speed
            if self.last_octave[1] == 1:
                self.cc_speed_set(midinote)
            else:
                # normal note
                self.play_with_velocity(midinote, velocity)
        else:  # it is withing the control octave
            if midinote <= Cx2:
                self.last_octave[midinote - C2] = 1
            else:
                # C2 is down, the pressed key changes either table (D, E, F) or grain-duration
                if self.last_octave[0] == 1:    
                    if midinote == D2:
                        self.table_change(TABLE_VC)
                    elif midinote == E2:
                        self.table_change(TABLE_VLA)
                    elif midinote == F2:
                        self.table_change(TABLE_VL)
                    elif midinote == Eb2:
                        self.panic()
                    else:
                        # grain-duration
                        self.cc_graindur_set(midinote)
                elif self.last_octave[1] == 1:   # Cx2 is down!
                    if self.allow_kbd_rate_factor_change:
                        # Cx2 + [Eb2-B2] changes the rate-factor as defined in self.ratefactors
                        idx = midinote - Eb2
                        if 0 <= idx < len(self.ratefactors):
                            factor = self.ratefactors[idx]
                            self.ratefactor_set(factor)
                else:
                    # change the grain rate
                    self.last_octave[midinote - C2] = 1
                    rate = sum(map(operator.mul, self.last_octave, self.grainrate_mask))
                    self.grainrate_change(rate)

    def noteoff(self, midinote):
        if not self.notesheld[midinote]:
            self.panic()
            return
        self.notesheld[midinote] = False
        if self.sustainpedal:
            print("note held by pedal")
            return
        self._release_note(midinote)

    def _release_note(self, midinote):
        if midinote < C2:
            return
        if midinote >= C3:
            self.notesdown -= 1
            self._oscserver.send(self._csound_addr, '/noteoff', midinote)
        else:
            self.last_octave[midinote - C2] = 0

    def cc(self, cc, value):
        func = self.controllers.get(cc)
        if func:
            func(value)
        else:
            s = "CC {cc}: {value}".format(cc=cc, value=value)
            self.info(s)
            self.debug(s)

    def gain_set(self, factor):
        """amp is a float between 0-1"""
        mingain = self.config['mingain_db']
        maxgain = self.config['maxgain_db']
        curve = self.config['volpedal_curve']
        factor = factor ** curve
        gain_db = mingain + (maxgain - mingain) * factor
        amp = db2amp(gain_db)
        self._oscserver.send(self._csound_addr, '/gain', amp)
        self.info("/gain", amp)
        self.info("/gainrel", factor)
        self.gain = amp

    def cc_gainchange(self, midivalue):
        gain_factor = midivalue / 127
        self.gain_set(gain_factor)

    def sustainpedal_handler(self, midivalue):
        self.sustainpedal = sustainpedal = midivalue > 0
        print("pedal: %s" % ("ON" if sustainpedal else "OFF"))
        if not sustainpedal:
            print("sustain pedal up, notes to release: %d" % len(self.notesheld_by_pedal))
            for midinote in self.notesheld_by_pedal:
                if not self.notesheld[midinote]:
                    print("releasing note: %d" % midinote)
                    self._release_note(midinote)
                else:
                    print("note is held by key")
            self.notesheld_by_pedal = set()
        else:
            # pedal pressed, hold all notes that are down
            notesheld = self.notesheld
            for midinote in range(48, 108):
                if notesheld[midinote]:
                    self.notesheld_by_pedal.add(midinote)

    def panic(self):
        self._oscserver.send(self._csound_addr, '/panic', 1)
        self.notesheld = [False for i in range(len(self.notesheld))]
        self.notesheld_by_pedal = set()
        self.sustainpedal = False
        self.last_octave = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        self.info('RESET')

    def cc_speed_set(self, midinote):
        index = midinote - C3
        if 0 <= index < self.num_speed_values:
            speed = self.speed_values[index]
            self.speed_set(speed)
        else:
            self.debug("speed change with key out of range")

    def speed_set(self, speed):
        self.speed = speed
        self._oscserver.send(self._csound_addr, '/speed', speed)
        self.info("/speed", speed)

    def table_change_raw(self, tableindex):
        self._oscserver.send(self._csound_addr, '/table', tableindex)
        self.info("/table", tableindex)

    def table_change(self, table):
        """
        table: an int identifying the table
        """
        self._oscserver.send(self._csound_addr, '/table', table)
        self.table = INSTRS[table]
        self.tableindex = table
        self.info('INSTR', self.table)

    def cc_sensibility_change(self, midivalue):
        maxdb = self.noteon_max_db
        mindb = linlin(midivalue, 0, 127, -60, maxdb)
        # mindb = -60 + ((127 - midivalue) / 127) * (maxdb - -60)
        self.sensibility_change(mindb, maxdb)

    def sensibility_change(self, mindb=None, maxdb=None):
        if maxdb is not None:
            self.config['noteon_max_db'] = self.noteon_max_db = maxdb
            self.info("/maxdb", maxdb)
        if mindb is not None:
            self.config['noteon_min_db'] = self.noteon_min_db = mindb
            self.info("/mindb", mindb)

    def cc_compress_change(self, midivalue):
        self.compress_change(midivalue/127.0)
        
    def compress_change(self, v=None):
        if v is not None:
            self.config['compression'] = self.compression = v
        self._oscserver.send(self._csound_addr, '/compress', self.compression)
        self.info("/compress", self.compression)

    def cc_randomness_change(self, midivalue):
        self.randomness_set(midivalue/127)
        
    def randomness_set(self, r=None):
        if r is not None:
            self.config['randomness'] = self.randomness = r
        self._oscserver.send(self._csound_addr, '/random', self.randomness)
        self.info("/random", self.randomness)

    def cc_ratefactor_set(self, midivalue):
        ratefactor_min = self.config['ratefactor_min']
        ratefactor_max = self.config['ratefactor_max']
        factor = ratefactor_min + (ratefactor_max - ratefactor_min) * (midivalue / 127)
        self.ratefactor_set(factor)

    def ratefactor_set(self, factor):
        self.ratefactor = factor
        # changing the ratefactor modifies the effective rate, which needs to be 
        # notified to csound
        self.grainrate_change(self.rate)

    def cc_graindur_set(self, midinote):
        index = midinote - Fx2
        self.graindur_change_index(index)

    def graindur_change_index(self, index):
        if not (0 <= index <= len(self.graindurs)):
            logger.warn("grain dur change with key out of range, valid keys: F#2-B2 (hold C2)")
            return
        graindur = self.graindurs[index]
        self.graindurindex = index
        self.graindur_change(graindur)

    def graindur_change(self, graindur):
        self._oscserver.send(self._csound_addr, '/dur', graindur)
        self.info("/graindur", graindur)
        self.graindur = graindur

    def grainrate_change(self, rate):
        self.rate = rate
        self._oscserver.send(self._csound_addr, '/rate', rate * self.ratefactor)
        self.info('/rate', rate)

    def play_with_velocity(self, midinote, velocity):
        pos = (midinote - C3) / 48
        mindb = self.noteon_min_db
        amp_db = mindb + (self.noteon_max_db - mindb) * (velocity / 127)
        amp = db2amp(amp_db)
        send = self._oscserver.send
        addr = self._csound_addr
        send(addr, '/noteon', midinote, pos, amp)
        
    def openconfig(self):
        userconfig = os.path.abspath(os.path.join(USERFOLDER, "userconfig.json"))
        print(">>>>>>>>>>>>>>>>>>>>>> opening userconfig")
        open_in_editor(userconfig)
        
    def midi_callback(self, msg, timestamp):
        msg0 = msg[0]
        channel = msg0 & 0b00001111
        if self._midi_enabled_channels[channel]:
            kind = msg0 & 0b11110000
            if kind == 144:
                vel = msg[2]
                if vel > 0:
                    self.noteon(msg[1], vel)
                else:
                    self.noteoff(msg[1])
            elif kind == 176:  # CC
                self.cc(msg[1], msg[2])
            if kind == 128:
                # dont need the velocity
                self.noteoff(msg[1])

    def openlog(self):
        open_in_editor(LOGPATH)
        
    def run_in_mainthread(self, func, args=()):
        """
        run function in the main thread.
        This should be called from a callback running in a different thread
        """
        self._tasks.put((func, args))

    def run_in_background(self, func, args=()):
        self._scheduler.apply_after(0, func, args)

    def tick(self):
        self._oscserver.recv(10)
        now = time.time()
        if now - self._tasks_lastcheck > 0.5:
            while not self._tasks.empty():
                func, args = self._tasks.get()
                func(*args)
            self._tasks_lastcheck = now

    def background_task(self):
        if self._running:
            now = time.time()
            if now - self._lastheartbeat > 2 and now - self._starttime > 5:
                self.debug("csd is not connected")
                self._lastheartbeat = now
                self.info("/status", "disconnected")
                self._csd_connected = False
                print("background_task: csound connection error, throwing exception (CsoundConnectionError)")
                self.run_in_mainthread(raise_exception, [CsoundConnectionError])
            if now - self._gui_lastheartbeat > 2 and now - self._starttime > 5:
                self.debug("gui is not connected")
                self._gui_connected = False
                self._gui_lastheartbeat = now
                self.run_in_mainthread(raise_exception, [GuiConnectionError])

    def _csound_restart(self):
        self._background_tast_enabled = False
        self.run_in_mainthread(raise_exception, [CsoundRestart])
    
    def start(self):
        self._running = True
        self._starttime = time.time()
        recv = self._oscserver.recv
        tasks = self._tasks
        while self._running:
            for _ in range(20):
                recv(20)
            while not tasks.empty():
                func, args = self._tasks.get()
                func(*args)
        self.debug("exiting mainloop, closing oscserver")
        self._oscserver.free()
        self.debug("stopped")

    def state_save(self):
        state_save(self.config)

    def stop(self):
        self.debug("stopping csound...")
        self.state_save()
        self._oscserver.send(self._csound_addr, '/stop', 1.0)
        
        self.debug("stopping mainloop")
        self._running = False
        time.sleep(0.2)


def open_in_editor(userconfig):
    print(userconfig)
    os.system(f'xdg-open "{userconfig}" &')
