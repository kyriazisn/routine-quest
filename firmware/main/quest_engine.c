#include "quest_engine.h"

#include <limits.h>
#include <string.h>

static bool state_is_open(qe_state_t s)
{
    return s == QE_ACTIVE || s == QE_IN_PROGRESS || s == QE_COMPLETE;
}

static uint8_t popcount8(uint8_t v)
{
    uint8_t c = 0;
    while (v) {
        c += v & 1u;
        v >>= 1;
    }
    return c;
}

static uint8_t steps_mask(const qe_routine_t *r)
{
    return (uint8_t)((1u << r->step_count) - 1u);
}

static qe_out_t make_out(const qe_engine_t *e, qe_out_type_t type, int8_t step, uint8_t button)
{
    qe_out_t o;
    memset(&o, 0, sizeof(o));
    o.type = type;
    o.routine_idx = e->active_idx;
    o.button = button;
    o.step = step < 0 ? 0 : (uint8_t)step;
    const qe_routine_t *r = qe_active_routine(e);
    if (r) {
        o.routine_id = r->routine_id;
        o.step_count = r->step_count;
        o.done_count = popcount8(e->done_mask);
    }
    return o;
}

static void close_window(qe_engine_t *e)
{
    e->active_idx = QE_NO_ROUTINE;
    e->done_mask = 0;
    e->first_press_set = false;
    e->fast_eligible = false;
    e->state = QE_SLEEPING;
}

static void roll_week(qe_engine_t *e, const qe_clock_t *now)
{
    int32_t wid = qe_week_id(now->day_index);
    if (wid != e->week_id) {
        e->week_id = wid;
        e->week_stars = 0;
    }
}

/* ---------------------------------------------------------------- helpers */

int32_t qe_days_from_civil(int32_t y, uint32_t m, uint32_t d)
{
    /* Howard Hinnant's days_from_civil, proleptic Gregorian. */
    y -= m <= 2;
    const int32_t era = (y >= 0 ? y : y - 399) / 400;
    const uint32_t yoe = (uint32_t)(y - era * 400);
    const uint32_t doy = (153u * (m + (m > 2 ? (uint32_t)-3 : 9u)) + 2u) / 5u + d - 1u;
    const uint32_t doe = yoe * 365u + yoe / 4u - yoe / 100u + doy;
    return era * 146097 + (int32_t)doe - 719468;
}

int32_t qe_week_id(int32_t day_index)
{
    /* 1970-01-01 was a Thursday: shift so weeks start on Monday, floor-divide. */
    int32_t x = day_index + 3;
    return x >= 0 ? x / 7 : -((-x + 6) / 7);
}

int8_t qe_routine_at(const qe_schedule_t *s, const qe_clock_t *now)
{
    if (!s) {
        return QE_NO_ROUTINE;
    }
    for (uint8_t i = 0; i < s->routine_count && i < QE_MAX_ROUTINES; i++) {
        const qe_routine_t *r = &s->routines[i];
        if ((r->days_mask & (1u << now->weekday)) &&
            now->minute_of_day >= r->start_min && now->minute_of_day < r->end_min) {
            return (int8_t)i;
        }
    }
    return QE_NO_ROUTINE;
}

int8_t qe_step_for_button(const qe_routine_t *r, uint8_t button)
{
    for (uint8_t i = 0; i < r->step_count; i++) {
        if (r->button_for_step[i] == button) {
            return (int8_t)i;
        }
    }
    return -1;
}

const qe_routine_t *qe_active_routine(const qe_engine_t *e)
{
    if (!e->sched || e->active_idx < 0 || e->active_idx >= e->sched->routine_count) {
        return NULL;
    }
    return &e->sched->routines[e->active_idx];
}

uint8_t qe_done_count(const qe_engine_t *e)
{
    return popcount8(e->done_mask);
}

