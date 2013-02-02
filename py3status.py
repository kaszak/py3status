#!/usr/bin/env python
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#  
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#  

from json import dumps
from subprocess import Popen, call, PIPE
from socket import socket, SOCK_DGRAM
from threading import Thread, Event, Lock
from queue import Queue
from time import sleep, strftime
from configparser import ConfigParser
from os.path import expanduser
from array import array
from struct import pack
from fcntl import ioctl
import re
import os

from mpd import MPDClient, ConnectionError
from psutil import disk_partitions, disk_usage
from alsaaudio import Mixer, ALSAAudioError

class WorkerThread(Thread):
    '''
    Skeleton Class for all worker threads.
    '''
    def __init__(self, 
                 name, 
                 idn, 
                 queue, 
                 interval,
                 color_critical,
                 color_warning, 
                 color_normal,
                 **kwargs):
        Thread.__init__(self, **kwargs)
        self.daemon = True # kill threads when StatusBar exits
        self.show = False
        self.urgent = False
        self.blanked = True # was the output empty previously?
        self.interval = int(interval)
        self.name = name
        self.idn = idn #Identification number, sort of
        self.color_warning = color_warning
        self.color_critical =  color_critical
        self.color_normal = color_normal
        self.queue = queue
        
        # Template for self._data, mangled by get_output()
        self._data = {'full_text': '',
                      'short_text': '',
                      'color': self.color_normal
                     }
        
        # prevoius value of _data, for comparision
        self._data_prev = self._data.copy()
    
    def _fill_queue(self):
        if self.show and (True if self.blanked else (self._data != self._data_prev)):
            self.queue.put((self.idn, self.get_output()))
            self._data_prev = self._data.copy()
            self.blanked = False
        elif not self.show if not self.blanked else False:
            self.queue.put((self.idn, None))
            self.blanked = True
        
    def _update_data(self):
        '''
        This function has to manipulate self._data variable that 
        should store internal readings ready to be dumped by 
        get_output().
        '''
        raise NotImplementedError()
    
    def get_output(self):
        '''
        Returns a dictionary ready to be sent to i3bar.
        '''
        output = {'full_text': self._data['full_text'],
                  'name': self.name,
                  }
        if self._data['color']:
            output['color'] = self._data['color']
        if self._data['short_text']:
            output['short_text'] = self._data['short_text']
        if self.urgent:
            output['urgent'] = self.urgent
        return output
    
    def run(self):
        '''Main worker loop.'''
        while True:
            self._update_data()
            self._fill_queue()
            sleep(self.interval)


class GetTemp(WorkerThread):
    '''
    Skeleton Class for worker threads monitoring temperature of
    various pc components.
    '''
    def __init__(self, temp_warning, temp_critical, **kwargs):
        WorkerThread.__init__(self, **kwargs)
        self.temp_warning = float(temp_warning)
        self.temp_critical = float(temp_critical)
        
    def _check_temp(self, temp):
        '''
        If the measured temperature is higher than temp_critical 
        value, display it and set urgency. Stop displaying when
        temperature drops below temp_warning threshold.
        '''
        if temp >= self.temp_critical:
            self._data['color'] = self.color_critical
            self.urgent = True
            self.show = True
        elif self.temp_warning <= temp < self.temp_critical:
            self._data['color'] = self.color_warning
            self.urgent = False
        elif temp < self.temp_warning:
            self.show = False
            self.urgent = False
        self._data['full_text'] = '{}: {}C'.format(self.name, temp)
        
        
class FIFObserver(Thread):
    def __init__(self, fifofile, **kwargs):
        Thread.__init__(self, **kwargs)
        self.daemon = True
        self.fifofile = fifofile
        self._make_fifo()
        # Avaible commands to be processed by this class
        # Registered with register_command()
        self._commands = {}
            
    def _make_fifo(self):
        try:
            os.mkfifo(self.fifofile)
        except OSError:
            os.remove(self.fifofile)
            self._make_fifo()
    
    def register_command(self, command, queue):
        self._commands[command.lower()] = queue
    
    def run(self):
        while True:
            with open(self.fifofile) as fifo:
                # Should be a string 'TARGET:COMMAND', so output will be
                # a 2-item list
                target, command = fifo.read().strip().split(':')
                # Normalize commands
                target, command = target.lower(), command.lower()
            if target in self._commands:
                self._commands[target].put(command)
        
