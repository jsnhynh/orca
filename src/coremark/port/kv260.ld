/* board run: orca's cached ddr window (orca 0x1000_0000, loaded over jtag); the boot
 * stub calls _start, which returns to it when main is done */
OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { DDR (rwx) : ORIGIN = 0x10000000, LENGTH = 1M }
SECTIONS {
    .text : ALIGN(4) { KEEP(*(.text.start)) *(.text .text.*) } > DDR
    .rodata : ALIGN(4) { *(.rodata .rodata.*) } > DDR
    .data : ALIGN(4) { *(.sdata .sdata.*) *(.data .data.*) } > DDR
    .bss (NOLOAD) : ALIGN(4) {
        __bss_start = .; *(.sbss .sbss.*) *(.bss .bss.*) *(COMMON); __bss_end = .;
    } > DDR
    . = ALIGN(16);
    __stack_top = ORIGIN(DDR) + LENGTH(DDR);
    /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) *(.riscv.attributes) }
}
