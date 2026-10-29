# ORCA no-MMU Linux

A Buildroot external tree for a machine-mode, no-MMU Linux on ORCA (RV32IMA, Zicsr, Zifencei; no compressed instructions, no FPU), with a BusyBox initramfs and ORCA's 16550 UART as the console.

| File | Contents |
|---|---|
| `configs/orca_rv32_nommu_defconfig` | Buildroot 2026.08 configuration: RV32IMA, ilp32, uClibc-ng with FLAT binaries, kernel 6.18.7, initramfs |
| `board/orca/linux.config` | kernel configuration: no MMU, machine mode, no SMP, 8250 console, CLINT timer, initramfs |
| `board/orca/orca-kv260-200-jtag.dts` | device tree for the published bitstream: 200 MHz, 256 MiB DDR window at `0x1000_0000`, 115200 baud |
| `board/orca/orca-kv260-150-jtag.dts` | the same for a 150 MHz bitstream |
| `patches/buildroot/` | one patch to Buildroot (uClibc without the F extension is soft float) |
| `build.sh` | downloads Buildroot, applies the patch and builds |

## Build

```sh
./build.sh
```

The kernel image with its built-in initramfs lands in `build/out/images/Image`, and the device trees in the same folder. The build compiles the toolchain, kernel, BusyBox and `dtc`.

| Host requirement | Why |
|---|---|
| Linux host, about 15 GB of free disk | toolchain and kernel build |
| `build-essential`, `cpio`, `unzip`, `rsync`, `bc`, `wget`, `python3` | Buildroot prerequisites |
| GNU coreutils | Buildroot rejects other `install` implementations |

## Facts the configuration relies on

| Fact | Consequence |
|---|---|
| A no-MMU kernel selects `RELOCATABLE` unless `PHYS_RAM_BASE_FIXED` is set | the kernel runs from ORCA's RAM at `0x1000_0000`, and `PAGE_OFFSET` is the device tree's RAM base |
| Machine-mode entry code rereads `mhartid` and writes PMP registers under a temporary trap handler | ORCA's lack of PMP is tolerated |
| The device tree address arrives in `a1` | the loader sets it before jumping to the kernel |
| The UART is polled | the tree has no interrupt controller and the UART node has no interrupt |
