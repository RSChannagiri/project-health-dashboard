"""Earned value management (EVM).

Conventions used throughout (PMBOK style):

* BAC  Budget at completion: sum of task budgets.
* PV   Planned value: budget that the plan says should be spent by the status
       date. Each task accrues its budget linearly from planned_start to
       planned_finish (finish date inclusive, so a one-day task is a full day).
* EV   Earned value: BAC x percent complete, per task.
* AC   Actual cost to date.
* CV = EV - AC         SV = EV - PV
* CPI = EV / AC        SPI = EV / PV
* EAC = BAC / CPI      (assumes current cost efficiency continues)
* ETC = EAC - AC       VAC = BAC - EAC
* TCPI = (BAC - EV) / (BAC - AC)   efficiency needed on remaining work to land on BAC

Ratios are ``None`` when their denominator is zero, rather than inf or a fake 1.0.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd


@dataclass(frozen=True)
class EVMetrics:
    bac: float
    pv: float
    ev: float
    ac: float
    cv: float
    sv: float
    cpi: float | None
    spi: float | None
    eac: float
    etc: float
    vac: float
    tcpi: float | None
    percent_complete: float
    percent_planned: float

    def as_dict(self) -> dict[str, float | None]:
        return asdict(self)


def _safe_div(num: float, den: float) -> float | None:
    if abs(den) < 1e-9:
        return None
    return num / den


def planned_fraction(
    planned_start: pd.Timestamp, planned_finish: pd.Timestamp, status_date: pd.Timestamp
) -> float:
    """Fraction of a task's planned duration elapsed at end of ``status_date``.

    Days are inclusive: a task planned 1st to 10th is 10 days long, and on the
    5th (end of day) it is 50% planned.
    """
    start = pd.Timestamp(planned_start).normalize()
    finish = pd.Timestamp(planned_finish).normalize()
    status = pd.Timestamp(status_date).normalize()
    total_days = (finish - start).days + 1
    elapsed_days = (status - start).days + 1
    if total_days <= 0:
        return 1.0 if status >= finish else 0.0
    return float(min(max(elapsed_days / total_days, 0.0), 1.0))


def task_earned_value(tasks: pd.DataFrame, status_date: pd.Timestamp) -> pd.DataFrame:
    """Add per-task ``planned_pct``, ``pv``, ``ev``, ``ac``, ``cv``, ``sv`` columns."""
    out = tasks.copy()
    if out.empty:
        for col in ("planned_pct", "pv", "ev", "ac", "cv", "sv"):
            out[col] = pd.Series(dtype="float64")
        return out
    out["planned_pct"] = [
        planned_fraction(s, f, status_date)
        for s, f in zip(out["planned_start"], out["planned_finish"], strict=True)
    ]
    out["pv"] = out["budget"] * out["planned_pct"]
    out["ev"] = out["budget"] * out["percent_complete"] / 100.0
    out["ac"] = out["actual_cost"]
    out["cv"] = out["ev"] - out["ac"]
    out["sv"] = out["ev"] - out["pv"]
    return out


def compute_metrics(bac: float, pv: float, ev: float, ac: float) -> EVMetrics:
    """Derive every EVM indicator from the four base quantities."""
    cpi = _safe_div(ev, ac)
    spi = _safe_div(ev, pv)
    # With no spend yet there is no cost performance signal, so forecast = plan.
    eac = bac / cpi if cpi else (bac if ac == 0 else ac + (bac - ev))
    etc = eac - ac
    tcpi = _safe_div(bac - ev, bac - ac) if bac - ac > 0 else None
    return EVMetrics(
        bac=bac,
        pv=pv,
        ev=ev,
        ac=ac,
        cv=ev - ac,
        sv=ev - pv,
        cpi=cpi,
        spi=spi,
        eac=eac,
        etc=etc,
        vac=bac - eac,
        tcpi=tcpi,
        percent_complete=(ev / bac * 100.0) if bac else 0.0,
        percent_planned=(pv / bac * 100.0) if bac else 0.0,
    )


def project_metrics(tasks: pd.DataFrame, status_date: pd.Timestamp) -> EVMetrics:
    """Roll tasks up into one set of EV metrics (one project, or a whole portfolio)."""
    t = task_earned_value(tasks, status_date)
    return compute_metrics(
        bac=float(t["budget"].sum()),
        pv=float(t["pv"].sum()),
        ev=float(t["ev"].sum()),
        ac=float(t["ac"].sum()),
    )


def portfolio_metrics(tasks: pd.DataFrame, status_date: pd.Timestamp) -> pd.DataFrame:
    """One row of EV metrics per project, indexed by ``project_id``."""
    rows = []
    for pid, group in tasks.groupby("project_id", sort=True):
        m = project_metrics(group, status_date)
        rows.append(
            {
                "project_id": pid,
                "project_name": group["project_name"].iloc[0],
                "project_manager": group["project_manager"].iloc[0]
                if "project_manager" in group
                else None,
                **m.as_dict(),
            }
        )
    return pd.DataFrame(rows).set_index("project_id") if rows else pd.DataFrame()
