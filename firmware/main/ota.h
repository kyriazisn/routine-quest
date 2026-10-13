/*
 * OTA over HTTPS with A/B partitions and automatic rollback
 * (CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE). A new image boots in PENDING_VERIFY;
 * it is marked valid only after the first successful backend round-trip.
 * If it crashes or never reaches the backend, the bootloader reverts on next reset.
 *
 * Production builds additionally enable Secure Boot v2 (signed images) and flash
 * encryption — see firmware/README.md "Production security".
 */
#pragma once

#include <stdbool.h>

#include "esp_err.h"

const char *ota_running_version(void);
bool        ota_pending_verify(void);
void        ota_mark_valid(void);
/* Downloads and installs `url` if `version` differs from the running one. Restarts on success. */
esp_err_t   ota_update_if_newer(const char *version, const char *url);
