/*
 * send_command2.c
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
#include <limits.h>
#include "lock.h"
#include "config.h"

/* Tool to pass comands trough FIFO pipe. */
    
int main(int argc, char **argv)
{
    int i;
    char command[MAX_C] = "\0"; // strcat sometimes resulted with
    char filename[PATH_MAX] = "\0";// garbage without this initialization.
    char lockname[PATH_MAX] = "\0";// static declaration would work as well.
    FILE* fp;
    Lock* lock;
    
    // Construct path
    strcat(filename, "/tmp/");
    strcat(filename, getenv("USER"));
    strcat(filename, FILENAME);
    
    // Ditto, for .lock file
    strcat(lockname, filename);
    strcat(lockname, ".lock");
    
    // send_command TARGET COMMAND
    if(argc < 3) exit(1);
    
    // Build command
    // looks like TARGET:COMMAND
    strcat(command, argv[1]);
    strcat(command, ":");
    for(i = 2; i < argc;i++) {
        strcat(command, argv[i]);
        strcat(command, " ");
    }
    // lock the file
    if((lock = acquire(lockname)) == NULL) exit(1);

    if((fp = fopen(filename, "w")) == NULL) exit(1);
    fputs(command, fp);
    fclose(fp);
    
    // remove the .lock file and bail out
    release(lock);
    return 0;
}
