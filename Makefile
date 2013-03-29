CC=gcc
OBJS=lock.o send_command.o
CFLAGS=-Wall -O2
.PHONY= all clean clean_all

all: send_command

send_command: $(OBJS)
	$(CC) $(CFLAGS) $(OBJS) -o $@
	
$(OBJS): %.o: %.c
	$(CC) -c $(CFLAGS) $< -o $@

clean:
	rm $(OBJS)

clean_all: clean
	rm send_command
