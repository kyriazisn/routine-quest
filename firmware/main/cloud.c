#include "cloud.h"

#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/task.h"
#include "net.h"
#include "ota.h"
#include "sdkconfig.h"

static const char *TAG = "cloud";

#define EVENT_BATCH        20
#define MAX_BATCHES        5
#define SYNC_INTERVAL_MS   15000
#define CONFIG_INTERVAL_MS 60000
#define RESP_CAP           4096
#define TOKEN_LEN          128

static TaskHandle_t s_task;
static QueueHandle_t s_config_q;
static char s_token[TOKEN_LEN];
static uint32_t s_cfg_version;
static int64_t s_last_config_ms = -CONFIG_INTERVAL_MS;

bool cloud_is_paired(void) { return s_token[0] != '\0'; }
void cloud_kick(void)       { if (s_task) xTaskNotifyGive(s_task); }

static int64_t now_ms(void) { return esp_timer_get_time() / 1000; }

/* ----------------------------------------------------------------- HTTP */

typedef struct {
    const char *method;
    const char *path;
    const char *body;       /* may be NULL */
    bool        auth;
    const char *if_none_match;
    char       *resp;       /* may be NULL */
    size_t      resp_cap;
} http_req_t;

static int http_do(const http_req_t *r)
{
    char url[192];
    snprintf(url, sizeof(url), "%s%s", CONFIG_RQ_API_BASE_URL, r->path);
    const esp_http_client_config_t cfg = {
        .url = url,
        .method = strcmp(r->method, "POST") == 0 ? HTTP_METHOD_POST : HTTP_METHOD_GET,
        .crt_bundle_attach = esp_crt_bundle_attach,
        .timeout_ms = 10000,
    };
    esp_http_client_handle_t c = esp_http_client_init(&cfg);
    if (!c) return -1;

    esp_http_client_set_header(c, "User-Agent", "routine-quest-fw");
    esp_http_client_set_header(c, "X-Device-Id", net_device_id());
    esp_http_client_set_header(c, "X-Fw-Version", ota_running_version());
    if (r->body) esp_http_client_set_header(c, "Content-Type", "application/json");
    if (r->auth) {
        char h[TOKEN_LEN + 8];
        snprintf(h, sizeof(h), "Bearer %s", s_token);
        esp_http_client_set_header(c, "Authorization", h);
    }
    if (r->if_none_match) esp_http_client_set_header(c, "If-None-Match", r->if_none_match);

    int status = -1;
    const int body_len = r->body ? (int)strlen(r->body) : 0;
    if (esp_http_client_open(c, body_len) == ESP_OK) {
        if (body_len == 0 || esp_http_client_write(c, r->body, body_len) == body_len) {
            esp_http_client_fetch_headers(c);
            status = esp_http_client_get_status_code(c);
            if (r->resp && r->resp_cap > 0) {
                int n = esp_http_client_read_response(c, r->resp, (int)r->resp_cap - 1);
                r->resp[n > 0 ? n : 0] = '\0';
            }
        }
    }
    esp_http_client_close(c);
    esp_http_client_cleanup(c);
    return status;
}

static void handle_unauthorized(void)
{
    ESP_LOGW(TAG, "device token rejected (revoked?) — re-pair with factory reset");
    s_token[0] = '\0';
    storage_erase_key("token");
}

/* ---------------------------------------------------------------- claim */

static bool try_claim(char *resp)
{
    char code[72];
    if (storage_get_str("claim", code, sizeof(code)) != ESP_OK) return false;

    cJSON *b = cJSON_CreateObject();
    cJSON_AddStringToObject(b, "device_id", net_device_id());
    cJSON_AddStringToObject(b, "claim_code", code);
    cJSON_AddStringToObject(b, "fw_version", ota_running_version());
    char *body = cJSON_PrintUnformatted(b);
    cJSON_Delete(b);

    const http_req_t r = { .method = "POST", .path = "/v1/device/claim", .body = body,
                           .resp = resp, .resp_cap = RESP_CAP };
    const int st = http_do(&r);
    free(body);

    if (st == 200) {
        cJSON *j = cJSON_Parse(resp);
        const cJSON *t = cJSON_GetObjectItem(j, "device_token");
        if (cJSON_IsString(t) && strlen(t->valuestring) < TOKEN_LEN) {
            strcpy(s_token, t->valuestring);
            storage_set_str("token", s_token);
            storage_erase_key("claim");
            ESP_LOGI(TAG, "device claimed");
        }
        cJSON_Delete(j);
    } else if (st == 400 || st == 404 || st == 409 || st == 410) {
        ESP_LOGW(TAG, "claim code rejected (%d), discarding", st);
        storage_erase_key("claim");
    }
    return cloud_is_paired();
}

