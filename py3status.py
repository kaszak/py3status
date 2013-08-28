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
from subprocess import Popen, call, PIPE, call, check_output
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
import ctypes
import sys

from mpd import MPDClient, ConnectionError
import psutil


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
        self.daemon = True  # kill threads when StatusBar exits
        self.show = False
        self.urgent = False
        self.blanked = True  # was the output empty previously?
        self.interval = int(interval)
        self.name = name
        self.idn = idn  # Identification number, sort of
        self.color_warning = color_warning
        self.color_critical = color_critical
        self.color_normal = color_normal
        self.queue = queue

        # Template for self._data, mangled by get_output()
        self._data = {'full_text': '',
                      'color': self.color_normal
                      }

        # prevoius value of _data, for comparision
        self._data_prev = self._data.copy()

    def _fill_queue(self):
        if self.show and (True if self.blanked
                          else (self._data != self._data_prev)):
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
        if self.urgent:
            output['urgent'] = self.urgent
        return output

    def run(self):
        '''Main worker loop.'''
        while True:
            self._update_data()
            self._fill_queue()
            sleep(self.interval)

class DebugStdin(WorkerThread):
    '''
    click_events explaination in the protocol was unclear, wrote this to test them.
    '''
    def __init__(self, **kwargs):
        WorkerThread.__init__(self, **kwargs)
        self.show = True
        
    def _update_data(self):
        self._data["full_text"] = sys.stdin.readline()

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
        
        
class Toggler(WorkerThread):
    def __init__(self, observer,
                 command_q, 
                 command_off, 
                 command_on,
                 rexpression,
                 trueval,
                 **kwargs):
        WorkerThread.__init__(self, **kwargs)
        self.rexpression = re.compile(rexpression)
        self.command_q = command_q.split()
        self.command_off = command_off
        self.command_on = command_on
        self.commandq = Queue()
        self.trueval = trueval
        observer.register_command(self.name, self.commandq)
        # Override default interval, fifo will serve as a timer/blocker
        self.interval = 0
        self._data['color'] = self.color_warning
        self._data['full_text'] = self.name
        
    def _show(self):
        self.show = self._is_disabled()
        self._fill_queue()
    
    def _is_disabled(self):
        xset = Popen(self.command_q, stdout=PIPE)
        output = xset.stdout.read().decode()
        state = self.rexpression.search(output).group('state')
        if state == self.trueval:
            return False
        else:
            return True
            
    def toggle(self):
        xset = Popen(self.command_q, stdout=PIPE)
        output = xset.stdout.read().decode()
        dpms_state = self.rexpression.search(output).group('state')
        if self._is_disabled():
            self.on()
        else:
            self.off()
        
    def on(self):
        call(self.command_on, shell=True)
        self.show = False
    
    def off(self):
        call(self.command_off, shell=True)
        self.show = True
    
    def _update_data(self):
        command = self.commandq.get().lower()
        try:
            getattr(self, command)()
        except AttributeError:
            pass


class FIFObserver(Thread):
    '''
    Reads messages sent to a named pipe and hands them to appropriate
    handler.
    '''
    def __init__(self, **kwargs):
        Thread.__init__(self, **kwargs)
        self.daemon = True
        self.dir = '/tmp/' + os.getenv('USER')
        self.fullpath = self.dir + '/py3status.fifo'
        self._make_fifo()
        # Avaible commands to be processed by this class
        # Registered with register_command()
        self._commands = {}

    def _make_fifo(self):
        try:
            os.remove(self.fullpath)
            os.rmdir(self.dir)
        except OSError:
            pass
        finally:
            os.mkdir(self.dir)
            os.mkfifo(self.fullpath)

    def register_command(self, command, queue):
        if not command in self._commands:
            self._commands[command.lower()] = queue
        else:
            raise KeyError('Command already registered')

    def run(self):
        while True:
            with open(self.fullpath) as fifo:
                # Should be a string 'TARGET:COMMAND', so output will be
                # a 2-item list
                stuff = fifo.read().strip()
            # Normalize commands
            try:
                target, command = stuff.split(':')
            except ValueError:
                # Wrong thingie, ignore it
                pass
            else:
                target, command = target.lower(), command.lower()
                if target in self._commands:
                    self._commands[target].put(command)


