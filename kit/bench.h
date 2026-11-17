/*
 * bench.h - shared helpers for every C benchmark kernel in this repo.
 *
 * Every kernel program is run as:
 *     ./kernel <variant> <n> <repeats> <datadir>
 * and prints one line per timed run:
 *     WARM <ns> <check>      (warm-up run, recorded but not used in stats)
 *     RUN  <ns> <check>      (measured run)
 *     NOTE <text>            (optional extra info)
 *     MEM  <kb>              (peak memory of the whole process, printed once at the end)
 *
 * <check> is the answer the kernel computed. The harness compares it across
 * languages so we know every version did the same work - and printing it stops
 * the compiler from deleting the computation (dead code elimination).
 */
#ifndef BENCH_H
#define BENCH_H

#ifdef __APPLE__
#define _DARWIN_C_SOURCE
#else
#define _POSIX_C_SOURCE 199309L
#endif
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/resource.h>

#define BENCH_WARMUP 1

/* Monotonic clock in nanoseconds. Monotonic = never jumps if the wall clock is changed.
 * On macOS, CLOCK_MONOTONIC only counts whole microseconds, which is far too coarse for a run that
 * takes a few hundred nanoseconds. CLOCK_UPTIME_RAW is finer, and it is the same clock Python's
 * time.perf_counter_ns() uses on macOS, so C and Python are timed alike. */
static inline uint64_t now_ns(void) {
#ifdef __APPLE__
    return clock_gettime_nsec_np(CLOCK_UPTIME_RAW);
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
#endif
}

/* r < 0 means a warm-up run. */
static inline void report(int r, uint64_t ns, const char *check) {
    printf("%s %llu %s\n", r < 0 ? "WARM" : "RUN", (unsigned long long)ns, check);
    fflush(stdout);
}

/* Peak memory of this program. On Linux we read VmHWM ("high water mark") from /proc,
 * because getrusage's ru_maxrss also counts the memory of the process that launched us. */
static inline void report_mem(void) {
    long kb = -1;
    FILE *f = fopen("/proc/self/status", "r");
    if (f) {
        char line[256];
        while (fgets(line, sizeof line, f))
            if (sscanf(line, "VmHWM: %ld", &kb) == 1) break;
        fclose(f);
    }
    if (kb < 0) {
        struct rusage ru;
        getrusage(RUSAGE_SELF, &ru);
#ifdef __APPLE__
        kb = ru.ru_maxrss / 1024; /* macOS reports bytes */
#else
        kb = ru.ru_maxrss;        /* Linux reports kilobytes */
#endif
    }
    printf("MEM %ld\n", kb);
}

typedef struct {
    const char *variant;
    long long n;
    int repeats;
    const char *datadir;
} bench_args;

static inline bench_args parse_args(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: %s <variant> <n> <repeats> [datadir]\n", argv[0]);
        exit(2);
    }
    bench_args a;
    a.variant = argv[1];
    a.n = atoll(argv[2]);
    a.repeats = atoi(argv[3]);
    a.datadir = argc > 4 ? argv[4] : ".";
    return a;
}

/* Read the first n bytes of datadir/name into a malloc'd buffer (plus a 0 byte). */
static inline unsigned char *read_data(const char *datadir, const char *name, long long n) {
    char path[4096];
    snprintf(path, sizeof path, "%s/%s", datadir, name);
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); exit(1); }
    unsigned char *buf = malloc((size_t)n + 1);
    if (!buf) { fprintf(stderr, "out of memory\n"); exit(1); }
    size_t got = fread(buf, 1, (size_t)n, f);
    fclose(f);
    if ((long long)got != n) { fprintf(stderr, "%s: wanted %lld bytes, got %zu\n", path, n, got); exit(1); }
    buf[n] = 0;
    return buf;
}

#define IS(v, name) (strcmp((v), (name)) == 0)

#endif
