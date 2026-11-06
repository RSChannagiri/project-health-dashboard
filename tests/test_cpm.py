"""Critical path forward and backward pass, checked against a hand-solved network."""

from __future__ import annotations

import pandas as pd
import pytest

from project_health.cpm import (
    CycleError,
    attach_cpm,
    critical_path,
    task_duration,
    topological_order,
)


def test_duration_is_inclusive():
    assert task_duration(pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-03")) == 3
    assert task_duration(pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-01")) == 1


def test_forward_and_backward_pass_match_hand_solution(diamond):
    # Hand solution:
    #   A: ES 0 EF 3 | LS 0 LF 3 | slack 0
    #   B: ES 3 EF 5 | LS 5 LF 7 | slack 2
    #   C: ES 3 EF 7 | LS 3 LF 7 | slack 0
    #   D: ES 7 EF 8 | LS 7 LF 8 | slack 0
    result = critical_path(diamond)
    s = result.schedule.set_index("task_id")
    assert s.loc["A", ["es", "ef", "ls", "lf", "slack"]].tolist() == [0, 3, 0, 3, 0]
    assert s.loc["B", ["es", "ef", "ls", "lf", "slack"]].tolist() == [3, 5, 5, 7, 2]
    assert s.loc["C", ["es", "ef", "ls", "lf", "slack"]].tolist() == [3, 7, 3, 7, 0]
    assert s.loc["D", ["es", "ef", "ls", "lf", "slack"]].tolist() == [7, 8, 7, 8, 0]
    assert result.project_duration == 8
    assert result.critical_path == ["A", "C", "D"]


def test_independent_tasks_only_longest_is_critical(make):
    tasks = make(
        [
            {"planned_start": "2026-01-01", "planned_finish": "2026-01-10"},
            {"planned_start": "2026-01-01", "planned_finish": "2026-01-04"},
        ]
    )
    result = critical_path(tasks)
    assert result.project_duration == 10
    assert result.critical_path == ["T1"]
    assert result.schedule.set_index("task_id").at["T2", "slack"] == 6


def test_linear_chain_is_fully_critical(make):
    tasks = make(
        [
            {"planned_start": "2026-01-01", "planned_finish": "2026-01-02"},
            {
                "planned_start": "2026-01-03",
                "planned_finish": "2026-01-05",
                "dependencies": "T1",
            },
            {
                "planned_start": "2026-01-06",
                "planned_finish": "2026-01-06",
                "dependencies": "T2",
            },
        ]
    )
    result = critical_path(tasks)
    assert result.critical_path == ["T1", "T2", "T3"]
    assert result.project_duration == 6


def test_cycle_is_detected(make):
    tasks = make(
        [
            {"planned_start": "2026-01-01", "planned_finish": "2026-01-02", "dependencies": "T2"},
            {"planned_start": "2026-01-03", "planned_finish": "2026-01-04", "dependencies": "T1"},
        ]
    )
    with pytest.raises(CycleError, match="T1, T2"):
        critical_path(tasks)


def test_topological_order_is_stable():
    assert topological_order({"x": [], "y": [], "z": ["x"]}) == ["x", "y", "z"]


def test_empty_project():
    result = critical_path(pd.DataFrame(columns=["task_id", "planned_start", "planned_finish"]))
    assert result.project_duration == 0 and result.critical_path == []


def test_attach_cpm_runs_per_project(make, diamond):
    other = make(
        [{"project_id": "P2", "planned_start": "2026-02-01", "planned_finish": "2026-02-05"}]
    )
    combined = attach_cpm(pd.concat([diamond, other], ignore_index=True))
    p2 = combined[combined["project_id"] == "P2"].iloc[0]
    assert p2["critical"] and p2["duration"] == 5
    assert combined["critical"].sum() == 4  # A, C, D + P2's only task