/* --------------------------------------------------------------- events */

static const char *event_type_str(uint8_t t)
{
    switch (t) {
    case RQ_EV_WINDOW_OPEN:    return "window_open";
    case RQ_EV_STEP_DONE:      return "step_done";
    case RQ_EV_STEP_UNDONE:    return "step_undone";
    case RQ_EV_QUEST_COMPLETE: return "quest_complete";
    case RQ_EV_QUEST_EXPIRED:  return "quest_expired";
    case RQ_EV_BOOT:           return "boot";
    default:                   return "unknown";
    }
}

static void uuid_str(const uint8_t u[16], char out[37])
{
    snprintf(out, 37, "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
             u[0], u[1], u[2], u[3], u[4], u[5], u[6], u[7], u[8], u[9], u[10], u[11], u[12], u[13], u[14], u[15]);
}

static void flush_events(void)
{
    static rq_event_t batch[EVENT_BATCH];
    for (int round = 0; round < MAX_BATCHES; round++) {
        const size_t n = storage_event_peek(batch, EVENT_BATCH);
        if (n == 0) return;

        cJSON *root = cJSON_CreateObject();
        cJSON_AddStringToObject(root, "device_id", net_device_id());
        cJSON *arr = cJSON_AddArrayToObject(root, "events");
        for (size_t i = 0; i < n; i++) {
            const rq_event_t *e = &batch[i];
            char id[37];
            uuid_str(e->event_id, id);
            cJSON *o = cJSON_CreateObject();
            cJSON_AddStringToObject(o, "event_id", id);
            cJSON_AddNumberToObject(o, "seq", e->seq);
            cJSON_AddStringToObject(o, "type", event_type_str(e->type));
            cJSON_AddNumberToObject(o, "ts", (double)e->ts_unix);
            cJSON_AddNumberToObject(o, "day_index", e->day_index);
            cJSON_AddNumberToObject(o, "routine_id", e->routine_id);
            cJSON_AddNumberToObject(o, "step", e->step);
            cJSON_AddBoolToObject(o, "fast", (e->flags & QE_FLAG_FAST) != 0);
            cJSON_AddItemToArray(arr, o);
        }
        char *body = cJSON_PrintUnformatted(root);
        cJSON_Delete(root);

        const http_req_t r = { .method = "POST", .path = "/v1/device/events", .body = body, .auth = true };
        const int st = http_do(&r);
        free(body);

        if (st >= 200 && st < 300) {
            storage_event_pop(n); /* backend dedupes on event_id, so a lost ack is safe to resend */
        } else if (st == 401) {
            handle_unauthorized();
            return;
        } else if (st == 400 || st == 422) {
            ESP_LOGE(TAG, "backend rejected event batch (%d), dropping %u events", st, (unsigned)n);
            storage_event_pop(n); /* poison batch must not block the queue forever */
        } else {
            ESP_LOGW(TAG, "event upload failed (%d), %u pending", st, (unsigned)storage_event_count());
            return;
        }
    }
}

/* --------------------------------------------------------------- config */

