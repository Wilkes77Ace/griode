import collections
import enum
import glob
import logging
import mido
import time
import os
import re
from pygame import mixer

from gridgets import Gridget, Surface
from palette import palette

sounds_directory = "sounds"

# Immunity timers are period (Seconds) withing it's impossible to stop a newly launched ...
immunity_timer_sound = 2 # Sound
immunity_timer_music = 5 # Music


# Compiled regular expression to find button associated directories
re_directory = re.compile(r"^(?P<btn>[A-Z]) - ")

# Compiled regular expression to find directory type (music or not)
re_directory_type = re.compile(r"\[Music\]")

# Compiled regular expression to find looped sounds
re_loops = re.compile(r"\[Loop ?(?P<qty>\d)?\]")

color_disabled = palette.BLACK
color_enabled = palette.TRIG[0]
color_playing = palette.PLAY[0]
color_control = palette.GATE[1]


class Sound(object):

    def __init__(self, path, is_music):
        self.path = path
        self.is_music = is_music
        self.mixer_sound = None
        self.mixer_channel = None
        if is_music:
            self.playing = False
        else:
            self.sound_start = None

        # The loops argument controls how many times the sample will be repeated after being played the first time.
        # The default value (zero) means the Sound is not repeated, and so is only played once.
        # If loops is set to -1 the Sound will loop indefinitely (call stop() to stop it).
        find_loops = re_loops.search(self.path)
        if find_loops == None:
            self.loops = 0
        elif find_loops.group('qty') == None:
            self.loops = -1
        else:
            self.loops = int(find_loops.group('qty'))

    def play(self):
        if self.is_music:
            if mixer.music.get_busy(): # If sound currently played
                if time.time() - mixer.music_start < immunity_timer_music: # New music immunity
                    logging.info("Stop music immunity {}".format(mixer.music.current))
                    return
                logging.info("Stop music {}".format(mixer.music.current))
                mixer.music.stop()
                if mixer.music.current == self.path:
                    return False
            logging.info("Play music {}".format(self.path))
            mixer.music_start = time.time()
            self.playing = True
            mixer.music.current = self.path
            mixer.music.load(self.path)
            mixer.music.play(self.loops)
        else:
            if self.mixer_channel != None and self.mixer_channel.get_busy():
                if time.time() - self.sound_start < immunity_timer_sound: # New sound immunity
                    logging.info("Stop sound immunity {}".format(self.path))
                    return False
                logging.info("Stop sound {}".format(self.path))
                self.mixer_channel.stop()
                self.mixer_channel = None
            else:
                logging.info("Play sound {}, Loop={}".format(self.path, self.loops))
                self.sound_start = time.time()
                self.mixer_sound = mixer.Sound(self.path)
                self.mixer_channel = self.mixer_sound.play(self.loops)
        return True

    def is_playing(self):
        if self.is_music:
            if mixer.music.get_busy() and self.path == mixer.music.current:
                return True
            return False
        else:
            if self.sound_start == None: # Not started
                return False
            return True

    def has_ended(self):
        if self.is_music: # Music
            if not self.playing: # Not started
                return False
            elif (time.time() - mixer.music_start) < 1: # 1 second immunity
                return False
            elif mixer.music.get_busy() and self.path == mixer.music.current: # Currently played
                return False
            self.playing = False
        else:
            if self.sound_start == None: # Not started
                return False
            elif (time.time() - self.sound_start) < 1: # 1 second immunity
                return False
            elif self.mixer_channel != None and self.mixer_channel.get_busy():
                return False
            self.mixer_channel = None # Channel recycling
            self.sound_start = None
        logging.debug("Music/Sound has_ended() for {}".format(self.path))
        return True


