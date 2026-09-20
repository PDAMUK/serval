/*
 * The cyclic PDO maps, and which optional object groups a drive family keeps.
 *
 * Split out of libecrt_igh.c so the selection logic can be executed by a test
 * without an EtherCAT master: nothing here calls an ecrt_* function, it only
 * needs ec_pdo_entry_info_t for the entry type.
 *
 * Two groups are optional because nothing in this endpoint consumes them.
 * `tx.touch_probe` and `tx.phys_outputs` are never assigned anywhere, so the
 * two RxPDO entries they feed put constant zeros on the wire; the four TxPDO
 * entries that pair with them are registered and never read back. They stay
 * mapped for the A6-EC because that is the map its drives are known to accept,
 * and a family whose dictionary has not been confirmed drops them — which is
 * also the likeliest cause of a refused map (rc=-6) on first contact.
 */
#ifndef KALICO_PDO_MAP_H
#define KALICO_PDO_MAP_H

#include <stdint.h>

typedef struct {
    int touch_probe;     /* 60B8h out; 60B9h/60BAh/60BCh in */
    int digital_io;      /* 60FEh:01 out; 60FDh in */
    int following_error; /* 60F4h in */
} pdo_groups_t;

/* Canonical maps, in the order the fixed arrays used to declare them. A
 * profile that keeps every group therefore gets byte-for-byte what was
 * declared before these became runtime-built. */
static const ec_pdo_entry_info_t kalico_rx_entries_all[] = {
    {0x6040, 0x00, 16}, {0x607A, 0x00, 32}, {0x60B8, 0x00, 16},
    {0x60FE, 0x01, 32}, {0x60B1, 0x00, 32}, {0x60B2, 0x00, 16},
};
static const ec_pdo_entry_info_t kalico_tx_entries_all[] = {
    {0x603F, 0x00, 16}, {0x6041, 0x00, 16}, {0x6064, 0x00, 32},
    {0x606C, 0x00, 32}, {0x6077, 0x00, 16}, {0x60B9, 0x00, 16},
    {0x60BA, 0x00, 32}, {0x60BC, 0x00, 32}, {0x60FD, 0x00, 32},
    {0x60F4, 0x00, 32},
};

#define KALICO_RX_ENTRIES_MAX \
    (sizeof(kalico_rx_entries_all) / sizeof(kalico_rx_entries_all[0]))
#define KALICO_TX_ENTRIES_MAX \
    (sizeof(kalico_tx_entries_all) / sizeof(kalico_tx_entries_all[0]))

/* Widths of the map with every group kept. Pinned because the A6-EC's drives
 * are running against exactly this. */
#define KALICO_OUT_BYTES_FULL 18u
#define KALICO_IN_BYTES_FULL  32u

static int kalico_entry_dropped(uint16_t index, pdo_groups_t groups) {
    switch (index) {
    case 0x60B8: case 0x60B9: case 0x60BA: case 0x60BC:
        return !groups.touch_probe;
    case 0x60FE: case 0x60FD:
        return !groups.digital_io;
    case 0x60F4:
        return !groups.following_error;
    default:
        return 0;
    }
}

/* Copy the entries this profile keeps, preserving their canonical order, and
 * report the process-image width they sum to. */
static unsigned kalico_copy_entries(const ec_pdo_entry_info_t *src, unsigned n,
                                    pdo_groups_t groups,
                                    ec_pdo_entry_info_t *dst, unsigned *bytes) {
    unsigned kept = 0;
    *bytes = 0;
    for (unsigned i = 0; i < n; i++) {
        if (kalico_entry_dropped(src[i].index, groups)) continue;
        dst[kept++] = src[i];
        *bytes += (unsigned)src[i].bit_length / 8u;
    }
    return kept;
}

#endif /* KALICO_PDO_MAP_H */
