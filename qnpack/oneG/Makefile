# Compiler and flags
CC = gcc
CFLAGS = -Wall -fPIC -O2
LDFLAGS = -shared

# Library name
TARGET_LIB = librepeater.so

# Source files and object files
SRCS = c_helpers.c
OBJS = $(SRCS:.c=.o)

.PHONY: all clean

all: $(TARGET_LIB)

$(TARGET_LIB): $(OBJS)
	$(CC) $(LDFLAGS) -o $@ $^

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f $(TARGET_LIB) $(OBJS)