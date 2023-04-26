<CsoundSynthesizer>
/*
    Eduardo Moguillansky
    ZAEHMUNGEN #2 (Bogenwechsel)

    Granular Playback for the midi keyboard

*/
<CsOptions>
-b 256               ; Buffer size. Make it bigger if there are glitches, smaller for shorter latency
-B 512               ; HW Buffer Size. As a rule, the double of the previous value.
-odac                ; use default audio device (OSX: set the audio device in Audio MIDI Setup)
-+rtaudio=jack       ; dont touch this
--env:CSNOSTOP=yes   ; dont touch this

; -------------------------------------------------
--nodisplays         ; suppress wave-form displays
--new-parser    
-m 0                 ; dont print/log messages for each note
</CsOptions>
<CsInstruments>
/*
          ################################
          #         AUDIO SETUP          #
          ################################
*/
sr = 44100          ; sample rate. will use system rate
nchnls = 2          ; number of channels
ksmps = 64	        ; block-size in samples. make it bigger if there are x-runs. default=64
0dbfs  = 1          ; dont change this

/*
          ################################
          #         GLOBAL SETUP         #
          ################################
*/

;; CONFIGURATION
#define LAG_GLOBAL  #0.005#                       ; lag time for most of the OSC actions   
#define LAG_RATE    #0.005#
#define LAG_SPEED   #0.1#
#define ATTACK      #0.002#
#define RELEASE     #0.02#   
#define RATEMULT    #1.05#  
#define RANDOM_MULT #2#     
#define OSCPORT     #7770#                         ; OSC port to listen to
#define HEARTPORT   #7771#                         ; a heartbeat '/heart' is transmitted to this port to show that we are alive
#define INFOPORT    #7771#                         ; analysis and information is sent here


; select the set of files used by the keyboard. DEFAULT: sndfiles/48/NORMALIZED
#define SNDFILE_VL    #"assets/sndfiles48/NORMALIZED/VL.wav"#
#define SNDFILE_VLA   #"assets/sndfiles48/NORMALIZED/VLA.wav"#
#define SNDFILE_VC    #"assets/sndfiles48/NORMALIZED/VC.wav"#

; OSC communication
#define HEARTFREQ  #2#                            ; the frequency of the heartbeat, in Hz
#define INFOSENDFREQ #18#

;; DEBUGGING
#define DEBUG       #0#             ;; 0 for no debugging, a positive number indicates debug rate

;;; ------------------------------------------------------------------------------
;;; FROM HERE, DO NOT CHANGE IF YOU DO NOT KNOW WHAT YOU ARE DOING
;;;
;;; Things that might be changed: random position, random transposition, etc.
;;; ------------------------------------------------------------------------------

;; internal constants, DO NOT CHANGE
#define OSC         #2#
#define PARTIKKEL   #20# 
#define PINGBACK    #100#  
#define MASTER      #500#
#define FOREVER     #36000#

giSine         ftgen   0, 0, 2^10, 10, 1 
giCosine       ftgen   0, 0, 8193, 9, 1, 1, 90     ; cosine
giDisttab      ftgen   0, 0, 32768, 7, 0, 32768, 1 ; for kdistribution
;;giWin        ftgen   0, 0, 4096, 20, 9, 1        ; grain envelope
giWin          ftgen   0, 0, 8192, 20, 7, 1, 2     ; grain envelope
giSigmoRise    ftgen   0, 0, 8193, 19, 0.5, 1, 270, 1  ; rising sigmoid
giSigmoFall    ftgen   0, 0, 8193, 19, 0.5, 1, 90, 1   ; falling sigmoid
giPan          ftgen   0, 0, 32768, -21, 1, 0     ; for panning (random values between 0 and 1)
gi_sndfile_VL  ftgen   0, 0,     0, -1, $SNDFILE_VL,  0, 0, 0  ; soundfile for source waveform. -1 = do not normalize
gi_sndfile_VLA ftgen   0, 0,     0, -1, $SNDFILE_VLA, 0, 0, 0
gi_sndfile_VC  ftgen   0, 0,     0, -1, $SNDFILE_VC,  0, 0, 0
; gi_sndfiles    ftgen   0, 0,    -3, -2, gi_sndfile_VL, gi_sndfile_VLA, gi_sndfile_VC
gi_sndfiles[] fillarray gi_sndfile_VL, gi_sndfile_VLA, gi_sndfile_VC
gk_rate     init 8      ;; grain rate in Hz
gk_speed    init 1      ;; playback speed in x (1 == original speed)
gk_dur      init 50     ;; grain duration in ms
gk_gain     init 1      ;; gain of the partikkel instr
gk_pos      init 0      ;; position in time into the buffer
gk_table    init    gi_sndfile_VL
gk_compr    init 1
gk_rnd      init 0
gk_rms      init 0
gk_peak     init 0
gk_safemode init 0

