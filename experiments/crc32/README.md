# CRC-32: should you rewrite it in C?

My faster-qr project sends a file as a stream of QR codes. Before sending, it computes a CRC-32
checksum of the whole file. The receiver computes it again, and if the two don't match, the file
didn't arrive intact. A CRC is pure bit manipulation: shifts, XOR and AND.

**Question:** If a checksum is too slow in Python, what should you do: rewrite it in C, pick a
better algorithm, or call a library someone already wrote? And what does it cost to call C from Python?

**Run it:** `python3 kit/bench.py crc32` writes `results/crc32/summary.md` (about 4 minutes).

## The files

| file | what it holds |
|---|---|
| `crc.py` | the Python versions: bitwise, table, ctypes, zlib, zlib once per byte |
| `crc.c` | the C versions: bitwise, table, slicing-by-8, zlib |
| `crc_hotspot.c` | only the table loop, built as a shared library so Python can call it |
| `experiment.py` | the list of cases and sizes that `kit/bench.py` runs |

## What is compared

| case | what it does |
|---|---|
| `py_bitwise`, `c_bitwise_O0`, `c_bitwise_O2` | the textbook version: 8 shift/XOR steps per byte |
| `py_table`, `c_table_O2` | precompute those 8 steps for all 256 byte values, then 1 table lookup per byte |
| `c_slice8_O2` | slicing-by-8: 8 tables, 8 bytes per step, and the 8 lookups don't wait on each other |
| `py_ctypes` | Python calls the C table loop in `crc_hotspot.c` once, through `ctypes` |
| `py_zlib` | Python calls `zlib.crc32()` once for all the data |
| `py_zlib_per_byte` | Python calls `zlib.crc32()` once per byte, continuing from the previous result |
| `c_zlib` | C calls the same zlib function once |

Every version must produce the same 8-digit hex checksum. The `answer` column in the results
checks this.

Sizes: 1 KB, 1 MB and 16 MB. Every version runs at every size.

## Things to try

1. Change `SIZES` in `experiment.py` to `[10, 100, 1_000]` and watch the cost of crossing from Python into C grow.
2. Flip one bit of `build/data/crc_input.bin` and check that every version's answer changes.
3. Build `crc.c` with `-O3 -march=native` and see if the compiler can speed up the table loop.
