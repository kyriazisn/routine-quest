/*
 * Light & sound feedback. Implements the device feedback map of
 * docs/02-game-design.md §5 and Figma page "Device UI" (D1–D7).
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "quest_engine.h"

typedef struct {
    bool       needs_setup;  /* D1: no Wi-Fi config or no valid time */
    qe_state_t state;
    uint8_t    step_count;
    uint8_t    done_mask;
    uint8_t    button_for_step[QE_MAX_STEPS];
    uint8_t    week_stars;   /* 0..12 */
    uint8_t    level;        /* 1.. → ring colour */
    uint8_t    volume;       /* 0..3 */
    uint8_t    brightness;   /* 0..3 */
    bool       night;        /* auto-dim */
} fb_scene_t;

typedef enum {
    FB_ANIM_STEP_DONE,  /* arg: button */
    FB_ANIM_STEP_UNDO,  /* arg: button */
    FB_ANIM_DUPLICATE,  /* arg: button */
    FB_ANIM_SLEEP_TAP,  /* arg: button */
    FB_ANIM_WINDOW_OPEN,
    FB_ANIM_COMPLETE,
    FB_ANIM_TREASURE,
    FB_ANIM_LEVEL_UP,
    FB_ANIM_RESET,
} fb_anim_t;

void feedback_init(void);
void feedback_set_scene(const fb_scene_t *scene);
void feedback_play(fb_anim_t anim, uint8_t arg);
