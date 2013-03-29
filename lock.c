/*
 * lock.c
 * 
 * Copyright 2013 Kaszak <kaszak696@gmail.com>
 * 
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 * 
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 * 
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
 * MA 02110-1301, USA.
 * 
 * 
 */


#include <stdio.h>
#include <errno.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdlib.h>
#include "lock.h"

static int descriptor;

int acquire(char* lockname) 
{
    if(lockname == NULL) return -1;
    
    // Gonna grind until file is succesfully created, which results in
    // a lock. Necessary, because rapid execution of this gizmo can go
    // haywire, leave zombies. Or not.
    // usleep to not waste cpu
    while(1)
    {
        descriptor = open(lockname, O_CREAT|O_EXCL|O_RDWR, S_IRWXU);
        if(errno == EEXIST) 
        {
            errno = 0; // errno does not reset itself, good
            usleep(50000); //0.05 second
            continue;
        }
        else 
        {
            if(!errno)
                break;
            else return -1; //something blew up
        } 
    }
    return 0;
}

void release(char* lockname) 
{
    if(descriptor != 1) 
    {
        close(descriptor);
        unlink(lockname);
    }
}
