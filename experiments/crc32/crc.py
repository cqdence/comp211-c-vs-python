"""CRC-32 checksum of n bytes in Python (the same algorithms as crc.c).

Variants:
  bitwise  one byte at a time, then 8 shift/XOR steps per byte
  table    256-entry lookup table, one lookup per byte
  ctypes   only the hot loop rewritten in C (crc_hotspot.c), called from Python with ctypes
  zlib     zlib.crc32(data): Python calls the C library zlib once
  zlib_per_byte  the same library, called once per byte (1 million calls for 1 MB)
"""
import zlib
from benchutil import parse_args, run, report_mem, read_data

POLY = 0xEDB88320
variant, n, repeats, datadir = parse_args()
data = read_data(datadir, "crc_input.bin", n)


def crc_bitwise(p):
    c = 0xFFFFFFFF
    for byte in p:
        c ^= byte
        for _ in range(8):
            c = (c >> 1) ^ POLY if c & 1 else c >> 1   # lowest bit set? shift and XOR
    return c ^ 0xFFFFFFFF


TABLE = []
for b in range(256):
    c = b
    for _ in range(8):
        c = (c >> 1) ^ POLY if c & 1 else c >> 1
    TABLE.append(c)


def crc_table(p):
    c = 0xFFFFFFFF
    t = TABLE
    for byte in p:
        c = t[(c ^ byte) & 0xFF] ^ (c >> 8)
    return c ^ 0xFFFFFFFF


def crc_zlib_per_byte(p):
    c = 0
    for i in range(len(p)):
        c = zlib.crc32(p[i:i + 1], c)   # zlib.crc32 can continue from a previous checksum
    return c


def load_hotspot():
    """Load the C version of crc_table (built by experiment.py into the data folder)."""
    import ctypes
    lib = ctypes.CDLL(f"{datadir}/libcrc_hotspot.so")
    lib.crc32_table.argtypes = [ctypes.c_char_p, ctypes.c_size_t]   # bytes are passed without copying
    lib.crc32_table.restype = ctypes.c_uint32
    return lib.crc32_table


if variant == "bitwise":
    fn = lambda: crc_bitwise(data)
elif variant == "table":
    fn = lambda: crc_table(data)
elif variant == "ctypes":
    hot = load_hotspot()
    fn = lambda: hot(data, len(data))
elif variant == "zlib":
    fn = lambda: zlib.crc32(data)
elif variant == "zlib_per_byte":
    fn = lambda: crc_zlib_per_byte(data)
else:
    raise SystemExit(f"unknown variant {variant}")

run(fn, repeats, check_fmt=lambda v: f"{v:08x}")
report_mem()
