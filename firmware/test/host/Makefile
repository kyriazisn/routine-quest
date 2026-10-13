CC      ?= cc
CFLAGS  ?= -std=c11 -O1 -g -Wall -Wextra -Werror -Wshadow -Wconversion -fsanitize=address,undefined
SRC_DIR := ../../main

test: test_quest_engine
	./test_quest_engine

test_quest_engine: test_quest_engine.c $(SRC_DIR)/quest_engine.c $(SRC_DIR)/quest_engine.h
	$(CC) $(CFLAGS) -I$(SRC_DIR) -o $@ test_quest_engine.c $(SRC_DIR)/quest_engine.c

clean:
	rm -f test_quest_engine

.PHONY: test clean
