# Fake CR-01 card reader for openMSX, so the UPA-01 cartridge can read a
# Playcard .bin image that no emulated hardware exists for.
#
#   openmsx.exe -machine yamaha_cx5m -cart <UPA-01.rom> -script fake_cr01.tcl
#
# Set ::card to the .bin to feed and ::result to where the dump should go.
#
# ---------------------------------------------------------------------------
# The reader is memory-mapped at 0x7FFF in the cartridge's address space.
# Writes are control strobes; reads return a status byte:
#
#     bit 7  reader active   (0 = stream finished)
#     bit 6  a data bit is ready
#     bit 5  the data bit itself
#
# Cartridge code:
#   0x6892  LD A,(0x7FFF)   poll - only bit 7 is tested
#   0x68B2  LD A,(0x7FFF)   bit loop - tests bits 7, 6, then takes bit 5
#
# Both are 3-byte instructions, so we answer by setting A and stepping PC past
# them.  The cartridge writes its own 4-byte preamble (00 00 00 01) into the
# buffer before the card bytes, which is exactly the 31 zeros + 1 bit that the
# extracted .bin files are missing.
# ---------------------------------------------------------------------------

# Paths are taken relative to this script, so the folder can live anywhere.
# The original cards are Yamaha's and are not in the repository; they belong in
# "Original Playcards" beside this file.
set ::here [file dirname [file normalize [info script]]]
if {![info exists ::card]}   {
    set ::card [file join $::here {Original Playcards} playcard_17-557_christmas-1_silent_night.bin]
}
if {![info exists ::result]} { set ::result [file join $::here fake_cr01_out.txt] }

set ::out [open $::result w]
proc emit {m} { puts $::out $m; flush $::out }

# --- load the card image as a bit string -----------------------------------
set fh [open $::card rb]
fconfigure $fh -translation binary
set ::carddata [read $fh]
close $fh
binary scan $::carddata B* ::bits
set ::nbits [string length $::bits]
set ::bitpos 0
set ::consumed 0

emit "card    : $::card"
emit "bytes   : [string length $::carddata]   bits: $::nbits"

proc hexdump {addr n} {
    binary scan [debug read_block memory $addr $n] H* h
    return $h
}

# --- the fake reader --------------------------------------------------------
proc cr01_poll {} {
    # only bit 7 is examined here; do not consume a bit
    if {$::bitpos < $::nbits} { reg A 0x80 } else { reg A 0x00 }
    reg PC 0x6895
}

proc cr01_bit {} {
    if {$::bitpos >= $::nbits} {
        reg A 0x00
    } else {
        set b [string index $::bits $::bitpos]
        incr ::bitpos
        incr ::consumed
        reg A [expr {0xC0 | ($b == "1" ? 0x20 : 0x00)}]
    }
    reg PC 0x68B5
}

proc stage1 {} {
    emit "PC at boot = [format 0x%04X [reg PC]]"
    debug set_bp 0x6892 {} {cr01_poll}
    debug set_bp 0x68B2 {} {cr01_bit}
    emit "fake reader armed at 0x6892 / 0x68B2"
    keymatrixdown 6 0x20
    after time 1 {keymatrixup 6 0x20}
    after time 12 stage2
}

proc stage2 {} {
    emit "bits consumed by the cartridge: $::consumed of $::nbits"
    emit "PC now = [format 0x%04X [reg PC]]"
    emit ""
    emit "BUFFER 0xD377 (1024 bytes):"
    emit "  [hexdump 0xD377 1024]"
    emit "TABLE 0xE3AE (192 bytes):"
    emit "  [hexdump 0xE3AE 192]"
    emit "VARS: E47B=[hexdump 0xE47B 2] E481=[hexdump 0xE481 2] E48B=[hexdump 0xE48B 1]"
    emit ""
    emit "screen:"
    set base [expr {[debug read "VDP regs" 2] * 0x400}]
    for {set row 0} {$row < 24} {incr row} {
        binary scan [debug read_block VRAM [expr {$base + $row*32}] 32] cu* bytes
        set s {}
        foreach b $bytes {
            if {$b >= 32 && $b < 127} { append s [format %c $b] } else { append s " " }
        }
        set s [string trimright $s]
        if {$s ne ""} { emit [format "  %2d| %s" $row $s] }
    }
    close $::out
    exit
}

after time 6 stage1
