#include "ota.h"

#include <string.h>

#include "esp_app_desc.h"
#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_https_ota.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_system.h"

static const char *TAG = "ota";

const char *ota_running_version(void)
{
    return esp_app_get_description()->version;
}

bool ota_pending_verify(void)
{
    esp_ota_img_states_t st;
    const esp_partition_t *running = esp_ota_get_running_partition();
    return esp_ota_get_state_partition(running, &st) == ESP_OK && st == ESP_OTA_IMG_PENDING_VERIFY;
}

void ota_mark_valid(void)
{
    if (ota_pending_verify()) {
        ESP_LOGI(TAG, "new firmware %s verified, cancelling rollback", ota_running_version());
        esp_ota_mark_app_valid_cancel_rollback();
    }
}

esp_err_t ota_update_if_newer(const char *version, const char *url)
{
    if (!version || !url || !version[0] || !url[0]) return ESP_ERR_INVALID_ARG;
    if (strcmp(version, ota_running_version()) == 0) return ESP_OK;
    if (strncmp(url, "https://", 8) != 0) {
        ESP_LOGE(TAG, "refusing non-HTTPS OTA url");
        return ESP_ERR_INVALID_ARG;
    }
    ESP_LOGI(TAG, "updating %s -> %s", ota_running_version(), version);

    const esp_http_client_config_t http = {
        .url = url,
        .crt_bundle_attach = esp_crt_bundle_attach,
        .timeout_ms = 15000,
        .keep_alive_enable = true,
    };
    const esp_https_ota_config_t cfg = { .http_config = &http };
    esp_err_t err = esp_https_ota(&cfg);
    if (err == ESP_OK) {
        ESP_LOGI(TAG, "OTA written, restarting");
        esp_restart();
    }
    ESP_LOGE(TAG, "OTA failed: %s", esp_err_to_name(err));
    return err;
}
