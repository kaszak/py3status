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
    int len;                   
    char* filename;
    char* lockname;
    char* username;
    FILE* fp;
    Lock* lock;
    
    filename = (char*)calloc((len = strlen(TMPDIR) + strlen(username = getenv("USER")) + strlen(FILENAME) + 1), sizeof(char));
    lockname = (char*)calloc(len + strlen(LOCK_SUFFIX), sizeof(char));
    
    // Construct path
    strcat(filename, TMPDIR);
    strcat(filename, username);
    strcat(filename, FILENAME);
    
    // Ditto, for .lock file
    strcat(lockname, filename);
    strcat(lockname, LOCK_SUFFIX);
    
    // send_command TARGET COMMAND
    if(argc < 3) exit(1);
    
    // lock the file
    if((lock = acquire(lockname)) == NULL) exit(1);

    if((fp = fopen(filename, "w")) == NULL) 
    {
        release(lock);
        exit(1);
    }

    fprintf(fp, "%s:%s", argv[1], argv[2]);

    fclose(fp);
    free(filename);
    free(lockname);
    
    // remove the .lock file and bail out
    release(lock);
    return 0;
}
