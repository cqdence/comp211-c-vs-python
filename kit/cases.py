"""Helpers that experiment files use to describe what to benchmark.

    c(name, src, flags, variant)   a C kernel compiled with gcc and these flags
    py(name, src, variant)         a Python kernel run with the current python3

Optional keywords on c() and py():
    max_n    skip sizes above this (pure Python is too slow for the biggest sizes)
    env      extra environment variables for the process
    family   the bar colour/legend group: "C", "Python", "Python + my C", "Python + C library"
    expect   "differs" if this case is SUPPOSED to give a different answer (e.g. overflow demos)
    note     one-line description shown in the results table
    libs     extra linker flags for C, e.g. ["-lz"]
    label    a plain-English name for charts, e.g. "C -O2, table" (default: the case name)
"""


def c(name, src, flags, variant, max_n=None, env=None, family="C", expect=None, note="", libs=(), label=None):
    return dict(kind="c", name=name, src=src, flags=list(flags), variant=variant, max_n=max_n,
                env=env or {}, family=family, expect=expect, note=note, libs=list(libs), label=label or name)


def py(name, src, variant, max_n=None, env=None, family="Python", expect=None, note="", label=None):
    return dict(kind="py", name=name, src=src, flags=[], variant=variant, max_n=max_n,
                env=env or {}, family=family, expect=expect, note=note, libs=[], label=label or name)
