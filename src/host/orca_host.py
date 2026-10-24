#!/usr/bin/env python3
"""load and run one ORCA payload through the host aperture (uio, /dev/mem, or jtag)."""

import argparse
import asyncio
import csv
import ctypes
import functools
import math
import mmap
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

APERTURE_SIZE = 0x20000
DMA_BASE = 0x00000
# the dma region sits at the top of the ddr window; aperture offset 0 is its first byte
DMA_CPU_BASE = 0x1FFFC000
DMA_SIZE = 0x04000
MMIO_BASE = 0x10000
SOC_CSRS = MMIO_BASE + 0x3000

CONTROL = SOC_CSRS + 0x00
STATUS = SOC_CSRS + 0x04
BOOT_ENTRY = SOC_CSRS + 0x08
BOOT_ARG0 = SOC_CSRS + 0x0C
RUN_ID = SOC_CSRS + 0x10
TRAP_PC = SOC_CSRS + 0x20
TRAP_CAUSE = SOC_CSRS + 0x24
TRAP_TVAL = SOC_CSRS + 0x28
CYCLE_LO = SOC_CSRS + 0x2C
INSTRET_LO = SOC_CSRS + 0x30

PAYLOAD_OFFSET = 0x0100
PAYLOAD_ADDR = DMA_CPU_BASE + PAYLOAD_OFFSET
PAYLOAD_LIMIT = 0x2000
DONE = DMA_BASE + 0x3FF8
MAILBOX = DMA_BASE + 0x3FFC
# an architecture test's own cycle and retired-instruction counts, stored just below the mailbox
ACT_CYCLES = MAILBOX - 12
ACT_INSTRET = MAILBOX - 8
# an embench image's return code, then the cycles and retired instructions of its timed region
# (scripts/compare/embench/boardsupport.c)
EMBENCH_RESULT = DMA_BASE + 0x800
# host end of the on-chip console null modem: a 16550 at orca 0x8000_4000 whose
# serial lines cross to orca's uart
HOST_UART = MMIO_BASE + 0x4000
UART_RBR_THR = 0x00
UART_IER_DLM = 0x04
UART_FCR = 0x08
UART_LCR = 0x0C
UART_LSR = 0x14
UART_LSR_DATA_READY = 0x01
UART_LSR_THR_EMPTY = 0x20
UART_FIFO_DEPTH = 16
# linux launch: the kernel image sits at the start of orca's cached ddr window
# (orca 0x1000_0000, ps physical --ddr-phys) and the dtb near its end. the boot
# stub calls the payload with a0 = arg0, so this shim moves the dtb address to
# a1 and jumps to the image (mv a1,a0; li a0,0; lui t0,0x10000; fence.i; jr t0).
LINUX_RAM_BASE = 0x1000_0000
LINUX_DTB_OFFSET = 0x03F0_0000
LINUX_SHIM = bytes.fromhex("93050500" "13050000" "b7020010" "0f100000" "67800200")
# architecture-test verdict words written by the board halt macros (sim/act/orca-rv32ima-zicsr-zifencei/rvmodel_macros.h)
ACT_PASS = 0x600DAC70
ACT_FAIL = 0xBADAC701
CPU_RUN = 1
CPU_STOP = 2
CPU_STOPPED = 1
CPU_RUNNING = 2


class HostError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunResult:
    run_id: int
    mailbox: int
    status: int
    trap_pc: int
    trap_cause: int
    trap_tval: int
    cycles: int
    instructions: int


