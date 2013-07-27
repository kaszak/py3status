#pragma once
#include <limits.h>

#define DELAY 50000 //0.05 second

typedef struct Lock 
{
    int descriptor;
    char lockpath[PATH_MAX];
} Lock;

Lock* acquire(char* lockname);
void release(Lock*);

