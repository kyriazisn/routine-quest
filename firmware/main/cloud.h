/*
 * Backend client (HTTPS, TLS via the ESP x509 certificate bundle).
 *
 * Device API contract (finalised in Phase 5, docs/05-backend.md):
 *   POST /v1/device/claim   {device_id, claim_code, fw_version}  -> {device_token}
 *   POST /v1/device/events  Bearer token, {device_id, events[]}  -> {accepted}
 *                           idempotent on events[].event_id
 *   GET  /v1/device/config  Bearer token, If-None-Match: "<ver>" -> 200 config | 304
 *   401 on any authenticated call = token revoked by the parent → re-pairing needed.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "quest_engine.h"
#include "storage.h"

typedef enum {
    CLOUD_ANIM_NONE = 0,
    CLOUD_ANIM_TREASURE,
    CLOUD_ANIM_LEVEL_UP,
} cloud_anim_t;

typedef struct {
    qe_schedule_t sched;
    char          tz[64];
    rq_settings_t settings;
    uint8_t       week_stars;
    int32_t       paused_day;   /* INT32_MIN if none */
    cloud_anim_t  anim;         /* one-shot, deduplicated by anim_seq */
} cloud_config_t;

/* Starts the sync task. New configs are posted to `config_q` (cloud_config_t). */
esp_err_t cloud_start(QueueHandle_t config_q);
/* Ask for an immediate sync (e.g. right after a new event). */
void      cloud_kick(void);
bool      cloud_is_paired(void);
