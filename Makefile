CC=gcc
OBJS=lock.o send_command.o
PROG=send_command
CFLAGS=-Wall -Os
.PHONY= all clean clean_all

all: $(PROG)

$(PROG): $(OBJS)
	$(CC) $(CFLAGS) $(OBJS) -o $@
	
$(OBJS): %.o: %.c
	$(CC) -c $(CFLAGS) $< -o $@

clean:
	rm $(OBJS)

clean_all: clean
	rm $(PROG)
