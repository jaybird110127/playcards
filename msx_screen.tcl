# Dump the MSX screen as text, headlessly, to a file.
#
#   openmsx.exe -machine yamaha_cx5m -cart <cart> -script msx_screen.tcl
#
# Set ::secs to how many emulated seconds to wait before dumping, and
# ::outfile to where the text should go.  Both can be overridden by
# defining them before this script runs.

if {![info exists ::outfile]} {
    set ::outfile [file join [file dirname [file normalize [info script]]] msx_screen.txt]
}
if {![info exists ::secs]}    { set ::secs 10 }

set ::out [open $::outfile w]
proc emit {msg} { puts $::out $msg; flush $::out }

proc vram {addr n} {
    set d [debug read_block VRAM $addr $n]
    binary scan $d cu* bytes
    return $bytes
}

# MSX character codes -> printable ASCII, with graphics chars shown as '.'
proc torow {bytes} {
    set s {}
    foreach b $bytes {
        if {$b >= 32 && $b < 127} { append s [format %c $b] } else { append s " " }
    }
    return [string trimright $s]
}

proc dumpscreen {} {
    if {[catch {
        # VDP register 0/1 tell us the screen mode; name table base is in reg 2
        set r0 [debug read "VDP regs" 0]
        set r1 [debug read "VDP regs" 1]
        set r2 [debug read "VDP regs" 2]
        set base [expr {$r2 * 0x400}]
        set m1 [expr {($r1 >> 4) & 1}]
        set m2 [expr {($r1 >> 3) & 1}]
        set m3 [expr {($r0 >> 1) & 1}]
        if {$m1} { set cols 40 } else { set cols 32 }
        emit "screen mode bits M1=$m1 M2=$m2 M3=$m3  -> $cols columns"
        emit "name table base = [format 0x%04X $base]"
        emit "PC = [format 0x%04X [reg PC]]"
        emit "----- screen -----"
        for {set row 0} {$row < 24} {incr row} {
            set line [torow [vram [expr {$base + $row * $cols}] $cols]]
            emit [format "%2d| %s" $row $line]
        }
        emit "------------------"
    } err]} {
        emit "ERROR: $err"
    }
    close $::out
    exit
}

after time $::secs dumpscreen
