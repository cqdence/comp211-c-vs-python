"""CRC-32 checksums: should you rewrite it in C?

The same checksum, climbing a ladder: pure Python, a better algorithm in Python, the same
algorithms rewritten in C, a faster algorithm in C, only the hot loop in C called from Python,
and finally just calling a library (zlib) that already exists - once, or once per byte.
"""
import os
import random
import subprocess
from pathlib import Path
from cases import c, py

TITLE = "CRC-32: should you rewrite it in C?"
UNIT = "bytes"
SIZES = [1_000, 1_000_000, 16_000_000]
QUICK_SIZES = [1_000, 100_000]
REFERENCE = "py_bitwise"

CASES = [
    py("py_bitwise", "crc.py", "bitwise", note="Python, 8 shift/XOR steps per byte", label="Python, bitwise"),
    py("py_table", "crc.py", "table", note="Python, 256-entry lookup table", label="Python, table"),
    c("c_bitwise_O0", "crc.c", ["-O0"], "bitwise", note="C, 8 shift/XOR steps per byte, no optimisation", label="C -O0, bitwise"),
    c("c_bitwise_O2", "crc.c", ["-O2"], "bitwise", note="C, 8 shift/XOR steps per byte, -O2", label="C -O2, bitwise"),
    c("c_table_O2", "crc.c", ["-O2"], "table", note="C, lookup table, -O2", label="C -O2, table"),
    c("c_slice8_O2", "crc.c", ["-O2"], "slice8", note="C, slicing-by-8: 8 tables, 8 bytes per step, -O2", label="C -O2, slicing-by-8"),
    py("py_ctypes", "crc.py", "ctypes", family="Python + my C",
       note="Python calling the C table loop (crc_hotspot.c, -O2) through ctypes", label="Python calling my C table"),
    py("py_zlib", "crc.py", "zlib", family="Python + C library", note="zlib.crc32(data) from Python, one call", label="Python calling zlib once"),
    py("py_zlib_per_byte", "crc.py", "zlib_per_byte", family="Python + C library",
       note="zlib.crc32 from Python, called once per byte", label="Python calling zlib per byte"),
    c("c_zlib", "crc.c", ["-O2", "-DHAVE_ZLIB"], "zlib", libs=["-lz"], note="C calling zlib's crc32()", label="C calling zlib"),
]


def prepare(datadir, max_n):
    path = datadir / "crc_input.bin"
    if not path.exists() or path.stat().st_size < max_n:
        path.write_bytes(random.Random(42).randbytes(max_n))  # same bytes every time
    # the hot-spot library that py_ctypes loads
    src = Path(__file__).resolve().parent / "crc_hotspot.c"
    cc = os.environ.get("CC", "gcc")
    subprocess.run([cc, "-O2", "-shared", "-fPIC", "-o", str(datadir / "libcrc_hotspot.so"), str(src)], check=True)
