/* ocm: code at the base, stack below the shared block at 0xfffd0000 */
ENTRY(_start)
MEMORY { OCM (rwx) : ORIGIN = 0xFFFC0000, LENGTH = 0x10000 }
SECTIONS {
    .text : { KEEP(*(.text.start)) *(.text*) *(.rodata*) } > OCM
    .data : { *(.data*) *(.bss*) *(COMMON) } > OCM
}