class HostConsole:
    """host end of orca's console: polls the host-side 16550 and relays bytes.

    service() drains received bytes and, when the transmit fifo is empty, sends up
    to a fifo of queued input, so it fits in a poll loop. script entries
    (trigger, reply) queue reply once newly received text ends with trigger, or
    after stall seconds without any received byte (typed-ahead input just waits in
    the tty, so a late send is harmless).
    """

    def __init__(self, transport, divisor: int, script=(), echo=None, stall: float = 0.0,
                 delay: float = 0.0, key_delay: float = 0.0):
        if not 1 < divisor < 0x10000:
            raise HostError("console divisor must be 2..65535")
        self.transport = transport
        self.divisor = divisor
        self.received = bytearray()
        self.pending = bytearray()
        self.script = list(script)
        self.scripted = bool(self.script)
        self.stall = stall
        self.delay = delay
        self.held = b""
        self.release_at = 0.0
        self.key_delay = key_delay
        self.typing = b""
        self.next_key = 0.0
        self.matched = 0
        self.last_rx = time.monotonic()
        self.echo = echo

    @property
    def script_done(self) -> bool:
        return self.scripted and not self.script and not self.held and not self.typing

    def _reply(self) -> None:
        # a scripted reply goes out delay seconds after its trigger, so a viewer can read
        self.matched = len(self.received)
        self.last_rx = time.monotonic()
        reply = self.script.pop(0)[1]
        if self.delay or self.key_delay:
            self.held = reply
            self.release_at = time.monotonic() + self.delay
        else:
            self.pending += reply

    async def init(self) -> None:
        base = HOST_UART
        await self.transport.write32(base + UART_IER_DLM, 0)
        await self.transport.write32(base + UART_LCR, 0x80)
        await self.transport.write32(base + UART_RBR_THR, self.divisor & 0xFF)
        await self.transport.write32(base + UART_IER_DLM, (self.divisor >> 8) & 0xFF)
        await self.transport.write32(base + UART_LCR, 0x03)
        await self.transport.write32(base + UART_FCR, 0x07)
        if getattr(self.transport, "relay", False):
            await self.transport.relay_go()

    def send(self, data: bytes) -> None:
        self.pending += data

    def _received(self, byte: int) -> None:
        self.received.append(byte)
        self.last_rx = time.monotonic()
        if self.echo is not None:
            self.echo(bytes([byte]))
        # a trigger must end in text that arrived after the previous match
        if self.script and not self.held and not self.typing and len(self.received) - self.matched >= len(self.script[0][0]) \
                and self.received.endswith(self.script[0][0]):
            self._reply()

    async def service(self) -> None:
        now = time.monotonic()
        if self.held and now >= self.release_at:
            if self.key_delay:
                self.typing, self.held = self.held, b""
            else:
                self.pending += self.held
                self.held = b""
        if self.typing and now >= self.next_key:
            # one key at a time, so the command appears to be typed
            self.pending += self.typing[:1]
            self.typing = self.typing[1:]
            self.next_key = now + self.key_delay
        elif self.stall and self.matched and self.script and not self.held and not self.typing \
                and time.monotonic() - self.last_rx > self.stall:
            self._reply()
        if getattr(self.transport, "relay", False):
            # an arm-side relay owns the uart registers; use its rings only
            for byte in await self.transport.relay_read():
                self._received(byte)
            if self.pending:
                await self.transport.relay_send(bytes(self.pending))
                self.pending.clear()
            return
        drain = getattr(self.transport, "drain_uart", None)
        if drain is not None:
            # one round trip for the whole rx fifo (jtag), then the usual path
            for byte in await drain(HOST_UART + UART_LSR, HOST_UART + UART_RBR_THR, 64):
                self._received(byte)
        lsr = await self.transport.read32(HOST_UART + UART_LSR)
        while lsr & UART_LSR_DATA_READY:
            self._received((await self.transport.read32(HOST_UART + UART_RBR_THR)) & 0xFF)
            lsr = await self.transport.read32(HOST_UART + UART_LSR)
        if self.pending and lsr & UART_LSR_THR_EMPTY:
            chunk = self.pending[:UART_FIFO_DEPTH]
            del self.pending[:UART_FIFO_DEPTH]
            for byte in chunk:
                await self.transport.write32(HOST_UART + UART_RBR_THR, byte)


class OrcaHost:
    """transport-independent load/start/wait; requires exclusive aperture ownership."""

    def __init__(self, transport, console: HostConsole | None = None):
        self.transport = transport
        self.console = console

    @staticmethod
    def _polls(polls: int) -> None:
        if not isinstance(polls, int) or polls <= 0:
            raise HostError("polls must be a positive integer")

    @staticmethod
    def _launch_args(run_id: int, entry: int, arg0: int) -> None:
        for name, value in (("run ID", run_id), ("entry", entry), ("arg0", arg0)):
            if not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF:
                raise HostError(f"{name} must fit in an unsigned 32-bit word")
        if run_id == 0:
            raise HostError("run ID zero is reserved by the boot stub")
        if entry & 3:
            raise HostError("entry address must be word aligned")

    async def stop(self, polls: int = 12000) -> None:
        """hold cpu reset and wait for stopped acknowledgement."""
        self._polls(polls)
        await self.transport.write32(CONTROL, CPU_STOP)
        control = await self.transport.read32(CONTROL)
        if control != CPU_STOP:
            raise HostError(f"cpu stop control readback failed: control={control:#x}")
        for _ in range(polls):
            status = await self.transport.read32(STATUS)
            if status & (CPU_STOPPED | CPU_RUNNING) == CPU_STOPPED:
                return
            await self.transport.pause()
        raise HostError(f"cpu stop timed out: status={status:#x}; payload not safe to write")

    async def load(self, image: bytes, verify: bool = True, polls: int = 12000) -> None:
        if not image:
            raise HostError("payload is empty")
        if len(image) > PAYLOAD_LIMIT - PAYLOAD_OFFSET:
            raise HostError("payload exceeds the host-load region")

        await self.stop(polls)
        padded = image + bytes((-len(image)) % 4)
        for offset in range(0, len(padded), 4):
            word = int.from_bytes(padded[offset:offset + 4], "little")
            await self.transport.write32(PAYLOAD_OFFSET + offset, word)

        if verify:
            for offset in range(0, len(padded), 4):
                expected = int.from_bytes(padded[offset:offset + 4], "little")
                observed = await self.transport.read32(PAYLOAD_OFFSET + offset)
                if observed != expected:
                    raise HostError(
                        f"verify failed at {PAYLOAD_ADDR + offset:#010x}: "
                        f"wrote {expected:#010x}, read {observed:#010x}"
                    )

    async def launch(
        self, run_id: int, entry: int = PAYLOAD_ADDR, arg0: int = 0,
        polls: int = 12000,
    ) -> None:
        self._launch_args(run_id, entry, arg0)
        await self.stop(polls)

        await self.transport.write32(DONE, 0)
        await self.transport.write32(MAILBOX, 0)
        for offset in (DONE, MAILBOX):
            observed = await self.transport.read32(offset)
            if observed != 0:
                raise HostError(f"completion clear failed at {offset:#x}: stale={observed:#x}")
        await self.transport.write32(BOOT_ENTRY, entry)
        await self.transport.write32(BOOT_ARG0, arg0)
        await self.transport.write32(RUN_ID, run_id)
        for offset, expected in ((BOOT_ENTRY, entry), (BOOT_ARG0, arg0), (RUN_ID, run_id)):
            observed = await self.transport.read32(offset)
            if observed != expected:
                raise HostError(f"launch verify failed at {offset:#x}: wrote={expected:#x} read={observed:#x}")
        await self.transport.write32(CONTROL, CPU_RUN)
        if await self.transport.read32(CONTROL) != CPU_RUN:
            raise HostError("cpu run control readback failed")

    async def status(self, run_id: int) -> RunResult:
        return RunResult(
            run_id=run_id,
            mailbox=await self.transport.read32(MAILBOX),
            status=await self.transport.read32(STATUS),
            trap_pc=await self.transport.read32(TRAP_PC),
            trap_cause=await self.transport.read32(TRAP_CAUSE),
            trap_tval=await self.transport.read32(TRAP_TVAL),
            cycles=await self.transport.read32(CYCLE_LO),
            instructions=await self.transport.read32(INSTRET_LO),
        )

    async def wait(self, run_id: int, polls: int = 12000) -> RunResult:
        self._launch_args(run_id, PAYLOAD_ADDR, 0)
        self._polls(polls)
        stale = 0
        stale_polls = 0
        for _ in range(polls):
            if self.console is not None:
                await self.console.service()
            done = await self.transport.read32(DONE)
            if done == run_id:
                if self.console is not None:
                    await self.console.service()
                return await self.status(run_id)
            if done:
                stale = done
                stale_polls += 1
            await self.transport.pause()
        done = await self.transport.read32(DONE)
        if done == run_id:
            return await self.status(run_id)
        result = await self.status(run_id)
        raise HostError(
            f"run {run_id} timed out: status={result.status:#x} "
            f"done={done:#x} mailbox={result.mailbox:#x} "
            f"stale_done={stale:#x} stale_polls={stale_polls} "
            f"trap_pc={result.trap_pc:#x} trap_cause={result.trap_cause:#x} "
            f"trap_tval={result.trap_tval:#x} cycles={result.cycles} "
            f"instructions={result.instructions}"
        )

    async def run(
        self,
        image: bytes,
        run_id: int,
        entry: int = PAYLOAD_ADDR,
        arg0: int = 0,
        polls: int = 12000,
    ) -> RunResult:
        self._launch_args(run_id, entry, arg0)
        self._polls(polls)
        await self.load(image, polls=polls)
        if self.console is not None:
            await self.console.init()
        try:
            await self.launch(run_id, entry, arg0, polls=polls)
            return await self.wait(run_id, polls)
        except HostError as error:
            try:
                await self.stop(polls)
            except HostError as stop_error:
                raise HostError(f"{error}; recovery failed: {stop_error}") from error
            raise


