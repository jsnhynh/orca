/* ORCA ACT layout: the whole test image sits in the cached DDR window at orca 0x1000_0000, in simulation and on the board. */
RAM_ORIGIN = 0x10000000;
RAM_LENGTH = 0x00200000;
TEST_BASE = 0x10000000;
NUM_HARTS = 1;
STACK_SIZE = 0x00001000;

OUTPUT_ARCH("riscv")
ENTRY(rvtest_entry_point)

MEMORY {
  ram (rwx) : ORIGIN = RAM_ORIGIN, LENGTH = RAM_LENGTH
}

PROVIDE(__stack_size = STACK_SIZE);
PROVIDE(__num_harts = NUM_HARTS);

SECTIONS {
  .text.init TEST_BASE : { *(.text.init) } > ram
  .text.rvtest . : { *(.text.rvtest) *(.text.rvtest.*) } > ram

  . = ALIGN(0x1000);
  .rodata . : { *(.rodata) *(.rodata.*) *(.srodata) *(.srodata.*) } > ram
  .data . : { *(.data) *(.data.*) *(.sdata) *(.sdata.*) } > ram
  .bss . : {
    __bss_start = .;
    *(.sbss) *(.sbss.*) *(.bss) *(.bss.*) *(COMMON)
    . = ALIGN(16);
    __bss_end = .;
  } > ram
  . = ALIGN(16);
  __stack_bottom = .;
  . += __stack_size * __num_harts;
  __stack_top = .;
  . = ALIGN(16);
  .text.rvmodel . : { *(.text.rvmodel) *(.text.rvmodel.*) *(.text) *(.text.*) } > ram
  _end = .;

  ASSERT(_end <= RAM_ORIGIN + RAM_LENGTH, "ACT ELF exceeds the board image window")
}
