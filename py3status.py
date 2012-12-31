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

import json
import re
from subprocess import Popen, PIPE
from socket import socket
from threading import Thread, Event
from time import sleep, strftime
import os

from mpd import MPDClient
from psutil import disk_partitions, disk_usage
from alsaaudio import Mixer, ALSAAudioError

#Files containing CPU temperatures
CORE0        = '/sys/devices/platform/coretemp.0/temp2_input'
CORE1        = '/sys/devices/platform/coretemp.0/temp3_input'

class WorkerThread(Thread):
    '''Skeleton Class for all worker threads.'''
    def __init__(self, name, interval=1, **kwargs):
        super().__init__(**kwargs)
        self.stopped = Event()
        self.paused = Event()
        self.show = False
        self.urgent = False
        self.interval = interval
        self.name = name
        self.color_good = "#597B20"
        self.color_warning = "#DED838"
        self.color_critical =  "#C12121"
        
        # Subclasses need to upadte this value in their's _update_data()
        # It's type generally doesn't matter
        self._data = ''

    
    def stop(self):
        '''Breaks the run() loop.'''
        self.stopped.set()
    
    def _update_data(self):
        '''This function has to manipulate self._data variable that 
        should store internal readings ready to be dumped by 
        get_output()'''
        pass
    
    def get_output(self):
        '''This function is supposed to output data in a i3bar-friendly
        format. Should be overrided by subclasses to accomodate to 
        their's specific self._data type, altough it does provide 
        rudimentary functionality.'''
        output = {'full_text': self._data, 
                  'name': self.name, 
                  'urgent': self.urgent
                  }
        return output
    
    def run(self):
        '''Main worker loop.'''
        while not self.stopped.is_set():
            self._update_data()
            sleep(self.interval)
        
        
        
class GetTemp(WorkerThread):
    '''Skeleton Class for worker threads monitoring temperature of
    various pc components.'''
    def __init__(self, temp_warning, temp_critical, **kwargs):
        super().__init__(**kwargs)
        self.temp_warning = temp_warning
        self.temp_critical = temp_critical
        
    def _check_temp(self, temp):
        '''If the measured temperature is higher than temp_critical 
        value, display it and set urgency. Stop displaying when
        temperature drops below temp_warning threshold.'''
        self.color = ''
        if temp >= self.temp_critical:
            self.show = True
            self.color = self.color_critical
            self.urgent = True
        elif self.temp_warning <= temp < self.temp_critical:
            self.color = self.color_warning
            self.urgent = False
        elif temp < self.temp_warning:
            self.show = False
            self.urgent = False
        if self.show:
            self._data = temp
            
    def get_output(self):
        output = {'full_text': '{}: {}C'.format(self.name, self._data),
            'name': self.name, 'urgent': self.urgent}
        if self.color:
            output['color'] = self.color
        return output
        
        
        
class MPDCurrentSong(WorkerThread):
    '''Grabs current sog from MPD. Shows data only if MPD is 
    currently playing. If ConnectionError exception is encountered, 
    try to reconnect until succesfull.'''
    def __init__(self, host='localhost', port=6600, interval=1, 
            name='Currently Playing', **kwargs):
        super().__init__(interval=interval,name=name, **kwargs)
        self.host = host
        self.port = port
        self.mpd_client = MPDClient()
        self._connect_to_mpd()
        
        
    def _connect_to_mpd(self):
        try:
            self.mpd_client.connect(self.host, self.port)
        except ConnectionError:
            pass
        
    def _update_data(self):
        '''Updates self._data to a string in a format "Artist - Song"'''
        self._data = ''
        try:
            if self.mpd_client.status()['state'] == 'stop' or self.mpd_client.status()['state'] == 'pause':
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
                self._data = mpd_artist + ' - ' + mpd_title
                self.show = True
        except ConnectionError:
            self.show = False
            self._connect_to_mpd()
    
