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
from socket import socket
from threading import Thread, Event
from time import sleep, strftime
from configparser import ConfigParser
from os.path import expanduser

from mpd import MPDClient, ConnectionError
from psutil import disk_partitions, disk_usage
from alsaaudio import Mixer, ALSAAudioError


class WorkerThread(Thread):
    '''Skeleton Class for all worker threads.'''
    def __init__(self, name, interval=1, 
                 color_warning="#DED838", 
                 color_critical="#C12121", 
                 **kwargs):
        super().__init__(**kwargs)
        self.stopped = Event()
        self.paused = Event()
        self.show = False
        self.urgent = False
        self.interval = int(interval)
        self.name = name
        self.color_warning = color_warning
        self.color_critical =  color_critical
        
        # Template for self._data, containing strings
        self._data = {'full_text': '',
                      'short_text': '',
                      'color': ''
                     }

    def stop(self):
        '''Breaks the run() loop.'''
        self.stopped.set()
    
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
        while not self.stopped.is_set():
            # Empties _data every run
            # self._data = self._data_orig.copy()
            self._update_data()
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
    currently playing. If ConnectionError exception is encountered, 
    try to reconnect until succesfull.'''
    def __init__(self, host='localhost', port=6600, interval=1, 
                 name='Currently Playing', **kwargs):
        super().__init__(interval=interval,name=name, **kwargs)
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
    def __init__(self, host='localhost', port=7634, 
                 interval=60, name='HDD', **kwargs):
        super().__init__(interval=interval, name=name, **kwargs)
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
    def __init__(self, vendor, interval=2, name='GPU', **kwargs):
        super().__init__(interval=interval, name=name, **kwargs)
        if vendor == 'catalyst':
            self._update_data = self._update_data_catalyst
        elif vendor == 'nvidia':
            self._update_data = self._update_data_nvidia
        
    def _update_data_catalyst(self):
        command = 'aticonfig --odgt'
        catalyst = Popen(command.split(), stdout=PIPE)
        output = catalyst.stdout.read()
        temp = float(output.splitlines()[2].split()[4]) #shudder
        self._check_temp(temp)
        
    def _update_data_nvidia(self):
        command = 'nvidia-settings -q gpucoretemp -t'
        nvidia = Popen(command.split(), stdout=PIPE)
        output = nvidia.stdout.read()
        temp = float(output)
        self._check_temp(temp)


class HwmonTemp(GetTemp):
    '''Reads temperature from every file specified in temp_files list
    and displays the highest one. Altough this class is supposed to deal
    with CPU temperatures, any temperature file from hwmon driver should
    work.'''
    def __init__(self, temp_files, interval=2, name='CPU', **kwargs):
        super().__init__(interval=interval, name=name,**kwargs)
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
    def __init__(self, mountpoint,
                 interval=30, 
                 percentage=90, 
                 name="Disk Usage", 
                 **kwargs):
        super().__init__(interval=interval, name=name,**kwargs)
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
    def __init__(self, interval=60, name='Date', **kwargs):
        super().__init__(interval=interval, name=name,**kwargs)
        self.show=True
    
    def _update_data(self):
        self._data['full_text'] = strftime('%d-%m-%Y %H:%M')
        self._data['short_text'] = strftime('%H:%M')

    
class BatteryStatus(WorkerThread):
    '''Monitors battery status. Lots of files!'''
    def __init__(self, interval=5, critical=5, name='Battery', 
            battery_file_full='/sys/class/power_supply/BAT0/energy_full',
            battery_file_present='/sys/class/power_supply/BAT0/present',
            battery_file_charge='/sys/class/power_supply/BAT0/energy_now',
            battery_file_status='/sys/class/power_supply/BAT0/status', 
            **kwargs):
        
        super().__init__(interval=interval, name=name,**kwargs)
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
    def __init__(self, interface,
            interval=2, name='Network', **kwargs):
        super().__init__(interval=interval, name=name,**kwargs)
        self.interface = interface
        self.show = True
    
    def _update_data(self):
        command = 'iwgetid --raw {}'.format(self.interface)
        essid_command = Popen(command.split(), stdout=PIPE)
        if essid_command.poll() == 255:
            self._data['full_text'] = '{}: {} is not wireless'.format(
                self.name, self.interface)
            self._data['short_text'] = '{}!'.format(self.name)
            self.color = self.color_critical
            self.urgent = True
        output = essid_command.stdout.read().decode().strip()
        
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
    def __init__(self, channel='Master', interval=1, 
                 name='Volume', mixer_id=0, card_index=0, **kwargs):
        super().__init__(interval=interval, name=name,**kwargs)
        self.channel = channel
        self.mixer_id = int(mixer_id)
        self.card_index = int(card_index)
        self.show = True
        self.amixer = Mixer(control=self.channel, 
                            id=self.mixer_id,
                            cardindex=self.card_index)
        self.channels = 0
        for channel in self.amixer.getvolume():
            self.channels += 1
            
    
    def _update_data(self):
        self.amixer = Mixer(control=self.channel, 
                            id=self.mixer_id,
                            cardindex=self.card_index)
        self._data['full_text'] = '♪: '
        self._data['color'] = ''
        try:
            muted = self.amixer.getmute()
        except ALSAAudioError:
            muted = [False for i in range(0, self.channels)]
        volume = self.amixer.getvolume()
        for i in range(0, self.channels):
            self._data['full_text'] += str(volume[i]) + '%'
            if i < self.channels - 1:
                self._data['full_text'] += ' '
            if muted[i]:
                self._data['color'] = self.color_critical

        
class StatusBar():
    def __init__(self):
        home = expanduser('~')
        self.threads = []
        
    def _start_threads(self):
        config = ConfigParser()
        config.read([expanduser('~/.py3status.conf'),
                    'py3status.conf', 
                    '/etc/py3status.conf'
                    ])
        
        types = {
	    "MPDCurrentSong": MPDCurrentSong, 
	    "HDDTemp": HDDTemp, 
	    "GPUTemp": GPUTemp, 
	    "HwmonTemp": HwmonTemp, 
	    "DiskUsage": DiskUsage, 
	    "WirelessStatus": WirelessStatus, 
	    "BatteryStatus": BatteryStatus, 
	    "Volume": Volume, 
	    "Date": Date
        }
        
        self.interval = int(config['DEFAULT']['interval'])
        
        order = config['DEFAULT'].pop('order').split()

        for entry in order:
            self.threads.append(types[config[entry].pop('class_type')](
                                **config[entry]))
        for thread in self.threads:
            thread.start()
        
    def run(self):
        comma = ''

        print('{"version":1}', flush=True)
        print('[', flush=True)
        
        self._start_threads()
        
        while True:
            try:
                items = []
                for thread in self.threads:
                    if thread.show:
                        item = thread.get_output()
                        if isinstance(item, list):
                            items.extend(item)
                        else:
                            items.append(item)
                        
                print(comma, dumps(items), flush=True, sep='')
                comma = ','
                sleep(self.interval)
            except KeyboardInterrupt:
                for thread in self.threads:
                    thread.stop()
                raise
                
if __name__ == '__main__':
    statusbar = StatusBar()
    statusbar.run()
