// rvmodel macros for ORCA: the same images run in simulation and on the KV260 board
// SPDX-License-Identifier: Apache-2.0

#ifndef ORCA_RVMODEL_MACROS_H
#define ORCA_RVMODEL_MACROS_H

#define RVMODEL_DATA_SECTION
#define STANDARD_SM_SUPPORTED

// the verdict goes to x31 and to the last word of the uncached dma region (orca 0x1fff_fffc, host
// aperture offset 0x3ffc). the board host polls the mailbox and the simulation bench reads x31. the
// host clears the mailbox before every launch, so the first nonzero value is this test's verdict.
#define ORCA_ACT_MAILBOX 0x1ffffffc
#define ORCA_ACT_PASS 0x600dac70
#define ORCA_ACT_FAIL 0xbadac701

// before the verdict the test stores its own cycle and retired-instruction counts (low 32 bits, counted from reset,
// so the boot stub is included) just below the mailbox, at 0x1ffffff0 and 0x1ffffff4. the simulation reads them from
// x28 and x29, the board host from memory, and scripts/act/compare_perf.py checks one against the other.
#define ORCA_ACT_PERF \
  csrr x28, mcycle ; \
  csrr x29, minstret ; \
  li x30, ORCA_ACT_MAILBOX ; \
  sw x28, -12(x30) ; \
  sw x29, -8(x30)

#define RVMODEL_HALT_PASS \
  ORCA_ACT_PERF ; \
  li x31, ORCA_ACT_PASS ; \
  sw x31, 0(x30) ; \
1: j 1b

#define RVMODEL_HALT_FAIL \
  ORCA_ACT_PERF ; \
  li x31, ORCA_ACT_FAIL ; \
  sw x31, 0(x30) ; \
1: j 1b

#define RVMODEL_IO_INIT(_R1, _R2, _R3)
#define RVMODEL_IO_WRITE_STR(_R1, _R2, _R3, _STR_PTR)

#define RVMODEL_MTIMECMP_ADDRESS 0x80002000
#define RVMODEL_MTIME_ADDRESS 0x80002008
#define RVMODEL_MSIP_ADDRESS 0x80002010
#define RVMODEL_MEXT_ADDRESS 0x80002014

#define RVMODEL_MAX_CYCLES_PER_TIMER_TICK 1
// loop iterations (two instructions each) a test idles after raising an interrupt through the clint. the raising
// store is uncached and crosses the mmio bridge's register slice each way, while the idle loop runs without
// bubbles from the l0: 10 let the interrupt arrive after the loop on the board (InterruptsSm at 192 and 200 MHz)
#define RVMODEL_INTERRUPT_LATENCY 100
// ticks between a test arming the timer and expecting it: a test may clear mtimecmp in between with uncached
// stores (about 20 cycles each, plus the clint path), so 100 left only a few ticks of margin
#define RVMODEL_TIMER_INT_SOON_DELAY 1000

#define RVMODEL_SET_MEXT_INT(_R1, _R2) \
  li _R1, 1 ; \
  li _R2, RVMODEL_MEXT_ADDRESS ; \
  sw _R1, 0(_R2)

#define RVMODEL_CLR_MEXT_INT(_R1, _R2) \
  li _R2, RVMODEL_MEXT_ADDRESS ; \
  sw zero, 0(_R2)

#define RVMODEL_SET_MSW_INT(_R1, _R2) \
  li _R1, 1 ; \
  li _R2, RVMODEL_MSIP_ADDRESS ; \
  sw _R1, 0(_R2)

#define RVMODEL_CLR_MSW_INT(_R1, _R2) \
  li _R2, RVMODEL_MSIP_ADDRESS ; \
  sw zero, 0(_R2)
#define RVMODEL_SET_SEXT_INT(_R1, _R2)
#define RVMODEL_CLR_SEXT_INT(_R1, _R2)
#define RVMODEL_SET_SSW_INT(_R1, _R2)
#define RVMODEL_CLR_SSW_INT(_R1, _R2)

#endif