gaL init 0
gaR init 0

gi_osc      OSCinit $OSCPORT

alwayson $OSC
alwayson $MASTER

instr $OSC
  krate0, krate   init 0, 8
  kspeed0, kspeed init 0, 1
  kdur0, kdur     init 0, 100
  kgain0, kgain   init 0, 1
  kpos0, kpos     init 0, 0
  ktmp            init 0
  ktableindex     init 0
  knoteon_pos, knoteon_gain, knoteon_pos0, knoteon_gain0 init 0, 0, 0, 0
  kcompr0, kcompr init 0, 1
  krnd0, krnd     init 0, 0
  kpingport       init 0
  ksafemode       init 0
  kmidinote init 0
  kmidinoteoff init 0
  krcv_noteoff init 0
  k0, kpinged init 0
  
  NEXTMSG:
  krcv_rate   OSClisten gi_osc, "/rate",  "f", krate0      ;; grain rate in Hz
  krcv_speed  OSClisten gi_osc, "/speed", "f", kspeed0     ;; speed (1 = normal speed)
  krcv_dur    OSClisten gi_osc, "/dur",   "i", kdur0       ;; grain duration (size) in ms
  krcv_gain   OSClisten gi_osc, "/gain",  "f", kgain0      ;; gain
  krcv_stop   OSClisten gi_osc, "/stop",  "f", ktmp        ;; stop the engine
  krcv_table  OSClisten gi_osc, "/table", "f", ktableindex ;; the index of the table to read from. 0=VL, 1=VLA, 2=VC
  krcv_noteon OSClisten gi_osc, "/noteon", "iff", kmidinote, knoteon_pos, knoteon_gain
  
  kpinged OSClisten gi_osc, "/ping", "i", kpingport
  if (kpinged == 1) then
    event "i", $PINGBACK, 0, 1, kpingport
  endif
  k0 OSClisten gi_osc, "/panic", "i", k0
  if (k0 == 1) then
    turnoff2 $PARTIKKEL, 0, 0.1
  endif
  
  krcv_noteoff OSClisten gi_osc, "/noteoff", "i", kmidinoteoff
  if (krcv_noteoff == 1) then
    turnoff2 $PARTIKKEL + kmidinoteoff/128, 4, $RELEASE
  endif
  
  krcv_compr  OSClisten gi_osc, "/compress", "f", kcompr0
  krcv_rnd    OSClisten gi_osc, "/random", "f", krnd0
  
  if (krcv_rate == 1) then
    krate = krate0
  endif
  if (krcv_speed == 1) then
    kspeed = kspeed0
  endif
  if (krcv_dur == 1) then
    kdur = kdur0
  endif
  if (krcv_gain == 1) then
    kgain = kgain0
  endif
  if (krcv_noteon == 1) then
	turnoff2 $PARTIKKEL + kmidinote/128, 4, $RELEASE
	;;         midinote                    t  maxdur          rate             cent   centrand    pos
    ;;                                              speed              grainsize  posrand pan distr            gain
    event "i", $PARTIKKEL + kmidinote/128, 0, 3600, gk_speed, gk_rate, gk_dur, 0, 30, 30, 0, 0.1, knoteon_pos, knoteon_gain
  endif
  if (krcv_table == 1) then
    ; gk_table table   ktableindex, gi_sndfiles
    gk_table = gi_sndfiles[ktableindex]
  endif
  if (krcv_compr == 1) then
    kcompr = kcompr0
  endif
  if (krcv_rnd == 1) then
    krnd = krnd0 * $RANDOM_MULT
  endif
  if (krcv_stop == 1) then
    event "i", 999, 0, 1
  endif
	
  krecvosc = krcv_speed * krcv_gain * krcv_noteon * krcv_noteoff
  if (krecvosc == 1) kgoto NEXTMSG
    
  gk_rate  = port(krate, $LAG_RATE) * $RATEMULT
  gk_speed port kspeed,$LAG_SPEED
  gk_dur   port kdur,  $LAG_GLOBAL
  gk_gain  port kgain, $LAG_GLOBAL
  gk_pos = kpos
  gk_compr  port kcompr, $LAG_GLOBAL
  gk_rnd = krnd
	
  kheart_trig metro $HEARTFREQ
  kinfo_trig  metro $INFOSENDFREQ
  OSCsend kheart_trig, "", $HEARTPORT, "/heart", "i",  1
  OSCsend kinfo_trig,  "", $INFOPORT,  "/info",  "ff", dbamp(gk_rms), dbamp(gk_peak)
