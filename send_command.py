#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  bez nazwy.py
#  
#  Copyright 2013 Unknown <kaszak@localhost>
#  
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
#  
import sys
import os
from time import sleep

FIFO = '/tmp/' + os.getenv('USER') + '/py3status.fifo'

class FileLock():
    def __init__(self, file_path, delay=.05):
        self._lock_path = file_path + '.lock'
        self._locked = False
        self.delay = delay
        
    def acquire(self):
        while True:
            try:
                self.descriptor = os.open(self._lock_path, flags=os.O_CREAT|os.O_EXCL|os.O_RDWR)
                break
            except OSError as fuck:
                if fuck.errno == 17: #  Means that the file already exist
                    sleep(self.delay)
                else:
                    raise
        self._locked = True
        
    def release(self):
        if self._locked:
            os.close(self.descriptor)
            os.unlink(self._lock_path)
            self._locked = False
            

def main():
    '''
    Simple tool to send commands to py3status.
    Usage:
    send_command.py TARGET COMMAND
    '''
    if len(sys.argv) < 3:
        sys.exit(1)
    
    target = sys.argv[1]
    command = ' '.join(sys.argv[2:])
    lock = FileLock(FIFO)
    lock.acquire()
    with open(FIFO, 'w') as fifo:
        fifo.write(target + ':' + command)
        fifo.flush()
    lock.release()

if __name__ == '__main__':
	main()