def validate_uio_mapping(
    device: str,
    expected_name: str = "orca",
    sysfs_root: Path = Path("/sys/class/uio"),
) -> None:
    """confirm that a UIO device is the expected ORCA aperture."""
    uio_name = Path(device).name
    if not re.fullmatch(r"uio[0-9]+", uio_name):
        return

    uio_dir = sysfs_root / uio_name
    try:
        actual_name = (uio_dir / "name").read_text().strip()
        size = int((uio_dir / "maps" / "map0" / "size").read_text().strip(), 0)
    except (OSError, ValueError) as error:
        raise HostError(f"cannot inspect {device} through {uio_dir}: {error}") from error

    if actual_name != expected_name:
        raise HostError(
            f"{device} is UIO device {actual_name!r}, expected {expected_name!r}"
        )
    if size != APERTURE_SIZE:
        raise HostError(
            f"{device} map0 is {size:#x} bytes, expected {APERTURE_SIZE:#x}"
        )


@functools.lru_cache(maxsize=1)
def native_mmio():
    """build the native accessor once; never fall back to python mmio."""
    if sys.byteorder != "little":
        raise HostError("native MMIO requires a little-endian host")
    source = Path(__file__).resolve().with_name("orca_mmio.c")
    try:
        with tempfile.TemporaryDirectory(prefix="orca-mmio-") as temp_dir:
            library = Path(temp_dir) / "orca_mmio.so"
            result = subprocess.run(
                ["cc", "-shared", "-fPIC", "-O2", "-std=c11", "-Wall", "-Wextra",
                 "-Werror", str(source), "-o", str(library)],
                capture_output=True, text=True, check=False,
            )
            if result.returncode:
                raise HostError(f"native MMIO build failed: {result.stderr.strip()}")
            native = ctypes.CDLL(str(library))
    except OSError as error:
        raise HostError(f"native MMIO unavailable (requires cc): {error}") from error
    native.orca_read32.argtypes = [ctypes.c_void_p]
    native.orca_read32.restype = ctypes.c_uint32
    native.orca_write32.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    native.orca_write32.restype = None
    return native


