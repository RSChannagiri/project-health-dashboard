from __future__ import annotations

import pandas as pd
import pytest

from project_health.burn import burn_series
from project_health.resources import owner_summary, weekly_load
from project_health.risk import RiskRules, exceptions, flag_tasks, overdue_counts

STATUS = pd.Timestamp("2026-01-15")  # a Thursday


def _status_of(flagged, task_id):
    return flagged.set_index("task_id").loc[task_id]


def test_task_statuses(make):
    tasks = make(
        [
            # T1 complete
            {
                "planned_start": "2026-01-01",
                "planned_finish": "2026-01-05",
                "percent_complete": 100,
                "actual_finish": "2026-01-07",
                "actual_start": "2026-01-01",
            },
            # T2 overdue: planned to finish Jan 10, still 60%
            {
                "planned_start": "2026-01-01",
                "planned_finish": "2026-01-10",
                "percent_complete": 60,
                "actual_start": "2026-01-01",
            },
            # T3 at risk: 15 of 20 days elapsed (75% planned), only 30% done
            {
                "planned_start": "2026-01-01",
                "planned_finish": "2026-01-20",
                "percent_complete": 30,
                "actual_start": "2026-01-01",
            },
            # T4 on track
            {
                "planned_start": "2026-01-11",
                "planned_finish": "2026-02-28",
                "percent_complete": 10,
                "actual_start": "2026-01-11",
            },
            # T5 future
            {"planned_start": "2026-03-01", "planned_finish": "2026-03-10"},
        ]
    )
    f = flag_tasks(tasks, STATUS)
    assert _status_of(f, "T1").status == "Complete"
    assert _status_of(f, "T1").reasons == "finished 2d late"
    assert _status_of(f, "T2").status == "Overdue"
    assert _status_of(f, "T2").days_late == 5
    assert _status_of(f, "T3").status == "At risk"
    assert "45 pts behind plan" in _status_of(f, "T3").reasons
    assert _status_of(f, "T4").status == "On track"
    assert _status_of(f, "T5").status == "Not started"


def test_due_soon_rule(make):
    tasks = make(
        [
            {
                "planned_start": "2026-01-10",
                "planned_finish": "2026-01-18",
                "percent_complete": 60,
            }
        ]
    )
    # planned 6/9 = 67%, done 60%: gap 7 pts, but due in 3 days at 60% < 75%
    f = flag_tasks(tasks, STATUS)
    assert f.iloc[0].status == "At risk"
    assert f.iloc[0].reasons == "due in 3d at 60%"
    relaxed = flag_tasks(tasks, STATUS, RiskRules(due_soon_min_pct=50))
    assert relaxed.iloc[0].status == "On track"


def test_cost_overrun_rule(make):
    tasks = make(
        [
            {
                "planned_start": "2026-01-10",
                "planned_finish": "2026-03-01",
                "budget": 1000,
                "percent_complete": 10,
                "actual_cost": 200,
            }
        ]
    )
    f = flag_tasks(tasks, STATUS)
    assert f.iloc[0].status == "At risk"
    assert "cost 2.0x earned value" in f.iloc[0].reasons


@pytest.mark.parametrize(
    "kwargs",
    [
        {"schedule_gap_pts": 0},
        {"due_soon_days": -1},
        {"due_soon_min_pct": 120},
        {"cost_overrun_ratio": 0.5},
    ],
)
def test_invalid_risk_rules(kwargs):
    with pytest.raises(ValueError):
        RiskRules(**kwargs)


def test_exceptions_sorted_worst_first(make):
    tasks = make(
        [
            {"planned_start": "2026-01-01", "planned_finish": "2026-01-12"},
            {"planned_start": "2026-01-01", "planned_finish": "2026-01-02"},
            {"planned_start": "2026-01-10", "planned_finish": "2026-01-18"},
        ]
    )
    f = flag_tasks(tasks, STATUS)
    ex = exceptions(f)
    assert ex["task_id"].tolist() == ["T2", "T1", "T3"]
    assert overdue_counts(f).to_dict() == {"P1": 2}