class HDDTemp(GetTemp):
    '''Monitors HDD temperature, depends on hddtemp daemon running.'''
    def __init__(self, host='localhost', port=7634, interval=60, name='HDD', **kwargs):
        super().__init__(interval=interval, name=name, **kwargs)
        self.host = host
        self.port = port
    
    def _update_data(self):
        temp = 0
        # Hddtemp sometimes sends empty data, try until it sends something 
        # worthwhile.
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
    '''Monitors the temperature of GPU, currently only properietary ATI 
    and nVidia drivers work.''' 
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
    
class CPUTemp(GetTemp):
    '''Reads temperature from every file specified in temp_files list
    and displays the highest one. Altough this class is supposed to deal
    with CPU temperatures, any temperature file from hwmon driver should
    work.'''
    def __init__(self, temp_files, interval=2, name='CPU', **kwargs):
        super().__init__(interval=interval, name=name,**kwargs)
        self.temp_files = temp_files
        
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
    def __init__(self, interval=30, percentage=95, 
            name="Disk Usage", **kwargs):
        super().__init__(interval=interval, name=name,**kwargs)
        self.percentage = percentage 
        
    def _update_partitions(self):
        self.partitions = disk_partitions()
        #No need to track disk usage of read-only media
        for partition in self.partitions[:]:
            if partition.fstype == 'iso9660':
                self.partitions.remove(partition)
        
    def _update_data(self):
        self._update_partitions()
        data_temp = []
        self._data = []
        for partition in self.partitions:
            try:
                usage = disk_usage(partition.mountpoint)
            except OSError:
                pass
            else:
                data_temp.append([partition.mountpoint, usage])
            for entry in data_temp:
                if entry[1].percent > self.percentage:
                    over = True
                    self._data.append({'point': entry[0], 
                        'free': self.human_size(entry[1].free)})
            if self._data:
                self.show = True
                self.urgent = True
            else:
                self.show = False
                self.urgent = False
                
    def get_output(self):
        output = []
        for entry in self._data:
            output.append({'full_text': '{}: {}'.format(entry['point'], 
                entry['free']),
                'name': self.name, 'urgent': self.urgent})
        return output
            
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
        self._data = []
        self._data.append(strftime("%d-%m-%Y %H:%M"))
        self._data.append(strftime("%H:%M"))
    
    def get_output(self):
        output = {'full_text': self._data[0],'short_text': self._data[1], 'name': self.name}
        return output
        
class BatteryStatus(WorkerThread):
    '''Monitors battery status. Lots of files!'''
    def __init__(self, interval=5, critical=5, name='Battery', 
            battery_file_full='/sys/class/power_supply/BAT0/energy_full',
            battery_file_present='/sys/class/power_supply/BAT0/present',
            battery_file_charge='/sys/class/power_supply/BAT0/energy_now',
            battery_file_status='/sys/class/power_supply/BAT0/status', 
            **kwargs):
        
        super().__init__(interval=interval, name=name,**kwargs)
        self.critical = critical
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
            return
        elif status =='Charging':
            status = 'C'
            
        elif status == 'Discharging':
            status = 'D'
        
        elif status == 'Unknown':
            self.show = False
            return
        
        self._data = []        
        with open(self.battery_file_full) as bat_f:
            full = int(bat_f.read().strip())
        
        with open(self.battery_file_charge) as bat_c:
            charge = int(bat_c.read().strip())
        
        percentage = charge * 100 / full
        if percentage < self.critical:
            self.urgent = True
        else:
            self.urgent = False
        self._data.append(status)
        self._data.append(percentage)
        self.show = True
        
    def get_output(self):
        output = {'full_text': '{} {:.0f}%'.format(self._data[0], self._data[1]), 
            'short_text': self._data[0], 'name': self.name,'urgent': self.urgent}
        return output

