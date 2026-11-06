"""Deterministic synthetic portfolio: 5 projects with distinct health profiles.

All names are generated with Faker. No real people or real project data.
Run ``python -m project_health.sample_data`` to regenerate the files in ``data/``.
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from faker import Faker

from project_health.schema import template_frame

SAMPLE_STATUS_DATE = pd.Timestamp("2026-10-30")  # a Friday


@dataclass(frozen=True)
class Profile:
    """How a project is performing: >1 schedule_factor means ahead, >1 cost_factor over budget."""

    schedule_factor: float
    cost_factor: float


# name, duration (calendar days), dependency indexes, budget weight
Template = list[tuple[str, int, list[int], float]]

PROJECTS: list[tuple[str, str, int, Profile, Template]] = [
    (
        "PRJ-101",
        "Patient Portal Upgrade",
        -60,
        Profile(1.0, 1.02),
        [
            ("Stakeholder interviews", 10, [], 0.6),
            ("Requirements sign-off", 7, [0], 0.4),
            ("UX wireframes", 14, [1], 1.0),
            ("API integration", 28, [1], 2.2),
            ("Front-end build", 30, [2], 2.0),
            ("Security review", 10, [3], 0.8),
            ("User acceptance testing", 14, [4, 5], 1.0),
            ("Training materials", 10, [2], 0.5),
            ("Go-live and hypercare", 10, [6, 7], 0.8),
        ],
    ),
    (
        "PRJ-102",
        "Data Warehouse Migration",
        -80,
        Profile(0.85, 1.2),
        [
            ("Source system inventory", 12, [], 0.6),
            ("Target schema design", 18, [0], 1.2),
            ("ETL pipeline build", 40, [1], 3.0),
            ("Historical data backfill", 21, [2], 1.4),
            ("Data quality rules", 20, [1], 1.0),
            ("Reconciliation testing", 18, [3, 4], 1.2),
            ("Report repointing", 14, [2], 0.8),
            ("Legacy decommission", 10, [5, 6], 0.6),
        ],
    ),
    (
        "PRJ-103",
        "Vendor Onboarding Automation",
        -50,
        Profile(0.7, 1.04),
        [
            ("Process mapping", 10, [], 0.5),
            ("Vendor form redesign", 12, [0], 0.6),
            ("Workflow configuration", 25, [1], 1.8),
            ("VBA invoice macro retirement", 8, [0], 0.4),
            ("Approval routing rules", 14, [2], 0.9),
            ("Pilot with finance team", 12, [3, 4], 0.7),
            ("Rollout and comms", 7, [5], 0.4),
        ],
    ),
    (
        "PRJ-104",
        "Tableau Self-Service Rollout",
        -86,
        Profile(1.0, 0.94),
        [
            ("License procurement", 10, [], 1.5),
            ("Server setup", 14, [0], 1.2),
            ("Certified data sources", 25, [1], 1.6),
            ("Dashboard templates", 18, [2], 1.0),
            ("Analyst training cohort 1", 10, [3], 0.6),
            ("Analyst training cohort 2", 10, [4], 0.6),
            ("Governance playbook", 12, [2], 0.5),
            ("Adoption review", 5, [5, 6], 0.3),
        ],
    ),
    (
        "PRJ-105",
        "Student Success CRM Pilot",
        -25,
        Profile(0.97, 1.08),
        [
            ("Pilot charter", 5, [], 0.3),
            ("CRM sandbox setup", 10, [0], 0.8),
            ("Advisor journey design", 14, [0], 0.7),
            ("Data import mapping", 16, [1], 1.0),
            ("GenAI note summarizer prototype", 20, [1, 2], 1.4),
            ("Advisor pilot", 21, [3, 4], 1.2),
            ("Pilot evaluation report", 7, [5], 0.4),
        ],
    ),
]


def _schedule(template: Template, start: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Plan dates so each task starts the day after its last predecessor finishes."""
    dates: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for _, duration, deps, _ in template:
        s = max((dates[d][1] + pd.Timedelta(days=1) for d in deps), default=start)
        dates.append((s, s + pd.Timedelta(days=duration - 1)))
    return dates


def generate(seed: int = 42, status_date: pd.Timestamp = SAMPLE_STATUS_DATE) -> pd.DataFrame:
    """Build the sample task table. Same seed, same output."""
    rng = random.Random(seed)
    fake = Faker("en_US")
    fake.seed_instance(seed)
    team = [fake.unique.name() for _ in range(12)]
    managers = [fake.unique.name() for _ in range(len(PROJECTS))]
    rows: list[dict[str, object]] = []

    for p_idx, (pid, name, offset, profile, template) in enumerate(PROJECTS):
        start = status_date + pd.Timedelta(days=offset)
        start -= pd.Timedelta(days=start.weekday())  # projects kick off on a Monday
        total_budget = rng.randrange(180, 650) * 1000
        weight_sum = sum(w for *_, w in template)
        owners = rng.sample(team, 5)
        progress: list[float] = []
        for t_idx, ((task, _dur, deps, weight), (ps, pf)) in enumerate(
            zip(template, _schedule(template, start), strict=True)
        ):
            budget = round(total_budget * weight / weight_sum, -2)
            span = (pf - ps).days + 1
            # Slower teams stretch every task: actual duration = planned / schedule_factor.
            stretch = span / profile.schedule_factor * rng.uniform(0.97, 1.08)
            preds_done = all(progress[d] >= 100 for d in deps)
            preds_close = all(progress[d] >= 80 for d in deps)
            a_start = ps + pd.Timedelta(days=rng.choice([0, 0, 1, 2]))
            if deps and not preds_done:
                a_start = max(a_start, status_date - pd.Timedelta(days=rng.randint(0, 6)))
            elapsed = (status_date - a_start).days + 1
            pct = 0.0
            if elapsed > 0 and preds_close:
                pct = float(min(100, max(0, round(elapsed / stretch * 100 / 5) * 5)))
                if pct >= 100 and not preds_done:
                    pct = 90.0
            progress.append(pct)
            ev = budget * pct / 100
            cost = round(ev * profile.cost_factor * rng.uniform(0.95, 1.06), 2) if pct else 0.0
            actual_start = a_start if pct > 0 else None
            actual_finish = None
            if pct >= 100:
                actual_finish = min(a_start + pd.Timedelta(days=round(stretch) - 1), status_date)
            rows.append(
                {
                    "project_id": pid,
                    "project_name": name,
                    "project_manager": managers[p_idx],
                    "task_id": f"T{t_idx + 1:02d}",
                    "task_name": task,
                    "owner": owners[t_idx % len(owners)],
                    "planned_start": ps.date().isoformat(),
                    "planned_finish": pf.date().isoformat(),
                    "actual_start": actual_start.date().isoformat() if actual_start else "",
                    "actual_finish": actual_finish.date().isoformat() if actual_finish else "",
                    "budget": budget,
                    "percent_complete": pct,
                    "actual_cost": cost,
                    "dependencies": ";".join(f"T{d + 1:02d}" for d in deps),
                }
            )
    return pd.DataFrame(rows)


def write_files(out_dir: Path, seed: int = 42) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    df = generate(seed)
    csv_path = out_dir / "sample_portfolio.csv"
    xlsx_path = out_dir / "sample_portfolio.xlsx"
    template_path = out_dir / "upload_template.csv"
    df.to_csv(csv_path, index=False)
    with pd.ExcelWriter(xlsx_path) as xw:
        df.to_excel(xw, sheet_name="tasks", index=False)
    template_frame().to_csv(template_path, index=False)
    return [csv_path, xlsx_path, template_path]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    for path in write_files(args.out, args.seed):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
