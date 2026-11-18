    # arm entry for the console relay: stack near the top of the arm on-chip memory (ocm), call main, then spin
    .section .text.start
    .global _start
_start:
    ldr x0, =0xFFFCFF00
    mov sp, x0
    bl main
1:  b 1b