class MPDCurrentSong(WorkerThread):
    '''
    Grabs current song from MPD. Shows data only if MPD is
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
        status = self.mpd_client.status()
        if (status['state'] == 'stop' or
                status['state'] == 'pause'):
            return True
        else:
            return False

    def _playing(self):
        if not self.show:
            self.show = True

    def _pausing(self):
        if self.show:
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
                if not self.is_stopped():
                    self._update_data()
                self._fill_queue()

    def _update_data(self):
        '''
        Updates self._data to a string in a format "Artist - Song"
        '''
        # If mpd has been stopped from outside of this script, this should catch it.
        if self.is_stopped():
            self._pausing()
        else:
            self._playing()
            self.mpd_lock.acquire()
            try:
                song = self.mpd_client.currentsong()
        
                if 'artist' in song:
                    mpd_artist = song['artist']
                else:
                    mpd_artist = ''
        
                if 'title' in song:
                    mpd_title = song['title']
                else:
                    mpd_title = ''
                if mpd_artist and mpd_title:
                    self._data['full_text'] = mpd_artist + ' - ' + mpd_title
                elif not mpd_artist and not mpd_title:
                    self._data['full_text'] = 'Unknown'
                else:
                    self._data['full_text'] = mpd_artist + mpd_title # one is empty, so it doesn't matter
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
        # Hddtemp sometimes sends empty or incomplete data, try until it sends 
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
            usage = psutil.disk_usage(self.mountpoint)
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
        suffixes = ('B', 'K', 'M', 'G', 'T', 'P')
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
        self.fmt = 'PB' # Format for struct.pack(), P = void*, B=unsigned char
        self.magic_number = 0x8B1B # Wizardry
        # Socket to the kernel, seems like it doesn't need recreating
        # every loop.
        self.kernel_socket = socket(type=SOCK_DGRAM)
        self.essid = array('B', b'\0' * self.length)
        self.address = self.essid.buffer_info()[0] # (address, self.length)
        self.iwrequest = array('B', bytes(self.interface.encode()) + b'\0' * (16-len(interface)))
        self.iwrequest.extend(pack(self.fmt, self.address, self.length))
        self.show = True
        
    
    def _update_data(self):
        # Moment of truth
        ioctl(self.kernel_socket.fileno(), self.magic_number, self.iwrequest)
        output = self.essid.tostring().strip(b'\x00').decode()
        
        if output:
            self._data['full_text'] = output
            self._data['color'] = self.color_normal
            self.urgent = False
        else:
            self._data['full_text'] = '{} disconnected'.format(
                self.interface)
            self._data['color'] = self.color_critical
            self.urgent = True
        
        # Regenerate for reuse
        # memset essid to zeros
        # Set length to self.length again
        # [24], because:
        # [0-15] array with interface name
        # [16-23] 8-byte memory adress to self.essid
        # [24] one-byte value with length
        # ioctl sets length byte to the actual essid length, causes OSError
        # if not re-set to default value
        ctypes.memset(self.address, 0, self.iwrequest[24])
        self.iwrequest[24] = self.length
        


    
class Volume(WorkerThread):
    '''
    Monitor volume of the given channel using amixer.
    Probably going to make it more generic, TODO.
    '''
    def __init__(self, 
                 channel,
                 mixer_id, 
                 card_index,
                 step,
                 observer,
                 **kwargs):
        WorkerThread.__init__(self, **kwargs)
        self.channel = channel
        self.mixer_id = int(mixer_id)
        self.card_index = int(card_index)
        self.commandq = Queue()
        observer.register_command('alsa', self.commandq)
        self.interval = 0
        self.step = int(step)
        self.getvolre = re.compile(r'\[(?P<volume>[0-9]*)%\]')
        self.getmutere = re.compile(r'\[(?P<mute>on|off)\]')
                            
        self._update_volume()
        self.show = True
        self._fill_queue()
        
    def return_amixer_output(self):
        return check_output('amixer sget {} -M'.format(self.channel).split(), universal_newlines=True)
        
    def getvolume(self):
        return int(self.getvolre.search(self.return_amixer_output()).group('volume'))
    
    def is_muted(self):
        state = self.getmutere.search(self.return_amixer_output()).group('mute')
        if state == 'on':
            return False # Not muted
        elif state =='off':
            return True
        
    def setvolume(self, volume):
        if volume > 100:
            volume = 100
        elif volume < 0:
            volume = 0
            
        call('amixer sset {} {}% -M -q'.format(self.channel, volume).split())
        
    def togmute(self):
        if self.is_muted():
            action = 'unmute'
        else:
            action = 'mute'
        
        call('amixer sset {} {} -q'.format(self.channel, action).split())
        
        
    def _update_data(self):
        command = self.commandq.get()
        if command == 'up' or command == 'down':
            volume = self.getvolume()
            if command == 'up':
                new_volume = volume + self.step
            
            elif command == 'down':
                new_volume = volume - self.step
            
            self.setvolume(new_volume)
        
        elif command == 'mute':
            self.togmute()
        
        self._update_volume()
            
    def _update_volume(self):
        muted = self.is_muted()
        volume = self.getvolume()
        self._data['full_text'] = '♪:{:3d}%'.format(volume)
        if muted:
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
            
        
class DPMS(Toggler):
    '''
    Recieves messages from external script, that turns DPMS on/off.
    We can assume that DPMS is always on initially.
    ''' 
    def __init__(self,
                 turn_screen_off,
                 **kwargs):
        Toggler.__init__(self, **kwargs)
        self.turn_screen_off = turn_screen_off
        self._show()
    
    def turn_off(self):
        call(self.turn_screen_off, shell=True)
        # DPMS always turns on if you call this command
        self.show = False
            

class TouchPad(Toggler):
    def __init__(self, **kwargs):
        Toggler.__init__(self, **kwargs)
        mouses = 0
        for device in os.listdir('/dev/input'):
            if device.startswith('mouse'):
                mouses += 1
        if mouses > 1:
            self.off()
            self.show = False
        else:
            self.on()
            self.show = True
        self._fill_queue()
        
    def _is_disabled(self):
        return not Toggler._is_disabled(self)

    def on(self):
        Toggler.on(self)
        self.show = True
    
    def off(self):
        Toggler.off(self)
        self.show = False
        
class RadeonPowerProfile(WorkerThread):
    def __init__(self, observer, profile_file, **kwargs):
        WorkerThread.__init__(self, **kwargs)
        self.profile_file = profile_file
        self.commandq = Queue()
        observer.register_command(self.name, self.commandq)
        self.interval = 0
        self._data['color'] = self.color_warning
        self.if_show(self.get_profile())
        self._fill_queue()
        
        
    def _update_data(self):
        command = self.commandq.get()
        if command == 'toggle':
            current = self.get_profile()
            if current == 'low' or current == 'mid':
                self.write_profile('high')
            else:
                self.write_profile('low')
        else:
            profile.write(command)

    def write_profile(self, new_profile):
         with open(self.profile_file, 'w') as profile:
            profile.write(new_profile)
         self.if_show(new_profile)
    
    def get_profile(self):
        with open(self.profile_file) as profile:
            current = profile.readline().strip()
        return current
    
    def if_show(self, profile):
        if profile == 'high' or profile == 'auto':
            self.show = True
            self._data['full_text'] = self.name + ' ' + profile
        else:
            self.show = False
    
class StatusBar():
    def __init__(self):
        self.threads = []
        # Holds the last known output of threads
        self.data = []
        self.comma = ''
        self.updates = Queue()
        self.process = psutil.Process(os.getpid())
        self.process.set_nice(5)
        self.process.set_ionice(psutil.IOPRIO_CLASS_IDLE)
        
    def _start_threads(self):
        config = ConfigParser()
        config.read([expanduser('~/.py3status.conf'),
                     expanduser('~/py3status.conf'),
                    'py3status.conf', 
                    '/etc/py3status.conf'
                    ])
        
        self.observer = FIFObserver()
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
            # Blocks here, message expected is (thread id, get_output() with output or None)
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
        print('{"version":1, "click_events": true }\n[', flush=True)
        
        self._start_threads()
        self._handle_updates()
                
if __name__ == '__main__':
    statusbar = StatusBar()
    statusbar.run()
