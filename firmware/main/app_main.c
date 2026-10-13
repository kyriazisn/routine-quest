/*
 * Routine Quest firmware — orchestration.
 *
 * Tasks:
 *   main      (prio 1)  : owns the quest engine; handles buttons, ticks, config
 *   buttons   (prio 10) : 5 ms polling, debounce, long-press, reset combo
 *   fb_render (prio 6)  : 30 fps LED rendering
 *   fb_sound  (prio 5)  : buzzer melodies
 *   cloud     (prio 4)  : claim, event upload, config poll, OTA
 */
#include <limits.h>
#include <string.h>
#include <time.h>

#include "board.h"
#include "buttons.h"
#include "cloud.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "feedback.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "net.h"
#include "ota.h"
#include "quest_engine.h"
#include "sdkconfig.h"
#include "storage.h"

static const char *TAG = "app";

#define NIGHT_START_MIN (20 * 60 + 30)
#define NIGHT_END_MIN   (6 * 60 + 30)

static qe_engine_t s_eng;
static qe_schedule_t s_sched;
static rq_settings_t s_settings = { .volume = 2, .brightness = 2, .level = 1 };
static QueueHandle_t s_btn_q;
static QueueHandle_t s_cfg_q;

static bool get_clock(qe_clock_t *c)
{
    c->mono_ms = (uint32_t)(esp_timer_get_time() / 1000);
    if (!net_time_valid()) return false;
    const time_t t = time(NULL);
    struct tm tm;
    localtime_r(&t, &tm);
    c->day_index = qe_days_from_civil(tm.tm_year + 1900, (uint32_t)tm.tm_mon + 1, (uint32_t)tm.tm_mday);
    c->weekday = (uint8_t)((tm.tm_wday + 6) % 7);
    c->minute_of_day = (uint16_t)(tm.tm_hour * 60 + tm.tm_min);
    return true;
}

static void update_scene(const qe_clock_t *c, bool time_ok)
{
    fb_scene_t s = { 0 };
    s.needs_setup = !net_is_provisioned() || !time_ok || s_sched.routine_count == 0;
    s.state = s_eng.state;
    s.done_mask = s_eng.done_mask;
    s.week_stars = s_eng.week_stars;
    s.level = s_settings.level;
    s.volume = s_settings.volume;
    s.brightness = s_settings.brightness;
    s.night = time_ok && (c->minute_of_day >= NIGHT_START_MIN || c->minute_of_day < NIGHT_END_MIN);
    const qe_routine_t *r = qe_active_routine(&s_eng);
    if (r) {
        s.step_count = r->step_count;
        memcpy(s.button_for_step, r->button_for_step, sizeof(s.button_for_step));
    }
    feedback_set_scene(&s);
}

static void record(rq_event_type_t type, const qe_out_t *o, const qe_clock_t *c)
{
    rq_event_t ev = { 0 };
    ev.type = (uint8_t)type;
    ev.ts_unix = net_time_valid() ? (int64_t)time(NULL) : 0;
    ev.day_index = c ? c->day_index : 0;
    if (o) {
        ev.routine_id = o->routine_id;
        ev.step = o->step;
        ev.flags = o->flags;
    }
    storage_event_push(&ev);
    cloud_kick();
}

static const char *out_name(qe_out_type_t t);

