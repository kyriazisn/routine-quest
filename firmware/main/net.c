#include "net.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "storage.h"
#include "wifi_provisioning/manager.h"
#include "wifi_provisioning/scheme_ble.h"

static const char *TAG = "net";

#define CLAIM_ENDPOINT   "rq-claim"
#define CLAIM_MAX_LEN    64
#define RECONNECT_MIN_MS 1000
#define RECONNECT_MAX_MS 60000

static char s_device_id[24];
static char s_device_name[12];
static volatile bool s_connected;
static bool s_provisioned;
static uint32_t s_backoff_ms = RECONNECT_MIN_MS;
static esp_timer_handle_t s_reconnect_timer;

const char *net_device_id(void)   { return s_device_id; }
const char *net_device_name(void) { return s_device_name; }
bool net_is_provisioned(void)     { return s_provisioned; }
bool net_is_connected(void)       { return s_connected; }

bool net_time_valid(void)
{
    return time(NULL) > 1735689600; /* after 2025-01-01: SNTP has synced at least once */
}

void net_set_timezone(const char *posix_tz)
{
    if (posix_tz && posix_tz[0]) {
        setenv("TZ", posix_tz, 1);
        tzset();
    }
}

static void init_ids(void)
{
    uint8_t mac[6];
    ESP_ERROR_CHECK(esp_read_mac(mac, ESP_MAC_WIFI_STA));
    snprintf(s_device_id, sizeof(s_device_id), "rq-%02x%02x%02x%02x%02x%02x",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    snprintf(s_device_name, sizeof(s_device_name), "RQ-%02X%02X", mac[4], mac[5]);
}

static void reconnect_cb(void *arg)
{
    (void)arg;
    esp_wifi_connect();
}

#if !CONFIG_RQ_SIM_MODE
/* Custom provisioning endpoint: the PWA sends a one-time claim code that links this
 * device to the parent's family on the backend (exchanged for a device token later). */
static esp_err_t claim_handler(uint32_t session_id, const uint8_t *inbuf, ssize_t inlen,
                               uint8_t **outbuf, ssize_t *outlen, void *priv)
{
    (void)session_id;
    (void)priv;
    const char *reply = "ok";
    if (!inbuf || inlen <= 0 || inlen > CLAIM_MAX_LEN) {
        reply = "err:len";
    } else {
        char code[CLAIM_MAX_LEN + 1];
        memcpy(code, inbuf, (size_t)inlen);
        code[inlen] = '\0';
        if (storage_set_str("claim", code) != ESP_OK) {
            reply = "err:store";
        } else {
            ESP_LOGI(TAG, "claim code received (%d bytes)", (int)inlen);
        }
    }
    *outbuf = (uint8_t *)strdup(reply);
    if (!*outbuf) return ESP_ERR_NO_MEM;
    *outlen = (ssize_t)strlen(reply);
    return ESP_OK;
}
#endif

static void on_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    if (base == WIFI_PROV_EVENT) {
        switch (id) {
        case WIFI_PROV_START:
            ESP_LOGI(TAG, "provisioning: advertising as %s", s_device_name);
            break;
        case WIFI_PROV_CRED_RECV: {
            const wifi_sta_config_t *c = (const wifi_sta_config_t *)data;
            ESP_LOGI(TAG, "provisioning: credentials for SSID \"%s\"", (const char *)c->ssid);
            break; /* never log the password */
        }
        case WIFI_PROV_CRED_FAIL: {
            const wifi_prov_sta_fail_reason_t *r = (const wifi_prov_sta_fail_reason_t *)data;
            ESP_LOGW(TAG, "provisioning failed: %s",
                     *r == WIFI_PROV_STA_AUTH_ERROR ? "auth error" : "AP not found");
            wifi_prov_mgr_reset_sm_state_on_failure(); /* let the parent retry */
            break;
        }
        case WIFI_PROV_CRED_SUCCESS:
            ESP_LOGI(TAG, "provisioning succeeded");
            s_provisioned = true;
            break;
        case WIFI_PROV_END:
            wifi_prov_mgr_deinit();
            break;
        default:
            break;
        }
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        s_connected = false;
        ESP_LOGW(TAG, "disconnected, retry in %u ms", (unsigned)s_backoff_ms);
        esp_timer_start_once(s_reconnect_timer, (uint64_t)s_backoff_ms * 1000);
        s_backoff_ms = s_backoff_ms * 2 > RECONNECT_MAX_MS ? RECONNECT_MAX_MS : s_backoff_ms * 2;
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        s_connected = true;
        s_backoff_ms = RECONNECT_MIN_MS;
        ESP_LOGI(TAG, "connected");
    }
}

esp_err_t net_start(const char *pop)
{
    init_ids();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    const esp_timer_create_args_t targs = { .callback = reconnect_cb, .name = "wifi_reconnect" };
    ESP_ERROR_CHECK(esp_timer_create(&targs, &s_reconnect_timer));

    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_PROV_EVENT, ESP_EVENT_ANY_ID, on_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_event, NULL));

    const wifi_init_config_t wcfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&wcfg));
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_MIN_MODEM));

    esp_sntp_config_t scfg = ESP_NETIF_SNTP_DEFAULT_CONFIG("pool.ntp.org");
    esp_netif_sntp_init(&scfg);

#if CONFIG_RQ_SIM_MODE
    /* Wokwi: no BLE. Skip the provisioning manager and join the simulator's open network. */
    (void)pop;
    wifi_config_t sta = { 0 };
    strcpy((char *)sta.sta.ssid, "Wokwi-GUEST");
    sta.sta.channel = 6; /* Wokwi-GUEST is on channel 6; skips the full scan */
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &sta));
    ESP_ERROR_CHECK(esp_wifi_start());
    s_provisioned = true;
    ESP_LOGW(TAG, "SIMULATION MODE: provisioning bypassed, joining Wokwi-GUEST");
    return ESP_OK;
#else
    const wifi_prov_mgr_config_t pcfg = {
        .scheme = wifi_prov_scheme_ble,
        .scheme_event_handler = WIFI_PROV_SCHEME_BLE_EVENT_HANDLER_FREE_BTDM,
    };
    ESP_ERROR_CHECK(wifi_prov_mgr_init(pcfg));
    ESP_ERROR_CHECK(wifi_prov_mgr_is_provisioned(&s_provisioned));

    if (!s_provisioned) {
        ESP_ERROR_CHECK(wifi_prov_mgr_endpoint_create(CLAIM_ENDPOINT));
        ESP_ERROR_CHECK(wifi_prov_mgr_start_provisioning(WIFI_PROV_SECURITY_1, (const void *)pop,
                                                         s_device_name, NULL));
        ESP_ERROR_CHECK(wifi_prov_mgr_endpoint_register(CLAIM_ENDPOINT, claim_handler, NULL));
    } else {
        wifi_prov_mgr_deinit();
        ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
        ESP_ERROR_CHECK(esp_wifi_start());
    }
    return ESP_OK;
#endif
}
