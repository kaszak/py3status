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
from subprocess import Popen, PIPE
from socket import socket, SOCK_DGRAM
from threading import Thread
from queue import Queue
from time import sleep, strftime
from configparser import ConfigParser
from os.path import expanduser
from array import array
from struct import pack
from fcntl import ioctl
import re

from mpd import MPDClient, ConnectionError
from psutil import disk_partitions, disk_usage
from alsaaudio import Mixer, ALSAAudioError

class WorkerThread(Thread):
    '''Skeleton Class for all worker threads.'''
    def __init__(self, 
                 name, 
                 idn, 
                 queue, 
                 interval,
                 color_warning, 
                 color_critical, 
                 **kwargs):
        super().__init__(**kwargs)
        self.daemon = True # kill threads when StatusBar exits
        self.show = False
        self.urgent = False
        self.interval = int(interval)
        self.name = name
        self.idn = idn #Identification number, sort of
        self.color_warning = color_warning
        self.color_critical =  color_critical
        self.queue = queue
        
        # Template for self._data, mangled by get_output()
        self._data = {'full_text': '',
                      'short_text': '',
                      'color': ''
                     }
    
    def _update_data(self):
        '''This function has to manipulate self._data variable that 
        should store internal readings ready to be dumped by 
        get_output()'''
        pass
    
    def get_output(self):
        '''Returns a dictionary ready to be sent to i3bar'''
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
            if self.show:
                self.queue.put((self.idn, self.get_output()))
            else:
                self.queue.put((self.idn, None))
            sleep(self.interval)


class GetTemp(WorkerThread):
    '''Skeleton Class for worker threads monitoring temperature of
    various pc components.'''
    def __init__(self, temp_warning, temp_critical, **kwargs):
        super().__init__(**kwargs)
        self.temp_warning = float(temp_warning)
        self.temp_critical = float(temp_critical)
        
    def _check_temp(self, temp):
        '''If the measured temperature is higher than temp_critical 
        value, display it and set urgency. Stop displaying when
        temperature drops below temp_warning threshold.'''
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

        
class MPDCurrentSong(WorkerThread):
    '''Grabs current sog from MPD. Shows data only if MPD is 
    currently playing. If exception is encountered, 
    try to reconnect until succesfull.'''
    def __init__(self, host='localhost', port=6600, **kwargs):
        super().__init__(**kwargs)
        self.host = host
        self.port = int(port)
        self.mpd_client = MPDClient()
        self._connect_to_mpd()
        
        
    def _connect_to_mpd(self):
        try:
            self.mpd_client.connect(self.host, self.port)
        except (ConnectionError, ConnectionRefusedError):
            pass
        
    def _update_data(self):
        '''Updates self._data to a string in a format "Artist - Song"'''
        try:
            if (self.mpd_client.status()['state'] == 'stop' or 
                self.mpd_client.status()['state'] == 'pause'):
                self.show = False
            else:
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
                self.show = True
        except (ConnectionError, ConnectionRefusedError):
            self.show = False
            self._connect_to_mpd()

    
class HDDTemp(GetTemp):
    '''Monitors HDD temperature, depends on hddtemp daemon running.'''
    def __init__(self, host='localhost', port=7634, **kwargs):
        super().__init__(**kwargs)
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
    '''Monitors the temperature of GPU with properietary drivers 
    installed. Use HwmonTemp for open-source ones.''' 
    def __init__(self, vendor, **kwargs):
        super().__init__(**kwargs)
        self.vendor = vendor
        self.command = ''
        self.extractor = ''
      
    def decorate(updater):
        def wrapper(self):
            if not self.command or not self.extractor:
                if self.vendor == 'catalyst':
                    self.command = 'aticonfig --odgt'.split()
                    self.extractor = 'float(output.splitlines()[2].split()[4])'
                elif self.vendor == 'nvidia':
                    self.command = 'nvidia-settings -q gpucoretemp -t'.split()
                    self.extractor = 'float(output)'
            
            output = updater(self, self.command)
            temp = eval(self.extractor)
            self._check_temp(temp)
        
        return wrapper
    
    @decorate
    def _update_data(self, command):
        tool = Popen(command, stdout=PIPE)
        return tool.stdout.read()

class HwmonTemp(GetTemp):
    '''Reads temperature from every file specified in temp_files list
    and displays the highest one. Altough this class is supposed to deal
    with CPU temperatures, any temperature file from hwmon driver should
    work.'''
    def __init__(self, temp_files, **kwargs):
        super().__init__(**kwargs)
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
    '''Monitor disk usage using psutil interface. Shows data only when
    free space on one or more partitions is less than 
    (100 - self.percentage)%'''
    def __init__(self, mountpoint, percentage=90, **kwargs):
        super().__init__(**kwargs)
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
        '''Present amount of bytes in human-readable format.'''
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
        super().__init__(**kwargs)
        self.show=True
    
    def _update_data(self):
        self._data['full_text'] = strftime('%d-%m-%Y %H:%M')
        self._data['short_text'] = strftime('%H:%M')

    
