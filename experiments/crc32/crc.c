/* CRC-32 checksum of n bytes, in C. The same checksum faster-qr computes over a whole file
 * before turning it into QR codes, so the receiver can tell if the file arrived intact.
 *
 * A CRC treats the data as one huge binary number and divides it by a fixed "polynomial";
 * the remainder is the checksum. Division in this world is just shifts and XORs.
 *
 * Variants (the rungs of the "should you rewrite it in C?" ladder):
 *   bitwise  one byte at a time, then 8 shift/XOR steps per byte  (the textbook version)
 *   table    precompute the 8 steps for all 256 byte values once, then 1 lookup per byte
 *   slice8   8 tables, 8 bytes per step  (the idea fast libraries use)
 *   zlib     call zlib's crc32() - the same library Python's zlib.crc32 calls
 */
#include "bench.h"
#ifdef HAVE_ZLIB
#include <zlib.h>
#endif

#define POLY 0xEDB88320u   /* the standard CRC-32 polynomial, bit-reversed */

static uint32_t crc_bitwise(const unsigned char *p, long long n) {
    uint32_t c = 0xFFFFFFFFu;
    for (long long i = 0; i < n; i++) {
        c ^= p[i];
        for (int k = 0; k < 8; k++)
            c = (c & 1) ? (c >> 1) ^ POLY : (c >> 1);   /* lowest bit set? shift and XOR */
    }
    return c ^ 0xFFFFFFFFu;
}

/* T[0] is the classic 256-entry table: T[0][b] = what 8 bitwise steps do to byte b.
 * T[k] is the same thing pushed k bytes further along, so 8 bytes can be looked up at once. */
static uint32_t T[8][256];

static void make_tables(void) {
    for (uint32_t b = 0; b < 256; b++) {
        uint32_t c = b;
        for (int k = 0; k < 8; k++)
            c = (c & 1) ? (c >> 1) ^ POLY : (c >> 1);
        T[0][b] = c;
    }
    for (int k = 1; k < 8; k++)
        for (int b = 0; b < 256; b++)
            T[k][b] = (T[k - 1][b] >> 8) ^ T[0][T[k - 1][b] & 0xFF];
}

static uint32_t crc_table(const unsigned char *p, long long n) {
    uint32_t c = 0xFFFFFFFFu;
    for (long long i = 0; i < n; i++)
        c = T[0][(c ^ p[i]) & 0xFF] ^ (c >> 8);
    return c ^ 0xFFFFFFFFu;
}

/* Slicing-by-8: each step reads 8 bytes and does 8 independent lookups that are XORed together.
 * The table version has to finish one byte before it can start the next; here the 8 lookups
 * don't depend on each other, so the CPU can do several at the same time. */
static uint32_t crc_slice8(const unsigned char *p, long long n) {
    uint32_t c = 0xFFFFFFFFu;
    while (n >= 8) {
        uint32_t lo = c ^ ((uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24);
        uint32_t hi = (uint32_t)p[4] | (uint32_t)p[5] << 8 | (uint32_t)p[6] << 16 | (uint32_t)p[7] << 24;
        c = T[7][lo & 0xFF] ^ T[6][(lo >> 8) & 0xFF] ^ T[5][(lo >> 16) & 0xFF] ^ T[4][lo >> 24]
          ^ T[3][hi & 0xFF] ^ T[2][(hi >> 8) & 0xFF] ^ T[1][(hi >> 16) & 0xFF] ^ T[0][hi >> 24];
        p += 8;
        n -= 8;
    }
    while (n-- > 0)                                    /* the last 0-7 bytes, one at a time */
        c = T[0][(c ^ *p++) & 0xFF] ^ (c >> 8);
    return c ^ 0xFFFFFFFFu;
}

int main(int argc, char **argv) {
    bench_args a = parse_args(argc, argv);
    unsigned char *data = read_data(a.datadir, "crc_input.bin", a.n);
    make_tables();
    char check[16];
    for (int r = -BENCH_WARMUP; r < a.repeats; r++) {
        uint32_t crc;
        uint64_t t0 = now_ns();
        if (IS(a.variant, "bitwise")) crc = crc_bitwise(data, a.n);
        else if (IS(a.variant, "table")) crc = crc_table(data, a.n);
        else if (IS(a.variant, "slice8")) crc = crc_slice8(data, a.n);
#ifdef HAVE_ZLIB
        else if (IS(a.variant, "zlib")) crc = (uint32_t)crc32(0L, data, (uInt)a.n);
#endif
        else { fprintf(stderr, "unknown variant %s\n", a.variant); return 2; }
        uint64_t t1 = now_ns();
        snprintf(check, sizeof check, "%08x", crc);
        report(r, t1 - t0, check);
    }
    free(data);
    report_mem();
    return 0;
}
