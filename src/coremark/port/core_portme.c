// SPDX-License-Identifier: Apache-2.0
// comparison port of sw/benchmarks/coremark/core_portme.c for the spinalhdl testbenches.
// the timed region and seeds are the same; the end of run prints raw mcycle counts and
// jumps to compare_pass or compare_fail, which the testbench watches.

#include "coremark.h"
#ifdef COMPARE_PUTC_UART
#include "orca_uart.h"
#endif

#ifndef COREMARK_CPU_HZ
#define COREMARK_CPU_HZ 100000000u
#endif

#define COREMARK_TIMER_SHIFT 6u
#define EE_TICKS_PER_SEC (COREMARK_CPU_HZ >> COREMARK_TIMER_SHIFT)

#if VALIDATION_RUN
volatile ee_s32 seed1_volatile = 0x3415;
volatile ee_s32 seed2_volatile = 0x3415;
volatile ee_s32 seed3_volatile = 0x66;
#endif

#if PERFORMANCE_RUN
volatile ee_s32 seed1_volatile = 0;
volatile ee_s32 seed2_volatile = 0;
volatile ee_s32 seed3_volatile = 0x66;
#endif

volatile ee_s32 seed4_volatile = ITERATIONS;
volatile ee_s32 seed5_volatile = 0;

ee_u32 default_num_contexts = 1;

static unsigned long long start_cycles;
static unsigned long long stop_cycles;
static ee_u32 start_instret;
static ee_u32 stop_instret;

static unsigned long long read_cycles(void) {
	ee_u32 hi_before;
	ee_u32 lo;
	ee_u32 hi_after;

	do {
		__asm__ volatile ("csrr %0, mcycleh" : "=r"(hi_before));
		__asm__ volatile ("csrr %0, mcycle" : "=r"(lo));
		__asm__ volatile ("csrr %0, mcycleh" : "=r"(hi_after));
	} while (hi_before != hi_after);
	return ((unsigned long long)hi_after << 32) | lo;
}

// retired instructions over the timed region (32-bit minstret: rsd has no minstreth)
static ee_u32 read_instret(void) {
	ee_u32 value;
	__asm__ volatile ("csrr %0, minstret" : "=r"(value));
	return value;
}

void start_time(void) {
	start_instret = read_instret();
	start_cycles = read_cycles();
}

void stop_time(void) {
	stop_cycles = read_cycles();
	stop_instret = read_instret();
}

CORE_TICKS get_time(void) {
	return (CORE_TICKS)((stop_cycles - start_cycles) >> COREMARK_TIMER_SHIFT);
}

secs_ret time_in_secs(CORE_TICKS ticks) {
	return ticks / EE_TICKS_PER_SEC;
}

void portable_init(core_portable *port, int *argc, char *argv[]) {
	(void)argc;
	(void)argv;
	port->portable_id = 1;
#ifdef COMPARE_PUTC_UART
	orca_uart_init(COREMARK_CPU_HZ, COMPARE_UART_BAUD);
#endif
}

void compare_pass(void) __attribute__((noreturn, noinline));
void compare_fail(void) __attribute__((noreturn, noinline));
void compare_pass(void) { for (;;) __asm__ volatile (""); }
void compare_fail(void) { for (;;) __asm__ volatile (""); }

void portable_fini(core_portable *port) {
	port->portable_id = 0;
	ee_printf("ORCA_COMPARE cycles=%lu instret=%lu iterations=%lu failed=%lu\n",
		(unsigned long)(stop_cycles - start_cycles),
		(unsigned long)(stop_instret - start_instret), (unsigned long)seed4_volatile,
		(unsigned long)coremark_port_failed);
#ifdef COMPARE_RETURN_AT_END
	// rsd's startup jumps to its goal pc when main returns
	return;
#endif
	if (coremark_port_failed) compare_fail();
	compare_pass();
}