class MmapTransport:
    """ordered word accesses; the kernel must map the aperture as device memory."""

    def __init__(
        self,
        device: str,
        base: int,
        poll_interval: float,
        expected_uio_name: str = "orca",
    ):
        if base < 0 or base % mmap.PAGESIZE:
            raise HostError("mmap base must be nonnegative and page aligned")
        if not math.isfinite(poll_interval) or poll_interval < 0:
            raise HostError("poll interval must be finite and nonnegative")
        validate_uio_mapping(device, expected_uio_name)
        self.native = native_mmio()
        self.closed = False
        self.fd = os.open(device, os.O_RDWR | os.O_SYNC)
        try:
            self.mapping = mmap.mmap(
                self.fd,
                APERTURE_SIZE,
                flags=mmap.MAP_SHARED,
                prot=mmap.PROT_READ | mmap.PROT_WRITE,
                offset=base,
            )
            self.address = ctypes.addressof(ctypes.c_char.from_buffer(self.mapping))
            if self.address & 3:
                self.mapping.close()
                raise HostError("mmap address must be word aligned")
        except Exception:
            os.close(self.fd)
            raise
        self.poll_interval = poll_interval

    async def write32(self, offset: int, value: int) -> None:
        if self.closed:
            raise HostError("transport is closed")
        self._check(offset)
        self.native.orca_write32(self.address + offset, value & 0xFFFFFFFF)

    async def read32(self, offset: int) -> int:
        if self.closed:
            raise HostError("transport is closed")
        self._check(offset)
        return self.native.orca_read32(self.address + offset)

    async def pause(self) -> None:
        await asyncio.sleep(self.poll_interval)

    def close(self) -> None:
        if not self.closed:
            self.mapping.close()
            os.close(self.fd)
            self.closed = True

    @staticmethod
    def _check(offset: int) -> None:
        if offset < 0 or offset + 4 > APERTURE_SIZE or offset & 3:
            raise HostError(f"invalid aperture offset {offset:#x}")


KV260_APERTURE_PHYS = 0xA400_0000


def windows_path(path: Path) -> str:
    """the drive path of a file under /mnt/<drive>, for a windows xsdb reached from a linux shell."""
    text = str(path.resolve())
    match = re.fullmatch(r"/mnt/([a-z])/(.*)", text)
    if not match:
        raise HostError(f"{path} must be on a windows drive (/mnt/<drive>/...) for xsdb")
    return f"{match.group(1).upper()}:/{match.group(2)}"


def xsdb_via_cmd() -> bool:
    """true when xsdb is a windows program reached through cmd.exe from a linux shell;
    anywhere else (linux, or windows python) it is launched directly."""
    return shutil.which("cmd.exe") is not None and Path("/mnt/c").is_dir()


def staging_dir() -> Path:
    """a windows-visible folder for files that live on the linux side."""
    for base in ("/mnt/c/Users/Public", "/mnt/c/Temp", "/mnt/c/ProgramData"):
        if os.access(base, os.W_OK):
            stage = Path(base) / "orca-stage"
            stage.mkdir(exist_ok=True)
            return stage
    raise HostError("no writable windows folder found to stage files for xsdb")


def xsdb_path(path: Path) -> str:
    """the path as xsdb should see it. a windows xsdb gets a drive path, and a file that is
    not on a drive is copied to a staging folder first; elsewhere the plain path is used."""
    if not xsdb_via_cmd():
        return str(path.resolve()).replace("\\", "/")
    if not re.match(r"/mnt/[a-z]/", str(path.resolve())):
        copy = staging_dir() / path.name
        shutil.copyfile(path, copy)
        path = copy
    return windows_path(path)


def lock_jtag() -> int:
    """one jtag session at a time: a second orca_host (or a leftover xsdb it spawned)
    would fight the first over the cable. the lock dies with the process."""
    path = Path(tempfile.gettempdir()) / "orca-jtag.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
    try:
        try:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:  # native windows python
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    except OSError:
        holder = os.read(fd, 32).decode(errors="replace").strip() or "unknown"
        os.close(fd)
        raise HostError(f"another orca_host jtag session is running (pid {holder}); "
                        "stop it first, or remove the stale lock " + str(path))
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    return fd


