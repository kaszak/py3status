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

#define MAX_C 200

int acquire(char* lockname) 
{
    int descriptor;
    if(lockname == NULL) return -1;
    
    // Gonna grind until file is succesfully created, which results in
    // a lock. Necessary, because rapid execution of this gizmo can go
    // haywire, leave zombies. Or not.
    // usleep to not waste cpu
    while(1){
        descriptor = open(lockname, O_CREAT|O_EXCL|O_RDWR, S_IRWXU);
        if(errno == EEXIST) {
            errno = 0; // errno does not reset itself, good
            usleep(50000); //0.05 second
            continue;
        }
        else {
            break;
        }
    }
    return descriptor;
}

void release(int descriptor, char* lockname) 
{
    close(descriptor);
    unlink(lockname);
}
    
int main(int argc, char **argv)
{
    int descriptor, i;
    char command[MAX_C] = "\0"; // strcat sometimes resulted with
    char filename[MAX_C] = "\0";// garbage without this initialization.
    char lockname[MAX_C] = "\0";
    FILE* fp;
    
    // Construct path
    strcat(filename, "/tmp/");
    strcat(filename, getenv("USER"));
    strcat(filename, "/py3status.fifo");
    
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
	descriptor = acquire(lockname);
    if(descriptor == -1) exit(1);
    
    fp = fopen(filename, "w");
    if(fp == NULL) exit(1);
    fprintf(fp, "%s", command);
    fclose(fp);
    
    // remove the .lock file and bail out
    release(descriptor, lockname);
	return 0;
}

