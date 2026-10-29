# ORCA

ORCA is a two-wide out-of-order RV32IMA processor (with Zicsr and Zifencei) and an FPGA system on chip, written in SystemVerilog. It runs at 200 MHz on a Kria KV260, where it scores 1,032 CoreMark/s (5.16 CoreMark/MHz) and an Embench-IoT speed score of 2.31 per MHz, passes all 67 RISC-V architecture tests, and boots a no-MMU Linux kernel.

Documentation, results and diagrams: https://jsnhynh.github.io/orca/

This repository holds the built site (`docs/`), the draw.io diagrams (`diagrams/`), board logs and Vivado reports (`results/`), and a kit to reproduce the board runs (`src/`). The RTL is private because the source repository still holds some coursework RTL and infrastructure code that I am not allowed to make public. All rights reserved; the files may be used to build and run the kit (see `NOTICE.md`).

## Reproduce on a Kria KV260

<!-- reproduce-start -->
You need a KV260 powered and connected by its USB cable, xsdb from AMD Vivado or Vitis 2026.1, and Python 3.9 or later. Close other tools that use the board's JTAG cable. No SD card is used.

Run these from the folder you downloaded. On Windows, type `py` in place of `python3`.

```
python3 src/run.py linux
python3 src/run.py coremark
python3 src/run.py act
```

`linux` boots Linux and opens its console; log in as `root` and press ctrl-] to quit. `coremark` runs CoreMark and prints the score. `act` runs the 67 RISC-V architecture tests on the board, one bitstream load per test, and takes about 7 minutes; `--only add` runs the tests whose names contain `add`, and `--quick` loads the bitstream once, which finishes all 67 in under a minute. Each run puts the board in JTAG boot mode, runs the PS initialization, loads the bitstream, starts a console relay on the first Arm core, and writes the image into reserved DDR.

`results/linux-boot-kv260.log`, `results/coremark-kv260.log`, `results/act-kv260.log` and `results/embench-kv260.log` are recorded runs of this build. If xsdb is not found, add `--xsdb /path/to/xsdb`.

The bitstream is prebuilt because the RTL is not published (see above). The software rebuilds from `src/` with `python3 src/run.py build coremark`, `build linux` or `build relay`.
<!-- reproduce-end -->
