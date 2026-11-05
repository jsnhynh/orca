# ORCA

ORCA is a two-wide out-of-order RV32IMA processor and FPGA system on chip, written in SystemVerilog. It runs at 200 MHz on a Kria KV260, scores 1,032 CoreMark/s, and boots no-MMU Linux.

**Everything is on the site: https://jsnhynh.github.io/orca/**

- [Results](https://jsnhynh.github.io/orca/results.html): benchmarks, timing, area, the comparison with other cores and the larger design decisions
- [Microarchitecture](https://jsnhynh.github.io/orca/uarch/core/index.html): the core, memory and SoC
- [Building](https://jsnhynh.github.io/orca/building.html): running the kit on your own KV260

## This repository

| Folder | Contents |
|---|---|
| `docs/` | the built site |
| `diagrams/` | draw.io and SVG diagrams |
| `results/` | board logs, Vivado reports for the full SoC, and the ASAP7 estimate's timing and area reports |
| `src/` | the KV260 kit: `run.py`, the prebuilt bitstream and images, and the software sources |

Quick start, with a KV260 on USB and `xsdb` installed:

```
python3 src/run.py linux
```

The RTL is private, because the source repository still holds coursework RTL and infrastructure I'm not allowed to publish. All rights reserved; the files may be used to build and run the kit (see `NOTICE.md`).
