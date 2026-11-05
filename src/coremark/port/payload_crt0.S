    .section .text.start
    .globl _start
_start:
    /* the boot stub keeps its csr base in t0 across this call, so keep ra and t0
     * on the payload stack and give them back on return */
    la sp, __stack_top
    addi sp, sp, -16
    sw ra, 12(sp)
    sw t0, 8(sp)
    la t0, __bss_start
    la t1, __bss_end
    sub t2, t1, t0
1:
    beqz t2, 2f
    sw zero, 0(t0)
    addi t0, t0, 4
    addi t2, t2, -4
    j 1b
2:
    call main
    lw t0, 8(sp)
    lw ra, 12(sp)
    addi sp, sp, 16
    ret