class SoundsPanel(object):

    def __init__(self, path, surface, limit):
        self.sounds = {}
        self.led2sound = {}
        self.sound2leds = collections.defaultdict(list)
        self.path = path
        is_music = SoundsPanel.is_directory_music(path)
        sounds = SoundsPanel.get_sounds(path)
        self.led2sound.clear()
        for led in surface:
            if isinstance(led, tuple):
                row, column = led
                index = SoundsPanel.get_index(row, column)
                if index >= ( 8*8 - limit ):
                    continue
                if index < len(sounds):
                    self.led2sound[led] = index
                    self.sounds[index] = Sound(sounds[index], is_music)
        self.sound2leds.clear()
        for led, sound in self.led2sound.items():
            if sound not in self.sound2leds:
                self.sound2leds[sound] = []
            self.sound2leds[sound].append(led)

    def get_index(row, column):
        return ( row - 1 ) * 8 + column - 1

    def is_directory_music(path):
        find_directory_type = re_directory_type.search(path)
        if find_directory_type:
            return True
        return False

    def get_sounds(path):
        sounds = sorted(glob.glob(os.path.join(glob.escape(path), '*.ogg')))
        sounds.extend(sorted(glob.glob(os.path.join(glob.escape(path), '*.mp3'))))
        logging.debug("Sounds gridget - Sounds count : {}".format(len(sounds)))
        return sounds

class Sounds(Gridget):

    def get_grids(grid):
        list = {}
        dirs = next(os.walk(sounds_directory))[1]
        for dir in dirs:
            find_directory = re_directory.search(dir)
            if find_directory:
                list[find_directory.group('btn')] = Sounds(grid, "{}/{}/".format(sounds_directory, dir))
        return list

    def __init__(self, grid, path):
        logging.debug("Sounds gridget init - Path : {}".format(path))
        self.grid = grid
        self.surface = Surface(grid.surface)
        if not mixer.get_init():
            mixer.init()
            mixer.music_start = None
        self.panels = []
        subdirs = sorted(next(os.walk(path))[1])
        if len(subdirs) > 0: # Files inside subdirectories
            logging.debug("Sounds gridget init - Subdirectories count {}".format(len(subdirs)))
            if len(subdirs) <= 8:
                self.control = 1 # One panel, one led representation
                limit = len(subdirs)
            else:
                # Binary representation
                # The current pannel will be showed with unique pattern
                # witch is a reversed binary representation of it number
                self.control = 2
                # Formula to determine bit count (limit) is : 2**limit-1 = capacity
                limit = 4 # Starting at 4, capacity = 15
                while 2**limit-1 < len(subdirs):
                    limit += 1
                if limit > 8:
                    limit = 8
            self.limit = limit
            for subdir in subdirs:
                subpath = "{}{}/".format(path, subdir)
                logging.debug("Sounds gridget init - Subpath : {}".format(subpath))
                self.panels.append(SoundsPanel(subpath, self.surface, self.limit))
        else: # Files inside main directory
            self.control = 0
            self.panels.append(SoundsPanel(path, self.surface, 0))
        self.panel_num = -1
        self.cycle()

    def cycle(self):
        self.panel_num += 1
        if self.panel_num >= len(self.panels):
            self.panel_num = 0
        self.panel = self.panels[self.panel_num]
        logging.debug("Sounds gridget - Selected panel ({}) : {} ".format(self.panel_num, self.panel.path))
        self.draw()

    def draw(self):
        if self.control == 2:
            binary = bin(self.panel_num + 1)[2:].zfill(8) # panel_num binary representation
        for led in self.surface:
            if led in self.panel.led2sound: # Sound led
                sound = self.panel.led2sound[led]
                self.surface[led] = ( color_enabled if (sound != None) else color_disabled )
                continue
            elif self.control != 0 and isinstance(led, tuple): # Control led
                row, column = led
                if row == 8:
                    index = 64 - SoundsPanel.get_index(row, column)
                    if self.control == 1 and index == self.panel_num + 1:
                        self.surface[led] = color_control
                        continue
                    elif self.control == 2 and index <= self.limit:
                        if binary[-index] == "1":
                            self.surface[led] = color_control
                            continue
            self.surface[led] = color_disabled

    def pad_pressed(self, row, column, velocity):
        led = row, column
        if velocity > 0:
            if led in self.panel.led2sound:
                sound = self.panel.led2sound[led]
                if self.panel.sounds[sound].play():
                    self.surface[led] = color_playing

    def tick(self, tick):
        for led in self.surface:
            if led in self.panel.led2sound:
                sound = self.panel.led2sound[led]
                if self.panel.sounds[sound].is_playing():
                    self.surface[led] = color_playing
                if self.panel.sounds[sound].has_ended():
                    self.surface[led] = color_enabled
