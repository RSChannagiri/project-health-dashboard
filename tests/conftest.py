from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from project_health.schema import coerce_types

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CSV = ROOT / "data" / "sample_portfolio.csv"


def make_tasks(rows: list[dict]) -> pd.DataFrame:
    """Build a type-coerced task table from minimal dicts, filling sensible defaults."""
    defaults = {
        "project_id": "P1",
        "project_name": "Test Project",
        "project_manager": "Pat Manager",
        "owner": "Alex Owner",
        "budget": 1000.0,
        "percent_complete": 0.0,
        "actual_cost": 0.0,
        "actual_start": None,
        "actual_finish": None,
        "dependencies": "",
    }
    full = []
    for i, r in enumerate(rows):
        row = {**defaults, "task_id": f"T{i + 1}", "task_name": f"Task {i + 1}", **r}
        full.append(row)
    df, report = coerce_types(pd.DataFrame(full))
    assert report.ok, report.errors
    return df


@pytest.fixture
def make() -> callable:
    return make_tasks


@pytest.fixture
def diamond() -> pd.DataFrame:
    """Classic CPM network, hand-solved in tests/test_cpm.py.

    A (3d) -> B (2d) -> D (1d)
    A (3d) -> C (4d) -> D (1d)
    """
    return make_tasks(
        [
            {"task_id": "A", "planned_start": "2026-01-01", "planned_finish": "2026-01-03"},
            {
                "task_id": "B",
                "planned_start": "2026-01-04",
                "planned_finish": "2026-01-05",
                "dependencies": "A",
            },
            {
                "task_id": "C",
                "planned_start": "2026-01-04",
                "planned_finish": "2026-01-07",
                "dependencies": "A",
            },
            {
                "task_id": "D",
                "planned_start": "2026-01-08",
                "planned_finish": "2026-01-08",
                "dependencies": "B; C",
            },
        ]
    )


@pytest.fixture(scope="session")
def sample_tasks() -> pd.DataFrame:
    from project_health.schema import load_tasks

    df, _ = load_tasks(SAMPLE_CSV)
    return df
