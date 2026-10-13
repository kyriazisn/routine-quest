#include "storage.h"

#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "esp_random.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "nvs.h"
#include "nvs_flash.h"

static const char *TAG = "storage";
static const char *NS_CFG = "rq";
static const char *NS_EV = "rqev";

static SemaphoreHandle_t s_lock;
static nvs_handle_t s_cfg;
static nvs_handle_t s_ev;
static uint32_t s_head, s_tail, s_seq;

#define LOCK()   xSemaphoreTake(s_lock, portMAX_DELAY)
#define UNLOCK() xSemaphoreGive(s_lock)

static void slot_key(uint32_t idx, char key[8])
{
    snprintf(key, 8, "e%03u", (unsigned)(idx % RQ_EVENT_CAPACITY));
}

esp_err_t storage_init(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "NVS needs erase (%s)", esp_err_to_name(err));
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    s_lock = xSemaphoreCreateMutex();
    ESP_ERROR_CHECK(nvs_open(NS_CFG, NVS_READWRITE, &s_cfg));
    ESP_ERROR_CHECK(nvs_open(NS_EV, NVS_READWRITE, &s_ev));
    nvs_get_u32(s_ev, "head", &s_head);
    nvs_get_u32(s_ev, "tail", &s_tail);
    nvs_get_u32(s_ev, "seq", &s_seq);
    ESP_LOGI(TAG, "event ring: %u pending, seq=%u", (unsigned)(s_tail - s_head), (unsigned)s_seq);
    return ESP_OK;
}

esp_err_t storage_factory_reset(void)
{
    /* Erases Wi-Fi credentials (nvs.net80211), tokens, schedule and events. */
    nvs_close(s_cfg);
    nvs_close(s_ev);
    return nvs_flash_erase();
}

/* ------------------------------------------------------------ key/value */

esp_err_t storage_get_str(const char *key, char *out, size_t out_len)
{
    LOCK();
    size_t len = out_len;
    esp_err_t err = nvs_get_str(s_cfg, key, out, &len);
    UNLOCK();
    return err;
}

esp_err_t storage_set_str(const char *key, const char *value)
{
    LOCK();
    esp_err_t err = nvs_set_str(s_cfg, key, value);
    if (err == ESP_OK) err = nvs_commit(s_cfg);
    UNLOCK();
    return err;
}

esp_err_t storage_erase_key(const char *key)
{
    LOCK();
    esp_err_t err = nvs_erase_key(s_cfg, key);
    if (err == ESP_OK) err = nvs_commit(s_cfg);
    UNLOCK();
    return err == ESP_ERR_NVS_NOT_FOUND ? ESP_OK : err;
}

static esp_err_t get_blob(const char *key, void *out, size_t len)
{
    LOCK();
    size_t got = len;
    esp_err_t err = nvs_get_blob(s_cfg, key, out, &got);
    UNLOCK();
    if (err == ESP_OK && got != len) {
        return ESP_ERR_INVALID_SIZE; /* layout changed between firmware versions */
    }
    return err;
}

static esp_err_t set_blob(const char *key, const void *in, size_t len)
{
    LOCK();
    esp_err_t err = nvs_set_blob(s_cfg, key, in, len);
    if (err == ESP_OK) err = nvs_commit(s_cfg);
    UNLOCK();
    return err;
}

esp_err_t storage_load_schedule(qe_schedule_t *out)          { return get_blob("sched", out, sizeof(*out)); }
esp_err_t storage_save_schedule(const qe_schedule_t *s)      { return set_blob("sched", s, sizeof(*s)); }
esp_err_t storage_load_progress(qe_progress_t *out)          { return get_blob("prog", out, sizeof(*out)); }
esp_err_t storage_save_progress(const qe_progress_t *p)      { return set_blob("prog", p, sizeof(*p)); }
esp_err_t storage_load_settings(rq_settings_t *out)          { return get_blob("settings", out, sizeof(*out)); }
esp_err_t storage_save_settings(const rq_settings_t *s)      { return set_blob("settings", s, sizeof(*s)); }

/* ------------------------------------------------------------ event ring */

esp_err_t storage_event_push(rq_event_t *ev)
{
    esp_fill_random(ev->event_id, sizeof(ev->event_id));
    ev->event_id[6] = (uint8_t)((ev->event_id[6] & 0x0F) | 0x40); /* UUID v4 */
    ev->event_id[8] = (uint8_t)((ev->event_id[8] & 0x3F) | 0x80); /* RFC 4122 variant */

    LOCK();
    ev->seq = ++s_seq;
    if (s_tail - s_head >= RQ_EVENT_CAPACITY) {
        ESP_LOGW(TAG, "event ring full, dropping oldest");
        s_head++;
        nvs_set_u32(s_ev, "head", s_head);
    }
    char key[8];
    slot_key(s_tail, key);
    esp_err_t err = nvs_set_blob(s_ev, key, ev, sizeof(*ev));
    if (err == ESP_OK) {
        s_tail++;
        nvs_set_u32(s_ev, "tail", s_tail);
        nvs_set_u32(s_ev, "seq", s_seq);
        err = nvs_commit(s_ev);
    }
    UNLOCK();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "event push failed: %s", esp_err_to_name(err));
    }
    return err;
}

size_t storage_event_count(void)
{
    LOCK();
    size_t n = (size_t)(s_tail - s_head);
    UNLOCK();
    return n;
}

size_t storage_event_peek(rq_event_t *out, size_t max)
{
    LOCK();
    size_t n = 0;
    for (uint32_t i = s_head; i != s_tail && n < max; i++) {
        char key[8];
        slot_key(i, key);
        size_t len = sizeof(rq_event_t);
        if (nvs_get_blob(s_ev, key, &out[n], &len) == ESP_OK && len == sizeof(rq_event_t)) {
            n++;
        } else {
            break; /* corrupt slot: stop here; pop() will skip it on next ack */
        }
    }
    UNLOCK();
    return n;
}

esp_err_t storage_event_pop(size_t n)
{
    LOCK();
    uint32_t avail = s_tail - s_head;
    s_head += (n > avail) ? avail : (uint32_t)n;
    nvs_set_u32(s_ev, "head", s_head);
    esp_err_t err = nvs_commit(s_ev);
    UNLOCK();
    return err;
}
