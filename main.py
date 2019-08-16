# main.py -- put your code here!
#Import relevant modules
import network
import pyb
import utime
import machine
import micropython
import adcwd                # CUSTOM MIRCOPYTHON MODULE!
import usocket as socket
from machine import Pin
from pyb import ExtInt
from pyb import USB_VCP
from pyb import I2C
from pyb import ADC
from pyb import DAC
from pyb import LED
from array import array

micropython.alloc_emergency_exception_buf(100) # For interrupt debugging

#==================================================================================#
# SETUP
#==================================================================================#

# OBJECT DEFINITIONS
led = LED(1)                            # define diagnostic LED
usb = USB_VCP()                         # init VCP object

i2c = I2C(1, I2C.MASTER,
    baudrate=400000)                    # define I2C channel, master/slave protocol and baudrate needed
t2 = pyb.Timer(1,freq=1000000)          # init timer for polling
ti = pyb.Timer(2,freq=1000000)          # init timer for interrupts

# PIN SETUP AND INITIAL POLARITY/INTERRUPT MODE
Pin('PULL_SCL', Pin.OUT, value=1)       # enable 5.6kOhm X9/SCL pull-up
Pin('PULL_SDA', Pin.OUT, value=1)       # enable 5.6kOhm X10/SDA pull-up
adc = ADC(Pin('X12'))                   # define ADC pin for pulse stretcher measurement
calibadc = ADC(Pin('X3'))               # define ADC pin for measuring shaper voltage
pin_mode = Pin('X8', Pin.OUT)           # define pulse clearing mode pin
pin_mode.value(1)                       # disable manual pulse clearing (i.e. pin -> low)
clearpin = Pin('X7',Pin.OUT)            # choose pin used for manually clearing the pulse once ADC measurement is complete
polarpin = Pin('X6', Pin.OUT)           # define pin that chooses polarity   
testpulsepin = Pin('X11',Pin.OUT)       # pin to enable internal test pulses on APIC
polarpin.value(0)                       # set to 1 for positive polarity

# DATA STORAGE AND COUNTERS
sendbuf = array('H',[500])
data = array('H',[0]*4)                 # buffer for writing adc interrupt data from adc.read_timed() in calibration() and ADCi()
calibdata = array('H',[0]*4)            # buffer to store ADC data from calibadc
tim = bytearray(4)                      # bytearray for microsecond, 4 byte timestamps
t0=0                                    # time at the beginning of the experiment
count=0                                 # counter for pulses read
ratecounter = 0                         # counter for rate measurements
STATE = "STARTUP"                       # state variable for applying startup settings etc. 

# SET UP WIRELESS ACCESS POINT
wl_ap = network.WLAN(1)                 # init wlan object
wl_ap.config(essid='PYBD')              # set AP SSID
wl_ap.config(channel=1)                 # set AP channel
wl_ap.active(1)                         # enable the AP

while wl_ap.status('stations')==[]:
    utime.sleep(1)

utime.sleep(2)

print("CONNECTION RECEIVED")

# SET UP THE NETWORK SOCKET FOR UDP
s = socket.socket(socket.AF_INET,
    socket.SOCK_DGRAM)
s.bind(('',8080))                       # network listens on port 8080
cipv4 = ('192.168.4.16', 8080)          # destination for sending data
awdipv4 = ('192.168.4.16', 9000)        # ip passed to the awd module
print("SOCKET BOUND")

#==================================================================================#
# BOARD STATE CHECKING
#==================================================================================#

def checkstate():
    a = STATE.encode('utf-8')
    s.sendto(a, cipv4)

def setstate():
    utime.sleep(0.1)
    STATE = s.recv(32).decode('utf-8')

def drain_socket():
    s.settimeout(0)
    while True:
        try:
            s.recv(2048)
        except:
            break
    s.settimeout(None)

#==================================================================================#
# I2C CONTROL
#==================================================================================#

def Ir():
    if i2c.is_ready(0x2D) and i2c.is_ready(0x2C):
        gain = i2c.recv(1,addr=0x2D)
        threshold = i2c.recv(1,addr=0x2C)
        s.sendto(gain,cipv4)
        s.sendto(threshold,cipv4)
    else:
        raise Exception
    return None

def Iw(address):
    if i2c.is_ready(address):
        recvd = s.recv(1)
        value = int.from_bytes(recvd,'little',False)
        b = bytearray([0x00,value])
        i2c.send(b,addr=address)
    else:
        raise Exception
    return None

def Is():
    scan = bytearray(2)
    i2clist = i2c.scan()
    if i2clist == []:
        pass
    else:
        for idx,chip in enumerate(i2clist):
            scan[idx] = chip
    s.sendto(scan, cipv4)
    return None

#==================================================================================#
# CALIBRATION CURVE CODE
#==================================================================================#
"""
def calibrate():
    global calibint
    #clearpin.value(1)
    #clearpin.value(0)
    calibint.enable()
    utime.sleep(10)
    calibint.disable()

def cbcal(line):
    #adc.read_timed(data,t2)
    s.sendto(data,cipv4)
    #clearpin.value(1)
    #clearpin.value(0)
    calibadc.read_timed(calibdata,t2)
    s.sendto(calibdata,cipv4)
"""
#==================================================================================#
# RATE MEASUREMENT CODE
#==================================================================================#

