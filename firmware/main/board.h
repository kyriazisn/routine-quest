/*
 * Board definition — ESP32-S3-WROOM-1 (N8). Prototype target: ESP32-S3-DevKitC-1.
 *
 * Avoided pins: strapping (0, 3, 45, 46), USB D-/D+ (19, 20),
 * flash/PSRAM (26–37), DevKitC on-board RGB LED (48).
 * Final assignment is confirmed in Phase 6 (schematic).
 */
#pragma once

#include "driver/gpio.h"

#define RQ_NUM_BUTTONS 4
/* Active-low, internal pull-up; RC filter + TVS on the PCB. Index = button 0..3 (red, blue, green, yellow). */
#define RQ_BUTTON_GPIOS { GPIO_NUM_4, GPIO_NUM_5, GPIO_NUM_6, GPIO_NUM_7 }

/* Single WS2812B chain: ring LEDs 0..11, then one LED under each button 12..15. */
#define RQ_LED_GPIO        GPIO_NUM_38
#define RQ_RING_LEDS       12
#define RQ_BUTTON_LED_BASE RQ_RING_LEDS
#define RQ_LED_COUNT       (RQ_RING_LEDS + RQ_NUM_BUTTONS)

/* Piezo buzzer via LEDC PWM (NPN driver on the PCB). */
#define RQ_BUZZER_GPIO GPIO_NUM_15

/* Timing (docs/02-game-design.md §8) */
#define RQ_BUTTON_POLL_MS   5
#define RQ_DEBOUNCE_MS      30
#define RQ_UNDO_HOLD_MS     2000
#define RQ_RESET_HOLD_MS    10000
#define RQ_RESET_BUTTON_A   0 /* buttons 1 + 4 */
#define RQ_RESET_BUTTON_B   3
#define RQ_FAST_QUEST_MS    10000

/* Power budget: USB 5 V / 500 mA. 16 LEDs × 60 mA full white = 960 mA, so cap brightness.
 * 64/255 → worst case ≈ 240 mA for LEDs. Verified against measurement in Phase 7. */
#define RQ_LED_MAX_BRIGHTNESS 64
