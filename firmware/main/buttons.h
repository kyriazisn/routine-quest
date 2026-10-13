#pragma once

#include <stdint.h>

#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

typedef enum {
    BTN_EVT_PRESS,       /* fires on debounced press-down (<100 ms feedback) */
    BTN_EVT_LONG,        /* held >= RQ_UNDO_HOLD_MS, fires once per hold */
    BTN_EVT_RESET_COMBO, /* buttons 1+4 held >= RQ_RESET_HOLD_MS */
} btn_evt_type_t;

typedef struct {
    btn_evt_type_t type;
    uint8_t        button;
    uint32_t       t_ms;
} btn_evt_t;

/* Starts a polling task that posts btn_evt_t to `out`. */
esp_err_t buttons_start(QueueHandle_t out);