class JtagTransport:
    """aperture accesses through xsdb (scripts/board/kv260_jtag.tcl) over the board's usb jtag.

    the helper resets the ps into jtag boot mode, runs psu_init and loads the
    bitstream, so no board os is involved. every access is one xsdb round trip.
    """

    def __init__(self, xsdb: str, psu_init: Path, bitstream: Path, poll_interval: float,
                 aperture_phys: int = KV260_APERTURE_PHYS, relay: Path | None = None):
        self.lock_fd = lock_jtag()
        here = Path(__file__).resolve().parent
        script = here / "kv260_jtag.tcl"  # beside this file in a bundle,
        if not script.exists():
            script = here / "board" / "kv260_jtag.tcl"  # or in the repo
        via_cmd = xsdb_via_cmd()
        if via_cmd:
            # a windows xsdb reads files by drive path, so stage the script beside the inputs,
            # or in the windows staging folder when the inputs live on the linux side
            staged = None
            for candidate in (psu_init.parent, bitstream.parent):
                if str(candidate.resolve()).startswith("/mnt/"):
                    staged = candidate
                    break
            local_script = (staged or staging_dir()) / "kv260_jtag.tcl"
            local_script.write_text(script.read_text())
        else:
            local_script = script
        # the launcher takes plain words; no spaces allowed
        words = [xsdb, xsdb_path(local_script), xsdb_path(psu_init), xsdb_path(bitstream)]
        if relay is not None:
            words.append(xsdb_path(relay))
        self.relay = relay is not None
        if any(" " in word for word in words):
            raise HostError("xsdb, script and file paths must not contain spaces")
        if via_cmd:
            command, cwd = ["cmd.exe", "/d", "/c", "call", *words], "/mnt/c"
        elif sys.platform == "win32":
            command, cwd = ["cmd.exe", "/d", "/c", "call", *words], None
        else:
            command, cwd = words, None
        self.process = subprocess.Popen(command, cwd=cwd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.base = aperture_phys
        self.poll_interval = poll_interval
        self.closed = False
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise HostError("xsdb exited during board setup")
            line = line.strip()
            if line == "ready":
                break
            if line.startswith("err"):
                raise HostError(f"xsdb {line}")
            print(f"xsdb: {line}", file=sys.stderr)

    def _call(self, command: str) -> str:
        if self.closed:
            raise HostError("transport is closed")
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise HostError("xsdb exited")
            line = line.strip()
            if line == "ok" or line.startswith("ok "):
                return line[3:]
            if line.startswith("err"):
                raise HostError(f"xsdb {line}")

    async def write32(self, offset: int, value: int) -> None:
        MmapTransport._check(offset)
        self._call(f"w {self.base + offset:#x} {value & 0xFFFFFFFF:#x}")

    async def read32(self, offset: int) -> int:
        MmapTransport._check(offset)
        return int(self._call(f"r {self.base + offset:#x}"), 16)

    async def drain_uart(self, lsr: int, rbr: int, limit: int) -> bytes:
        return bytes.fromhex(self._call(f"u {self.base + lsr:#x} {self.base + rbr:#x} {limit}"))

    async def relay_go(self) -> None:
        self._call("g")

    async def relay_read(self) -> bytes:
        return bytes.fromhex(self._call("c"))

    async def relay_send(self, data: bytes) -> None:
        # orca's linux polls its uart on a timer (no interrupt), so a burst longer
        # than its 16-byte fifo overruns: pace input at 8 bytes per 30 ms
        for start in range(0, len(data), 8):
            if start:
                await asyncio.sleep(0.03)
            self._call(f"t {data[start:start + 8].hex()}")

    def reload(self) -> None:
        """load the bitstream again: the next run starts from a clean orca."""
        self._call("f")

    def load_file(self, path: Path, phys: int) -> None:
        self._call(f"d {xsdb_path(path)} {phys:#x}")

    async def pause(self) -> None:
        await asyncio.sleep(self.poll_interval)

    def close(self) -> None:
        if not self.closed:
            try:
                self._call("q")
            except HostError:
                pass
            self.closed = True
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
            os.close(self.lock_fd)


def open_transport(args):
    if args.jtag:
        if args.psu_init is None or args.bitstream is None:
            raise HostError("--jtag needs --psu-init and --bitstream")
        return JtagTransport(args.xsdb, args.psu_init, args.bitstream, args.poll_interval,
                             relay=args.jtag_relay)
    return MmapTransport(args.device, args.base, args.poll_interval, args.uio_name)


async def relay_forever(console: HostConsole, pause: float, tour: bool = False) -> None:
    """interactive console: print orca's output and forward input.

    on a terminal, keys go through one at a time (vi, ctrl-c and arrows work) and
    ctrl-] quits; otherwise stdin is forwarded line by line. a tour ignores stdin
    and returns once its script has run and the last output has settled.
    """
    import threading
    chunks: list[bytes] = []
    lock = threading.Lock()
    done = threading.Event()
    fd = sys.stdin.fileno()
    raw = sys.stdin.isatty() and not tour

    def line_reader() -> None:
        for line in sys.stdin.buffer:
            with lock:
                chunks.append(line.replace(b"\n", b"\r"))
        done.set()

    def key_reader() -> None:
        while True:
            data = os.read(fd, 64)
            if not data or b"\x1d" in data:
                with lock:
                    chunks.append(data.split(b"\x1d")[0])
                done.set()
                return
            with lock:
                chunks.append(data)

    saved = None
    if raw:
        import termios
        import tty
        saved = termios.tcgetattr(fd)
        tty.setraw(fd)
        print("[orca console: keys go to orca; ctrl-] quits]", end="\r\n", flush=True)
    if not tour:
        threading.Thread(target=key_reader if raw else line_reader, daemon=True).start()
    try:
        while not (raw and done.is_set()):
            with lock:
                while chunks:
                    console.send(chunks.pop(0))
            await console.service()
            await asyncio.sleep(pause)
            if tour and console.script_done and not console.pending:
                # the last command is typed: let its output arrive, then stop
                for _ in range(40):
                    await console.service()
                    await asyncio.sleep(pause)
                return
    finally:
        if saved is not None:
            import termios
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
            print()


def load_ddr(path: str, ddr_phys: int, image: bytes, dtb: bytes) -> None:
    """copy the kernel image and dtb into the ps ddr that backs orca's window."""
    size = LINUX_DTB_OFFSET + len(dtb)
    if len(image) > LINUX_DTB_OFFSET:
        raise HostError("kernel image overlaps the dtb slot")
    fd = os.open(path, os.O_RDWR | os.O_SYNC)
    try:
        mapping = mmap.mmap(fd, size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE,
                            offset=ddr_phys)
        try:
            mapping[0:len(image)] = image
            mapping[LINUX_DTB_OFFSET:LINUX_DTB_OFFSET + len(dtb)] = dtb
            mapping.flush()
            if mapping[0:len(image)] != image or \
               mapping[LINUX_DTB_OFFSET:LINUX_DTB_OFFSET + len(dtb)] != dtb:
                raise HostError("ddr read-back mismatch")
        finally:
            mapping.close()
    finally:
        os.close(fd)


async def linux_command(args) -> None:
    """load linux into the ddr window, start it, relay the console until ^c."""
    image = args.binary.read_bytes()
    if len(image) > LINUX_DTB_OFFSET:
        raise HostError("kernel image overlaps the dtb slot")
    transport = open_transport(args)
    try:
        if args.jtag:
            transport.load_file(args.binary, args.ddr_phys)
            transport.load_file(args.dtb, args.ddr_phys + LINUX_DTB_OFFSET)
        else:
            load_ddr(args.ddr_device, args.ddr_phys, image, args.dtb.read_bytes())
        divisor = args.console_divisor or max(2, round(args.core_hz / (16 * args.baud)))
        script = ()
        if args.tour is not None:
            commands = [line for line in args.tour.read_text().splitlines()
                        if line.strip() and not line.startswith("#")]
            # log in when the prompt shows, then one command per shell prompt
            script = ((b"login: ", b"root\r"),) + tuple((b" # ", c.encode() + b"\r") for c in commands)
        console = HostConsole(transport, divisor, script=script, stall=10.0 if script else 0.0, delay=args.tour_pause, key_delay=args.tour_key_delay,
                              echo=lambda data: (sys.stdout.buffer.write(data),
                                                 sys.stdout.buffer.flush()))
        host = OrcaHost(transport, console)
        await host.load(LINUX_SHIM, polls=args.polls)
        await console.init()
        await host.launch(args.run_id, PAYLOAD_ADDR, LINUX_RAM_BASE + LINUX_DTB_OFFSET,
                          polls=args.polls)
        await relay_forever(console, args.poll_interval, tour=args.tour is not None)
    finally:
        transport.close()


def number(text: str) -> int:
    return int(text, 0)


def act_verdict(word: int) -> str:
    """classify the mailbox word an architecture test leaves behind."""
    return "PASS" if word == ACT_PASS else "FAIL" if word == ACT_FAIL else "UNKNOWN"


async def run_images(args, images: list[Path], read_result) -> dict[str, int]:
    """load each image into the ddr window, start it through the boot stub and wait for its mailbox word.
    read_result(transport, image, word) returns (verdict, detail) once the word is set."""
    transport = open_transport(args)
    counts = {"PASS": 0, "FAIL": 0, "UNKNOWN": 0, "TIMEOUT": 0}
    try:
        for index, image in enumerate(images, 1):
            if index > 1 and not args.act_no_reload:
                transport.reload()
            transport.load_file(image, args.ddr_phys)
            host = OrcaHost(transport)
            await host.load(bytes.fromhex("67800000"), polls=args.polls)
            await host.launch(index, LINUX_RAM_BASE, 0, polls=args.polls)
            deadline = time.monotonic() + args.act_timeout
            word = 0
            while not word and time.monotonic() < deadline:
                word = await transport.read32(MAILBOX)
                if not word:
                    await transport.pause()
            if word:
                verdict, detail = await read_result(transport, image, word)
            else:
                verdict, detail = "TIMEOUT", f"status={await transport.read32(STATUS):#x}"
            counts[verdict] += 1
            print(f"{verdict:7} {index:3}/{len(images)} {image.stem}  {detail}", flush=True)
    finally:
        transport.close()
    return counts


def select_images(folder: Path, only: str | None, what: str) -> list[Path]:
    images = sorted(folder.glob("*.bin"))
    if only:
        images = [image for image in images if only in image.stem]
    if not images:
        raise HostError(f"no {what} images in {folder}")
    return images


async def act_command(args) -> int:
    """run the packed architecture tests on the board, one fresh bitstream per test."""
    if not args.jtag:
        raise HostError("--act-dir runs over --jtag")
    images = select_images(args.act_dir, args.act_only, "architecture test")

    async def read_act(transport, image, word):
        cycles = await transport.read32(ACT_CYCLES)
        instret = await transport.read32(ACT_INSTRET)
        return act_verdict(word), f"mailbox={word:#010x} cycles={cycles} instret={instret}"

    counts = await run_images(args, images, read_act)
    print(f"architecture tests on the board: {counts['PASS']} passed, {counts['FAIL']} failed, "
          f"{counts['UNKNOWN']} unknown, {counts['TIMEOUT']} timed out, {len(images)} run")
    return 0 if counts["PASS"] == len(images) else 1


async def embench_command(args) -> int:
    """run embench images (build-embench.sh orca) on the board and keep each timed region in a csv
    with the columns embench_run.py scores (bench, cycles, instret, rc, wall)."""
    if not args.jtag:
        raise HostError("--embench-dir runs over --jtag")
    images = select_images(args.embench_dir, args.act_only, "embench")
    rows = {}

    async def read_embench(transport, image, word):
        rc = await transport.read32(EMBENCH_RESULT)
        cycles = await transport.read32(EMBENCH_RESULT + 4)
        instret = await transport.read32(EMBENCH_RESULT + 8)
        rows[image.stem] = {"bench": image.stem, "cycles": cycles, "instret": instret, "rc": rc, "wall": 0}
        ipc = instret / cycles if cycles else 0.0
        return act_verdict(word), f"cycles={cycles} instret={instret} ipc={ipc:.3f} rc={rc}"

    counts = await run_images(args, images, read_embench)
    if args.embench_csv is not None:
        args.embench_csv.parent.mkdir(parents=True, exist_ok=True)
        with args.embench_csv.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["bench", "cycles", "instret", "rc", "wall"])
            writer.writeheader()
            for name in sorted(rows):
                writer.writerow(rows[name])
    print(f"embench on the board: {counts['PASS']} passed, {counts['FAIL']} failed, "
          f"{counts['UNKNOWN']} unknown, {counts['TIMEOUT']} timed out, {len(images)} run")
    return 0 if counts["PASS"] == len(images) else 1


