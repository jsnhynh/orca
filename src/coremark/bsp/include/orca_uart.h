#ifndef ORCA_UART_H
#define ORCA_UART_H

#include <stdint.h>

void orca_uart_init(uint32_t clock_hz, uint32_t baud);
void orca_uart_putc(char value);
void orca_uart_puts(const char *value);
void orca_uart_flush(void);
int orca_uart_rx_ready(void);
char orca_uart_getc(void);
void orca_uart_puthex(uint32_t value);

#endif