class MPDCurrentSong(WorkerThread):
    '''
    Grabs current sog from MPD. Shows data only if MPD is 
    currently playing. If exception is encountered, 
    try to reconnect until succesfull.
    '''
    def __init__(self, host, port, observer, **kwargs):
        WorkerThread.__init__(self, **kwargs)
        self.host = host
        self.port = int(port)
        self.mpd_client = MPDClient()
        self._connect_to_mpd()
        self.commandq = Queue()
        observer.register_command('mpd', self.commandq)
        self.playing = Event()
        self.mpd_lock = Lock()
        wait_for_commands = Thread(target=self._command_mangler, daemon=True)
        wait_for_commands.start()
        if not self.is_stopped():
            self._playing()
        
    def _connect_to_mpd(self):
        try:
            self.mpd_client.connect(self.host, self.port)
        except (ConnectionError, ConnectionRefusedError):
            pass
    
    def is_stopped(self):
        if (self.mpd_client.status()['state'] == 'stop' or 
        self.mpd_client.status()['state'] == 'pause'):
            return True
        else:
            return False
    
    def _playing(self):
        self.show = True
        self.playing.set()
    
    def _pausing(self):
        self.playing.clear()
        self.show = False
    
    def _command_mangler(self):
        while True:
            command = self.commandq.get()
            self.mpd_lock.acquire()
            try:
                if command == 'toggle':
                    if self.is_stopped():
                        self.mpd_client.play()
                        self._playing()
                    else:
                        self.mpd_client.pause()
                        self._pausing()
                elif command == 'next' or command == 'prev':
                    if command == 'next':
                        self.mpd_client.next()
                    else:
                        self.mpd_client.previous()
                    if self.is_stopped():
                        self.mpd_client.play()
                        self._playing()
                        
            except:
                self.show = False
                self._connect_to_mpd()
            finally:
                self.mpd_lock.release()
                self._fill_queue()
                    
    def _update_data(self):
        '''
        Updates self._data to a string in a format "Artist - Song"
        '''
        
        self.playing.wait()
        self.mpd_lock.acquire()
        try:
                song = self.mpd_client.currentsong()
            
                if 'artist' in song:
                    mpd_artist = song['artist']
                else:
                    mpd_artist = 'Unknown Artist'
            
                if 'title' in song:
                    mpd_title = song['title']
                else:
                    mpd_title = 'Unknown Title'
                self._data['full_text'] = mpd_artist + ' - ' + mpd_title
                self._data['short_text'] = mpd_title
        except (ConnectionError, ConnectionRefusedError):
            self._connect_to_mpd()
        finally:
            self.mpd_lock.release()

    
class HDDTemp(GetTemp):
    '''
    Monitors HDD temperature, depends on hddtemp daemon running.
    '''
    def __init__(self, host, port, **kwargs):
        GetTemp.__init__(self, **kwargs)
        self.host = host
        self.port = int(port)
    
    def _update_data(self):
        temp = 0
        # Hddtemp sometimes sends empty data, try until it sends 
        # something worthwhile.
        while not temp:
            hdd_temp = socket()
            hdd_temp.connect((self.host, self.port))
            output = hdd_temp.recv(4096).split(b'|')
            if len(output) >= 4:
                try:
                    temp = float(output[3])
                # Disk spun down, hddtemp shows SLP 
                # instead of temperature
                except ValueError:
                    self.show = False
                    break
                else:
                    self._check_temp(temp)
    

