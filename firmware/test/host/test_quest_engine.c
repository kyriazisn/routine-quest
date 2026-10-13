/* Host unit tests for quest_engine.c — run with `make -C firmware/test/host`. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "quest_engine.h"

static int g_failed, g_run;

#define CHECK(cond)                                                                  \
    do {                                                                             \
        g_run++;                                                                     \
        if (!(cond)) {                                                               \
            g_failed++;                                                              \
            fprintf(stderr, "  FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);        \
        }                                                                            \
    } while (0)

#define TEST(name) static void name(void)
#define RUN(name)                                                                    \
    do {                                                                             \
        int before = g_failed;                                                       \
        name();                                                                      \
        printf("%s %s\n", g_failed == before ? "ok  " : "FAIL", #name);              \
    } while (0)

/* 2026-10-12 is a Monday. */
static const int32_t MON = 20738;
#define FAST_MS 10000u

static qe_schedule_t sched(void)
{
    qe_schedule_t s;
    memset(&s, 0, sizeof(s));
    s.version = 1;
    s.routine_count = 2;
    s.routines[0] = (qe_routine_t){ .routine_id = 11, .start_min = 7 * 60, .end_min = 8 * 60 + 15,
                                    .days_mask = 0x1F, .step_count = 4,
                                    .button_for_step = { 0, 1, 2, 3 } };
    s.routines[1] = (qe_routine_t){ .routine_id = 12, .start_min = 19 * 60 + 30, .end_min = 20 * 60 + 30,
                                    .days_mask = 0x7F, .step_count = 3,
                                    .button_for_step = { 3, 1, 0 } };
    return s;
}

static qe_clock_t at(int32_t day, int hh, int mm, uint32_t ms)
{
    qe_clock_t c = { .day_index = day, .weekday = (uint8_t)(((day - MON) % 7 + 7) % 7),
                     .minute_of_day = (uint16_t)(hh * 60 + mm), .mono_ms = ms };
    return c;
}

TEST(test_civil_and_week)
{
    CHECK(qe_days_from_civil(1970, 1, 1) == 0);
    CHECK(qe_days_from_civil(2026, 10, 12) == MON);
    CHECK(qe_days_from_civil(2000, 2, 29) == 11016);
    CHECK(qe_week_id(MON) == qe_week_id(MON + 6));     /* Mon..Sun same week */
    CHECK(qe_week_id(MON + 7) == qe_week_id(MON) + 1); /* next Monday rolls */
    CHECK(qe_week_id(MON - 1) == qe_week_id(MON) - 1); /* Sunday before */
}

TEST(test_schedule_validation)
{
    qe_schedule_t s = sched();
    CHECK(qe_schedule_valid(&s));
    s.routines[1].start_min = 7 * 60 + 30; /* overlaps morning on weekdays */
    s.routines[1].end_min = 8 * 60;
    CHECK(!qe_schedule_valid(&s));
    s = sched();
    s.routines[0].button_for_step[1] = 0; /* duplicate button */
    CHECK(!qe_schedule_valid(&s));
    s = sched();
    s.routines[0].end_min = 6 * 60; /* end before start (midnight crossing) */
    CHECK(!qe_schedule_valid(&s));
}

TEST(test_sleeping_press_outside_window)
{
    qe_schedule_t s = sched();
    qe_engine_t e;
    qe_init(&e, &s, FAST_MS);
    qe_clock_t c = at(MON, 6, 59, 0);
    CHECK(qe_tick(&e, &c).type == QE_OUT_NONE);
    CHECK(e.state == QE_SLEEPING);
    qe_out_t o = qe_press(&e, &c, 0);
    CHECK(o.type == QE_OUT_SLEEP_PRESS);
    CHECK(e.done_mask == 0);
}