bool qe_schedule_valid(const qe_schedule_t *s)
{
    if (!s || s->routine_count > QE_MAX_ROUTINES) {
        return false;
    }
    for (uint8_t i = 0; i < s->routine_count; i++) {
        const qe_routine_t *r = &s->routines[i];
        if (r->step_count < 1 || r->step_count > QE_MAX_STEPS) return false;
        if (r->start_min >= r->end_min || r->end_min > 1440) return false;
        if (r->days_mask == 0 || r->days_mask >= 0x80) return false;
        uint8_t seen = 0;
        for (uint8_t k = 0; k < r->step_count; k++) {
            uint8_t b = r->button_for_step[k];
            if (b >= QE_NUM_BUTTONS || (seen & (1u << b))) return false;
            seen |= (uint8_t)(1u << b);
        }
        for (uint8_t j = 0; j < i; j++) {
            const qe_routine_t *o = &s->routines[j];
            bool shared_day = (o->days_mask & r->days_mask) != 0;
            bool overlap = r->start_min < o->end_min && o->start_min < r->end_min;
            if (shared_day && overlap) return false;
        }
    }
    return true;
}

/* ------------------------------------------------------------------- API */

void qe_init(qe_engine_t *e, const qe_schedule_t *sched, uint32_t fast_threshold_ms)
{
    memset(e, 0, sizeof(*e));
    e->sched = sched;
    e->state = QE_SLEEPING;
    e->active_idx = QE_NO_ROUTINE;
    e->paused_day = INT32_MIN;
    e->week_id = INT32_MIN;
    e->fast_threshold_ms = fast_threshold_ms;
}

void qe_set_schedule(qe_engine_t *e, const qe_schedule_t *sched)
{
    e->sched = sched;
    const qe_routine_t *r = qe_active_routine(e);
    if (!r) {
        close_window(e);
        return;
    }
    /* A schedule edit may shrink the step list: drop steps that no longer exist. */
    e->done_mask &= steps_mask(r);
    if (e->state == QE_COMPLETE && e->done_mask != steps_mask(r)) {
        e->state = e->done_mask ? QE_IN_PROGRESS : QE_ACTIVE;
    }
}

void qe_set_paused_day(qe_engine_t *e, int32_t day_index)
{
    e->paused_day = day_index;
}

void qe_set_week_stars(qe_engine_t *e, uint8_t stars)
{
    e->week_stars = stars > QE_RING_STARS ? QE_RING_STARS : stars;
}

qe_out_t qe_tick(qe_engine_t *e, const qe_clock_t *now)
{
    roll_week(e, now);
    const int8_t r = qe_routine_at(e->sched, now);

    /* Parent paused today: end any open quest silently (no expiry, no streak impact). */
    if (e->paused_day == now->day_index) {
        if (e->active_idx != QE_NO_ROUTINE) {
            close_window(e);
        }
        e->state = (r != QE_NO_ROUTINE) ? QE_PAUSED : QE_SLEEPING;
        return make_out(e, QE_OUT_NONE, -1, QE_BUTTON_UNUSED);
    }

    /* Close the current window when it ends or the day changes. */
    if (e->active_idx != QE_NO_ROUTINE && (r != e->active_idx || now->day_index != e->active_day)) {
        const bool incomplete = e->state == QE_ACTIVE || e->state == QE_IN_PROGRESS;
        qe_out_t out = make_out(e, incomplete ? QE_OUT_QUEST_EXPIRED : QE_OUT_NONE, -1, QE_BUTTON_UNUSED);
        close_window(e);
        if (incomplete) {
            return out; /* the next tick may open a following window */
        }
    }

    /* Open a new window. */
    if (e->active_idx == QE_NO_ROUTINE && r != QE_NO_ROUTINE) {
        e->active_idx = r;
        e->active_day = now->day_index;
        e->done_mask = 0;
        e->first_press_set = false;
        e->fast_eligible = true;
        e->state = QE_ACTIVE;
        return make_out(e, QE_OUT_WINDOW_OPEN, -1, QE_BUTTON_UNUSED);
    }

    if (e->active_idx == QE_NO_ROUTINE) {
        e->state = QE_SLEEPING;
    }
    return make_out(e, QE_OUT_NONE, -1, QE_BUTTON_UNUSED);
}