class GPUTemp(GetTemp):
    '''
    Monitors the temperature of GPU with properietary drivers 
    installed. Use HwmonTemp for open-source ones.
    ''' 
    def __init__(self, vendor, **kwargs):
        GetTemp.__init__(self, **kwargs)
        if vendor == 'catalyst':
            self.command = 'aticonfig --odgt'.split()
            self.extractor = lambda output: float(output.splitlines()[2].split()[4])
        elif vendor == 'nvidia':
            self.command = 'nvidia-settings -q gpucoretemp -t'.split()
            self.extractor = lambda output: float(output)
        else:
            raise ValueError(self.name + ': Unsupported vendor string.')
    
    def _update_data(self):
        tool = Popen(self.command, stdout=PIPE)
        output = tool.stdout.read()
        temp = self.extractor(output)
        self._check_temp(temp)
        
class HwmonTemp(GetTemp):
    '''
    Reads temperature from every file specified in temp_files list
    and displays the highest one. Altough this class is supposed to deal
    with CPU temperatures, any temperature file from hwmon driver should
    work.
    '''
    def __init__(self, temp_files, **kwargs):
        GetTemp.__init__(self, **kwargs)
        self.temp_files = temp_files.split()
        
    def _update_data(self):
        max_temp = 0
        for temp_file in self.temp_files:
            with open(temp_file) as temp_output:
                temp = float(temp_output.read())
                
            # if temp is higer than 1000, 
            # assume it's in milidegrees of Celsius
            if temp > 1000:
                temp = float(temp) / 1000
            
            if temp > max_temp:
                max_temp = temp
        self._check_temp(max_temp)

        
class DiskUsage(WorkerThread):
    '''
    Monitor disk usage using psutil interface. Shows data only when
    free space on one or more partitions is less than 
    (100 - self.percentage)%.
    '''
    def __init__(self, mountpoint, percentage, **kwargs):
        WorkerThread.__init__(self, **kwargs)
        self.percentage = float(percentage)
        self.mountpoint = mountpoint
        
    def _update_data(self):
        try:
            usage = disk_usage(self.mountpoint)
        except OSError:
            self.show = False
            pass
        else:
            if usage.percent > self.percentage:
                self.urgent = True
                self._data['full_text'] = '{}: {}% {}'.format(
                    self.mountpoint, 
                    usage.percent,
                    self.human_size(usage.free))
                # Last directory in mount point instead of full path
                self._data['short_text'] = '{}: {}%'.format(
                    self.mountpoint.split('/')[-1], 
                    usage.percent)
                self._data['color'] = self.color_warning
                self.show = True
            else:
                self.show = False
                self.urgent = False

    def human_size(self, byte):
        '''
        Present amount of bytes in human-readable format.
        '''
        if byte == 0:
            return '0.0 B'
        suffixes = ('B' ,'K', 'M', 'G', 'T', 'P')
        values = {}
        for n, suffix in enumerate(suffixes):
            values[suffix] = pow(2, (n*10))
        for suffix in reversed(suffixes):
            if byte >= values[suffix]:
                value = byte / values[suffix]
                value = '{:.1f} {}'.format(value, suffix)
                return value
            
class Date(WorkerThread):
    '''Shows date and time, nothing to see here.'''
    def __init__(self, **kwargs):
        WorkerThread.__init__(self, **kwargs)
        self.show=True
    
    def _update_data(self):
        self._data['full_text'] = strftime('%d-%m-%Y %H:%M')
        self._data['short_text'] = strftime('%H:%M')

    
