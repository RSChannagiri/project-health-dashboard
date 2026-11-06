"""Overdue and at-risk task detection."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from project_health.evm import task_earned_value


@dataclass(frozen=True)
class RiskRules:
    """Rules for flagging tasks that are not yet late but likely to be.

    * ``schedule_gap_pts``: planned % minus actual % at or above this is at risk.
    * ``due_soon_days`` / ``due_soon_min_pct``: due within N days and below this % done.
    * ``cost_overrun_ratio``: actual cost above earned value by this factor.
    """

    schedule_gap_pts: float = 20.0
    due_soon_days: int = 7
    due_soon_min_pct: float = 75.0
    cost_overrun_ratio: float = 1.2

    def __post_init__(self) -> None:
        if self.schedule_gap_pts <= 0:
            raise ValueError("schedule_gap_pts must be positive")
        if self.due_soon_days < 0:
            raise ValueError("due_soon_days cannot be negative")
        if not 0 <= self.due_soon_min_pct <= 100:
            raise ValueError("due_soon_min_pct must be between 0 and 100")
        if self.cost_overrun_ratio < 1:
            raise ValueError("cost_overrun_ratio must be at least 1.0")


def flag_tasks(
    tasks: pd.DataFrame, status_date: pd.Timestamp, rules: RiskRules | None = None
) -> pd.DataFrame:
    """Return every task with ``status`` (Complete, Overdue, At risk, On track,
    Not started) and a human readable ``reasons`` column."""
    rules = rules or RiskRules()
    status = pd.Timestamp(status_date).normalize()
    t = task_earned_value(tasks, status)
    statuses: list[str] = []
    reasons_col: list[str] = []
    days_late: list[int] = []
    for r in t.itertuples(index=False):
        reasons: list[str] = []
        late = 0
        if r.percent_complete >= 100:
            label = "Complete"
            if pd.notna(r.actual_finish) and r.actual_finish > r.planned_finish:
                reasons.append(f"finished {(r.actual_finish - r.planned_finish).days}d late")
        elif r.planned_finish < status:
            label = "Overdue"
            late = (status - r.planned_finish).days
            reasons.append(f"{late}d past planned finish at {r.percent_complete:.0f}%")
        else:
            gap = r.planned_pct * 100 - r.percent_complete
            if gap >= rules.schedule_gap_pts:
                reasons.append(f"{gap:.0f} pts behind plan")
            days_left = (r.planned_finish - status).days
            if days_left <= rules.due_soon_days and r.percent_complete < rules.due_soon_min_pct:
                reasons.append(f"due in {days_left}d at {r.percent_complete:.0f}%")
            if r.ev > 0 and r.ac > r.ev * rules.cost_overrun_ratio:
                reasons.append(f"cost {r.ac / r.ev:.1f}x earned value")
            elif r.ev == 0 and r.ac > 0:
                reasons.append("cost incurred with no progress")
            if reasons:
                label = "At risk"
            elif r.planned_start > status and r.percent_complete == 0:
                label = "Not started"
            else:
                label = "On track"
        statuses.append(label)
        reasons_col.append("; ".join(reasons))
        days_late.append(late)
    t["status"] = statuses
    t["reasons"] = reasons_col
    t["days_late"] = days_late
    return t


def overdue_counts(flagged: pd.DataFrame) -> pd.Series:
    """Number of overdue tasks per project_id (0 for projects with none)."""
    counts = flagged.assign(_o=flagged["status"].eq("Overdue")).groupby("project_id")["_o"].sum()
    return counts.astype(int)


def exceptions(flagged: pd.DataFrame) -> pd.DataFrame:
    """Overdue and at-risk tasks only, worst first."""
    order = {"Overdue": 0, "At risk": 1}
    out = flagged[flagged["status"].isin(order)].copy()
    out["_rank"] = out["status"].map(order)
    out = out.sort_values(["_rank", "days_late", "planned_finish"], ascending=[True, False, True])
    return out.drop(columns="_rank").reset_index(drop=True)