async def vectors_command(args) -> int:
    """run random vectors (build_vectors.py) on the board and compare each program's signature with sail's.

    a vector is <name>.bin (an image for the ddr window) and <name>.json with the signature offset in the dma
    region and the expected words. the program writes the pass word to the mailbox when its signature is stored.
    """
    import json
    if not args.jtag:
        raise HostError("--vectors runs over --jtag")
    metas = sorted(args.vectors.glob("*.json"))
    if args.act_only:
        metas = [m for m in metas if args.act_only in m.stem]
    if args.vector_limit:
        metas = metas[:args.vector_limit]
    if not metas:
        raise HostError(f"no vectors in {args.vectors}")
    transport = open_transport(args)
    counts = {"PASS": 0, "FAIL": 0, "TIMEOUT": 0}
    started = time.monotonic()
    try:
        for index, meta in enumerate(metas, 1):
            data = json.loads(meta.read_text())
            expect = [int(w, 16) for w in data["expect"]]
            offset = data["sig_offset"]
            if index > 1 and not args.act_no_reload:
                transport.reload()
            transport.load_file(meta.with_suffix(".bin"), args.ddr_phys)
            host = OrcaHost(transport)
            await host.load(bytes.fromhex("67800000"), polls=args.polls)
            for k in range(len(expect)):
                await transport.write32(DMA_BASE + offset + 4 * k, 0xDEADBEEF)  # a program that never stores cannot pass
            await host.launch(index, LINUX_RAM_BASE, 0, polls=args.polls)
            deadline = time.monotonic() + args.act_timeout
            word = 0
            while not word and time.monotonic() < deadline:
                word = await transport.read32(MAILBOX)
                if not word:
                    await transport.pause()
            if not word:
                verdict, detail = "TIMEOUT", f"status={await transport.read32(STATUS):#x}"
            else:
                got = [await transport.read32(DMA_BASE + offset + 4 * k) for k in range(len(expect))]
                bad = [k for k, (e, g) in enumerate(zip(expect, got)) if e != g]
                if word == ACT_PASS and not bad:
                    verdict, detail = "PASS", ""
                else:
                    verdict = "FAIL"
                    detail = f"mailbox={word:#x} " + "; ".join(
                        f"word {k}: expected {expect[k]:#010x} got {got[k]:#010x}" for k in bad[:4])
            counts[verdict] += 1
            print(f"{verdict:7} {index:4}/{len(metas)} {data['name']}  {detail}", flush=True)
    finally:
        transport.close()
    print(f"random vectors on the board: {counts['PASS']} passed, {counts['FAIL']} failed, "
          f"{counts['TIMEOUT']} timed out, {len(metas)} run in {time.monotonic() - started:.0f} s")
    return 0 if counts["PASS"] == len(metas) else 1