def test_weekly_load_counts_weekdays_only(make):
    # Mon Jan 12 to Sun Jan 18: 5 weekdays, one owner, two overlapping tasks
    tasks = make(
        [
            {"planned_start": "2026-01-12", "planned_finish": "2026-01-18"},
            {"planned_start": "2026-01-14", "planned_finish": "2026-01-16"},
        ]
    )
    load = weekly_load(tasks)
    assert len(load) == 1
    row = load.iloc[0]
    assert row.week_start == pd.Timestamp("2026-01-12")
    assert row.task_days == 8
    assert row.utilization == pytest.approx(1.6)


def test_weekly_load_skips_complete_and_past_weeks(make):
    tasks = make(
        [
            {
                "planned_start": "2026-01-05",
                "planned_finish": "2026-01-23",
            },
            {
                "planned_start": "2026-01-05",
                "planned_finish": "2026-01-09",
                "percent_complete": 100,
                "owner": "Done Person",
            },
        ]
    )
    load = weekly_load(tasks, status_date=STATUS)
    assert set(load["owner"]) == {"Alex Owner"}
    assert load["week_start"].min() == pd.Timestamp("2026-01-12")


def test_owner_summary(make):
    tasks = make(
        [
            {
                "owner": "Kim",
                "planned_start": "2026-01-01",
                "planned_finish": "2026-01-10",
                "budget": 1000,
                "percent_complete": 50,
            },
            {
                "owner": "Kim",
                "planned_start": "2026-01-12",
                "planned_finish": "2026-01-16",
                "budget": 500,
            },
            {
                "owner": "Kim",
                "planned_start": "2026-01-12",
                "planned_finish": "2026-01-16",
                "budget": 500,
            },
            {
                "owner": "Lee",
                "planned_start": "2026-02-02",
                "planned_finish": "2026-02-06",
                "budget": 300,
            },
        ]
    )
    summary = owner_summary(flag_tasks(tasks, STATUS), STATUS).set_index("owner")
    assert summary.at["Kim", "open_tasks"] == 3
    assert summary.at["Kim", "overdue"] == 1
    assert summary.at["Kim", "remaining_budget"] == 1500
    assert summary.at["Kim", "peak_utilization"] == pytest.approx(2.0)
    assert summary.at["Kim", "weeks_overallocated"] == 1
    assert summary.at["Lee", "peak_utilization"] == pytest.approx(1.0)
    assert summary.index[0] == "Kim"  # overdue owners sort first


def test_burn_series_hand_computed(make):
    tasks = make(
        [
            # Done on Jan 3 (planned Jan 1-4): earns 400 on Jan 3
            {
                "planned_start": "2026-01-01",
                "planned_finish": "2026-01-04",
                "budget": 400,
                "percent_complete": 100,
                "actual_start": "2026-01-01",
                "actual_finish": "2026-01-03",
            },
            # Planned Jan 5-8, 50% done, started Jan 5, status Jan 6: EV 300 over 2 days
            {
                "planned_start": "2026-01-05",
                "planned_finish": "2026-01-08",
                "budget": 600,
                "percent_complete": 50,
                "actual_start": "2026-01-05",
            },
        ]
    )
    s = burn_series(tasks, pd.Timestamp("2026-01-06")).set_index("date")
    assert s["scope"].iloc[0] == 1000
    assert s.at[pd.Timestamp("2026-01-02"), "planned"] == pytest.approx(200)
    assert s.at[pd.Timestamp("2026-01-08"), "planned"] == pytest.approx(1000)
    assert s.at[pd.Timestamp("2026-01-02"), "actual"] == 0
    assert s.at[pd.Timestamp("2026-01-03"), "actual"] == 400
    assert s.at[pd.Timestamp("2026-01-05"), "actual"] == pytest.approx(550)
    assert s.at[pd.Timestamp("2026-01-06"), "actual"] == pytest.approx(700)
    assert pd.isna(s.at[pd.Timestamp("2026-01-07"), "actual"])
    assert s.at[pd.Timestamp("2026-01-06"), "actual_remaining"] == pytest.approx(300)
    assert s.at[pd.Timestamp("2026-01-06"), "planned_remaining"] == pytest.approx(300)


def test_burn_series_empty(make):
    empty = make([{"planned_start": "2026-01-01", "planned_finish": "2026-01-02"}]).iloc[0:0]
    assert burn_series(empty, STATUS).empty