qe_out_t qe_press(qe_engine_t *e, const qe_clock_t *now, uint8_t button)
{
    const qe_routine_t *r = qe_active_routine(e);
    if (!r || !state_is_open(e->state)) {
        return make_out(e, QE_OUT_SLEEP_PRESS, -1, button);
    }
    const int8_t step = qe_step_for_button(r, button);
    if (step < 0) {
        return make_out(e, QE_OUT_SLEEP_PRESS, -1, button);
    }
    const uint8_t bit = (uint8_t)(1u << step);
    if (e->done_mask & bit) {
        return make_out(e, QE_OUT_DUPLICATE_PRESS, step, button);
    }
    if (!e->first_press_set) {
        e->first_press_ms = now->mono_ms;
        e->first_press_set = true;
    }
    e->done_mask |= bit;

    if (e->done_mask == steps_mask(r)) {
        e->state = QE_COMPLETE;
        if (e->week_stars < QE_RING_STARS) {
            e->week_stars++;
        }
        qe_out_t o = make_out(e, QE_OUT_QUEST_COMPLETE, step, button);
        if (e->fast_eligible && r->step_count > 1 &&
            (now->mono_ms - e->first_press_ms) < e->fast_threshold_ms) {
            o.flags |= QE_FLAG_FAST;
        }
        return o;
    }
    e->state = QE_IN_PROGRESS;
    return make_out(e, QE_OUT_STEP_DONE, step, button);
}

qe_out_t qe_long_press(qe_engine_t *e, const qe_clock_t *now, uint8_t button)
{
    (void)now;
    const qe_routine_t *r = qe_active_routine(e);
    if (!r || (e->state != QE_IN_PROGRESS && e->state != QE_COMPLETE)) {
        return make_out(e, QE_OUT_NONE, -1, button);
    }
    const int8_t step = qe_step_for_button(r, button);
    if (step < 0 || !(e->done_mask & (1u << step))) {
        return make_out(e, QE_OUT_NONE, -1, button);
    }
    if (e->state == QE_COMPLETE && e->week_stars > 0) {
        e->week_stars--;
    }
    e->done_mask &= (uint8_t)~(1u << step);
    e->state = e->done_mask ? QE_IN_PROGRESS : QE_ACTIVE;
    if (!e->done_mask) {
        e->first_press_set = false;
    }
    return make_out(e, QE_OUT_STEP_UNDONE, step, button);
}

qe_progress_t qe_get_progress(const qe_engine_t *e)
{
    qe_progress_t p = {
        .day_index = e->active_day,
        .routine_idx = e->active_idx,
        .done_mask = e->done_mask,
        .week_stars = e->week_stars,
        .week_id = e->week_id,
    };
    return p;
}

void qe_restore_progress(qe_engine_t *e, const qe_progress_t *p, const qe_clock_t *now)
{
    if (p->week_id == qe_week_id(now->day_index)) {
        e->week_id = p->week_id;
        qe_set_week_stars(e, p->week_stars);
    }
    const int8_t r = qe_routine_at(e->sched, now);
    if (r == QE_NO_ROUTINE || p->routine_idx != r || p->day_index != now->day_index ||
        e->paused_day == now->day_index) {
        return;
    }
    const qe_routine_t *rt = &e->sched->routines[r];
    e->active_idx = r;
    e->active_day = now->day_index;
    e->done_mask = p->done_mask & steps_mask(rt);
    e->first_press_set = false;
    e->fast_eligible = (e->done_mask == 0); /* elapsed time is unknown across a reboot */
    if (e->done_mask == steps_mask(rt)) {
        e->state = QE_COMPLETE;
    } else {
        e->state = e->done_mask ? QE_IN_PROGRESS : QE_ACTIVE;
    }
}