class NetworkStatus(WorkerThread):
    '''Monitor if given interface is connected to the internet.'''
    def __init__(self, interface, always_show=False,
            interval=2, name='Network', **kwargs):
        super().__init__(interval=interval, name=name,**kwargs)
        self.interface = interface
        self.always_show = always_show
        self.show = always_show
        self._data = {
            'connected': False,
            'inet': ''
            }
    
    def _update_data(self):
        self.color = ''
        command = 'ifconfig {}'.format(self.interface)
        ifconfig = Popen(command.split(), stdout=PIPE)
        output = ifconfig.stdout.read().decode().split()
        if 'inet' in output:
            self._data['connected'] = True
            self._data['inet'] = output[output.index('inet') + 1]
            self.color = self.color_good
            if not self.always_show:
                self.show = False
        else:
            self.show = True
            self._data['connected'] = False
            self.color = self.color_good

    def get_output(self):
        if self._data['connected'] == True:
            output = {'full_text': '{}: {}'.format(self.interface, 
            self._data['inet']),
            'short_text': self.interface, 'name': self.name}
        
        else:
            output = {'full_text': '{}: {}'.format(self.interface, 
            'Disconnected'),
            'short_text': '{}: {}'.format(self.interface, 'D/C'), 
            'name': self.name}
        if self.color:
            output['color'] = self.color
        return output
    
class Volume(WorkerThread):
    '''Monitor volume of the given channel usilg alssaudio python library.'''
    def __init__(self, channel='Master', interval=1, name='Volume', **kwargs):
        super().__init__(interval=interval, name=name,**kwargs)
        self.channel = channel
        self.show = True
        self.amixer = Mixer(control=self.channel)
        self._data = []
        for i, channel in enumerate(self.amixer.getvolume()):
            self._data.append({'channel': i, 'level': 0, 'muted': False})
    
    def _update_data(self):
        self.amixer = Mixer(control=self.channel)
        self.color = ''
        try:
            for i, channel in enumerate(zip(self.amixer.getmute(), self.amixer.getvolume())):
                self._data[i]['level'] = channel[1]
                if channel[0]:
                    self._data[i]['muted'] = True
                    self.color = self.color_critical
                else:
                    self._data[i]['muted'] = False
        except ALSAAudioError:
            for i, volume in enumerate(self.amixer.getvolume()):
                self._data[i]['level'] = volume
            
                    
    def get_output(self):
        output = []
        for entry in self._data:
            output.append({'full_text': '♪{}:{}%'.format(entry['channel'],
                entry['level']),
                'name': self.name})
            if self.color:
                output['color'] = self.color
        return output
                
        
class StatusBar():
    def __init__(self, interval=1):
        self.interval = interval
        
def main():
    version = {'version': 1}
    threads = []
    comma = ''
    mpd_thread = MPDCurrentSong(interval=1)
    hdd_thread = HDDTemp(temp_warning=60, temp_critical=70)
    gpu_thread = GPUTemp(temp_warning=80, temp_critical=90, vendor='catalyst')
    cpu_thread = CPUTemp(temp_warning=80, temp_critical=90, temp_files=[CORE0, CORE1])
    df_thread = DiskUsage()
    date = Date()
    battery = BatteryStatus()
    network = NetworkStatus(interface='wlan0', always_show=False)
    volume = Volume()

    
    threads.append(mpd_thread)
    threads.append(hdd_thread)
    threads.append(gpu_thread)
    threads.append(cpu_thread)
    threads.append(df_thread)
    threads.append(network)
    threads.append(battery)
    threads.append(volume)
    threads.append(date)
    
    for thread in threads:
        thread.start()
        
    print(json.dumps(version))
    print('[')
    
    while True:
        try:
            items = []
            for thread in threads:
                if thread.show:
                    item = thread.get_output()
                    if isinstance(item, list):
                        items.extend(item)
                    else:
                        items.append(item)
                    
            print(comma, json.dumps(items), flush=True, sep='')
            comma = ','
            sleep(0.3)
        except KeyboardInterrupt:
            for thread in threads:
                thread.stop()
            raise
        
if __name__ == '__main__':
    main()