static void handle_out(const qe_out_t *o, const qe_clock_t *c)
{
    bool progress_changed = true;
    if (o->type != QE_OUT_NONE) {
        /* Stable log format; the Wokwi CI scenario matches on these lines. */
        ESP_LOGI(TAG, "quest: %s routine=%u button=%u done=%u/%u state=%d stars=%u%s", out_name(o->type),
                 (unsigned)o->routine_id, o->button == QE_BUTTON_UNUSED ? 0u : o->button + 1u,
                 o->done_count, o->step_count, s_eng.state, s_eng.week_stars,
                 (o->flags & QE_FLAG_FAST) ? " FAST" : "");
    }
    switch (o->type) {
    case QE_OUT_WINDOW_OPEN:
        feedback_play(FB_ANIM_WINDOW_OPEN, 0);
        record(RQ_EV_WINDOW_OPEN, o, c);
        break;
    case QE_OUT_STEP_DONE:
        feedback_play(FB_ANIM_STEP_DONE, o->button);
        record(RQ_EV_STEP_DONE, o, c);
        break;
    case QE_OUT_STEP_UNDONE:
        feedback_play(FB_ANIM_STEP_UNDO, o->button);
        record(RQ_EV_STEP_UNDONE, o, c);
        break;
    case QE_OUT_QUEST_COMPLETE:
        feedback_play(FB_ANIM_COMPLETE, o->button);
        record(RQ_EV_QUEST_COMPLETE, o, c);
        break;
    case QE_OUT_QUEST_EXPIRED:
        record(RQ_EV_QUEST_EXPIRED, o, c); /* no negative signal to the child */
        break;
    case QE_OUT_SLEEP_PRESS:
        feedback_play(FB_ANIM_SLEEP_TAP, o->button);
        progress_changed = false;
        break;
    case QE_OUT_DUPLICATE_PRESS:
        feedback_play(FB_ANIM_DUPLICATE, o->button);
        progress_changed = false;
        break;
    case QE_OUT_NONE:
        progress_changed = false;
        break;
    }
    if (progress_changed) {
        const qe_progress_t p = qe_get_progress(&s_eng);
        storage_save_progress(&p);
    }
}

static void apply_config(const cloud_config_t *cfg)
{
    if (cfg->sched.version != s_sched.version || memcmp(&cfg->sched, &s_sched, sizeof(s_sched)) != 0) {
        s_sched = cfg->sched;
        qe_set_schedule(&s_eng, &s_sched);
        storage_save_schedule(&s_sched);
        ESP_LOGI(TAG, "schedule v%u applied (%u routines)", (unsigned)s_sched.version, s_sched.routine_count);
    }
    if (cfg->tz[0]) {
        char cur[64] = { 0 };
        storage_get_str("tz", cur, sizeof(cur));
        if (strcmp(cur, cfg->tz) != 0) {
            storage_set_str("tz", cfg->tz);
            net_set_timezone(cfg->tz);
        }
    }
    const uint8_t old_level = s_settings.level;
    s_settings.volume = cfg->settings.volume;
    s_settings.brightness = cfg->settings.brightness;
    s_settings.level = cfg->settings.level ? cfg->settings.level : old_level;
    storage_save_settings(&s_settings);
    qe_set_week_stars(&s_eng, cfg->week_stars); /* backend is the source of truth */
    qe_set_paused_day(&s_eng, cfg->paused_day);

    if (cfg->anim == CLOUD_ANIM_TREASURE) feedback_play(FB_ANIM_TREASURE, 0);
    else if (cfg->anim == CLOUD_ANIM_LEVEL_UP) feedback_play(FB_ANIM_LEVEL_UP, 0);
}

#if CONFIG_RQ_SIM_MODE
/* Demo schedule for the simulator: a quest is always active.
 *   00:00–12:00 "morning": all 4 buttons
 *   12:00–24:00 "evening": buttons 4, 2, 1 (button 3 = not part of the quest) */
static void load_sim_schedule(void)
{
    memset(&s_sched, 0, sizeof(s_sched));
    s_sched.version = 1;
    s_sched.routine_count = 2;
    s_sched.routines[0] = (qe_routine_t){ .routine_id = 1, .start_min = 0, .end_min = 12 * 60,
                                          .days_mask = 0x7F, .step_count = 4,
                                          .button_for_step = { 0, 1, 2, 3 } };
    s_sched.routines[1] = (qe_routine_t){ .routine_id = 2, .start_min = 12 * 60, .end_min = 24 * 60,
                                          .days_mask = 0x7F, .step_count = 3,
                                          .button_for_step = { 3, 1, 0 } };
    net_set_timezone("EET-2EEST,M3.5.0/3,M10.5.0/4"); /* Europe/Athens */
}
#endif