TEST(test_full_quest_any_order)
{
    qe_schedule_t s = sched();
    qe_engine_t e;
    qe_init(&e, &s, FAST_MS);
    qe_clock_t c = at(MON, 7, 0, 1000);
    qe_out_t o = qe_tick(&e, &c);
    CHECK(o.type == QE_OUT_WINDOW_OPEN && o.routine_id == 11);
    CHECK(e.state == QE_ACTIVE);

    c.mono_ms = 60000;
    o = qe_press(&e, &c, 2);
    CHECK(o.type == QE_OUT_STEP_DONE && o.step == 2 && o.done_count == 1);
    CHECK(e.state == QE_IN_PROGRESS);
    o = qe_press(&e, &c, 2);
    CHECK(o.type == QE_OUT_DUPLICATE_PRESS);
    CHECK(qe_done_count(&e) == 1);

    c.mono_ms = 120000;
    qe_press(&e, &c, 0);
    qe_press(&e, &c, 3);
    c.mono_ms = 300000;
    o = qe_press(&e, &c, 1);
    CHECK(o.type == QE_OUT_QUEST_COMPLETE && o.done_count == 4 && o.step_count == 4);
    CHECK(!(o.flags & QE_FLAG_FAST));
    CHECK(e.state == QE_COMPLETE);
    CHECK(e.week_stars == 1);

    /* Window ends after completion: no expiry event. */
    c = at(MON, 8, 15, 400000);
    CHECK(qe_tick(&e, &c).type == QE_OUT_NONE);
    CHECK(e.state == QE_SLEEPING);
}

TEST(test_fast_quest_flag)
{
    qe_schedule_t s = sched();
    qe_engine_t e;
    qe_init(&e, &s, FAST_MS);
    qe_clock_t c = at(MON, 7, 5, 0);
    qe_tick(&e, &c);
    for (uint8_t b = 0; b < 4; b++) {
        c.mono_ms = 5000u + b * 1000u;
        qe_out_t o = qe_press(&e, &c, b);
        if (b == 3) {
            CHECK(o.type == QE_OUT_QUEST_COMPLETE);
            CHECK(o.flags & QE_FLAG_FAST);
        }
    }
}

TEST(test_undo)
{
    qe_schedule_t s = sched();
    qe_engine_t e;
    qe_init(&e, &s, FAST_MS);
    qe_clock_t c = at(MON, 19, 45, 0);
    qe_tick(&e, &c);
    CHECK(e.active_idx == 1);
    CHECK(qe_long_press(&e, &c, 3).type == QE_OUT_NONE); /* nothing to undo yet */
    qe_press(&e, &c, 3);
    qe_out_t o = qe_long_press(&e, &c, 3);
    CHECK(o.type == QE_OUT_STEP_UNDONE && o.step == 0);
    CHECK(e.state == QE_ACTIVE && e.done_mask == 0);

    /* Undo after completion removes the week star. */
    qe_press(&e, &c, 3);
    qe_press(&e, &c, 1);
    c.mono_ms = 600000;
    CHECK(qe_press(&e, &c, 0).type == QE_OUT_QUEST_COMPLETE);
    CHECK(e.week_stars == 1);
    o = qe_long_press(&e, &c, 1);
    CHECK(o.type == QE_OUT_STEP_UNDONE);
    CHECK(e.state == QE_IN_PROGRESS && e.week_stars == 0);
    /* Button 2 is not part of the evening quest. */
    CHECK(qe_press(&e, &c, 2).type == QE_OUT_SLEEP_PRESS);
}

TEST(test_expiry)
{
    qe_schedule_t s = sched();
    qe_engine_t e;
    qe_init(&e, &s, FAST_MS);
    qe_clock_t c = at(MON, 7, 10, 0);
    qe_tick(&e, &c);
    qe_press(&e, &c, 0);
    c = at(MON, 8, 15, 0);
    qe_out_t o = qe_tick(&e, &c);
    CHECK(o.type == QE_OUT_QUEST_EXPIRED && o.routine_id == 11 && o.done_count == 1);
    CHECK(e.state == QE_SLEEPING && e.active_idx == QE_NO_ROUTINE);
    CHECK(e.week_stars == 0);
}

TEST(test_weekend_no_morning)
{
    qe_schedule_t s = sched();
    qe_engine_t e;
    qe_init(&e, &s, FAST_MS);
    qe_clock_t c = at(MON + 5, 7, 10, 0); /* Saturday */
    CHECK(qe_tick(&e, &c).type == QE_OUT_NONE);
    CHECK(e.state == QE_SLEEPING);
    c = at(MON + 5, 19, 30, 0);
    CHECK(qe_tick(&e, &c).type == QE_OUT_WINDOW_OPEN);
}

