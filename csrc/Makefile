# Build the two C tools.  Tested with MSYS2 UCRT64 gcc 15.2.0 on Windows and
# with plain gcc/g++ elsewhere.
#
#     make            both tools
#     make playcard   the emulator only  (C, needs nothing but z80.c)
#     make fmlog2wav  the renderer only  (C++, needs ymfm/)
#
# On MSYS2, the compiler's own bin directory has to be on PATH or gcc exits 1
# with no diagnostics at all, which looks exactly like a broken install:
#
#     PATH="/c/msys/ucrt64/bin:$PATH" make

CC      ?= gcc
CXX     ?= g++
CFLAGS  ?= -O2 -Wall
CXXFLAGS?= -O2 -Wall -std=c++14

# Static by default, so the binaries carry no compiler runtime with them.  The
# C++ one otherwise wants libstdc++-6.dll and libgcc_s_seh-1.dll out of the
# toolchain, which is exactly the sort of thing that is missing on the machine
# you copy it to.  What is left after this is the operating system's own:
# KERNEL32 and the Universal CRT stubs on Windows, libc elsewhere.
#
#     make STATIC=            to link the usual way instead
STATIC  ?= -static

# gcc appends .exe on Windows whether or not it is asked to, so the targets
# have to carry it too, or make rebuilds everything on every run.
ifeq ($(OS),Windows_NT)
EXE := .exe
endif

all: playcard$(EXE) fmlog2wav$(EXE)

playcard$(EXE): playcard.c z80.c z80.h
	$(CC) $(CFLAGS) $(STATIC) -o $@ playcard.c z80.c

fmlog2wav$(EXE): fmlog2wav.cpp ymfm/ymfm_opm.cpp
	$(CXX) $(CXXFLAGS) $(STATIC) -I. -o $@ fmlog2wav.cpp ymfm/ymfm_opm.cpp

clean:
	rm -f playcard playcard.exe fmlog2wav fmlog2wav.exe

.PHONY: all clean
