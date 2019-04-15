# -*- coding: utf-8 -*-
"""
Superclass for behavioral task control

"""

from __future__ import division
import math, os, random, time
import h5py
import numpy as np
from psychopy import monitors, visual, event
import ProjectorWindow
import nidaq


class TaskControl():
    
    def __init__(self):
        self.rig = 'pilot' # 'pilot' or 'np3'
        self.subjectName = None
        self.saveParams = True # if True, saves all attributes not starting with underscore
        self.saveFrameIntervals = True
        self.saveMovie = False
        self.screen = 1 # monitor to present stimuli on
        self.drawDiodeBox = True
        self.nidaqDevice = 'USB-6009'
        self.nidaqDeviceName = 'Dev1'
        self.wheelRotDir = -1 # 1 or -1
        self.wheelSpeedGain = 500 # arbitrary scale factor
        self.spacebarRewardsEnabled = True
        if self.rig=='pilot':
            self.saveDir = 'C:\Users\SVC_CCG\Desktop\Data' # path where parameters and data saved
            self.monWidth = 47.2 # cm
            self.monDistance = 19.7 # cm
            self.monGamma = None # float or None
            self.monSizePix = (1680,1050)
            self.flipScreenHorz = False
            self.warp = 'Disabled' # one of ('Disabled','Spherical','Cylindrical','Curvilinear','Warpfile')
            self.warpFile = None
            self.diodeBoxSize = 50
            self.diodeBoxPosition = (815,-500)
        elif self.rig=='np3':
            pass
        
    
    def prepareSession(self):
        self.startTime = time.strftime('%Y%m%d_%H%M%S')
        self._win = None
        self._nidaqTasks = []
        
        self.numpyRandomSeed = random.randint(0,2**32)
        self._numpyRandom = np.random.RandomState(self.numpyRandomSeed)
        
        self.pixelsPerDeg = 0.5 * self.monSizePix[0] / (math.tan(0.5 * self.monWidth / self.monDistance) * 180 / math.pi)
        
        self.prepareWindow()

        self._diodeBox = visual.Rect(self._win,
                                    units='pix',
                                    width=self.diodeBoxSize,
                                    height=self.diodeBoxSize,
                                    lineColor=0,
                                    fillColor=1, 
                                    pos=self.diodeBoxPosition)
                                    
        self.startNidaqDevice()
        self.rotaryEncoderRadians = []
        self.deltaWheelPos = [] # change in wheel position (angle translated to screen pixels)
        self.lickInput = []
        
        self._continueSession = True
        self._sessionFrame = 0 # index of frame since start of session
        self._trialFrame = 0 # index of frame since start of trial
        self._reward = False # reward delivered at next frame flip if True
        self.manualRewardFrames = [] # index of frames at which reward manually delivered
        
        
    
    def prepareWindow(self):
        self._mon = monitors.Monitor('monitor1',
                                     width=self.monWidth,
                                     distance=self.monDistance,
                                     gamma=self.monGamma)
        self._mon.setSizePix(self.monSizePix)
        self._mon.saveMon()
        self._win =  ProjectorWindow.ProjectorWindow(monitor=self._mon,
                                                     screen=self.screen,
                                                     fullscr=True,
                                                     flipHorizontal=self.flipScreenHorz,
                                                     warp=getattr(ProjectorWindow.Warp,self.warp),
                                                     warpfile=self.warpFile,
                                                     units='pix')
        self.frameRate = self._win.getActualFrameRate() # do this before recording frame intervals
        self._win.setRecordFrameIntervals(self.saveFrameIntervals)
        
        
    def start(self,subjectName=None):
        try:
            if subjectName is not None:
                self.subjectName = subjectName
            
            self.prepareSession()
            
            self.taskFlow()
            
        except nidaq.DAQError:
            self.resetNidaqDevice()
            raise
        
        except:
            raise
            
        finally:
            self.completeSession()
    
    
    def taskFlow(self):
        # override this method in subclass
    
        while self._continueSession:
            # get rotary encoder and digital input states
            self.getNidaqData()
            
            # do stuff, for example:
            # check for licks and/or wheel movement
            # update/draw stimuli
            
            self.showFrame()
    
    
    def showFrame(self):
        # check for keyboard events
        # set frame acquisition and reward signals
        # flip frame buffer
        # update session and trial frame counters
        
        # spacebar delivers reward
        keys = event.getKeys()
        if self.spacebarRewardsEnabled and 'space' in keys:
            self._reward = True
            self.manualRewardFrames.append(self._sessionFrame)
        
        # set frame acquisition and reward signals 
        self._digitalOutputs.writeBit(0,1)
        if self._reward:
            self._digitalOutputs.writeBit(1,1)
        
        # show new frame
        if self.drawDiodeBox:
            self._diodeBox.fillColor = -self._diodeBox.fillColor
            self._diodeBox.draw()
        self._win.flip()
        if self.saveMovie:
            self._win.getMovieFrame()
        
        # reset frame acquisition and reward signals
        self._digitalOutputs.writeBit(0,1)
        if self._reward:
            self._digitalOutputs.writeBit(1,0)
            self._reward = False
        
        self._sessionFrame += 1
        self._trialFrame += 1
        
        # escape key ends session
        if 'escape' in keys:   
            self._continueSession = False
                                               
    
    def completeSession(self):
        subjName = '' if self.subjectName is None else self.subjectName+'_'
        fileBaseName = os.path.join(self.saveDir,self.__class__.__name__+'_'+subjName+self.startTime)
        if self._win is not None:
            if self.saveMovie:
                self._win.saveMovieFrames(os.path.join(fileBaseName+'.mp4'))
            self._win.close()
        self.stopNidaqDevice()
        if self.saveParams:
            fileOut = h5py.File(fileBaseName+'.hdf5','w')
            saveParameters(fileOut,self.__dict__)
            if self.saveFrameIntervals:
                fileOut.create_dataset('frameIntervals',data=self._win.frameIntervals)
            fileOut.close()
        
    
    def startNidaqDevice(self):
        # analog inputs
        # AI0: rotary encoder
        sampRate = 2000.0
        bufferSize = int(1 / self.frameRate * sampRate)
        self._analogInputs = nidaq.AnalogInput(device=self.nidaqDeviceName,
                                               channels=[0],
                                               voltage_range=(0,5.0),
                                               clock_speed=sampRate,
                                               buffer_size=bufferSize)
        self._nidaqTasks.append(self._analogInputs)
            
        # digital inputs (port 0)
        # line 0.0: lick input
        self._digitalInputs = nidaq.DigitalInput(device=self.nidaqDeviceName,port=0)
        self._nidaqTasks.append(self._digitalInputs)
        
        # digital outputs (port 1)
        # line 1.0: frame signal
        # line 1.1: water reward solenoid
        self._digitalOutputs = nidaq.DigitalOutput(device=self.nidaqDeviceName,port=1,initial_state='low')
        self._nidaqTasks.append(self._digitalOutputs)
        
        for task in self._nidaqTasks:
            task.start()
        
        # maks sure outputs are initialized to correct state
        self._digitalOutputs.write(np.zeros(self._digitalOutputs.no_lines,dtype=np.uint8))
    
    
    def stopNidaqDevice(self):
        self._digitalOutputs.write(np.zeros(self._digitalOutputs.no_lines,dtype=np.uint8))
        for task in self._nidaqTasks:
            task.clear()
            
    
    def resetNidaqDevice(self):
        nidaq.Device(self.nidaqDeviceName).reset()
            
    
    def getNidaqData(self):
        # analog
        encoderAngle = self._analogInputs.data * 2 * math.pi / 5
        self.rotaryEncoderRadians.append(np.arctan2(np.mean(np.sin(encoderAngle)),np.mean(np.cos(encoderAngle))))
        self.deltaWheelPos.append(self.translateEndoderChange())
        
        # digital
        self.lickInput.append(self._digitalInputs.read()[0])
        
    
    def translateEndoderChange(self):
        # translate encoder angle change to number of pixels to move visual stimulus
        if len(self.rotaryEncoderRadians) < 2:
            pixelsToMove = 0
        else:
            angleChange = self.rotaryEncoderRadians[-1] - self.rotaryEncoderRadians[-2]
            if angleChange < -math.pi:
                angleChange += 2 * math.pi
            elif angleChange > math.pi:
                angleChange -= 2 * math.pi
            pixelsToMove = angleChange * self.wheelRotDir * self.wheelSpeedGain
        return pixelsToMove
        


def saveParameters(fileOut,paramDict,dictName=None):
    for key,val in paramDict.items():
        if key[0] != '_':
            if dictName is None:
                paramName = key
            else:
                paramName = dictName+'_'+key
            if isinstance(val,dict):
                saveParameters(fileOut,val,paramName)
            else:
                try:
                    if val is None:
                        val = np.nan
                    fileOut.create_dataset(paramName,data=val)
                except:
                    print 'could not save ' + key
                    

if __name__ == "__main__":
    pass