static bool parse_config(const char *json, cloud_config_t *out, char *ota_ver, char *ota_url)
{
    cJSON *j = cJSON_Parse(json);
    if (!j) return false;
    memset(out, 0, sizeof(*out));
    out->paused_day = INT32_MIN;
    bool ok = true;

    const cJSON *v = cJSON_GetObjectItem(j, "version");
    out->sched.version = cJSON_IsNumber(v) ? (uint32_t)v->valuedouble : 0;

    const cJSON *tz = cJSON_GetObjectItem(j, "tz");
    if (cJSON_IsString(tz)) strncpy(out->tz, tz->valuestring, sizeof(out->tz) - 1);

    const cJSON *x;
    if (cJSON_IsNumber(x = cJSON_GetObjectItem(j, "volume")))     out->settings.volume = (uint8_t)x->valueint;
    if (cJSON_IsNumber(x = cJSON_GetObjectItem(j, "brightness"))) out->settings.brightness = (uint8_t)x->valueint;
    if (cJSON_IsNumber(x = cJSON_GetObjectItem(j, "level")))      out->settings.level = (uint8_t)x->valueint;
    if (cJSON_IsNumber(x = cJSON_GetObjectItem(j, "week_stars"))) out->week_stars = (uint8_t)x->valueint;
    if (cJSON_IsNumber(x = cJSON_GetObjectItem(j, "paused_day"))) out->paused_day = x->valueint;

    const cJSON *routines = cJSON_GetObjectItem(j, "routines");
    const cJSON *r;
    cJSON_ArrayForEach(r, routines) {
        if (out->sched.routine_count >= QE_MAX_ROUTINES) { ok = false; break; }
        const cJSON *id = cJSON_GetObjectItem(r, "id");
        const cJSON *start = cJSON_GetObjectItem(r, "start_min");
        const cJSON *end = cJSON_GetObjectItem(r, "end_min");
        const cJSON *days = cJSON_GetObjectItem(r, "days");
        const cJSON *btns = cJSON_GetObjectItem(r, "buttons");
        if (!cJSON_IsNumber(id) || !cJSON_IsNumber(start) || !cJSON_IsNumber(end) ||
            !cJSON_IsNumber(days) || !cJSON_IsArray(btns)) {
            ok = false;
            break;
        }
        qe_routine_t *q = &out->sched.routines[out->sched.routine_count++];
        q->routine_id = (uint32_t)id->valuedouble;
        q->start_min = (uint16_t)start->valueint;
        q->end_min = (uint16_t)end->valueint;
        q->days_mask = (uint8_t)days->valueint;
        const cJSON *b;
        cJSON_ArrayForEach(b, btns) {
            if (q->step_count >= QE_MAX_STEPS) { ok = false; break; }
            q->button_for_step[q->step_count++] = (uint8_t)b->valueint;
        }
    }

    const cJSON *anim = cJSON_GetObjectItem(j, "anim");
    if (cJSON_IsObject(anim)) {
        const cJSON *seq = cJSON_GetObjectItem(anim, "seq");
        const cJSON *type = cJSON_GetObjectItem(anim, "type");
        char last[16] = "0";
        storage_get_str("animseq", last, sizeof(last));
        if (cJSON_IsNumber(seq) && cJSON_IsString(type) && (uint32_t)seq->valuedouble > strtoul(last, NULL, 10)) {
            out->anim = strcmp(type->valuestring, "treasure") == 0 ? CLOUD_ANIM_TREASURE
                      : strcmp(type->valuestring, "level_up") == 0 ? CLOUD_ANIM_LEVEL_UP : CLOUD_ANIM_NONE;
            char s[16];
            snprintf(s, sizeof(s), "%" PRIu32, (uint32_t)seq->valuedouble);
            storage_set_str("animseq", s);
        }
    }

    const cJSON *ota = cJSON_GetObjectItem(j, "ota");
    if (cJSON_IsObject(ota)) {
        const cJSON *ov = cJSON_GetObjectItem(ota, "version");
        const cJSON *ou = cJSON_GetObjectItem(ota, "url");
        if (cJSON_IsString(ov) && cJSON_IsString(ou)) {
            strncpy(ota_ver, ov->valuestring, 31);
            strncpy(ota_url, ou->valuestring, 255);
        }
    }
    cJSON_Delete(j);
    return ok && qe_schedule_valid(&out->sched);
}

static void fetch_config(char *resp)
{
    char etag[16];
    snprintf(etag, sizeof(etag), "\"%" PRIu32 "\"", s_cfg_version);
    const http_req_t r = { .method = "GET", .path = "/v1/device/config", .auth = true,
                           .if_none_match = s_cfg_version ? etag : NULL, .resp = resp, .resp_cap = RESP_CAP };
    const int st = http_do(&r);
    if (st == 401) { handle_unauthorized(); return; }
    if (st == 304) { ota_mark_valid(); return; }
    if (st != 200) { ESP_LOGW(TAG, "config fetch failed (%d)", st); return; }

    ota_mark_valid(); /* a full backend round-trip succeeded on this image */

    static cloud_config_t cfg;
    char ota_ver[32] = { 0 }, ota_url[256] = { 0 };
    if (!parse_config(resp, &cfg, ota_ver, ota_url)) {
        ESP_LOGE(TAG, "invalid config from backend, keeping current schedule");
        return;
    }
    s_cfg_version = cfg.sched.version;
    xQueueOverwrite(s_config_q, &cfg);
    if (ota_ver[0]) ota_update_if_newer(ota_ver, ota_url);
}

/* ----------------------------------------------------------------- task */

static void cloud_task(void *arg)
{
    (void)arg;
    static char resp[RESP_CAP];
    for (;;) {
        ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(SYNC_INTERVAL_MS));
        if (!net_is_connected()) continue;
        if (!cloud_is_paired() && !try_claim(resp)) continue;

        flush_events();
        if (cloud_is_paired() && now_ms() - s_last_config_ms >= CONFIG_INTERVAL_MS) {
            s_last_config_ms = now_ms();
            fetch_config(resp);
        }
    }
}

esp_err_t cloud_start(QueueHandle_t config_q)
{
    s_config_q = config_q;
    if (storage_get_str("token", s_token, sizeof(s_token)) != ESP_OK) s_token[0] = '\0';
    return xTaskCreate(cloud_task, "cloud", 8192, NULL, 4, &s_task) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}
