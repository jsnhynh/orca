#ifndef ORCA_FIN_H
#define ORCA_FIN_H

#include <stdint.h>

/*
 * FIN accelerator interface.
 *
 * two programming models share the csr page:
 *
 *   raw tile  - the original 16x16 model, still available for debug
 *   tiled gemm - one start covers an entire A[MxK] x B[KxN] matrix product
 *
 * the tiled API performs one hardware start for a whole matrix. it contains no
 * software tile loop: the controller walks M, N, and K itself.
 *
 * software packs tensors into one permitted arena and writes their byte
 * offsets and shapes here. FIN allocates nothing. software checks the obvious
 * alignment, dimension, and span errors, but hardware repeats every
 * security-relevant range check regardless.
 */

#define ORCA_FIN_ARRAY_N 16

/* flags */
#define ORCA_FIN_FLAG_BIAS (1u << 0)
#define ORCA_FIN_FLAG_RELU (1u << 1)
#define ORCA_FIN_FLAG_RAW  (1u << 2)   /* store int32 C instead of requantizing */

/* error reasons reported in the error register, and by orca_fin_submit */
#define ORCA_FIN_ERR_NONE      0u
#define ORCA_FIN_ERR_MODE      1u
#define ORCA_FIN_ERR_ZERO_DIM  2u
#define ORCA_FIN_ERR_STRIDE    3u
#define ORCA_FIN_ERR_ALIGN     4u
#define ORCA_FIN_ERR_OVERFLOW  5u
#define ORCA_FIN_ERR_ARENA     6u
#define ORCA_FIN_ERR_AXI_READ  7u
#define ORCA_FIN_ERR_AXI_WRITE 8u
#define ORCA_FIN_ERR_CAPACITY  9u

#define ORCA_FIN_ACT_STRIP_K_MAX 1024u

/* extra software-only outcomes */
#define ORCA_FIN_ERR_BUSY      16u
#define ORCA_FIN_ERR_TIMEOUT   17u

/* which job field an error refers to */
#define ORCA_FIN_FIELD_NONE  0u
#define ORCA_FIN_FIELD_MODE  1u
#define ORCA_FIN_FIELD_FLAGS 2u
#define ORCA_FIN_FIELD_M     3u
#define ORCA_FIN_FIELD_N     4u
#define ORCA_FIN_FIELD_K     5u
#define ORCA_FIN_FIELD_A     6u
#define ORCA_FIN_FIELD_B     7u
#define ORCA_FIN_FIELD_BIAS  8u
#define ORCA_FIN_FIELD_C     9u
#define ORCA_FIN_FIELD_ARENA 10u

/*
 * the BSP-facing record mirrors the logical csr record, not the internal tile
 * counters. all offsets are byte offsets from arena_base; all strides are
 * bytes between rows.
 */
struct orca_fin_job {
    uint32_t arena_base;
    uint32_t arena_size;
    uint32_t a_offset;
    uint32_t b_offset;
    uint32_t bias_offset;
    uint32_t c_offset;
    uint16_t m;
    uint16_t n;
    uint16_t k;
    uint16_t reserved;
    uint32_t a_stride;
    uint32_t b_stride;
    uint32_t c_stride;
    uint32_t flags;
    uint32_t shift;
    uint32_t run_id;
};

/* completion record, read once a job has finished or failed */
struct orca_fin_result {
    uint32_t run_id;           /* done_id, echoed from the submitted job */
    uint32_t error;            /* ORCA_FIN_ERR_*, NONE on success */
    uint32_t error_field;      /* ORCA_FIN_FIELD_* */
    uint32_t dma_read_cycles;
    uint32_t compute_cycles;
    uint32_t dma_write_cycles;
    uint32_t stall_cycles;
    uint32_t tile_ops;
    uint32_t valid_macs_lo;
    uint32_t valid_macs_hi;
};

/* snapshot of FIN bus traffic since the last clear */
struct orca_fin_traffic {
    uint32_t dma_read_bursts;
    uint32_t dma_write_bursts;
    uint32_t dma_read_beats;
    uint32_t dma_write_beats;
    uint64_t dma_read_bytes;
    uint64_t dma_write_bytes;
    uint32_t axil_read_ops;
    uint32_t axil_write_ops;
    uint32_t dma_read_latency_cycles;
    uint32_t dma_write_latency_cycles;
    uint32_t axil_read_latency_cycles;
    uint32_t axil_write_latency_cycles;
};

/*
 * validate and start one tiled job. returns ORCA_FIN_ERR_NONE when the job was
 * accepted, ORCA_FIN_ERR_BUSY if the accelerator is still running, or the
 * software-detected reason otherwise. an accepted job is not yet complete;
 * call orca_fin_wait.
 */
uint32_t orca_fin_submit(const struct orca_fin_job *job);

/*
 * check a job in software without starting it. same reason codes as submit.
 */
uint32_t orca_fin_check(const struct orca_fin_job *job);

/*
 * wait for the job carrying run_id to finish. returns ORCA_FIN_ERR_NONE on
 * success, ORCA_FIN_ERR_TIMEOUT if the poll budget ran out, or the hardware
 * error reason. result may be NULL.
 */
uint32_t orca_fin_wait(uint32_t run_id, struct orca_fin_result *result);

/* clear while idle; snapshot after transactions drain. snapshot remains frozen */
void orca_fin_traffic_clear(void);
int orca_fin_traffic_snapshot(struct orca_fin_traffic *traffic);

/* raw 16x16 tile self test, unchanged. */
int orca_fin_self_test(uint32_t *checksum);

#endif
