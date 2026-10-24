#!/bin/bash
# build the CoreMark image that runs on ORCA on the KV260 (linked into the cached DDR window at
# orca address 0x10000000, loaded over JTAG, prints through ORCA's UART).
# usage: ./build.sh [iterations] [core_hz] [baud]       default 7000 iterations, 149998505 Hz, 115200 baud
# needs a RISC-V GCC (rv32im, ilp32) on PATH: RISCV_CC (default riscv64-unknown-elf-gcc) and
# RISCV_OBJCOPY; the published binary was built with GCC 14.2.0 (riscv64-unknown-elf-gcc from
# the Ubuntu gcc-riscv64-unknown-elf package). output: out/coremark_kv260.bin
set -eu
here=$(cd "$(dirname "$0")" && pwd)
iters=${1:-7000}; hz=${2:-149998505}; baud=${3:-115200}
cc=${RISCV_CC:-riscv64-unknown-elf-gcc}
objcopy=${RISCV_OBJCOPY:-riscv64-unknown-elf-objcopy}
commit=b56889a7bd9d5624fbeff2a73ba69878e6a9c146        # EEMBC CoreMark v1.01 + 74 commits
cm=$here/coremark
if [ ! -d "$cm" ]; then
	git clone https://github.com/eembc/coremark.git "$cm"
	git -C "$cm" checkout "$commit"
fi
out=$here/out
mkdir -p "$out"
flags="-O3 -march=rv32im_zicsr_zifencei -mabi=ilp32 -ffreestanding -nostdlib -nostartfiles \
 -msmall-data-limit=0 -fdata-sections -ffunction-sections -fno-builtin -fno-tree-loop-distribute-patterns"
srcs=("$cm/core_list_join.c" "$cm/core_main.c" "$cm/core_matrix.c" "$cm/core_state.c" "$cm/core_util.c"
	"$here/port/core_portme.c" "$here/port/ee_printf.c" "$here/bsp/uart.c" "$here/port/payload_crt0.S")
"$cc" $flags -Wall -Wextra -I "$cm" -I "$here/port" -I "$here/bsp/include" \
	-DTOTAL_DATA_SIZE=2000 -DITERATIONS="$iters" -DPERFORMANCE_RUN=1 -DFLAGS_STR="\"$flags\"" \
	-DCOREMARK_CPU_HZ="${hz}u" -DCOMPARE_PUTC_UART -DCOMPARE_UART_BAUD="${baud}u" -DCOMPARE_RETURN_AT_END \
	"${srcs[@]}" -Wl,--gc-sections -Wl,-T,"$here/port/kv260.ld" -lgcc -o "$out/coremark_kv260.elf"
"$objcopy" -O binary "$out/coremark_kv260.elf" "$out/coremark_kv260.bin"
sha256sum "$out/coremark_kv260.bin"
