"""Burnup and burndown series, measured in budget dollars of work.

There is no task history in a single status snapshot, so the actual line is
reconstructed:

* Completed tasks earn their full budget on ``actual_finish`` (or planned_finish
  if the actual date is missing).
* In-progress tasks earn their current EV evenly from ``actual_start`` (or
  planned_start) through the status date.

The planned line is cumulative PV. Burndown is simply BAC minus burnup.
"""

from __future__ import annotations

import pandas as pd

from project_health.evm import planned_fraction


def burn_series(tasks: pd.DataFrame, status_date: pd.Timestamp) -> pd.DataFrame:
    """Daily table with ``date``, ``scope``, ``planned``, ``actual`` (burnup), and
    ``planned_remaining``, ``actual_remaining`` (burndown). ``actual`` is NaN
    after the status date."""
    cols = ["date", "scope", "planned", "actual", "planned_remaining", "actual_remaining"]
    if tasks.empty:
        return pd.DataFrame(columns=cols)
    status = pd.Timestamp(status_date).normalize()
    start = tasks["planned_start"].min()
    actual_starts = tasks["actual_start"].dropna()
    if not actual_starts.empty:
        start = min(start, actual_starts.min())
    end = max(tasks["planned_finish"].max(), status)
    dates = pd.date_range(start, end, freq="D")
    bac = float(tasks["budget"].sum())

    planned = pd.Series(0.0, index=dates)
    actual = pd.Series(0.0, index=dates)
    for r in tasks.itertuples(index=False):
        planned += [
            planned_fraction(r.planned_start, r.planned_finish, d) * r.budget for d in dates
        ]
        ev = r.budget * r.percent_complete / 100.0
        if ev <= 0:
            continue
        if r.percent_complete >= 100:
            done = r.actual_finish if pd.notna(r.actual_finish) else r.planned_finish
            actual[dates >= min(done, status)] += ev
        else:
            a_start = r.actual_start if pd.notna(r.actual_start) else r.planned_start
            a_start = min(a_start, status)
            span = (status - a_start).days + 1
            for d in dates[(dates >= a_start)]:
                elapsed = min((d - a_start).days + 1, span)
                actual[d] += ev * elapsed / span

    out = pd.DataFrame({"date": dates, "scope": bac, "planned": planned.values})
    out["actual"] = actual.values
    out.loc[out["date"] > status, "actual"] = float("nan")
    out["planned_remaining"] = bac - out["planned"]
    out["actual_remaining"] = bac - out["actual"]
    return out[cols]
