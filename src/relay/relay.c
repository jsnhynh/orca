/* kv260 jtag console relay on cortex-a53 #0 (bare metal, mmu off, so every
 * access below is device memory and reaches ocm/pl in order).
 * copies orca's host-side 16550 rx fifo into an ocm ring the pc reads in bulk
 * over jtag, and sends bytes the pc queues in a small tx ring. */
#include <stdint.h>

#define HOST_UART 0xA4014000u            /* host aperture 0xa400_0000 + 0x1_4000 */
#define UART_RBR_THR (HOST_UART + 0x00u)
#define UART_LSR     (HOST_UART + 0x14u)
#define LSR_DR   0x01u
#define LSR_THRE 0x20u

/* shared block: header words, then the rings (sizes are powers of two) */
#define HDR      ((volatile uint32_t *)0xFFFD0000u)
#define TX_RING  ((volatile uint8_t *)0xFFFD0100u)
#define TX_MASK  0xFFu
#define RX_RING  ((volatile uint8_t *)0xFFFE0000u)
#define RX_SIZE  0x10000u
#define RX_MASK  (RX_SIZE - 1u)
enum { MAGIC, RX_W, RX_R, TX_W, TX_R, DROPPED, LOOPS, LAST_LSR, GO };

static inline uint32_t rd(uint32_t a) { return *(volatile uint32_t *)(uintptr_t)a; }
static inline void wr(uint32_t a, uint32_t v) { *(volatile uint32_t *)(uintptr_t)a = v; }

int main(void) {
    HDR[RX_W] = 0; HDR[RX_R] = 0; HDR[TX_W] = 0; HDR[TX_R] = 0; HDR[DROPPED] = 0; HDR[LOOPS] = 0; HDR[GO] = 0;
    HDR[MAGIC] = 0x52454C59u; /* "RELY": ready */
    /* the pc programs the uart first: a read here while it holds the divisor
     * latch (lcr.dlab) never completes and would hang this core */
    while (HDR[GO] == 0u) { }
    for (;;) {
        HDR[LOOPS] = HDR[LOOPS] + 1u;
        uint32_t lsr = rd(UART_LSR);
        HDR[LAST_LSR] = lsr;
        while (lsr & LSR_DR) {
            uint32_t w = HDR[RX_W];
            uint8_t c = (uint8_t)rd(UART_RBR_THR);
            if (w - HDR[RX_R] < RX_SIZE) {
                RX_RING[w & RX_MASK] = c;
                HDR[RX_W] = w + 1u;
            } else {
                HDR[DROPPED] = HDR[DROPPED] + 1u;
            }
            lsr = rd(UART_LSR);
        }
        if (lsr & LSR_THRE) {
            for (int n = 0; n < 16 && HDR[TX_R] != HDR[TX_W]; n++) {
                uint32_t r = HDR[TX_R];
                wr(UART_RBR_THR, TX_RING[r & TX_MASK]);
                HDR[TX_R] = r + 1u;
            }
        }
    }
}
