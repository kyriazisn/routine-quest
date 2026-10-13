#include "feedback.h"

#include <math.h>
#include <string.h>

#include "board.h"
#include "driver/ledc.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "led_strip.h"

static const char *TAG = "feedback";

typedef struct { float r, g, b; } rgb_t;

/* Button colours are fixed per position (docs/03-wireframes.md, decision 1). */
static const rgb_t BTN_COLOR[RQ_NUM_BUTTONS] = {
    { 1.00f, 0.15f, 0.15f }, /* red */
    { 0.15f, 0.35f, 1.00f }, /* blue */
    { 0.15f, 1.00f, 0.30f }, /* green */
    { 1.00f, 0.75f, 0.05f }, /* yellow */
};
/* Level colours: white, green, blue, purple, gold (docs/02-game-design.md §4.2). */
static const rgb_t LEVEL_COLOR[] = {
    { 1.0f, 1.0f, 1.0f }, { 0.2f, 1.0f, 0.3f }, { 0.2f, 0.45f, 1.0f },
    { 0.6f, 0.2f, 1.0f }, { 1.0f, 0.75f, 0.1f },
};
static const rgb_t GOLD = { 1.0f, 0.75f, 0.1f };
static const rgb_t ORANGE = { 1.0f, 0.4f, 0.0f };
static const rgb_t WHITE = { 1.0f, 1.0f, 1.0f };
static const rgb_t RED = { 1.0f, 0.0f, 0.0f };

#define FRAME_MS          33
#define COMPLETE_DIM_MS   30000

static led_strip_handle_t s_strip;
static SemaphoreHandle_t s_lock;
static QueueHandle_t s_sound_q;
static fb_scene_t s_scene;
static fb_anim_t s_anim;
static uint8_t s_anim_arg;
static int64_t s_anim_start_ms = -1;
static int64_t s_complete_at_ms = -1;

static int64_t now_ms(void) { return esp_timer_get_time() / 1000; }

/* ------------------------------------------------------------------ sound */

typedef struct { uint16_t hz; uint16_t ms; } note_t;
#define N(h, m) { (h), (m) }
static const note_t SND_UP[]       = { N(880, 70), N(1320, 110), N(0, 0) };
static const note_t SND_DOWN[]     = { N(1100, 80), N(660, 140), N(0, 0) };
static const note_t SND_TAP[]      = { N(440, 40), N(0, 0) };
static const note_t SND_DUP[]      = { N(1320, 40), N(0, 0) };
static const note_t SND_CHIME[]    = { N(784, 120), N(988, 120), N(1175, 220), N(0, 0) };
static const note_t SND_WIN[]      = { N(1047, 150), N(1319, 150), N(1568, 150), N(2093, 400), N(1, 80), N(1568, 150), N(2093, 600), N(0, 0) };
static const note_t SND_TREASURE[] = { N(1568, 100), N(1760, 100), N(1976, 100), N(2349, 100), N(2637, 500), N(0, 0) };
static const note_t SND_FANFARE[]  = { N(784, 150), N(784, 150), N(784, 150), N(1047, 600), N(0, 0) };
static const note_t SND_RESET[]    = { N(330, 600), N(0, 0) };

static const note_t *sound_for(fb_anim_t a)
{
    switch (a) {
    case FB_ANIM_STEP_DONE:   return SND_UP;
    case FB_ANIM_STEP_UNDO:   return SND_DOWN;
    case FB_ANIM_SLEEP_TAP:   return SND_TAP;
    case FB_ANIM_DUPLICATE:   return SND_DUP;
    case FB_ANIM_WINDOW_OPEN: return SND_CHIME;
    case FB_ANIM_COMPLETE:    return SND_WIN;
    case FB_ANIM_TREASURE:    return SND_TREASURE;
    case FB_ANIM_LEVEL_UP:    return SND_FANFARE;
    case FB_ANIM_RESET:       return SND_RESET;
    }
    return NULL;
}

static uint32_t duty_for_volume(uint8_t vol)
{
    /* 10-bit resolution; piezo is loudest near 50 % duty. */
    static const uint32_t duty[] = { 0, 60, 200, 512 };
    return duty[vol > 3 ? 3 : vol];
}

static void tone(uint16_t hz, uint32_t duty)
{
    if (hz <= 1 || duty == 0) {
        ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, 0);
    } else {
        ledc_set_freq(LEDC_LOW_SPEED_MODE, LEDC_TIMER_0, hz);
        ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, duty);
    }
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
}

static void sound_task(void *arg)
{
    (void)arg;
    fb_anim_t a;
    for (;;) {
        if (xQueueReceive(s_sound_q, &a, portMAX_DELAY) != pdTRUE) continue;
        const note_t *n = sound_for(a);
        xSemaphoreTake(s_lock, portMAX_DELAY);
        uint32_t duty = duty_for_volume(s_scene.volume);
        if (s_scene.night && duty > 60) duty = 60;
        xSemaphoreGive(s_lock);
        for (; n && n->ms; n++) {
            tone(n->hz, duty);
            vTaskDelay(pdMS_TO_TICKS(n->ms));
        }
        tone(0, 0);
    }
}

