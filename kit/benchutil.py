"""Shared helpers for every Python benchmark kernel in this repo.

Every kernel program is run as:
    python3 kernel.py <variant> <n> <repeats> <datadir>
and prints the same lines as the C kernels (see kit/bench.h):
    WARM <ns> <check> / RUN <ns> <check> / NOTE <text> / MEM <kb>
"""
import resource
import sys
import time

WARMUP = 1


def parse_args():
    if len(sys.argv) < 4:
        sys.exit(f"usage: {sys.argv[0]} <variant> <n> <repeats> [datadir]")
    variant = sys.argv[1]
    n = int(sys.argv[2])
    repeats = int(sys.argv[3])
    datadir = sys.argv[4] if len(sys.argv) > 4 else "."
    return variant, n, repeats, datadir


def run(fn, repeats, check_fmt=str):
    """Call fn() WARMUP + repeats times, timing each call with a monotonic clock."""
    for r in range(-WARMUP, repeats):
        t0 = time.perf_counter_ns()
        result = fn()
        t1 = time.perf_counter_ns()
        print("WARM" if r < 0 else "RUN", t1 - t0, check_fmt(result), flush=True)


def note(text):
    print("NOTE", text, flush=True)


def report_mem():
    """Peak memory of this process. On Linux read VmHWM from /proc (ru_maxrss would also count
    the memory of the process that launched us)."""
    kb = None
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    kb = int(line.split()[1])
                    break
    except OSError:
        pass
    if kb is None:
        kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":  # macOS reports bytes, Linux reports kilobytes
            kb //= 1024
    print("MEM", kb, flush=True)


def read_data(datadir, name, n):
    with open(f"{datadir}/{name}", "rb") as f:
        data = f.read(n)
    if len(data) != n:
        sys.exit(f"{name}: wanted {n} bytes, got {len(data)}")
    return data
