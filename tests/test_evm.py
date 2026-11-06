"""Earned value math checked against hand-computed values."""

from __future__ import annotations

import pandas as pd
import pytest

from project_health.evm import compute_metrics, planned_fraction, project_metrics, task_earned_value

STATUS = pd.Timestamp("2026-01-05")


def test_planned_fraction_is_inclusive_of_both_ends():
    # Jan 1..Jan 10 is 10 days; end of Jan 5 is 5 of 10 days.
    assert planned_fraction(pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-10"), STATUS) == 0.5


@pytest.mark.parametrize(
    ("status", "expected"),
    [("2025-12-31", 0.0), ("2026-01-01", 0.1), ("2026-01-10", 1.0), ("2026-02-01", 1.0)],
)
def test_planned_fraction_boundaries(status, expected):
    got = planned_fraction(
        pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-10"), pd.Timestamp(status)
    )
    assert got == pytest.approx(expected)


def test_single_day_task_is_fully_planned_on_its_day():
    day = pd.Timestamp("2026-01-05")
    assert planned_fraction(day, day, day) == 1.0
    assert planned_fraction(day, day, day - pd.Timedelta(days=1)) == 0.0


def test_hand_computed_metrics():
    # BAC 1000, PV 500, EV 400, AC 500
    m = compute_metrics(bac=1000, pv=500, ev=400, ac=500)
    assert m.cv == -100
    assert m.sv == -100
    assert m.cpi == pytest.approx(0.8)
    assert m.spi == pytest.approx(0.8)
    assert m.eac == pytest.approx(1250)  # 1000 / 0.8
    assert m.etc == pytest.approx(750)  # 1250 - 500
    assert m.vac == pytest.approx(-250)  # 1000 - 1250
    assert m.tcpi == pytest.approx(1.2)  # (1000 - 400) / (1000 - 500)
    assert m.percent_complete == pytest.approx(40)
    assert m.percent_planned == pytest.approx(50)


def test_under_budget_ahead_of_schedule():
    m = compute_metrics(bac=2000, pv=800, ev=1000, ac=800)
    assert m.cpi == pytest.approx(1.25)
    assert m.spi == pytest.approx(1.25)
    assert m.eac == pytest.approx(1600)
    assert m.vac == pytest.approx(400)
    assert m.tcpi == pytest.approx(1000 / 1200)


def test_not_started_has_no_ratios_and_eac_equals_bac():
    m = compute_metrics(bac=1000, pv=0, ev=0, ac=0)
    assert m.cpi is None
    assert m.spi is None
    assert m.eac == 1000
    assert m.etc == 1000
    assert m.vac == 0


def test_spend_without_progress_does_not_divide_by_zero():
    m = compute_metrics(bac=1000, pv=200, ev=0, ac=300)
    assert m.cpi == 0
    assert m.spi == 0
    # Falls back to AC + remaining work at budget rate.
    assert m.eac == pytest.approx(1300)


def test_tcpi_undefined_when_budget_exhausted():
    m = compute_metrics(bac=1000, pv=1000, ev=900, ac=1000)
    assert m.tcpi is None


def test_task_level_columns(make):
    tasks = make(
        [
            {
                "planned_start": "2026-01-01",
                "planned_finish": "2026-01-10",
                "budget": 1000,
                "percent_complete": 40,
                "actual_cost": 500,
            }
        ]
    )
    t = task_earned_value(tasks, STATUS).iloc[0]
    assert (t.pv, t.ev, t.ac, t.cv, t.sv) == (500, 400, 500, -100, -100)


def test_project_rollup_sums_tasks(make):
    tasks = make(
        [
            # fully planned and done: PV 1000, EV 1000, AC 900
            {
                "planned_start": "2025-12-01",
                "planned_finish": "2025-12-10",
                "budget": 1000,
                "percent_complete": 100,
                "actual_cost": 900,
            },
            # half planned, 25% done: PV 1000, EV 500, AC 700
            {
                "planned_start": "2026-01-01",
                "planned_finish": "2026-01-10",
                "budget": 2000,
                "percent_complete": 25,
                "actual_cost": 700,
            },
        ]
    )
    m = project_metrics(tasks, STATUS)
    assert m.bac == 3000
    assert m.pv == pytest.approx(2000)
    assert m.ev == pytest.approx(1500)
    assert m.ac == pytest.approx(1600)
    assert m.cpi == pytest.approx(1500 / 1600)
    assert m.spi == pytest.approx(0.75)
    assert m.eac == pytest.approx(3000 / (1500 / 1600))


def test_empty_task_table_gives_zeroes(make):
    tasks = make([{"planned_start": "2026-01-01", "planned_finish": "2026-01-02"}]).iloc[0:0]
    m = project_metrics(tasks, STATUS)
    assert m.bac == 0 and m.cpi is None and m.percent_complete == 0
