#!/usr/bin/env python3
"""The benchmark kit: compiles, runs, checks and summarises one or more experiments.

Usage (from the repo root):
    python3 kit/bench.py crc32               # run one experiment (any unique prefix works)
    python3 kit/bench.py all                 # run every experiment in experiments/
    python3 kit/bench.py crc32 --quick       # fewer runs, smaller sizes: a few-second smoke test
    python3 kit/bench.py crc32 --processes 5 --repeats 10 --pin 2

What it does for each experiment (experiments/<name>/experiment.py):
  1. Makes the input data once (same bytes for C and Python).
  2. Compiles each C kernel with the flags the experiment asks for.
  3. Runs every case as a FRESH PROCESS several times (--processes), and each process times
     the work several times (--repeats) after one untimed warm-up run.
     Cases take turns (A, B, C, A, B, C, ...) so slow drift on the machine - another program
     starting, the CPU heating up - hits every case equally instead of only the last one.
  4. Checks that every version computed the same answer.
  5. Reports the MEDIAN (the middle run: not thrown off by one unlucky slow run), the spread
     between the 25th and 75th percentile, and the coefficient of variation (how noisy it was).
  6. Writes results/<name>/summary.md, raw.csv, meta.json and an SVG chart per size.
"""
import argparse
import csv
import importlib.util
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "kit"
sys.path.insert(0, str(KIT))
import charts  # noqa: E402

CC = os.environ.get("CC", "gcc")


# ---------------------------------------------------------------- helpers

def fmt_ns(ns):
    if ns is None:
        return "-"
    if ns < 1_000:
        return f"{ns:.3g} ns" if ns < 10 else f"{ns:.0f} ns"
    if ns < 1_000_000:
        return f"{ns / 1e3:.3g} µs"
    if ns < 1_000_000_000:
        return f"{ns / 1e6:.3g} ms"
    return f"{ns / 1e9:.3g} s"


def fmt_n(n):
    for unit, size in (("G", 10**9), ("M", 10**6), ("K", 10**3)):
        if n >= size and n % size == 0:
            return f"{n // size}{unit}"
    for unit, size in (("Gi", 1 << 30), ("Mi", 1 << 20), ("Ki", 1 << 10)):
        if n >= size and n % size == 0:
            return f"{n // size}{unit}"
    return str(n)


