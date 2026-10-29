#include "orca_soc.h"
#include "orca_uart.h"

enum {
    UART_RBR_THR_DLL = 0x00,
    UART_IER_DLM     = 0x04,
    UART_FCR_IIR     = 0x08,
    UART_LCR         = 0x0c,
    UART_LSR         = 0x14,
};

#define UART_LCR_DLAB       0x80u
#define UART_LCR_8N1        0x03u
#define UART_LSR_DATA_READY 0x01u
#define UART_LSR_THR_EMPTY  0x20u
#define UART_LSR_TX_EMPTY   0x40u

static inline void uart_write(uint32_t offset, uint32_t value) {
    orca_mmio_write(ORCA_UART_BASE + offset, value);
}

static inline uint32_t uart_read(uint32_t offset) {
    return orca_mmio_read(ORCA_UART_BASE + offset);
}

void orca_uart_init(uint32_t clock_hz, uint32_t baud) {
    uint32_t divisor = clock_hz / (16u * baud);
    if (divisor == 0) divisor = 1;
    uart_write(UART_IER_DLM, 0);
    uart_write(UART_LCR, UART_LCR_DLAB);
    uart_write(UART_RBR_THR_DLL, divisor & 0xffu);
    uart_write(UART_IER_DLM, (divisor >> 8) & 0xffu);
    uart_write(UART_LCR, UART_LCR_8N1);
    uart_write(UART_FCR_IIR, 0);
}

/* the rtl's lsr flags are correct since the 2026-10-18 obi_uart_tx fork, so the
   writer polls thre like any 16550 driver instead of waiting a frame per byte. */
void orca_uart_putc(char value) {
#ifndef ORCA_UART_SIM_FAST
    while ((uart_read(UART_LSR) & UART_LSR_THR_EMPTY) == 0) { }
#endif
    uart_write(UART_RBR_THR_DLL, (uint8_t)value);
}

/* waits until the last bit has left the line (lsr.temt) */
void orca_uart_flush(void) {
#ifndef ORCA_UART_SIM_FAST
    while ((uart_read(UART_LSR) & UART_LSR_TX_EMPTY) == 0) { }
#endif
}

/* a string is on the line when this returns, so a program may finish (and the
   host stop the soc) right after its last message */
void orca_uart_puts(const char *value) {
    while (*value != '\0') {
        if (*value == '\n') orca_uart_putc('\r');
        orca_uart_putc(*value++);
    }
    orca_uart_flush();
}

int orca_uart_rx_ready(void) {
    return (uart_read(UART_LSR) & UART_LSR_DATA_READY) != 0;
}

char orca_uart_getc(void) {
    while (!orca_uart_rx_ready()) { }
    return (char)uart_read(UART_RBR_THR_DLL);
}

void orca_uart_puthex(uint32_t value) {
    static const char digits[] = "0123456789abcdef";
    orca_uart_puts("0x");
    for (int shift = 28; shift >= 0; shift -= 4)
        orca_uart_putc(digits[(value >> shift) & 0xfu]);
}
