# kv260 bring-up over jtag, no board os: xsdb (vivado's; xsct is disabled in 2026.1) puts the som in jtag boot mode, runs
# psu_init from the platform xsa (ps clocks, ddr, pl clock and reset), loads the
# bitstream, then serves memory accesses on stdin for scripts/board/orca_host.py --jtag.
# usage: xsdb kv260_jtag.tcl <psu_init.tcl> <bitstream.bit> [relay.elf]
# with relay.elf (sw/kv260_relay), cortex-a53 #0 copies the console uart into an ocm
# ring, so the console is read in bulk instead of one jtag access per register.
#
# protocol, one command per line, one reply line each:
#   w <addr> <value>      write a word            -> ok
#   r <addr>              read a word             -> ok <value>
#   d <file> <addr>       load a binary file      -> ok
#   u <lsr> <rbr> <max>   drain a 16550 rx fifo   -> ok <hex bytes>
#   c                     read the relay rx ring  -> ok <hex bytes>
#   t <hex bytes>         queue relay tx bytes    -> ok
#   g                     start the relay (after the pc has set up the uart) -> ok
#   f                     load the bitstream again: a clean orca, caches and ddr bridge included; ps and ddr stay up -> ok
#   q                     quit                    -> ok
# errors reply "err <message>". addresses are ps physical addresses.

set psu_init [lindex $argv 0]
set bitstream [lindex $argv 1]
set relay [expr {[llength $argv] > 2 ? [lindex $argv 2] : ""}]
# relay shared block (sw/kv260_relay/relay.c)
set hdr 0xFFFD0000
set tx_ring 0xFFFD0100
set rx_ring 0xFFFE0000
set rx_size 0x10000
set rx_r 0
set tx_w 0

proc say {line} {
	puts $line
	flush stdout
}

if {[catch {
	connect
	# alternate boot mode jtag (boot_mode_user = 0x0100), then a system reset: the
	# bootrom waits for jtag instead of starting the qspi boot firmware
	targets -set -nocase -filter {name =~ "*PSU*"}
	mwr 0xff5e0200 0x0100
	rst -system
	after 2000
	targets -set -nocase -filter {name =~ "*PSU*"}
	fpga -file $bitstream
	targets -set -nocase -filter {name =~ "*APU*"}
	source $psu_init
	psu_init
	after 500
	psu_ps_pl_isolation_removal
	after 500
	psu_ps_pl_reset_config
	catch {psu_protection}
	configparams force-mem-access 1
	if {$relay ne ""} {
		targets -set -nocase -filter {name =~ "*A53*#0"}
		rst -processor -clear-registers
		dow $relay
		con
		targets -set -nocase -filter {name =~ "*APU*"}
		set ready 0
		for {set i 0} {$i < 50} {incr i} {
			if {[mrd -force -value $hdr] == 0x52454C59} {set ready 1; break}
			after 20
		}
		if {!$ready} {error "console relay did not start on cortex-a53 #0"}
	}
} message]} {
	say "err setup: [string map {"\n" " "} $message]"
	exit 1
}
say "ready"

while {[gets stdin line] >= 0} {
	set cmd [lindex $line 0]
	if {[catch {
		switch -- $cmd {
			w {
				mwr -force [lindex $line 1] [lindex $line 2]
				say "ok"
			}
			r {
				say [format "ok 0x%08x" [mrd -force -value [lindex $line 1]]]
			}
			d {
				dow -data -force [lindex $line 1] [lindex $line 2]
				say "ok"
			}
			u {
				set lsr [lindex $line 1]
				set rbr [lindex $line 2]
				set max [lindex $line 3]
				set out ""
				while {[string length $out] < 2 * $max && ([mrd -force -value $lsr] & 1)} {
					append out [format "%02x" [expr {[mrd -force -value $rbr] & 0xff}]]
				}
				say "ok $out"
			}
			c {
				set w [mrd -force -value [expr {$hdr + 4}]]
				set n [expr {($w - $rx_r) & 0xffffffff}]
				if {$n > 4096} {set n 4096}
				set out ""
				while {$n > 0} {
					set off [expr {$rx_r & ($rx_size - 1)}]
					set chunk [expr {min($n, $rx_size - $off)}]
					foreach b [mrd -force -value -size b [expr {$rx_ring + $off}] $chunk] {
						append out [format "%02x" [expr {$b & 0xff}]]
					}
					set rx_r [expr {($rx_r + $chunk) & 0xffffffff}]
					set n [expr {$n - $chunk}]
				}
				mwr -force [expr {$hdr + 8}] $rx_r
				say "ok $out"
			}
			g {
				mwr -force [expr {$hdr + 0x20}] 1
				say "ok"
			}
			f {
				targets -set -nocase -filter {name =~ "*PSU*"}
				fpga -file $bitstream
				targets -set -nocase -filter {name =~ "*APU*"}
				after 500
				psu_ps_pl_isolation_removal
				after 500
				psu_ps_pl_reset_config
				configparams force-mem-access 1
				say "ok"
			}
			t {
				foreach {hi lo} [split [lindex $line 1] ""] {
					mwr -force -size b [expr {$tx_ring + ($tx_w & 0xff)}] [expr 0x$hi$lo]
					set tx_w [expr {($tx_w + 1) & 0xffffffff}]
				}
				mwr -force [expr {$hdr + 12}] $tx_w
				say "ok"
			}
			q {
				say "ok"
				exit 0
			}
			default {
				say "err unknown command: $cmd"
			}
		}
	} message]} {
		say "err [string map {"\n" " "} $message]"
	}
}