/* ------------------------------------------------------------------ light */

static float s_scale;

static void px(uint32_t i, rgb_t c, float k)
{
    if (k < 0) k = 0;
    if (k > 1) k = 1;
    const float s = s_scale * k;
    led_strip_set_pixel(s_strip, i, (uint32_t)(c.r * s), (uint32_t)(c.g * s), (uint32_t)(c.b * s));
}

static void button_px(uint8_t b, rgb_t c, float k) { px(RQ_BUTTON_LED_BASE + b, c, k); }

static rgb_t level_color(uint8_t level)
{
    const size_t n = sizeof(LEVEL_COLOR) / sizeof(LEVEL_COLOR[0]);
    size_t i = level == 0 ? 0 : (size_t)(level - 1);
    return LEVEL_COLOR[i >= n ? n - 1 : i];
}

static rgb_t hsv(float h)
{
    h = fmodf(h, 1.0f) * 6.0f;
    const float x = 1.0f - fabsf(fmodf(h, 2.0f) - 1.0f);
    switch ((int)h) {
    case 0: return (rgb_t){ 1, x, 0 };
    case 1: return (rgb_t){ x, 1, 0 };
    case 2: return (rgb_t){ 0, 1, x };
    case 3: return (rgb_t){ 0, x, 1 };
    case 4: return (rgb_t){ x, 0, 1 };
    default: return (rgb_t){ 1, 0, x };
    }
}

static int8_t step_of_button(const fb_scene_t *s, uint8_t b)
{
    for (uint8_t i = 0; i < s->step_count; i++) {
        if (s->button_for_step[i] == b) return (int8_t)i;
    }
    return -1;
}

static void render_base(const fb_scene_t *s, int64_t t)
{
    const float breath = 0.5f + 0.2f * sinf((float)t * 2.0f * (float)M_PI / 3000.0f); /* 30–70 %, 3 s */

    if (s->needs_setup) { /* D1 */
        const float pulse = 0.35f + 0.25f * sinf((float)t * 2.0f * (float)M_PI / 2000.0f);
        for (uint32_t i = 0; i < RQ_RING_LEDS; i++) px(i, ORANGE, pulse);
        for (uint8_t b = 0; b < RQ_NUM_BUTTONS; b++) button_px(b, WHITE, 0);
        return;
    }

    const bool open = s->state == QE_ACTIVE || s->state == QE_IN_PROGRESS || s->state == QE_COMPLETE;
    const uint8_t done = (uint8_t)__builtin_popcount(s->done_mask);

    /* Ring */
    if (open && done > 0 && s->step_count > 0) { /* D4/D6: progress in level colour */
        const uint32_t lit = (uint32_t)((done * RQ_RING_LEDS) / s->step_count);
        for (uint32_t i = 0; i < RQ_RING_LEDS; i++) px(i, level_color(s->level), i < lit ? 1.0f : 0.0f);
    } else { /* D2/D3: stars of the week */
        const float k = open ? 0.6f : 0.25f;
        for (uint32_t i = 0; i < RQ_RING_LEDS; i++) px(i, GOLD, i < s->week_stars ? k : 0.0f);
    }

    /* Buttons */
    const bool dimmed = s->state == QE_COMPLETE && s_complete_at_ms >= 0 && (t - s_complete_at_ms) > COMPLETE_DIM_MS;
    for (uint8_t b = 0; b < RQ_NUM_BUTTONS; b++) {
        const int8_t st = step_of_button(s, b);
        if (!open || st < 0) {
            button_px(b, BTN_COLOR[b], 0);
        } else if (s->done_mask & (1u << st)) {
            button_px(b, BTN_COLOR[b], dimmed ? 0.3f : 1.0f);
        } else {
            button_px(b, BTN_COLOR[b], breath);
        }
    }
}

