#ifndef ORCA_SOC_H
#define ORCA_SOC_H

#include <stdint.h>

#define ORCA_CPU_HZ       100000000u
#define ORCA_UART_BASE    0x80001000u
#define ORCA_MTIME_BASE   0x80002000u
#define ORCA_CLINT_BASE   0x80010000u
#define ORCA_FIN_BASE     0x80000000u
#define ORCA_DMA_BASE     0x1fffc000u

static inline void orca_mmio_write(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)(uintptr_t)addr = value;
}

static inline uint32_t orca_mmio_read(uint32_t addr) {
    return *(volatile uint32_t *)(uintptr_t)addr;
}

static inline uint32_t orca_cycle(void) {
    uint32_t value;
    __asm__ volatile ("csrr %0, cycle" : "=r"(value));
    return value;
}

static inline uint32_t orca_instret(void) {
    uint32_t value;
    __asm__ volatile ("csrr %0, instret" : "=r"(value));
    return value;
}

#endif