def sh(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def machine_info():
    info = {
        "date": datetime.now().isoformat(timespec="seconds"),
        "os": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "python": platform.python_version(),
        "compiler": sh([CC, "--version"]).splitlines()[0] if sh([CC, "--version"]) else CC,
        "logical_cpus": os.cpu_count(),
    }
    cpu = ""
    if Path("/proc/cpuinfo").exists():
        m = re.search(r"model name\s*:\s*(.+)", Path("/proc/cpuinfo").read_text())
        cpu = m.group(1).strip() if m else ""
    elif platform.system() == "Darwin":
        cpu = sh(["sysctl", "-n", "machdep.cpu.brand_string"])
    info["cpu"] = cpu or platform.processor()
    gov = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    info["cpu_governor"] = gov.read_text().strip() if gov.exists() else "unknown"
    import zlib
    info["zlib"] = zlib.ZLIB_RUNTIME_VERSION
    return info


def loadavg():
    try:
        return round(os.getloadavg()[0], 2)
    except OSError:
        return None


def load_experiment(name):
    matches = sorted(p for p in (ROOT / "experiments").iterdir() if p.is_dir() and p.name.startswith(name))
    if not matches:
        sys.exit(f"no experiment matching {name!r} in experiments/")
    exp_dir = matches[0]
    spec = importlib.util.spec_from_file_location(f"exp_{exp_dir.name.replace('-', '_')}", exp_dir / "experiment.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return exp_dir, mod


# ---------------------------------------------------------------- compile

def flag_slug(flags):
    return "_".join(f.lstrip("-").replace("=", "").replace("-", "") for f in flags) or "noflags"


def compile_c(exp_dir, build_dir, src, flags, libs):
    """Compile src with flags. If -march=native is rejected (some Apple compilers), try -mcpu=native."""
    exe = build_dir / f"{Path(src).stem}__{flag_slug(flags)}"
    attempts = [flags]
    if "-march=native" in flags:
        attempts.append([("-mcpu=native" if f == "-march=native" else f) for f in flags])
    last_err = ""
    for fl in attempts:
        argv = [CC, *fl, "-I", str(KIT), "-o", str(exe), str(exp_dir / src), *libs, "-lm"]
        r = subprocess.run(argv, capture_output=True, text=True)
        if r.returncode == 0:
            return exe, " ".join(argv[:1] + fl), None
        last_err = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "compile failed"
    return None, None, last_err


# ---------------------------------------------------------------- run

def parse_output(text):
    runs, notes, mem = [], [], None
    for line in text.splitlines():
        parts = line.split(maxsplit=2)
        if not parts:
            continue
        if parts[0] in ("RUN", "WARM") and len(parts) >= 2:
            runs.append((parts[0] == "WARM", int(parts[1]), parts[2].strip() if len(parts) > 2 else ""))
        elif parts[0] == "NOTE":
            notes.append(line[5:].strip())
        elif parts[0] == "MEM":
            mem = int(parts[1])
    return runs, notes, mem


def run_process(argv, env, pin, timeout):
    if pin is not None and shutil.which("taskset"):
        argv = ["taskset", "-c", str(pin), *argv]
    full_env = {**os.environ, **env}
    t0 = time.perf_counter_ns()
    r = subprocess.run(argv, capture_output=True, text=True, env=full_env, timeout=timeout)
    wall = time.perf_counter_ns() - t0
    if r.returncode != 0:
        raise RuntimeError(f"exit {r.returncode}: {r.stderr.strip()[-400:]}")
    return r.stdout, wall


# ---------------------------------------------------------------- stats

def summarize(samples):
    samples = sorted(samples)
    if not samples:
        return None
    q = statistics.quantiles(samples, n=4) if len(samples) >= 2 else [samples[0]] * 3
    mean = statistics.fmean(samples)
    sd = statistics.stdev(samples) if len(samples) >= 2 else 0.0
    return dict(n_samples=len(samples), median=statistics.median(samples), min=samples[0],
                max=samples[-1], p25=q[0], p75=q[2], mean=mean, cv=100 * sd / mean if mean else 0.0)


# ---------------------------------------------------------------- main experiment loop

def run_experiment(name, args):
    exp_dir, exp = load_experiment(name)
    title = getattr(exp, "TITLE", exp_dir.name)
    unit = getattr(exp, "UNIT", "items")
    sizes = list(getattr(exp, "QUICK_SIZES", exp.SIZES) if args.quick else exp.SIZES)
    cases = list(exp.CASES)
    reference = getattr(exp, "REFERENCE", None)
    processes = args.processes or (2 if args.quick else getattr(exp, "PROCESSES", 3))
    repeats = args.repeats or (2 if args.quick else getattr(exp, "REPEATS", 5))

    build_dir = ROOT / "build" / exp_dir.name
    data_dir = ROOT / "build" / "data"
    out_dir = ROOT / ("results-quick" if args.quick else "results") / exp_dir.name
    build_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=== {exp_dir.name}: {title}")
    print(f"    sizes {[fmt_n(s) for s in sizes]}, {processes} processes x {repeats} timed runs each (+1 warm-up)")

    if hasattr(exp, "prepare"):
        t0 = time.time()
        exp.prepare(data_dir, max(sizes))
        print(f"    input data ready ({time.time() - t0:.1f} s)")

    # compile
    compiled, skipped = {}, {}
    for case in cases:
        if case["kind"] == "c":
            src = case["src"]
            key = (src, tuple(case["flags"]), tuple(case["libs"]))
            if key not in compiled:
                exe, line, err = compile_c(exp_dir, build_dir, src, case["flags"], case["libs"])
                compiled[key] = (exe, line, err)
            exe, line, err = compiled[key]
            if err:
                skipped[case["name"]] = f"compile failed: {err}"
            case["_exe"], case["_compile"] = exe, line

    def argv_for(case, n):
        if case["kind"] == "c":
            return [str(case["_exe"]), case["variant"], str(n), str(repeats), str(data_dir)]
        return [sys.executable, str(exp_dir / case["src"]), case["variant"], str(n), str(repeats), str(data_dir)]

    rows = []
    load_before = loadavg()
    started = time.time()
    for n in sizes:
        active = [c for c in cases if c["name"] not in skipped and (c["max_n"] is None or n <= c["max_n"])]
        for p in range(processes):
            k = p % len(active)
            for case in active[k:] + active[:k]:      # rotate the order each round
                env = case["env"]
                if case["kind"] == "py":
                    env = {**env, "PYTHONPATH": str(KIT)}
                try:
                    out, wall = run_process(argv_for(case, n), env, args.pin, args.timeout)
                except Exception as e:  # keep going; record the failure
                    skipped.setdefault(case["name"], f"run failed at n={n}: {e}")
                    print(f"    ! {case['name']} n={fmt_n(n)}: {e}")
                    continue
                runs, notes, mem = parse_output(out)
                for i, (warm, ns, check) in enumerate(runs):
                    rows.append(dict(size=n, case=case["name"], family=case["family"], process=p, run=i,
                                     warm=int(warm), ns=ns, check=check, process_wall_ns=wall, mem_kb=mem,
                                     note=" | ".join(notes)))
            print(f"    n={fmt_n(n)} round {p + 1}/{processes} done ({time.time() - started:.0f} s)", flush=True)

    load_after = loadavg()

    # summarise
    results = []
    for n in sizes:
        size_rows = [r for r in rows if r["size"] == n]
        ref_check = None
        if reference:
            ref_checks = [r["check"] for r in size_rows if r["case"] == reference and not r["warm"]]
            ref_check = ref_checks[0] if ref_checks else None
        if ref_check is None:
            measured = [r["check"] for r in size_rows if not r["warm"]]
            ref_check = max(set(measured), key=measured.count) if measured else None
        ref_median = None
        for case in cases:
            cr = [r for r in size_rows if r["case"] == case["name"]]
            if not cr:
                continue
            st = summarize([r["ns"] for r in cr if not r["warm"]])
            warm = [r["ns"] for r in cr if r["warm"]]
            checks = sorted({r["check"] for r in cr if not r["warm"]})
            if case["expect"] == "unused":
                answer = "not used (on purpose)"
            elif len(checks) == 1 and checks[0] == ref_check:
                answer = "same"
            elif case["expect"] == "differs":
                answer = "different (expected)"
            else:
                answer = "DIFFERENT"
            res = dict(size=n, case=case["name"], label=case.get("label", case["name"]), family=case["family"], note=case["note"],
                       compile=case.get("_compile"), **st,
                       per_item=st["median"] / n, warmup_median=statistics.median(warm) if warm else None,
                       mem_kb=max((r["mem_kb"] or 0) for r in cr), answer=answer, checks=checks,
                       extra=cr[-1]["note"])
            if case["name"] == reference:
                ref_median = st["median"]
            results.append(res)
        for res in results:
            if res["size"] == n:
                res["vs_ref"] = (ref_median / res["median"]) if ref_median and res["median"] else None

    meta = dict(experiment=exp_dir.name, title=title, unit=unit, sizes=sizes, processes=processes,
                repeats=repeats, warmup=1, pinned_cpu=args.pin, quick=args.quick,
                load_before=load_before, load_after=load_after, skipped=skipped, machine=machine_info(),
                compile_lines=sorted({c.get("_compile") for c in cases if c.get("_compile")}))
    write_outputs(out_dir, meta, rows, results, reference)
    print_summary(meta, results, reference)
    return out_dir


# ---------------------------------------------------------------- outputs

def write_outputs(out_dir, meta, rows, results, reference):
    with open(out_dir / "raw.csv", "w", newline="") as f:
        fields = ["size", "case", "family", "process", "run", "warm", "ns", "check", "process_wall_ns", "mem_kb", "note"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    with open(out_dir / "meta.json", "w") as f:
        json.dump(dict(meta, results=results), f, indent=2, default=str)

    m = meta["machine"]
    lines = [f"# {meta['title']}", "",
             f"Generated by `kit/bench.py` on {m['date']}. "
             f"{meta['processes']} fresh processes x {meta['repeats']} timed runs per case, after 1 warm-up run each.",
             "", f"- CPU: {m['cpu']} ({m['logical_cpus']} logical CPUs), governor: {m['cpu_governor']}",
             f"- OS: {m['os']}; compiler: {m['compiler']}; Python {m['python']}; zlib {m['zlib']}",
             f"- Machine load (1-minute average) before / after: {meta['load_before']} / {meta['load_after']}"
             + (f"; pinned to CPU {meta['pinned_cpu']}" if meta["pinned_cpu"] is not None else ""),
             "- **median** = middle timed run. **spread** = 25th to 75th percentile. "
             "**noise** = coefficient of variation (standard deviation / mean). "
             f"**vs ref** = how many times faster than `{reference}`.", ""]
    if meta["quick"]:
        lines.insert(2, "> QUICK RUN: fewer runs and smaller sizes. Use a full run for real numbers.\n")
    for n in meta["sizes"]:
        rs = [r for r in results if r["size"] == n]
        if not rs:
            continue
        lines += [f"## n = {n:,} {meta['unit']}", "",
                  "| case | median | per item | spread | noise | first (warm-up) run | vs ref | peak memory | answer |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for r in sorted(rs, key=lambda r: r["median"]):
            vs = f"{r['vs_ref']:.3g}x" if r.get("vs_ref") else "-"
            lines.append(f"| `{r['case']}` | {fmt_ns(r['median'])} | {fmt_ns(r['per_item'])} | "
                         f"{fmt_ns(r['p25'])} - {fmt_ns(r['p75'])} | {r['cv']:.1f}% | {fmt_ns(r['warmup_median'])} | "
                         f"{vs} | {r['mem_kb'] / 1024:.0f} MB | {r['answer']} |")
        lines.append("")
        chart = f"chart_{n}.svg"
        def faster(r):
            v = r.get("vs_ref")
            return "" if not v or r["case"] == reference else (f"{v:,.0f}x faster" if v >= 10 else f"{v:.1f}x faster")
        charts.bar_chart(out_dir / chart, f"{meta['title']} - {n:,} {meta['unit']}",
                         [(r["label"], r["median"], r["family"], faster(r)) for r in sorted(rs, key=lambda r: r["median"])],
                         f"time for {n:,} {meta['unit']} (log scale), shorter is faster"
                         + (f"; \"x faster\" compares with {next((r['label'] for r in rs if r['case'] == reference), reference)}"
                            if any(r["case"] == reference for r in rs) else ""))
        lines += [f"![chart]({chart})", ""]
    lines += ["## What each case is", "", "| case | how it was built | description |", "|---|---|---|"]
    seen = set()
    for r in results:
        if r["case"] in seen:
            continue
        seen.add(r["case"])
        lines.append(f"| `{r['case']}` | {('`' + r['compile'] + '`') if r['compile'] else 'python3'} | {r['note']} |")
    extras = [(r["size"], r["case"], r["extra"]) for r in results if r["extra"]]
    if extras:
        lines += ["", "## Extra output from the kernels", ""]
        lines += [f"- n = {n:,}, `{c}`: {e}" for n, c, e in extras]
    if meta["skipped"]:
        lines += ["", "## Skipped", ""] + [f"- `{k}`: {v}" for k, v in meta["skipped"].items()]
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n")


def print_summary(meta, results, reference):
    for n in meta["sizes"]:
        rs = sorted([r for r in results if r["size"] == n], key=lambda r: r["median"])
        if not rs:
            continue
        print(f"\n  n = {n:,} {meta['unit']}")
        print(f"  {'case':<26}{'median':>11}{'per item':>12}{'noise':>8}{'vs ref':>11}{'memory':>9}  answer")
        for r in rs:
            vs = f"{r['vs_ref']:,.3g}x" if r.get("vs_ref") and r["vs_ref"] < 1e5 else (f"{r['vs_ref']:,.0f}x" if r.get("vs_ref") else "-")
            print(f"  {r['case']:<26}{fmt_ns(r['median']):>11}{fmt_ns(r['per_item']):>12}{r['cv']:>7.1f}%"
                  f"{vs:>11}{r['mem_kb'] / 1024:>7.0f}MB  {r['answer']}")
    if meta["skipped"]:
        print("\n  skipped:", meta["skipped"])
    print(f"\n  load before/after: {meta['load_before']} / {meta['load_after']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("experiment", help="experiment folder name or prefix (e.g. 01 or 01-summing), or 'all'")
    ap.add_argument("--quick", action="store_true", help="smoke test: smaller sizes, fewer runs")
    ap.add_argument("--processes", type=int, help="fresh processes per case (default from the experiment)")
    ap.add_argument("--repeats", type=int, help="timed runs inside each process (default from the experiment)")
    ap.add_argument("--pin", type=int, help="run everything on this one CPU core (Linux, needs taskset)")
    ap.add_argument("--timeout", type=int, default=600, help="seconds before a single process is killed")
    ap.add_argument("--strict", action="store_true", help="exit with an error if any case was skipped or gave a wrong answer")
    args = ap.parse_args()
    if args.pin is not None and not shutil.which("taskset"):
        print("note: --pin needs the Linux taskset command; running unpinned")
    names = sorted(p.name for p in (ROOT / "experiments").iterdir() if p.is_dir()) if args.experiment == "all" else [args.experiment]
    problems = []
    for name in names:
        out = run_experiment(name, args)
        print(f"  -> {out.relative_to(ROOT)}/summary.md")
        meta = json.loads((out / "meta.json").read_text())
        problems += [f"{name}: {k} skipped ({v})" for k, v in meta["skipped"].items()]
        problems += [f"{name}: {r['case']} at n={r['size']} gave a DIFFERENT answer" for r in meta["results"] if r["answer"] == "DIFFERENT"]
    if problems:
        print("\nPROBLEMS:\n  " + "\n  ".join(problems))
        if args.strict:
            sys.exit(1)


if __name__ == "__main__":
    main()