def rateaq():

    print('COUNTING RATE')
    global ratecounter
    global rateint

    ratecounter=0
    a=utime.ticks_ms()
    rateint.enable()
    utime.sleep(3)
    rateint.disable()
    
    b = utime.ticks_ms()-a
    
    finalrate = round((ratecounter/(b/1000)))
    finalratebyte = finalrate.to_bytes(4,'little',False)
    s.sendto(finalratebyte,cipv4)

def ratecount(line):
    global ratecounter
    ratecounter+=1
    clearpin.value(1)               # perform pulse clearing
    clearpin.value(0)

#==================================================================================#
# ADC INTERRUPT MEASUREMENT CODE:                            
# Python level legacy function, interrupt to take and send data    
# samples mnum peaks, uses schedule to delay measurements for               
# concurrent interrupts.                                
#==================================================================================#

# MAIN ADC MEASUREMENT CODE
def ADCi():
    
    global extint
    global count
    count = 0
    
    utime.sleep(0.5)
    print("MESSAGE RECV NOW")
    
    msg, addr = s.recvfrom(8)
    mnum = int.from_bytes(msg,'little')

    print(mnum)
    
    utime.sleep(1)
    extint.enable()
    
    while count < mnum:
        pass
    
    extint.disable()
    print("ADCI DONE")
    drain_socket()

# ISR CALLBACK FUNCTION
def callback(arg):
    
    extint.disable()
    global count                    # reference the global count counter
    adc.read_timed(data,ti)         # 4 microsecond measurement from ADC at X12,
    
    pos = (4*count)%500
    
    if pos == 124:
        sendbuf[pos:pos+4] = data
        
        try:
            s.sendto(sendbuf, cipv4)
    
        except:
            print("SEND FAILED")
    
    else:

        sendbuf[pos:pos+4] = data
    
    count+=1                        # pulse counter
    extint.enable()

# TEMP FIX FOR ISR OVERFLOW
# Uses micropython.schedule to delay interrupts
# that occur during ISR callback - interrupting usocket transfer is v. bad.
def cb(line):
    micropython.schedule(callback,'a')

# ENABLE INTERRUPT CHANNELS
irqstate=pyb.disable_irq()                  # disable all interrupts during initialisation
#calibint = ExtInt('X1',ExtInt.IRQ_RISING,
#    pyb.Pin.PULL_NONE,cbcal)               # calibration routine interrupts on pin X1
#calibint.disable()

extint = ExtInt('X2',ExtInt.IRQ_RISING,
    pyb.Pin.PULL_NONE,cb)                   # interrupts for ADC pulse DAQ on pin X2
extint.disable()

rateint = ExtInt('X4',ExtInt.IRQ_RISING,
    pyb.Pin.PULL_NONE,ratecount)            # interrupts to measure sample activity on pin X4
rateint.disable()

# disable each individually using extint for later enabling in the functions

pyb.enable_irq(irqstate) # re-enable irqs

#==================================================================================#
# AWD CODE
#==================================================================================#

def ADCwd():
    s.close()
    AWD = adcwd.adcwdObj(0,200)
    AWD.start_peakfinding_udp(1000,awdipv4)

#==================================================================================#
# COMMAND CODES:
# bytearrays used by main loop to execute functions
# expect a byte command.
#==================================================================================#

commands = {
    # bytes(bytearray([a,b])) : command function,
    bytes(bytearray([0,0])) : Ir,                       # read first gain potentiometer, then threshold
    bytes(bytearray([7,1])) : checkstate,               # check the state of the pybaord
    bytes(bytearray([7,0])) : setstate,                 # set the current state of the board

    bytes(bytearray([0,2])) : Is,                       # scan I2C addresses
    bytes(bytearray([1,0])) : lambda : Iw(0x2D),        # write gain pot
    bytes(bytearray([1,1])) : lambda : Iw(0x2C),        # write threshold pot
    bytes(bytearray([2,0])) : ADCwd,                    # AWD peakfinding
    bytes(bytearray([2,1])) : ADCi,                     # ADC interrupts

    bytes(bytearray([4,0])) : lambda : polarpin.value(0),       # Negative polarity
    bytes(bytearray([4,1])) : lambda : polarpin.value(1),       # Positive polarity

    #bytes(bytearray([5,0])) : calibrate,                       # measure detector/apic gain profile 
    bytes(bytearray([5,1])) : rateaq,                           # measure sample rate

    bytes(bytearray([6,0])) : lambda: testpulsepin.value(0),    # disable test pulses
    bytes(bytearray([6,1])) : lambda: testpulsepin.value(1)     # enable test pulses
    }

#==================================================================================#
# MAIN LOOP
#==================================================================================#
while True:
    mode = s.recv(2)            # wait until the board receives the 2 byte command code, no timeout
    print("MODE RECEIVED")
    commands[mode]()            # reference commands dictionary and run the corresponding function
