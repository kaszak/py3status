#pragma once
#include <limits.h>

typedef struct Lock 
{
    int descriptor;
    char lockpath[PATH_MAX];
} Lock;

Lock* acquire(char* lockname);
void release(Lock*);