endin

instr $PINGBACK 
  iport = p4
  prints "csound: /ping received, sending /pingback \n"
  OSCsend 1, "127.0.0.1", iport, "/pingback", "i", 1
  turnoff
endin

instr $PARTIKKEL
  /*score parameters*/
  ispeed          = p4        ; 1 = original speed 
  igrainrate      = p5        ; grain rate
  igrainsize      = p6        ; grain size in ms
  icent           = p7        ; transposition in cent
  iposrand        = p8        ; max time position randomness (offset) of the pointer in ms
  icentrand       = p9        ; max transposition randomness in cents
  ipan            = p10       ; panning narrow (0) to wide (1)
  idist           = p11       ; grain distribution (0=periodic, 1=scattered)
  ipos            = p12
  igain           = p13
    
  /*get length of source wave file, needed for both transposition and time pointer*/
  ifilen          tableng gi_sndfile_VL
  ifildur         = ifilen / sr
  
  /*sync input (disabled)*/
  async = 0     
  
  /*grain envelope*/
  kenv2amt = 1         ; use only secondary envelope
  ienv2tab = giWin     ; grain (secondary) envelope
  ienv_attack = giSigmoRise 
  ienv_decay = giSigmoFall
  ksustain_amount = 0.5       ; no meaning in this case (use only secondary envelope, ienv2tab)
  ka_d_ratio      = 0.5       ; no meaning in this case (use only secondary envelope, ienv2tab)
  
  /*amplitude*/
  kamp = 1*0dbfs         ; grain amplitude
  igainmasks = -1        ; (default) no gain masking
  
  /*transposition*/
  ktransprand = icentrand * gk_rnd
  kcentrand   rand ktransprand    ; random transposition
  
  iorig    = 1 / ifildur   ; original pitch
  kwavfreq = iorig * gk_speed * cent(icent + kcentrand)
  
  /*other pitch related (disabled)*/
  ksweepshape      = 0        ; no frequency sweep
  iwavfreqstarttab = -1       ; default frequency sweep start
  iwavfreqendtab   = -1       ; default frequency sweep end
  awavfm      = 0     ; no FM input
  ifmamptab   = -1        ; default FM scaling (=1)
  kfmenv      = -1        ; default FM envelope (flat)
  
  /*trainlet related (disabled)*/
  icosine = giCosine      ; cosine ftable
  kTrainCps = igrainrate  ; set trainlet cps equal to grain rate for single-cycle trainlet in each grain
  knumpartials = 1        ; number of partials in trainlet
  kchroma = 1             ; balance of partials in trainlet

  /*panning, using channel masks*/
  imid        = .5        ; center
  ileftmost   = imid - ipan/2
  irightmost  = imid + ipan/2
  /*
  giPanthis   ftgen   0, 0, 32768, -24, giPan, ileftmost, irightmost  ; rescales giPan according to ipan
  tableiw 0, 0, giPanthis             ; change index 0 ...
  tableiw 32766, 1, giPanthis         ; ... and 1 for ichannelmasks
  */
  ;; ichannelmasks = giPanthis       ; ftable for panning
  ichannelmasks = giPan

  /*random gain masking (disabled)*/
  krandommask     = 0 

  /*source waveforms*/
  kwaveform1      = gk_table      ; source waveform
  kwaveform2      = kwaveform1    ; all 4 sources are the same
  kwaveform3      = kwaveform1
  kwaveform4      = kwaveform1
  iwaveamptab     = -1        ; (default) equal mix of source waveforms and no amplitude for trainlets

  /*time pointer*/
  afilposphas     phasor ispeed / ifildur
  /*generate random deviation of the time pointer*/
  kposrandphase     = (iposrand * gk_rnd) / 1000 / ifildur
  krndpos         linrand  kposrandphase  ; random offset in phase values
  /*add random deviation to the time pointer*/
  ; asamplepos1       = floor(kslider1 * 2) / 96; afilposphas + krndpos; resulting phase values (0-1)
  ; asamplepos1     = gk_pos + krndpos
  asamplepos1     = ipos + krndpos
  asamplepos2     = asamplepos1
  asamplepos3     = asamplepos1   
  asamplepos4     = asamplepos1   

  /*original key for each source waveform*/
  kwavekey1       = 1
  kwavekey2       = kwavekey1 
  kwavekey3       = kwavekey1
  kwavekey4       = kwavekey1

  /* maximum number of grains per k-period*/
  imax_grains     = 100       
  kgrate = gk_rate  ; Hz
  ksize  = gk_dur   ; ms
  
  ktrig   metro $DEBUG
  ;; print p1
  
  aL, aR      partikkel gk_rate, idist, giDisttab, async, kenv2amt, ienv2tab, \
                          ienv_attack, ienv_decay, ksustain_amount, ka_d_ratio, \ 
                          ksize, kamp, igainmasks, kwavfreq, ksweepshape, \
                          iwavfreqstarttab, iwavfreqendtab, awavfm, ifmamptab, 
                          kfmenv, icosine, kTrainCps, knumpartials, kchroma, \ 
                          ichannelmasks, krandommask, \ 
                          kwaveform1, kwaveform2, kwaveform3, kwaveform4, \
                          iwaveamptab, asamplepos1, asamplepos2, asamplepos3, asamplepos4, \ 
                          kwavekey1, kwavekey2, kwavekey3, kwavekey4, imax_grains
  ; kgain = igain * gk_gain
    
  aenv linenr 1, $ATTACK, $RELEASE, 0.01
  aenv *= igain
  aL *= aenv
  gaL += aL
  gaR += aL
