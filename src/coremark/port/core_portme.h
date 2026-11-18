// SPDX-License-Identifier: Apache-2.0

#ifndef ORCA_CORE_PORTME_H
#define ORCA_CORE_PORTME_H

#include <stddef.h>
#include <stdint.h>

#define HAS_FLOAT      0
#define HAS_TIME_H     0
#define USE_CLOCK      0
#define HAS_STDIO      0
#define HAS_PRINTF     0
#define SEED_METHOD    SEED_VOLATILE
#define MEM_METHOD     MEM_STATIC
#define MULTITHREAD    1
#define USE_PTHREAD    0
#define USE_FORK       0
#define USE_SOCKET     0
#define MAIN_HAS_NOARGC 1
#define MAIN_HAS_NORETURN 0

#define COMPILER_VERSION "GCC " __VERSION__
#define COMPILER_FLAGS   FLAGS_STR
#define MEM_LOCATION     "STATIC"

typedef int16_t   ee_s16;
typedef uint16_t  ee_u16;
typedef int32_t   ee_s32;
typedef float     ee_f32;
typedef uint8_t   ee_u8;
typedef uint32_t  ee_u32;
typedef uintptr_t ee_ptr_int;
typedef size_t    ee_size_t;

#ifndef NULL
#define NULL ((void *)0)
#endif

#define align_mem(x) ((void *)(4u + (((ee_ptr_int)(x) - 1u) & ~(ee_ptr_int)3u)))

#define CORETIMETYPE ee_u32
typedef ee_u32 CORE_TICKS;

extern ee_u32 default_num_contexts;
extern volatile ee_u32 coremark_port_failed;

typedef struct CORE_PORTABLE_S {
	ee_u8 portable_id;
} core_portable;

void portable_init(core_portable *port, int *argc, char *argv[]);
void portable_fini(core_portable *port);
int ee_printf(const char *format, ...);

#endif
