/*
 * Networking: Wi-Fi station, BLE provisioning (wifi_provisioning, Security 1 + PoP),
 * a custom "rq-claim" provisioning endpoint, and SNTP time.
 *
 * Wi-Fi credentials go from the parent's phone straight to the device over the
 * encrypted provisioning session. They never reach the backend.
 */
#pragma once

#include <stdbool.h>

#include "esp_err.h"

/* Device identifiers derived from the factory MAC. */
const char *net_device_id(void);   /* e.g. "rq-a1b2c3d4e5f6" */
const char *net_device_name(void); /* BLE name, e.g. "RQ-7F3A" (matches sticker) */

/* Starts Wi-Fi. If not provisioned, advertises over BLE with the given proof-of-possession
 * (printed on the device label) and waits for credentials in the background. */
esp_err_t net_start(const char *pop);

bool net_is_provisioned(void);
bool net_is_connected(void);
bool net_time_valid(void);
void net_set_timezone(const char *posix_tz);
