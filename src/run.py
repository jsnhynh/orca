#!/usr/bin/env python3
"""Run ORCA on a Kria KV260 over USB JTAG.

    python3 run.py linux      boot Linux and open its console
    python3 run.py coremark   run CoreMark and print the score
    python3 run.py act        run the RISC-V architecture tests on the board and print a verdict per test
                              (add --quick to load the bitstream once instead of before every test)
    python3 run.py build coremark | relay | linux    rebuild one image from src/

Add --xsdb PATH when xsdb is not found automatically. xsdb comes with AMD Vivado and Vitis.
"""
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PREBUILT = HERE / "prebuilt"
HOST = HERE / "host" / "orca_host.py"
CORE_HZ = "149998505"
SOURCE = HERE
COMMON = ["--core-hz", CORE_HZ, "--baud", "115200", "--ddr-phys", "0x70000000"]


def find_xsdb(explicit):
    """the xsdb command to use: an explicit path, the environment, PATH, then common install folders."""
    if explicit:
        return explicit
    if os.environ.get("XSDB"):
        return os.environ["XSDB"]
    for name in ("xsdb", "xsdb.bat"):
        found = shutil.which(name)
        if found:
            return found
    patterns = []
    for root in (os.environ.get("XILINX_VIVADO"), os.environ.get("XILINX_VITIS")):
        if root:
            patterns += [f"{root}/bin/xsdb", f"{root}/bin/xsdb.bat"]
    patterns += [
        "C:/Xilinx/*/*/bin/xsdb.bat", "C:/AMDDesignTools/*/*/bin/xsdb.bat",
        "/tools/Xilinx/*/*/bin/xsdb", "/opt/Xilinx/*/*/bin/xsdb",
        str(Path.home() / "Xilinx/*/*/bin/xsdb"),
        "/mnt/c/Xilinx/*/*/bin/xsdb.bat", "/mnt/c/AMDDesignTools/*/*/bin/xsdb.bat",
    ]
    candidates = []
    for pattern in patterns:
        for found in glob.glob(pattern):
            version = re.search(r"(\d{4})\.(\d)", found)
            candidates.append(((int(version.group(1)), int(version.group(2))) if version else (0, 0), found))
    if candidates:
        found = max(candidates)[1]
        if found.startswith("/mnt/c/"):
            found = "C:/" + found[len("/mnt/c/"):]
        return found
    return None


def host_command(xsdb, extra, relay=True):
    return [sys.executable, "-u", str(HOST), "--jtag", "--xsdb", xsdb,
            *(["--jtag-relay", str(PREBUILT / "relay.elf")] if relay else []),
            "--psu-init", str(PREBUILT / "psu_init.tcl"),
            "--bitstream", str(PREBUILT / "orca_kv260.bit"), *COMMON, *extra]


def find_tool(names, patterns=()):
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for pattern in patterns:
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[-1]
    return None


def find_riscv_gcc():
    gcc = os.environ.get("RISCV_CC") or find_tool(
        ["riscv64-unknown-elf-gcc", "riscv32-unknown-elf-gcc", "riscv-none-elf-gcc", "riscv64-elf-gcc"])
    return gcc, (gcc[:-3] + "objcopy") if gcc else None


def find_aarch64_gcc(xsdb):
    if os.environ.get("AARCH64_GCC"):
        return os.environ["AARCH64_GCC"]
    found = find_tool(["aarch64-none-elf-gcc"])
    if found or not xsdb:
        return found
    root = Path(xsdb.replace("C:/", "/mnt/c/")).parent.parent.parent  # <install>/Vivado/<version>/bin -> install
    patterns = [str(root.parent / "gnu/aarch64/*/aarch64-none/bin/aarch64-none-elf-gcc*"),
                str(root / "gnu/aarch64/*/aarch64-none/bin/aarch64-none-elf-gcc*")]
    return find_tool([], patterns)


def build(target, xsdb):
    env = dict(os.environ)
    if target == "coremark":
        gcc, objcopy = find_riscv_gcc()
        if not gcc:
            print("no RISC-V GCC found. Install gcc-riscv64-unknown-elf or set RISCV_CC.", file=sys.stderr)
            return 2
        env.update(RISCV_CC=gcc, RISCV_OBJCOPY=objcopy)
    elif target == "relay":
        gcc = find_aarch64_gcc(xsdb)
        if not gcc:
            print("no aarch64 bare-metal GCC found. Vitis installs one; set AARCH64_GCC to it.", file=sys.stderr)
            return 2
        env["AARCH64_GCC"] = gcc
    return subprocess.call(["bash", str(SOURCE / target / "build.sh")], env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("linux", "coremark", "act", "build"))
    parser.add_argument("target", nargs="?", choices=("coremark", "relay", "linux"), help="what to rebuild (with build)")
    parser.add_argument("--only", help="with act: run only the tests whose name contains this text")
    parser.add_argument("--quick", action="store_true", help="with act: load the bitstream once, not before every test")
    parser.add_argument("--xsdb", help="path to xsdb (found automatically when it is on PATH or in a standard install folder)")
    args = parser.parse_args()
    xsdb = find_xsdb(args.xsdb)
    if args.command == "build":
        if not args.target:
            parser.error("build needs a target: coremark, relay or linux")
        return build(args.target, xsdb)
    if xsdb is None:
        print("xsdb was not found. Install AMD Vivado or Vitis 2026.1 (xsdb is included), "
              "or pass --xsdb /path/to/xsdb.", file=sys.stderr)
        return 2
    if args.command == "linux":
        extra = ["--linux-dtb", str(PREBUILT / "orca-kv260-150-jtag.dtb"), str(PREBUILT / "Image")]
        print("Booting Linux. Log in as root. Press ctrl-] to quit.")
    elif args.command == "act":
        extra = ["--act-dir", str(PREBUILT / "act"), *(["--act-only", args.only] if args.only else []),
                 *(["--act-no-reload"] if args.quick else [])]
        print("Running the architecture tests. " + ("The bitstream loads once; this takes under a minute." if args.quick else "Each test loads a fresh bitstream, so all 67 take about 7 minutes."), flush=True)
        return subprocess.call(host_command(xsdb, extra, relay=False))
    else:
        extra = ["--console", "--ddr-entry", "--polls", "2000000", str(PREBUILT / "coremark_kv260.bin")]
        print("Running CoreMark. It takes about 11 seconds after board setup.")
    return subprocess.call(host_command(xsdb, extra))


if __name__ == "__main__":
    sys.exit(main())