static void render_anim(const fb_scene_t *s, int64_t t)
{
    if (s_anim_start_ms < 0) return;
    const int64_t e = t - s_anim_start_ms;
    const uint8_t b = s_anim_arg < RQ_NUM_BUTTONS ? s_anim_arg : 0;
    int64_t dur = 0;

    switch (s_anim) {
    case FB_ANIM_STEP_DONE:
        dur = 150;
        if (e < dur) button_px(b, WHITE, 1.0f);
        break;
    case FB_ANIM_DUPLICATE:
        dur = 120;
        if (e < dur) button_px(b, BTN_COLOR[b], 1.0f);
        break;
    case FB_ANIM_SLEEP_TAP:
        dur = 200;
        if (e < dur) button_px(b, BTN_COLOR[b], 0.25f);
        break;
    case FB_ANIM_STEP_UNDO:
        dur = 600;
        if (e < dur) button_px(b, BTN_COLOR[b], 1.0f - (float)e / (float)dur);
        break;
    case FB_ANIM_COMPLETE: {
        dur = 2000;
        if (e < dur) {
            const uint32_t head = (uint32_t)(e / 50) % RQ_RING_LEDS;
            for (uint32_t i = 0; i < RQ_RING_LEDS; i++) {
                const uint32_t d = (head + RQ_RING_LEDS - i) % RQ_RING_LEDS;
                px(i, level_color(s->level), d < 4 ? 1.0f - 0.25f * (float)d : 0.1f);
            }
            const bool on = (e / 125) % 2 == 0;
            for (uint8_t k = 0; k < RQ_NUM_BUTTONS; k++) {
                if (step_of_button(s, k) >= 0) button_px(k, BTN_COLOR[k], on ? 1.0f : 0.2f);
            }
        }
        break;
    }
    case FB_ANIM_TREASURE:
        dur = 3000;
        if (e < dur) {
            for (uint32_t i = 0; i < RQ_RING_LEDS; i++) px(i, GOLD, (esp_random() % 3) ? 0.3f : 1.0f);
            for (uint8_t k = 0; k < RQ_NUM_BUTTONS; k++) button_px(k, GOLD, 0.6f);
        }
        break;
    case FB_ANIM_LEVEL_UP:
        dur = 3000;
        if (e < dur) {
            for (uint32_t i = 0; i < RQ_RING_LEDS; i++) {
                px(i, hsv((float)i / RQ_RING_LEDS + (float)e / 1000.0f), 1.0f);
            }
        }
        break;
    case FB_ANIM_RESET:
        dur = 1000;
        if (e < dur) for (uint32_t i = 0; i < RQ_RING_LEDS; i++) px(i, RED, 1.0f);
        break;
    case FB_ANIM_WINDOW_OPEN:
        dur = 0; /* sound only; base scene shows breathing buttons */
        break;
    }
    if (e >= dur) s_anim_start_ms = -1;
}

static void render_task(void *arg)
{
    (void)arg;
    for (;;) {
        const int64_t t = now_ms();
        xSemaphoreTake(s_lock, portMAX_DELAY);
        const fb_scene_t s = s_scene;
        s_scale = (float)RQ_LED_MAX_BRIGHTNESS * (float)(s.brightness + 1) / 4.0f * (s.night ? 0.4f : 1.0f);
        render_base(&s, t);
        render_anim(&s, t);
        xSemaphoreGive(s_lock);
        led_strip_refresh(s_strip);
        vTaskDelay(pdMS_TO_TICKS(FRAME_MS));
    }
}

/* -------------------------------------------------------------------- API */

void feedback_init(void)
{
    s_lock = xSemaphoreCreateMutex();
    s_sound_q = xQueueCreate(4, sizeof(fb_anim_t));
    memset(&s_scene, 0, sizeof(s_scene));
    s_scene.needs_setup = true;
    s_scene.volume = 2;
    s_scene.brightness = 2;
    s_scene.level = 1;

    const led_strip_config_t strip_cfg = {
        .strip_gpio_num = RQ_LED_GPIO,
        .max_leds = RQ_LED_COUNT,
        .led_pixel_format = LED_PIXEL_FORMAT_GRB,
        .led_model = LED_MODEL_WS2812,
        .flags.invert_out = false,
    };
    const led_strip_rmt_config_t rmt_cfg = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 10 * 1000 * 1000,
        .flags.with_dma = false,
    };
    ESP_ERROR_CHECK(led_strip_new_rmt_device(&strip_cfg, &rmt_cfg, &s_strip));
    led_strip_clear(s_strip);

    const ledc_timer_config_t tcfg = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .duty_resolution = LEDC_TIMER_10_BIT,
        .timer_num = LEDC_TIMER_0,
        .freq_hz = 2000,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ESP_ERROR_CHECK(ledc_timer_config(&tcfg));
    const ledc_channel_config_t ccfg = {
        .gpio_num = RQ_BUZZER_GPIO,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = LEDC_CHANNEL_0,
        .intr_type = LEDC_INTR_DISABLE,
        .timer_sel = LEDC_TIMER_0,
        .duty = 0,
        .hpoint = 0,
    };
    ESP_ERROR_CHECK(ledc_channel_config(&ccfg));

    xTaskCreate(render_task, "fb_render", 4096, NULL, 6, NULL);
    xTaskCreate(sound_task, "fb_sound", 3072, NULL, 5, NULL);
    ESP_LOGI(TAG, "feedback ready: %d LEDs on GPIO %d, buzzer GPIO %d", RQ_LED_COUNT, RQ_LED_GPIO, RQ_BUZZER_GPIO);
}

void feedback_set_scene(const fb_scene_t *scene)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    if (scene->state == QE_COMPLETE && s_scene.state != QE_COMPLETE) {
        s_complete_at_ms = now_ms();
    } else if (scene->state != QE_COMPLETE) {
        s_complete_at_ms = -1;
    }
    s_scene = *scene;
    xSemaphoreGive(s_lock);
}

void feedback_play(fb_anim_t anim, uint8_t arg)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_anim = anim;
    s_anim_arg = arg;
    s_anim_start_ms = now_ms();
    xSemaphoreGive(s_lock);
    xQueueSend(s_sound_q, &anim, 0); /* drop sound if busy rather than block the caller */
}
