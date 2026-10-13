/*
 * Persistent storage on NVS.
 *  - namespace "rq":   device token, claim code, timezone, schedule, progress, settings
 *  - namespace "rqev": offline event ring buffer (docs/01-product-brief.md S1)
 *
 * Production: enable flash encryption + NVS encryption so the device token is not
 * readable from a dumped flash (docs/09, Phase 9).
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"
#include "quest_engine.h"

#define RQ_EVENT_CAPACITY 512

typedef enum {
    RQ_EV_WINDOW_OPEN = 1,
    RQ_EV_STEP_DONE,
    RQ_EV_STEP_UNDONE,
    RQ_EV_QUEST_COMPLETE,
    RQ_EV_QUEST_EXPIRED,
    RQ_EV_BOOT,
} rq_event_type_t;

typedef struct __attribute__((packed)) {
    uint8_t  event_id[16]; /* UUIDv4, idempotency key on the backend */
    uint32_t seq;          /* monotonic per device */
    int64_t  ts_unix;      /* 0 if wall time unknown */
    uint32_t routine_id;
    int32_t  day_index;    /* local day the event belongs to */
    uint8_t  type;         /* rq_event_type_t */
    uint8_t  step;
    uint8_t  flags;        /* QE_FLAG_* */
    uint8_t  reserved;
} rq_event_t;

typedef struct {
    uint8_t volume;     /* 0..3 */
    uint8_t brightness; /* 0..3 */
    uint8_t level;      /* from server, for ring colour */
} rq_settings_t;

esp_err_t storage_init(void);
esp_err_t storage_factory_reset(void);

esp_err_t storage_get_str(const char *key, char *out, size_t out_len);
esp_err_t storage_set_str(const char *key, const char *value);
esp_err_t storage_erase_key(const char *key);

esp_err_t storage_load_schedule(qe_schedule_t *out);
esp_err_t storage_save_schedule(const qe_schedule_t *s);
esp_err_t storage_load_progress(qe_progress_t *out);
esp_err_t storage_save_progress(const qe_progress_t *p);
esp_err_t storage_load_settings(rq_settings_t *out);
esp_err_t storage_save_settings(const rq_settings_t *s);

/* Event ring. push() drops the oldest event when full. */
esp_err_t storage_event_push(rq_event_t *ev); /* fills event_id and seq */
size_t    storage_event_count(void);
size_t    storage_event_peek(rq_event_t *out, size_t max);
esp_err_t storage_event_pop(size_t n);
