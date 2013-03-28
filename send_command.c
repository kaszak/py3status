/*
 * send_command2.c
 * 
 * Copyright 2013 Unknown <kaszak@localhost>
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

int acquire(char* lockname) {
    int descriptor;
    if(lockname == NULL) return -1;
    
    while(1){
        descriptor = open(lockname, O_CREAT|O_EXCL|O_RDWR, S_IRWXU);
        if(errno == EEXIST) {
            errno = 0;
            usleep(50000); //0.05 second
            continue;
        }
        else {
            break;
        }
    }
    return descriptor;
}

void release(int descriptor, char* lockname) {
    
    close(descriptor);
    unlink(lockname);
}
    

int main(int argc, char **argv)
{
    int descriptor, i, len;
    char command[MAX_C] = "\0";
    char filename[MAX_C] = "\0";
    char lockname[MAX_C] = "\0";
    FILE* fp;
    
    //Construct path
    strcat(filename, "/tmp/");
    strcat(filename, getenv("USER"));
    strcat(filename, "/py3status.fifo");
    
    len = strlen(filename);
    if(len < 1) exit(1);
    strcat(lockname, filename);
    strcat(lockname, ".lock");
    
    if(argc < 3) exit(1);
    //Build command
    strcat(command, argv[1]);
    strcat(command, ":");
    for(i = 2; i < argc;i++) {
        strcat(command, argv[i]);
        strcat(command, " ");
    }
    
	descriptor = acquire(lockname);
    
    fp = fopen(filename, "w");
    if(fp == NULL) exit(1);
    fprintf(fp, "%s", command);
    fclose(fp);
    
    release(descriptor, lockname);
	return 0;
}

