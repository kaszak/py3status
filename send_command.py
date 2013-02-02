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

FIFO = '/tmp/statusbar.fifo'

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
    with open(FIFO, 'w') as fifo:
        fifo.write(target + ':' + command)
        fifo.flush()
	

if __name__ == '__main__':
	main()