async def run_command(args) -> RunResult:
    transport = open_transport(args)
    console = None
    if args.console:
        def show(data: bytes) -> None:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        divisor = args.console_divisor or max(2, round(args.core_hz / (16 * args.baud)))
        script = ()
        text = None
        if args.console_input is not None:
            text = args.console_input.encode().decode("unicode_escape").encode()
            if b"=>" in text:
                # "prompt=>reply": type reply once orca has printed prompt
                trigger, reply = text.split(b"=>", 1)
                script, text = ((trigger, reply),), None
        console = HostConsole(transport, divisor, script=script, echo=show)
        if text is not None:
            console.send(text)
    try:
        if args.ddr_entry:
            # a program linked at orca 0x1000_0000: copy it into the ddr window and
            # have the boot stub call it there (the host-load slot gets a bare ret)
            if args.jtag:
                transport.load_file(args.binary, args.ddr_phys)
            else:
                image = args.binary.read_bytes()
                load_ddr(args.ddr_device, args.ddr_phys, image, b"")
            return await OrcaHost(transport, console).run(
                bytes.fromhex("67800000"), args.run_id, LINUX_RAM_BASE, args.arg0, args.polls)
        return await OrcaHost(transport, console).run(
            args.binary.read_bytes(), args.run_id, args.entry, args.arg0, args.polls
        )
    finally:
        transport.close()


def _terminate(signum, frame) -> None:
    # unwind like ctrl-c so transports close (the jtag helper otherwise holds the cable)
    raise KeyboardInterrupt