class BatteryStatus(WorkerThread):
    '''Monitors battery status. Lots of files!'''
    def __init__(self, critical=5,
            battery_file_full='/sys/class/power_supply/BAT0/energy_full',
            battery_file_present='/sys/class/power_supply/BAT0/present',
            battery_file_charge='/sys/class/power_supply/BAT0/energy_now',
            battery_file_status='/sys/class/power_supply/BAT0/status', 
            **kwargs):
        
        super().__init__(**kwargs)
        self.critical = float(critical)
        self.battery_file_full = battery_file_full
        self.battery_file_present = battery_file_present
        self.battery_file_charge = battery_file_charge
        self.battery_file_status = battery_file_status
        
    def _update_data(self):
        self.color = ''
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
                self._data['color'] = ''
            self._data['full_text'] = '{} {:.0f}%'.format(status, 
                percentage)
            self._data['short_text'] = '{} {:.0f}%'.format(status_s, 
                percentage)
            self.show = True
        
        elif status == 'Unknown':
            self.show = False

            
class WirelessStatus(WorkerThread):
    '''Monitor if given interface is connected to the internet.'''
    def __init__(self, interface, **kwargs):
        super().__init__(**kwargs)
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
        packed = pack(self.fmt, address, self.length)
        iwrequest.extend(packed)
        
        # Moment of truth
        try:
            ioctl(self.kernel_socket.fileno(), self.magic_number, iwrequest)
        except OSError:
            self._data['full_text'] = '{}: {} is not wireless'.format(
                self.name, self.interface)
            self._data['short_text'] = '{}!'.format(self.name)
            self.color = self.color_critical
            self.urgent = True
            return
            
        output = essid.tostring().strip(b'\x00').decode()
        
        if output:
            self._data['full_text'] = output
            self._data['short_text'] = output
            self._data['color'] = ''
            self.urgent = False
        else:
            self._data['full_text'] = '{} disconnected'.format(
                self.interface)
            self._data['short_text'] = '{} D/C'.format(self.interface)
            self._data['color'] = self.color_critical
            self.urgent = True

    
class Volume(WorkerThread):
    '''Monitor volume of the given channel usilg alssaudio python 
    library.'''
    def __init__(self, 
                 channel='Master',
                 mixer_id=0, 
                 card_index=0, 
                 **kwargs):
        super().__init__(**kwargs)
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
        self._data['color'] = ''
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

        
class XInfo(WorkerThread):
    '''I need to come up with a better solution, but this will do for now.
    Shows if *Lock keys are on, and if DPMS of the monitor is off.'''
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.command = 'xset q'.split()
        self.lock_keys_re = re.compile(r'(Caps Lock|Num Lock|Scroll Lock):\s*(off|on)')
        self.dpms_re = re.compile(r'DPMS is (?P<state>Enabled|Disabled)')
        self._data['color'] = self.color_warning
        
    def _update_data(self):
        xset = Popen(self.command, stdout = PIPE)
        output = xset.stdout.read().decode()
        self._data['full_text'] = ''
        
        for match in self.lock_keys_re.finditer(output):
            key, state = match.groups()
            if state == 'on':
                self._data['full_text'] += key + ' '
        
        dpms_state = self.dpms_re.search(output).group('state')
        if dpms_state == 'Disabled':
            self._data['full_text'] += 'DPMS'
        
        if self._data['full_text']:
            self._data['full_text'] = self._data['full_text'].strip()
            self.show = True
        else:
            self.show = False
        

class StatusBar():
    def __init__(self):
        self.threads = []
        self.data = []
        self.data_prev = []
        self.comma = ''
        self.updates = Queue()
        
        
    def _start_threads(self):
        config = ConfigParser()
        config.read([expanduser('~/.py3status.conf'),
                     expanduser('~/py3status.conf'),
                    'py3status.conf', 
                    '/etc/py3status.conf'
                    ])
        
        order = config['DEFAULT'].pop('order').split()

        for i, entry in enumerate(order):
            self.threads.append(globals()[config[entry].pop('class_type')](
                                idn=i, queue=self.updates, **config[entry]))
            self.data.append(None)
        for thread in self.threads:
            thread.start()
    
    def _handle_updates(self):
        while self.updates:
            idn, entry = self.updates.get()
            self.updates.task_done()
            self.data[idn] = entry
            
            if self.data != self.data_prev:
                self._print_data()
                self.data_prev = self.data.copy()
            
            
    def _print_data(self):
        items = [item for item in self.data if item]
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
