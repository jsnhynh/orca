# Notices

## What this repository contains

- Design documents and diagrams written for ORCA.
- A prebuilt bitstream for the Kria KV260 (`src/prebuilt/orca_kv260.bit`). It is a build of ORCA's RTL, which is not published because the source repository includes coursework code that cannot be made public.
- Prebuilt boot files, a Linux image and a CoreMark image, with the host tools and software sources needed to run and rebuild them.

## License of ORCA-authored material

Copyright (c) 2026 Jason Huynh. All rights reserved.

ORCA is a personal project and is not open source. No license is granted to use, copy, modify or redistribute the design, the documents, the diagrams, the scripts or the software written for ORCA. The one permission is to download the published files and use them to build and run the reproduction kit on your own hardware. The third-party components below keep their own licenses.

## Third-party components and their licenses

- Linux kernel 6.18.7: GPL-2.0. `src/prebuilt/Image` contains it. Its source is available from kernel.org; the configuration is `src/linux/board/orca/linux.config` and the device trees are in `src/linux/board/orca/`.
- Buildroot 2026.08, BusyBox and the other packages in the initramfs: GPL-2.0 and compatible licenses. `src/linux/` holds the Buildroot external tree, defconfig and patches used to build the image; `src/linux/build.sh` downloads Buildroot and every package source.
- uClibc-ng: LGPL-2.1.
- EEMBC CoreMark: Apache-2.0. `src/coremark/build.sh` downloads it at a pinned commit.
- RISC-V Architecture Tests (ACT4, `riscv-arch-test`): the programs in `src/prebuilt/act/` are generated from this suite, which is licensed under Apache-2.0 and BSD-3-Clause. `src/act/` holds the board link script and halt macros that produced them.
- PULP Platform IP (AXI, common cells, APB and OBI peripherals) inside the bitstream: Solderpad Hardware License v0.51. The upstream license files accompany those repositories.
- AMD IP inside the bitstream (Zynq UltraScale+ processing system wrapper and interconnect) and `psu_init.tcl`, which Vivado generates for the K26 module: subject to AMD's license terms.

## Written offer for GPL source

The corresponding source for the GPL components in `src/prebuilt/Image` is obtained by running `src/linux/build.sh`, which downloads it from the upstream locations named in the Buildroot defconfig. If those locations are unavailable, open an issue in this repository and the source archive will be provided for three years from the date of publication.
