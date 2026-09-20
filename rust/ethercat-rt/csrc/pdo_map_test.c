/*
 * Executes the PDO map selection. Built and run by
 * test/test_pdo_map.py against the CI stub ecrt.h — nothing here calls an
 * ecrt_* function, so it needs no master and no libethercat.
 */
#include <ecrt.h>
#include <stdio.h>
#include <string.h>

#include "pdo_map.h"

static int failures;

static void check_map(const char *what, pdo_groups_t groups,
                      unsigned want_rx_n, unsigned want_rx_bytes,
                      unsigned want_tx_n, unsigned want_tx_bytes) {
    ec_pdo_entry_info_t rx[KALICO_RX_ENTRIES_MAX];
    ec_pdo_entry_info_t tx[KALICO_TX_ENTRIES_MAX];
    unsigned rx_bytes = 0, tx_bytes = 0;
    unsigned rx_n = kalico_copy_entries(kalico_rx_entries_all,
                                        (unsigned)KALICO_RX_ENTRIES_MAX,
                                        groups, rx, &rx_bytes);
    unsigned tx_n = kalico_copy_entries(kalico_tx_entries_all,
                                        (unsigned)KALICO_TX_ENTRIES_MAX,
                                        groups, tx, &tx_bytes);
    if (rx_n != want_rx_n || rx_bytes != want_rx_bytes
        || tx_n != want_tx_n || tx_bytes != want_tx_bytes) {
        printf("FAIL %s: rx %u entries/%u bytes (want %u/%u), "
               "tx %u entries/%u bytes (want %u/%u)\n",
               what, rx_n, rx_bytes, want_rx_n, want_rx_bytes,
               tx_n, tx_bytes, want_tx_n, want_tx_bytes);
        failures++;
        return;
    }
    printf("ok   %s: rx %u/%u tx %u/%u\n", what, rx_n, rx_bytes, tx_n, tx_bytes);
}

/* A kept group must never leave a hole: the entries that survive have to be a
 * subsequence of the canonical order, so the drive sees them in the order the
 * A6-EC map always declared. */
static void check_order_preserved(pdo_groups_t groups) {
    ec_pdo_entry_info_t out[KALICO_TX_ENTRIES_MAX];
    unsigned bytes = 0;
    unsigned n = kalico_copy_entries(kalico_tx_entries_all,
                                     (unsigned)KALICO_TX_ENTRIES_MAX, groups,
                                     out, &bytes);
    unsigned src = 0;
    for (unsigned i = 0; i < n; i++) {
        while (src < KALICO_TX_ENTRIES_MAX
               && kalico_tx_entries_all[src].index != out[i].index) {
            src++;
        }
        if (src >= KALICO_TX_ENTRIES_MAX) {
            printf("FAIL order: entry %04X is not in canonical order\n",
                   out[i].index);
            failures++;
            return;
        }
        src++;
    }
    printf("ok   order preserved for %u kept tx entries\n", n);
}

int main(void) {
    const pdo_groups_t all = {1, 1, 1};
    const pdo_groups_t none = {0, 0, 0};
    const pdo_groups_t no_ferr = {1, 1, 0};
    const pdo_groups_t estun = {0, 0, 0};

    /* a6ec keeps everything: exactly what the fixed arrays declared. */
    check_map("a6ec (all groups)", all, 6, KALICO_OUT_BYTES_FULL, 10,
              KALICO_IN_BYTES_FULL);
    /* Dropping 60F4h alone is the map this profile had before the groups
     * became droppable: nine tx entries, 28 bytes. */
    check_map("no following error", no_ferr, 6, 18, 9, 28);
    /* estun-pronet: 6040+607A+60B1+60B2 out, 603F+6041+6064+606C+6077 in. */
    check_map("estun-pronet (minimal)", estun, 4, 12, 5, 14);
    check_map("no optional groups", none, 4, 12, 5, 14);

    check_order_preserved(all);
    check_order_preserved(estun);
    check_order_preserved(no_ferr);

    if (failures) {
        printf("%d failure(s)\n", failures);
        return 1;
    }
    printf("all pdo map checks passed\n");
    return 0;
}