static const char *out_name(qe_out_type_t t)
{
    switch (t) {
    case QE_OUT_WINDOW_OPEN:     return "WINDOW_OPEN";
    case QE_OUT_STEP_DONE:       return "STEP_DONE";
    case QE_OUT_STEP_UNDONE:     return "STEP_UNDONE";
    case QE_OUT_QUEST_COMPLETE:  return "QUEST_COMPLETE";
    case QE_OUT_QUEST_EXPIRED:   return "QUEST_EXPIRED";
    case QE_OUT_SLEEP_PRESS:     return "SLEEP_PRESS";
    case QE_OUT_DUPLICATE_PRESS: return "DUPLICATE_PRESS";
    case QE_OUT_NONE:            return "NONE";
    }
    return "?";
}

static void factory_reset(void)
{
    ESP_LOGW(TAG, "factory reset requested");
    feedback_play(FB_ANIM_RESET, 0);
    vTaskDelay(pdMS_TO_TICKS(1200));
    storage_factory_reset();
    esp_restart();
}

void app_main(void)
{
    ESP_LOGI(TAG, "Routine Quest firmware %s", ota_running_version());
    ESP_ERROR_CHECK(storage_init());

    if (storage_load_settings(&s_settings) != ESP_OK) {
        s_settings = (rq_settings_t){ .volume = 2, .brightness = 2, .level = 1 };
    }
    if (storage_load_schedule(&s_sched) != ESP_OK || !qe_schedule_valid(&s_sched)) {
        memset(&s_sched, 0, sizeof(s_sched));
    }
    char tz[64];
    if (storage_get_str("tz", tz, sizeof(tz)) == ESP_OK) net_set_timezone(tz);
#if CONFIG_RQ_SIM_MODE
    ESP_LOGW(TAG, "SIMULATION MODE — demo schedule, no backend. Not for production.");
    load_sim_schedule();
#endif

    qe_init(&s_eng, &s_sched, RQ_FAST_QUEST_MS);
    feedback_init();

    s_btn_q = xQueueCreate(16, sizeof(btn_evt_t));
    s_cfg_q = xQueueCreate(1, sizeof(cloud_config_t));
    ESP_ERROR_CHECK(buttons_start(s_btn_q));

    /* TODO(phase-6/7): per-device PoP written to a factory NVS partition at manufacturing.
     * CONFIG_RQ_DEV_POP is for development boards only. */
    ESP_ERROR_CHECK(net_start(CONFIG_RQ_DEV_POP));
#if !CONFIG_RQ_SIM_MODE
    ESP_ERROR_CHECK(cloud_start(s_cfg_q)); /* events stay queued in NVS in simulation */
#endif
    record(RQ_EV_BOOT, NULL, NULL);
    ESP_LOGI(TAG, "device %s (%s), paired=%d", net_device_id(), net_device_name(), cloud_is_paired());

    bool restored = false;
    uint32_t last_tick_ms = 0;
    for (;;) {
        btn_evt_t ev;
        const bool got = xQueueReceive(s_btn_q, &ev, pdMS_TO_TICKS(200)) == pdTRUE;

        cloud_config_t cfg;
        if (xQueueReceive(s_cfg_q, &cfg, 0) == pdTRUE) apply_config(&cfg);

        qe_clock_t c;
        const bool time_ok = get_clock(&c);
        if (time_ok && !restored) {
            qe_progress_t p;
            if (storage_load_progress(&p) == ESP_OK) qe_restore_progress(&s_eng, &p, &c);
            restored = true;
            ESP_LOGI(TAG, "ready: time synced, day=%ld weekday=%u minute=%u",
                     (long)c.day_index, c.weekday, c.minute_of_day);
        }

        if (got) {
            if (ev.type == BTN_EVT_RESET_COMBO) {
                factory_reset();
            } else if (!time_ok) {
                feedback_play(FB_ANIM_SLEEP_TAP, ev.button);
            } else {
                const qe_out_t o = ev.type == BTN_EVT_PRESS ? qe_press(&s_eng, &c, ev.button)
                                                            : qe_long_press(&s_eng, &c, ev.button);
                handle_out(&o, &c);
            }
        }

        if (time_ok && c.mono_ms - last_tick_ms >= 1000) {
            last_tick_ms = c.mono_ms;
            const qe_out_t o = qe_tick(&s_eng, &c);
            handle_out(&o, &c);
        }
        update_scene(&c, time_ok);
    }
}