class BatteryStatus(WorkerThread):
    '''
    Monitors battery status. Lots of files!
    '''
    def __init__(self,
            critical,
            battery_file_full,
            battery_file_present,
            battery_file_charge,
            battery_file_status, 
            **kwargs):
        
        WorkerThread.__init__(self, **kwargs)
        self.critical = float(critical)
        self.battery_file_full = battery_file_full
        self.battery_file_present = battery_file_present
        self.battery_file_charge = battery_file_charge
        self.battery_file_status = battery_file_status
        
    def _update_data(self):
        with open(self.battery_file_present) as bat_p:
            present = bat_p.read().strip()
        if present != '1':
            self.show = False
            return
            
        with open(self.battery_file_status) as bat_s:
            status = bat_s.read().strip()
        
        if status == 'Full':
            self.show = False
            
        elif (status =='Charging') or (status == 'Discharging'):
            status_s = status[0]
            with open(self.battery_file_full) as bat_f:
                full = int(bat_f.read().strip())
        
            with open(self.battery_file_charge) as bat_c:
                charge = int(bat_c.read().strip())
                
            percentage = charge * 100 / full
            if percentage < self.critical:
                self.urgent = True
                self._data['color'] = self.color_critical
            else:
                self.urgent = False
                self._data['color'] = self.color_normal
            self._data['full_text'] = '{} {:.0f}%'.format(status, 
                percentage)
            self._data['short_text'] = '{} {:.0f}%'.format(status_s, 
                percentage)
            self.show = True
        
        elif status == 'Unknown':
            self.show = False

            
class WirelessStatus(WorkerThread):
    '''
    Monitor if given interface is connected to the internet. Uses ioctl()
    call.
    '''
    def __init__(self, interface, **kwargs):
        WorkerThread.__init__(self, **kwargs)
        self.interface = interface
        self.length = 32 # Max ESSID length
        self.fmt = 'PH' # Format for struct.pack(), P = void*, H=unsigned short
        self.magic_number = 0x8B1B # Wizardry
        # First part of the ioctl call, 16-byte string containing name 
        # of the interface.
        self.part_1 = bytes(self.interface.encode()) + b'\0' * (16-len(interface))
        # Second part of the ioctl call, 32-byte empty string that will
        # contain ESSID
        self.part_2 = b'\x00' * self.length
        # Socket to the kernel, seems like it doesn't need recreating
        # every loop.
        self.kernel_socket = socket(type=SOCK_DGRAM)
        self.show = True
    
    def _update_data(self):
        # Build the call
        iwrequest = array('B', self.part_1)
        essid = array('B', self.part_2)
        address = essid.buffer_info()[0] # (address, self.length)
        iwrequest.extend(pack(self.fmt, address, self.length)) # flag is omitted
        
        # Moment of truth
        ioctl(self.kernel_socket.fileno(), self.magic_number, iwrequest)
            
        output = essid.tostring().strip(b'\x00').decode()
        
        if output:
            self._data['full_text'] = output
            self._data['short_text'] = output
            self._data['color'] = self.color_normal
            self.urgent = False
        else:
            self._data['full_text'] = '{} disconnected'.format(
                self.interface)
            self._data['short_text'] = '{} D/C'.format(self.interface)
            self._data['color'] = self.color_critical
            self.urgent = True

    
class Volume(WorkerThread):
    '''
    Monitor volume of the given channel usilg alssaudio python 
    library.
    '''
    def __init__(self, 
                 channel,
                 mixer_id, 
                 card_index, 
                 **kwargs):
        WorkerThread.__init__(self, **kwargs)
        self.channel = channel
        self.mixer_id = int(mixer_id)
        self.card_index = int(card_index)
        self.show = True
        self.amixer = Mixer(control=self.channel, 
                            id=self.mixer_id,
                            cardindex=self.card_index)
        self.channels = len(self.amixer.getvolume())
            
    def _update_data(self):
        self.amixer = Mixer(control=self.channel, 
                            id=self.mixer_id,
                            cardindex=self.card_index)
        self._data['full_text'] = '♪:'
        try:
            muted = self.amixer.getmute()
        except ALSAAudioError:
            muted = [False for i in range(0, self.channels)]
        volume = self.amixer.getvolume()
        for i in range(0, self.channels):
            self._data['full_text'] += '{:3d}%'.format(volume[i])
            if i < self.channels - 1:
                self._data['full_text'] += ' '
            if muted[i]:
                self._data['color'] = self.color_critical
            else:
                self._data['color'] = self.color_normal

        
