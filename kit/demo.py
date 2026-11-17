#!/usr/bin/env python3
"""Live demos for the presentation. Each one runs in a few seconds.

    python3 kit/demo.py steps     # what one CRC step does to one byte, bit by bit
    python3 kit/demo.py flip      # flip a single bit of a message: the checksum changes completely
    python3 kit/demo.py ladder    # the same checksum of 1 MB, from pure Python up to zlib
    python3 kit/demo.py calls     # 1 call vs 1 million calls into C: the price of crossing over
    python3 kit/demo.py all
"""
import importlib.util
import statistics
import subprocess
import sys
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench  # noqa: E402

EXP = bench.ROOT / "experiments" / "crc32"
DATA = bench.ROOT / "build" / "data"
BUILD = bench.ROOT / "build" / "demo"
POLY = 0xEDB88320


def bits(v):
    s = f"{v:032b}"
    return " ".join(s[i:i + 8] for i in range(0, 32, 8))


def prepare(n):
    spec = importlib.util.spec_from_file_location("exp_crc32", EXP / "experiment.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    DATA.mkdir(parents=True, exist_ok=True)
    mod.prepare(DATA, n)


def build(flags, libs=()):
    BUILD.mkdir(parents=True, exist_ok=True)
    exe, _, err = bench.compile_c(EXP, BUILD, "crc.c", list(flags), list(libs))
    if err:
        sys.exit(f"compile failed: {err}")
    return exe


def time_it(argv, n, repeats):
    """Run one case; returns (median ns of the timed runs, checksum)."""
    out = subprocess.run([str(a) for a in argv] + [str(n), str(repeats), str(DATA)], capture_output=True,
                         text=True, check=True, env={**bench.os.environ, "PYTHONPATH": str(bench.KIT)}).stdout
    runs, _, _ = bench.parse_output(out)
    return statistics.median(ns for warm, ns, _ in runs if not warm), runs[-1][2]


def rungs():
    py = [sys.executable, EXP / "crc.py"]
    return [
        ("Python, bitwise (8 shift/XOR steps per byte)", py + ["bitwise"]),
        ("Python, lookup table (1 lookup per byte)", py + ["table"]),
        ("C -O2, bitwise", [build(["-O2"]), "bitwise"]),
        ("C -O2, lookup table", [build(["-O2"]), "table"]),
        ("C -O2, slicing-by-8 (8 bytes per step)", [build(["-O2"]), "slice8"]),
        ("Python calling my C table loop (ctypes)", py + ["ctypes"]),
        ("Python calling zlib.crc32 once per byte", py + ["zlib_per_byte"]),
        ("Python calling zlib.crc32 once", py + ["zlib"]),
    ]


def steps():
    byte = ord("A")
    c = 0xFFFFFFFF ^ byte
    print(f"\nOne byte, 'A' = {byte:08b}. The CRC starts as all 1s, then XORs the byte into the low end:\n")
    print(f"  start            {bits(c)}")
    for k in range(8):
        low = c & 1
        c = (c >> 1) ^ POLY if low else c >> 1
        print(f"  step {k + 1}: low bit {low}  {bits(c)}   {'shift right, then XOR the polynomial' if low else 'shift right'}")
    print(f"\n  The table version stores the result of these 8 steps for all 256 possible bytes,")
    print(f"  so it does one lookup instead of 8 steps.\n")


def flip():
    msg = bytearray(b"Hello, COMP 211!")
    a = zlib.crc32(msg)
    msg[7] ^= 0b00000001                       # flip the lowest bit of one character
    b = zlib.crc32(msg)
    changed = bin(a ^ b).count("1")
    print(f"\n  b'Hello, COMP 211!'  CRC-32 = {a:08x} = {bits(a)}")
    print(f"  {bytes(msg)!r}  CRC-32 = {b:08x} = {bits(b)}")
    print(f"\n  One bit of the message changed ('C' became 'B'); {changed} of the 32 checksum bits changed.\n")


def ladder(n=1_000_000):
    prepare(n)
    print(f"\nCRC-32 of {n:,} bytes. Same answer every time; 3 timed runs each, median shown.\n")
    base = None
    for label, argv in rungs():
        ns, check = time_it(argv, n, 3)
        base = base or ns
        print(f"  {label:<46} {bench.fmt_ns(ns):>9}   {base / ns:>6,.0f}x   crc {check}")
    print()


def best_of(fn, runs=5):
    times = []
    for _ in range(runs):
        t0 = time.perf_counter_ns()
        result = fn()
        times.append(time.perf_counter_ns() - t0)
    return statistics.median(times), result


def calls():
    prepare(1_000_000)
    import ctypes
    data = (DATA / "crc_input.bin").read_bytes()[:1_000_000]
    lib = ctypes.CDLL(str(DATA / "libcrc_hotspot.so"))
    lib.crc32_table.argtypes, lib.crc32_table.restype = [ctypes.c_char_p, ctypes.c_size_t], ctypes.c_uint32

    def chunks(size):
        c = 0
        for i in range(0, len(data), size):
            c = zlib.crc32(data[i:i + size], c)     # continue from the previous checksum
        return c

    print("\nThe same 1 MB through zlib.crc32, split into more and more calls.\n")
    for label, fn in [("1 call for the whole 1 MB", lambda: zlib.crc32(data)),
                      ("1,000 calls of 1 KB", lambda: chunks(1_000)),
                      ("1,000,000 calls of 1 byte", lambda: chunks(1))]:
        ns, crc = best_of(fn)
        print(f"  {label:<30} {bench.fmt_ns(ns):>9}   crc {crc:08x}")
    print("\nWhat one call costs before any work happens (an empty input, 1 million calls):\n")
    empty = b""
    for label, fn in [("zlib.crc32 (a C extension)", lambda: zlib.crc32(empty)),
                      ("my C function through ctypes", lambda: lib.crc32_table(empty, 0))]:
        t0 = time.perf_counter_ns()
        for _ in range(1_000_000):
            fn()
        print(f"  {label:<30} {(time.perf_counter_ns() - t0) / 1e6:>6.0f} ns per call")
    print("\n  Crossing from Python into C has a price per call. Few big calls: free. One per byte: as slow as Python.\n")


DEMOS = {"steps": steps, "flip": flip, "ladder": ladder, "calls": calls}

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "help"
    if which == "all":
        for fn in DEMOS.values():
            fn()
    elif which in DEMOS:
        DEMOS[which]()
    else:
        print(__doc__)
