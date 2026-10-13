/*
 * Quest engine — pure C state machine for Routine Quest.
 *
 * No ESP-IDF dependencies: compiled both into the firmware and into the
 * host unit tests (firmware/test/host). See docs/02-game-design.md §3.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#define QE_MAX_STEPS     4
#define QE_MAX_ROUTINES  2
#define QE_NUM_BUTTONS   4
#define QE_RING_STARS    12
#define QE_NO_ROUTINE    (-1)
#define QE_BUTTON_UNUSED 0xFF

typedef struct {
    uint32_t routine_id;                    /* backend id */
    uint16_t start_min;                     /* minutes since local midnight, inclusive */
    uint16_t end_min;                       /* exclusive; must be > start_min (no midnight crossing) */
    uint8_t  days_mask;                     /* bit0 = Monday ... bit6 = Sunday */
    uint8_t  step_count;                    /* 1..QE_MAX_STEPS */
    uint8_t  button_for_step[QE_MAX_STEPS]; /* button index 0..3 */
} qe_routine_t;

typedef struct {
    uint32_t     version;
    uint8_t      routine_count;
    qe_routine_t routines[QE_MAX_ROUTINES];
} qe_schedule_t;

/* Local wall-clock snapshot supplied by the caller. */
typedef struct {
    int32_t  day_index;     /* local days since 1970-01-01 */
    uint8_t  weekday;       /* 0 = Monday ... 6 = Sunday */
    uint16_t minute_of_day; /* 0..1439 */
    uint32_t mono_ms;       /* monotonic ms (for fast-quest detection) */
} qe_clock_t;

typedef enum {
    QE_SLEEPING = 0,
    QE_ACTIVE,
    QE_IN_PROGRESS,
    QE_COMPLETE,
    QE_PAUSED,
} qe_state_t;

typedef enum {
    QE_OUT_NONE = 0,
    QE_OUT_WINDOW_OPEN,
    QE_OUT_STEP_DONE,
    QE_OUT_STEP_UNDONE,
    QE_OUT_QUEST_COMPLETE,
    QE_OUT_QUEST_EXPIRED,   /* window closed with the quest incomplete */
    QE_OUT_SLEEP_PRESS,     /* press outside an active quest: soft feedback, no progress */
    QE_OUT_DUPLICATE_PRESS, /* step already done: soft confirmation */
} qe_out_type_t;

#define QE_FLAG_FAST 0x01   /* quest completed faster than the fast-quest threshold */

typedef struct {
    qe_out_type_t type;
    int8_t        routine_idx;
    uint32_t      routine_id;
    uint8_t       step;       /* step index, valid for STEP_* */
    uint8_t       button;     /* button that caused it, 0xFF if none */
    uint8_t       done_count;
    uint8_t       step_count;
    uint8_t       flags;
} qe_out_t;

/* Persisted progress so a reboot mid-window does not lose steps. */
typedef struct {
    int32_t day_index;
    int8_t  routine_idx;
    uint8_t done_mask;
    uint8_t week_stars;
    int32_t week_id;
} qe_progress_t;

typedef struct {
    const qe_schedule_t *sched;
    qe_state_t state;
    int8_t     active_idx;
    int32_t    active_day;
    uint8_t    done_mask;
    uint32_t   first_press_ms;
    bool       first_press_set;
    bool       fast_eligible;   /* false after a mid-quest reboot restore */
    int32_t    paused_day;      /* day_index the parent paused, or INT32_MIN */
    uint8_t    week_stars;      /* stars shown on the ring this week (display only) */
    int32_t    week_id;
    uint32_t   fast_threshold_ms;
} qe_engine_t;

void     qe_init(qe_engine_t *e, const qe_schedule_t *sched, uint32_t fast_threshold_ms);
void     qe_set_schedule(qe_engine_t *e, const qe_schedule_t *sched);
void     qe_set_paused_day(qe_engine_t *e, int32_t day_index);
void     qe_set_week_stars(qe_engine_t *e, uint8_t stars); /* server reconciliation */

/* Call periodically (e.g. 1 Hz). Returns at most one output per call. */
qe_out_t qe_tick(qe_engine_t *e, const qe_clock_t *now);
/* Short press (fires on press-down for <100 ms feedback). */
qe_out_t qe_press(qe_engine_t *e, const qe_clock_t *now, uint8_t button);
/* Long press (>= undo hold time) on a completed step undoes it. */
qe_out_t qe_long_press(qe_engine_t *e, const qe_clock_t *now, uint8_t button);

qe_progress_t qe_get_progress(const qe_engine_t *e);
void          qe_restore_progress(qe_engine_t *e, const qe_progress_t *p, const qe_clock_t *now);

/* Helpers */
int8_t  qe_routine_at(const qe_schedule_t *s, const qe_clock_t *now);
int8_t  qe_step_for_button(const qe_routine_t *r, uint8_t button);
uint8_t qe_done_count(const qe_engine_t *e);
const qe_routine_t *qe_active_routine(const qe_engine_t *e);
int32_t qe_days_from_civil(int32_t y, uint32_t m, uint32_t d);
int32_t qe_week_id(int32_t day_index); /* Monday-based week number */
bool    qe_schedule_valid(const qe_schedule_t *s);