endin

instr $MASTER
  kcomp_thresh = 0.2
  kcomp_loknee = 48
  kcomp_hiknee = 66
  kcomp_ratio  = 1 + gk_compr * 2
  kcomp_att    = 0.001
  kcomp_rel    = 0.17
  ilook        = 0.005

  aenv = interp(gk_gain)
  aL = gaL * aenv
  aR = gaR * aenv

  aLcompr compress aL, aL, kcomp_thresh, kcomp_loknee, kcomp_hiknee, kcomp_ratio, kcomp_att, kcomp_rel, ilook
  aRcompr compress aR, aR, kcomp_thresh, kcomp_loknee, kcomp_hiknee, kcomp_ratio, kcomp_att, kcomp_rel, ilook
  
  gk_rms    rms aLcompr
  kpeaktrig metro $INFOSENDFREQ * 4
  kmax    max_k aLcompr, kpeaktrig, 1
  gk_peak   port kmax, 0.01

  outs aLcompr, aRcompr
  gaR = 0
  gaL = 0
endin

instr 999
  prints "\n\n\ncsound: --------- EXIT ---------\n\n\n"
  turnoff2 $OSC, 0, 1
  turnoff2 $PARTIKKEL, 0, 1
  exitnow
endin

</CsInstruments>

;; --------------------- SCORE -----------------------
<CsScore>
f0 36000
e
</CsScore>
</CsoundSynthesizer>