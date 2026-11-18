// comparison port of sw/benchmarks/coremark/ee_printf.c: console output only differs
// SPDX-License-Identifier: Apache-2.0

#include <stdarg.h>

#include "coremark.h"

volatile ee_u32 coremark_port_failed;

static int contains(const char *text, const char *needle) {
	if (*needle == '\0') return 1;
	for (; *text != '\0'; text++) {
		const char *left = text;
		const char *right = needle;
		while (*left == *right && *right != '\0') {
			left++;
			right++;
		}
		if (*right == '\0') return 1;
	}
	return 0;
}

static void note_format(const char *format) {
	if (contains(format, "ERROR!") ||
		contains(format, "ERROR:") ||
		contains(format, "Cannot validate") ||
		contains(format, "list_head structure too big")) {
#ifdef COREMARK_ALLOW_SHORT
		if (contains(format, "Must execute for at least 10 secs")) return;
#endif
		coremark_port_failed = 1;
	}
}

// simulation console: a byte stored here is printed by the testbench
// (spinalhdl default; rsd's serial port is 0x40002000)
#ifndef COMPARE_PUTC_ADDR
#define COMPARE_PUTC_ADDR 0x10000000u
#endif
#ifdef COMPARE_PUTC_UART
// board: orca's 16550 through the bsp (orca_uart_init runs in portable_init)
#include "orca_uart.h"
static int emit_char(char value) {
	if (value == '\n') orca_uart_putc('\r');
	orca_uart_putc(value);
	return 1;
}
#elif defined(COMPARE_ORCA_ACT)
// orca in cpu_tb act mode has no console here; the result goes to registers
static int emit_char(char value) {
	(void)value;
	return 1;
}
#elif defined(COMPARE_HTIF)
#include "htif.h"
static int emit_char(char value) {
	htif_putc(value);
	return 1;
}
#else
static int emit_char(char value) {
	*(volatile ee_u32 *)COMPARE_PUTC_ADDR = (ee_u8)value;
	return 1;
}
#endif

static int emit_unsigned(unsigned long value, unsigned base, int width, char pad) {
	static const char digits[] = "0123456789abcdef";
	char buffer[16];
	int used = 0;
	int count = 0;

	do {
		buffer[used++] = digits[value % base];
		value /= base;
	} while (value != 0u);

	while (used < width) {
		count += emit_char(pad);
		width--;
	}
	while (used > 0) count += emit_char(buffer[--used]);
	return count;
}

static int emit_signed(long value, int width, char pad) {
	unsigned long magnitude;
	int count = 0;

	if (value < 0) {
		count += emit_char('-');
		if (width > 0) width--;
		magnitude = (unsigned long)(-(value + 1)) + 1u;
	} else {
		magnitude = (unsigned long)value;
	}
	return count + emit_unsigned(magnitude, 10u, width, pad);
}

int ee_printf(const char *format, ...) {
	va_list args;
	int count = 0;

	note_format(format);
	va_start(args, format);
	while (*format != '\0') {
		int width = 0;
		int is_long = 0;
		char pad = ' ';

		if (*format != '%') {
			count += emit_char(*format++);
			continue;
		}

		format++;
		if (*format == '%') {
			count += emit_char(*format++);
			continue;
		}
		if (*format == '0') {
			pad = '0';
			format++;
		}
		while (*format >= '0' && *format <= '9') {
			width = width * 10 + (*format++ - '0');
		}
		if (*format == 'l') {
			is_long = 1;
			format++;
		}

		switch (*format++) {
		case 'd':
			count += emit_signed(is_long ? va_arg(args, long) : va_arg(args, int),
							 width, pad);
			break;
		case 'u':
			count += emit_unsigned(is_long ? va_arg(args, unsigned long) :
									 (unsigned)va_arg(args, unsigned),
							   10u, width, pad);
			break;
		case 'x':
			count += emit_unsigned(is_long ? va_arg(args, unsigned long) :
									 (unsigned)va_arg(args, unsigned),
							   16u, width, pad);
			break;
		case 's': {
			const char *value = va_arg(args, const char *);
			while (*value != '\0') count += emit_char(*value++);
			break;
		}
		case 'c':
			count += emit_char((char)va_arg(args, int));
			break;
		default:
			count += emit_char('?');
			break;
		}
	}
	va_end(args);
	return count;
}
