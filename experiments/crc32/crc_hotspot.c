/* The "only rewrite the hot spot" option: just the table loop from crc.c, built as a shared
 * library so a Python program can call it (see the ctypes variant in crc.py).
 *
 *     gcc -O2 -shared -fPIC -o libcrc_hotspot.so crc_hotspot.c
 *
 * kit/bench.py builds this for you (experiment.py, prepare()).
 */
#include <stddef.h>
#include <stdint.h>

#define POLY 0xEDB88320u

static uint32_t TABLE[256];
static int table_ready = 0;

uint32_t crc32_table(const unsigned char *p, size_t n) {
    if (!table_ready) {                    /* build the table on the first call only */
        for (uint32_t b = 0; b < 256; b++) {
            uint32_t c = b;
            for (int k = 0; k < 8; k++)
                c = (c & 1) ? (c >> 1) ^ POLY : (c >> 1);
            TABLE[b] = c;
        }
        table_ready = 1;
    }
    uint32_t c = 0xFFFFFFFFu;
    for (size_t i = 0; i < n; i++)
        c = TABLE[(c ^ p[i]) & 0xFF] ^ (c >> 8);
    return c ^ 0xFFFFFFFFu;
}