TEST(test_pause_day)
{
    qe_schedule_t s = sched();
    qe_engine_t e;
    qe_init(&e, &s, FAST_MS);
    qe_clock_t c = at(MON, 7, 10, 0);
    qe_tick(&e, &c);
    qe_press(&e, &c, 0);
    qe_set_paused_day(&e, MON);
    qe_out_t o = qe_tick(&e, &c);
    CHECK(o.type == QE_OUT_NONE); /* silent, no expiry */
    CHECK(e.state == QE_PAUSED);
    CHECK(qe_press(&e, &c, 1).type == QE_OUT_SLEEP_PRESS);
    c = at(MON + 1, 7, 10, 0);
    CHECK(qe_tick(&e, &c).type == QE_OUT_WINDOW_OPEN);
}

TEST(test_week_reset_and_cap)
{
    qe_schedule_t s = sched();
    qe_engine_t e;
    qe_init(&e, &s, FAST_MS);
    qe_clock_t c = at(MON, 12, 0, 0);
    qe_tick(&e, &c);
    qe_set_week_stars(&e, 50);
    CHECK(e.week_stars == QE_RING_STARS);
    c = at(MON + 6, 12, 0, 0); /* Sunday, same week */
    qe_tick(&e, &c);
    CHECK(e.week_stars == QE_RING_STARS);
    c = at(MON + 7, 0, 0, 0); /* next Monday */
    qe_tick(&e, &c);
    CHECK(e.week_stars == 0);
}

TEST(test_restore_after_reboot)
{
    qe_schedule_t s = sched();
    qe_engine_t e;
    qe_init(&e, &s, FAST_MS);
    qe_clock_t c = at(MON, 7, 10, 0);
    qe_tick(&e, &c);
    qe_press(&e, &c, 0);
    qe_press(&e, &c, 1);
    qe_progress_t p = qe_get_progress(&e);

    qe_engine_t e2;
    qe_init(&e2, &s, FAST_MS);
    c = at(MON, 7, 20, 5);
    qe_restore_progress(&e2, &p, &c);
    CHECK(e2.state == QE_IN_PROGRESS && e2.done_mask == 0x03);
    CHECK(qe_tick(&e2, &c).type == QE_OUT_NONE); /* no duplicate WINDOW_OPEN */
    qe_press(&e2, &c, 2);
    qe_out_t o = qe_press(&e2, &c, 3);
    CHECK(o.type == QE_OUT_QUEST_COMPLETE);
    CHECK(!(o.flags & QE_FLAG_FAST)); /* elapsed time unknown after reboot */

    /* Stale progress (yesterday) is ignored. */
    qe_engine_t e3;
    qe_init(&e3, &s, FAST_MS);
    c = at(MON + 1, 7, 20, 0);
    qe_restore_progress(&e3, &p, &c);
    CHECK(e3.state == QE_SLEEPING);
}

TEST(test_schedule_shrink_while_active)
{
    qe_schedule_t s = sched();
    qe_engine_t e;
    qe_init(&e, &s, FAST_MS);
    qe_clock_t c = at(MON, 7, 10, 0);
    qe_tick(&e, &c);
    qe_press(&e, &c, 3); /* step 3 */
    qe_schedule_t s2 = s;
    s2.routines[0].step_count = 2;
    qe_set_schedule(&e, &s2);
    CHECK(e.done_mask == 0);
    CHECK(e.state == QE_IN_PROGRESS || e.state == QE_ACTIVE);
}

int main(void)
{
    RUN(test_civil_and_week);
    RUN(test_schedule_validation);
    RUN(test_sleeping_press_outside_window);
    RUN(test_full_quest_any_order);
    RUN(test_fast_quest_flag);
    RUN(test_undo);
    RUN(test_expiry);
    RUN(test_weekend_no_morning);
    RUN(test_pause_day);
    RUN(test_week_reset_and_cap);
    RUN(test_restore_after_reboot);
    RUN(test_schedule_shrink_while_active);
    printf("\n%d checks, %d failed\n", g_run, g_failed);
    return g_failed ? EXIT_FAILURE : EXIT_SUCCESS;
}
