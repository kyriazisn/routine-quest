#include "buttons.h"

#include <stdbool.h>

#include "board.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/task.h"

static const char *TAG = "buttons";
static const gpio_num_t s_gpio[RQ_NUM_BUTTONS] = RQ_BUTTON_GPIOS;

typedef struct {
    bool     stable;       /* debounced state, true = pressed */
    bool     last_raw;
    uint32_t raw_since_ms; /* when last_raw last changed */
    uint32_t pressed_at_ms;
    bool     long_sent;
} btn_state_t;

static QueueHandle_t s_out;

static uint32_t now_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

static void post(btn_evt_type_t type, uint8_t button, uint32_t t)
{
    btn_evt_t ev = { .type = type, .button = button, .t_ms = t };
    if (xQueueSend(s_out, &ev, 0) != pdTRUE) {
        ESP_LOGW(TAG, "event queue full, dropped %d/%u", type, button);
    }
}

static void buttons_task(void *arg)
{
    (void)arg;
    btn_state_t st[RQ_NUM_BUTTONS] = { 0 };
    bool reset_sent = false;

    for (;;) {
        const uint32_t t = now_ms();
        for (uint8_t i = 0; i < RQ_NUM_BUTTONS; i++) {
            const bool raw = gpio_get_level(s_gpio[i]) == 0; /* active low */
            btn_state_t *b = &st[i];
            if (raw != b->last_raw) {
                b->last_raw = raw;
                b->raw_since_ms = t;
            }
            if (raw != b->stable && (t - b->raw_since_ms) >= RQ_DEBOUNCE_MS) {
                b->stable = raw;
                if (raw) {
                    b->pressed_at_ms = t;
                    b->long_sent = false;
                    post(BTN_EVT_PRESS, i, t);
                }
            }
            if (b->stable && !b->long_sent && (t - b->pressed_at_ms) >= RQ_UNDO_HOLD_MS) {
                b->long_sent = true;
                post(BTN_EVT_LONG, i, t);
            }
        }

        const btn_state_t *a = &st[RQ_RESET_BUTTON_A];
        const btn_state_t *c = &st[RQ_RESET_BUTTON_B];
        if (a->stable && c->stable) {
            const uint32_t since = a->pressed_at_ms > c->pressed_at_ms ? a->pressed_at_ms : c->pressed_at_ms;
            if (!reset_sent && (t - since) >= RQ_RESET_HOLD_MS) {
                reset_sent = true;
                post(BTN_EVT_RESET_COMBO, 0xFF, t);
            }
        } else {
            reset_sent = false;
        }

        vTaskDelay(pdMS_TO_TICKS(RQ_BUTTON_POLL_MS));
    }
}

esp_err_t buttons_start(QueueHandle_t out)
{
    s_out = out;
    uint64_t mask = 0;
    for (int i = 0; i < RQ_NUM_BUTTONS; i++) {
        mask |= 1ULL << s_gpio[i];
    }
    const gpio_config_t cfg = {
        .pin_bit_mask = mask,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&cfg));
    /* Priority above feedback/network so presses are never starved. */
    return xTaskCreate(buttons_task, "buttons", 3072, NULL, 10, NULL) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}