class XInfo(WorkerThread):
    '''
    I need to come up with a better solution, but this will do for now.
    Shows if *Lock keys are on.
    '''
    def __init__(self, **kwargs):
        WorkerThread.__init__(self, **kwargs)
        self.command = 'xset q'.split()
        self.lock_keys_re = re.compile(r'(Caps Lock|Num Lock|Scroll Lock):\s*(off|on)')
        self._data['color'] = self.color_warning
        
    def _update_data(self):
        xset = Popen(self.command, stdout=PIPE)
        output = xset.stdout.read().decode()
        self._data['full_text'] = ''
        
        for match in self.lock_keys_re.finditer(output):
            key, state = match.groups()
            if state == 'on':
                self._data['full_text'] += key + ' '
        
        if self._data['full_text']:
            self._data['full_text'] = self._data['full_text'].strip()
            self.show = True
        else:
            self.show = False
            
        
class DPMS(WorkerThread):
    '''
    Recieves messages from external script, that turns DPMS on/off.
    We can assume that DPMS is always on initially.
    Script: https://github.com/kaszak/dots/blob/master/bin/dpms_on_off.py
    ''' 
    def __init__(self, observer, **kwargs):
        WorkerThread.__init__(self, **kwargs)
        self.dpms_re = re.compile(r'DPMS is (?P<state>Enabled|Disabled)')
        self.command_q = 'xset q'.split()
        self.command_off = 'xset -dpms; xset s off'
        self.command_on = 'xset +dpms; xset s on'
        self.command_dpms_off = 'xset dpms force off'
        self.commandq = Queue()
        observer.register_command('dpms', self.commandq)
        
        # Override default interval, fifo will serve as a timer/blocker
        self.interval = 0
        self._data['color'] = self.color_warning
        self._data['full_text'] = 'DPMS'
        
    def _update_data(self):
        command = self.commandq.get().lower()
        if command == 'toggle':
            xset = Popen(self.command_q, stdout=PIPE)
            output = xset.stdout.read().decode()
            dpms_state = self.dpms_re.search(output).group('state')
            if dpms_state == 'Enabled':
                call(self.command_off, shell=True)
                self.show = True
            else:
                call(self.command_on, shell=True)
                self.show = False
        elif command == 'off':
            call(self.command_dpms_off, shell=True)
            # DPMS always turns on if you call this command
            self.show = False


class StatusBar():
    def __init__(self):
        self.threads = []
        # Holds the last known output of threads
        self.data = []
        self.comma = ''
        self.updates = Queue()
        
    def _start_threads(self):
        config = ConfigParser()
        config.read([expanduser('~/.py3status.conf'),
                     expanduser('~/py3status.conf'),
                    'py3status.conf', 
                    '/etc/py3status.conf'
                    ])
        
        self.observer = FIFObserver(fifofile='/tmp/statusbar.fifo')
        self.observer.start()
        
        order = config['DEFAULT'].pop('order').split()

        # Initialize threads and start them.
        # While at it, populate data list
        for i, entry in enumerate(order):
            arguments = {'idn': i,
                         'queue': self.updates
                         }
            observe = config[entry].getboolean('observer')
            if observe:
                config[entry].pop('observer')
                arguments['observer'] = self.observer
            class_type = config[entry].pop('class_type')
            # Trick for merging two dictionaries
            arguments = dict(list(arguments.items()) + list(config[entry].items()))
            self.threads.append(globals()[class_type](**arguments))
            self.data.append(None)
            self.threads[i].start()
    
    def _handle_updates(self):
        while self.updates:
            # Blocks here, message expected is (thread number, dict with output or None)
            idn, entry = self.updates.get()
            self.updates.task_done()
            self.data[idn] = entry
            
            self._print_data()
            
    def _print_data(self):
        items = [item for item in self.data if item]
        if items:
            print(self.comma, dumps(items), flush=True, sep='')
            self.comma = ','
        
    def run(self):
        print('{"version":1}', flush=True)
        print('[', flush=True)
        
        self._start_threads()
        self._handle_updates()
                
if __name__ == '__main__':
    statusbar = StatusBar()
    statusbar.run()
