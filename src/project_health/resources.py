"""Resource load per owner.

Each open task is assumed to need its owner full time on every planned weekday
(Mon to Fri) between planned_start and planned_finish. Weekly utilisation is
assigned task-days divided by 5 working days, so 1.0 means fully booked and
anything above 1.0 means the owner is overallocated that week.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

WORKDAYS_PER_WEEK = 5


def weekly_load(
    tasks: pd.DataFrame,
    status_date: pd.Timestamp | None = None,
    include_complete: bool = False,
) -> pd.DataFrame:
    """Long table of ``owner``, ``week_start`` (Monday), ``task_days``, ``utilization``.

    When ``status_date`` is given, days before the status week are ignored so
    the view looks forward.
    """
    cols = ["owner", "week_start", "task_days", "utilization"]
    t = tasks if include_complete else tasks[tasks["percent_complete"] < 100]
    records: list[tuple[str, pd.Timestamp]] = []
    floor = None
    if status_date is not None:
        s = pd.Timestamp(status_date).normalize()
        floor = s - pd.Timedelta(days=s.weekday())
    for r in t.itertuples(index=False):
        days = pd.bdate_range(r.planned_start, r.planned_finish)
        if floor is not None:
            days = days[days >= floor]
        records.extend((r.owner, d) for d in days)
    if not records:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(records, columns=["owner", "day"])
    df["week_start"] = df["day"] - pd.to_timedelta(df["day"].dt.day_of_week, unit="D")
    out = df.groupby(["owner", "week_start"]).size().rename("task_days").reset_index()
    out["utilization"] = out["task_days"] / WORKDAYS_PER_WEEK
    return out[cols].sort_values(["owner", "week_start"]).reset_index(drop=True)


def owner_summary(flagged: pd.DataFrame, status_date: pd.Timestamp | None = None) -> pd.DataFrame:
    """Per-owner table: open, overdue and at-risk task counts, remaining budget,
    peak weekly utilisation, and weeks overallocated.

    ``flagged`` is the output of :func:`project_health.risk.flag_tasks`.
    """
    if flagged.empty:
        return pd.DataFrame(
            columns=[
                "owner", "open_tasks", "overdue", "at_risk", "remaining_budget",
                "peak_utilization", "weeks_overallocated",
            ]
        )  # fmt: skip
    f = flagged.assign(
        _open=flagged["percent_complete"] < 100,
        _overdue=flagged["status"].eq("Overdue"),
        _risk=flagged["status"].eq("At risk"),
        _remaining=flagged["budget"] - flagged["ev"],
    )
    base = f.groupby("owner").agg(
        open_tasks=("_open", "sum"),
        overdue=("_overdue", "sum"),
        at_risk=("_risk", "sum"),
        remaining_budget=("_remaining", "sum"),
    )
    load = weekly_load(flagged, status_date)
    if load.empty:
        base["peak_utilization"] = 0.0
        base["weeks_overallocated"] = 0
    else:
        grp = load.groupby("owner")["utilization"]
        base["peak_utilization"] = grp.max()
        base["weeks_overallocated"] = load[load["utilization"] > 1].groupby("owner").size()
        base = base.fillna({"peak_utilization": 0.0, "weeks_overallocated": 0})
    base = base.astype(
        {"open_tasks": int, "overdue": int, "at_risk": int, "weeks_overallocated": int}
    )
    base["remaining_budget"] = np.round(base["remaining_budget"].astype(float), 2)
    return base.sort_values(["overdue", "peak_utilization"], ascending=False).reset_index()