def main() -> int:
    import signal
    signal.signal(signal.SIGTERM, _terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path, nargs="?", help="flat host-load payload")
    parser.add_argument("--device", default="/dev/uio0", help="UIO device or /dev/mem")
    parser.add_argument("--base", type=number, default=0, help="mmap offset; use the physical aperture base with /dev/mem")
    parser.add_argument(
        "--uio-name",
        default="orca",
        help="expected /sys/class/uio name; ignored for non-UIO devices",
    )
    parser.add_argument("--entry", type=number, default=PAYLOAD_ADDR)
    parser.add_argument("--arg0", type=number, default=0)
    parser.add_argument("--run-id", type=number, default=1)
    parser.add_argument("--polls", type=number, default=12000)
    parser.add_argument("--poll-interval", type=float, default=0.001)
    parser.add_argument("--expect", type=number)
    parser.add_argument("--console", action="store_true",
                        help="relay orca's console through the host-side uart and print it")
    parser.add_argument("--console-input",
                        help="text to type into the console (escapes allowed); "
                             "'prompt=>text' waits for prompt first")
    parser.add_argument("--core-hz", type=number, default=125_000_000,
                        help="orca core clock, for the console divisor")
    parser.add_argument("--baud", type=number, default=115200)
    parser.add_argument("--console-divisor", type=number, default=0,
                        help="override the computed 16550 divisor")
    parser.add_argument("--linux-dtb", dest="dtb", type=Path,
                        help="boot linux: binary is the kernel Image, this is its dtb; "
                             "relays the console until interrupted")
    parser.add_argument("--tour", type=Path,
                        help="with --linux-dtb: log in and type each line of this file as a command, "
                             "one per shell prompt, then exit")
    parser.add_argument("--tour-pause", type=float, default=3.0,
                        help="seconds the tour waits after each prompt before typing (with --tour)")
    parser.add_argument("--tour-key-delay", type=float, default=0.08,
                        help="seconds between typed characters (with --tour)")
    parser.add_argument("--ddr-phys", type=number, default=0x7000_0000,
                        help="ps physical address behind orca's ddr window")
    parser.add_argument("--ddr-device", default="/dev/mem")
    parser.add_argument("--ddr-entry", action="store_true",
                        help="binary is linked at orca 0x1000_0000: load it into the ddr "
                             "window (--ddr-phys) and start it there")
    parser.add_argument("--act-dir", type=Path,
                        help="run every architecture-test image (*.bin) in this folder on the board, "
                             "one fresh bitstream each (with --jtag; make act-board builds them)")
    parser.add_argument("--act-only", help="only the images whose name contains this text "
                                           "(with --act-dir, --embench-dir or --vectors)")
    parser.add_argument("--embench-dir", type=Path,
                        help="run the embench images (*.bin) in this folder on the board (with --jtag)")
    parser.add_argument("--embench-csv", type=Path,
                        help="write the board's embench cycles here in embench_run.py's format (with --embench-dir)")
    parser.add_argument("--vectors", type=Path,
                        help="run the random vectors in this folder on the board and compare their signatures "
                             "(with --jtag; scripts/vectors/build_vectors.py builds them)")
    parser.add_argument("--vector-limit", type=int, default=0, help="run only the first N vectors (with --vectors)")
    parser.add_argument("--act-no-reload", action="store_true",
                        help="keep one bitstream for all tests: stop the cpu and load the next image "
                             "(with --act-dir); the default reloads the bitstream before every test")
    parser.add_argument("--act-timeout", type=float, default=20.0,
                        help="seconds to wait for each test's verdict (with --act-dir)")
    parser.add_argument("--jtag", action="store_true",
                        help="drive a kv260 over usb jtag with xsdb instead of a board os")
    parser.add_argument("--xsdb", default="C:/AMDDesignTools/2026.1/Vivado/bin/xsdb.bat" if xsdb_via_cmd() else "xsdb",
                        help="xsdb to run with --jtag: the windows path of xsdb.bat when xsdb is a windows program, "
                             "otherwise a command on PATH (xsct is disabled in 2026.1)")
    parser.add_argument("--psu-init", type=Path,
                        help="psu_init.tcl from the platform xsa (with --jtag)")
    parser.add_argument("--bitstream", type=Path, help="orca bitstream (with --jtag)")
    parser.add_argument("--jtag-relay", type=Path,
                        help="relay.elf (sw/kv260_relay): an a53 core buffers the console "
                             "so it can run fast (with --jtag)")
    args = parser.parse_args()

    if args.act_dir is not None or args.vectors is not None or args.embench_dir is not None:
        command = (act_command if args.act_dir is not None else
                   embench_command if args.embench_dir is not None else vectors_command)
        try:
            return asyncio.run(command(args))
        except (HostError, OSError) as error:
            parser.exit(1, f"orca-host: {error}\n")
    if args.binary is None:
        parser.error("a payload binary is required (or --act-dir)")

    if args.dtb is not None:
        try:
            asyncio.run(linux_command(args))
        except KeyboardInterrupt:
            return 0
        except (HostError, OSError) as error:
            parser.exit(1, f"orca-host: {error}\n")
        return 0

    try:
        result = asyncio.run(run_command(args))
    except (HostError, OSError) as error:
        parser.exit(1, f"orca-host: {error}\n")

    print(
        f"run={result.run_id} mailbox={result.mailbox:#010x} "
        f"status={result.status:#x} cycles={result.cycles} "
        f"instructions={result.instructions}"
    )
    if result.trap_cause:
        print(
            f"trap pc={result.trap_pc:#010x} cause={result.trap_cause:#010x} "
            f"tval={result.trap_tval:#010x}"
        )
    if args.expect is not None and result.mailbox != args.expect:
        print(
            f"orca-host: expected mailbox {args.expect:#010x}, "
            f"got {result.mailbox:#010x}"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
