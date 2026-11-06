"""Critical path method (CPM) with forward and backward passes.

Durations are planned calendar days, inclusive of both endpoints, so a task
planned 1st to 5th lasts 5 days. All links are finish-to-start with zero lag.
Times are expressed as day offsets from the start of the project (day 0):

* Forward pass:  ES = max(EF of predecessors) (0 if none);  EF = ES + duration
* Backward pass: LF = min(LS of successors) (project finish if none);  LS = LF - duration
* Total slack = LS - ES. Tasks with zero slack form the critical path.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import pandas as pd

from project_health.schema import parse_dependencies


class CycleError(ValueError):
    """Raised when dependencies form a loop, which makes scheduling impossible."""


@dataclass(frozen=True)
class CPMResult:
    schedule: pd.DataFrame  # one row per task: duration, es, ef, ls, lf, slack, critical
    project_duration: int
    critical_path: list[str]  # task_ids in execution order


def task_duration(start: pd.Timestamp, finish: pd.Timestamp) -> int:
    """Inclusive planned duration in days (a same-day task is 1 day)."""
    return max(int((pd.Timestamp(finish) - pd.Timestamp(start)).days) + 1, 0)


def topological_order(preds: dict[str, list[str]]) -> list[str]:
    """Kahn's algorithm. Ties are broken by input order for stable output."""
    order_index = {t: i for i, t in enumerate(preds)}
    indegree = {t: len(p) for t, p in preds.items()}
    succs: dict[str, list[str]] = {t: [] for t in preds}
    for t, ps in preds.items():
        for p in ps:
            succs[p].append(t)
    queue = deque(sorted((t for t, d in indegree.items() if d == 0), key=order_index.get))
    order: list[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for s in sorted(succs[node], key=order_index.get):
            indegree[s] -= 1
            if indegree[s] == 0:
                queue.append(s)
    if len(order) != len(preds):
        stuck = sorted(t for t, d in indegree.items() if d > 0)
        raise CycleError(f"circular dependency among tasks: {', '.join(stuck)}")
    return order


def critical_path(tasks: pd.DataFrame) -> CPMResult:
    """Run CPM on the tasks of a single project.

    Expects columns ``task_id``, ``planned_start``, ``planned_finish``, and
    ``dependencies``. Dependencies pointing outside the given task set are ignored
    (validation reports them separately).
    """
    if tasks.empty:
        empty = pd.DataFrame(
            columns=["task_id", "duration", "es", "ef", "ls", "lf", "slack", "critical"]
        )
        return CPMResult(empty, 0, [])

    ids = [str(t) for t in tasks["task_id"]]
    known = set(ids)
    durations = {
        str(r.task_id): task_duration(r.planned_start, r.planned_finish)
        for r in tasks.itertuples(index=False)
    }
    deps_col = tasks["dependencies"] if "dependencies" in tasks else [None] * len(tasks)
    preds = {
        tid: [d for d in parse_dependencies(dep) if d in known and d != tid]
        for tid, dep in zip(ids, deps_col, strict=True)
    }
    order = topological_order(preds)

    es: dict[str, int] = {}
    ef: dict[str, int] = {}
    for t in order:
        es[t] = max((ef[p] for p in preds[t]), default=0)
        ef[t] = es[t] + durations[t]

    project_duration = max(ef.values(), default=0)
    succs: dict[str, list[str]] = {t: [] for t in ids}
    for t, ps in preds.items():
        for p in ps:
            succs[p].append(t)

    lf: dict[str, int] = {}
    ls: dict[str, int] = {}
    for t in reversed(order):
        lf[t] = min((ls[s] for s in succs[t]), default=project_duration)
        ls[t] = lf[t] - durations[t]

    schedule = pd.DataFrame(
        {
            "task_id": ids,
            "duration": [durations[t] for t in ids],
            "es": [es[t] for t in ids],
            "ef": [ef[t] for t in ids],
            "ls": [ls[t] for t in ids],
            "lf": [lf[t] for t in ids],
        }
    )
    schedule["slack"] = schedule["ls"] - schedule["es"]
    schedule["critical"] = schedule["slack"] == 0
    path = [t for t in order if ls[t] - es[t] == 0]
    return CPMResult(schedule, project_duration, path)


def attach_cpm(tasks: pd.DataFrame) -> pd.DataFrame:
    """Return ``tasks`` with CPM columns joined on, computed project by project."""
    frames = []
    for _, group in tasks.groupby("project_id", sort=False):
        result = critical_path(group)
        merged = group.merge(
            result.schedule.astype({"task_id": "string"}),
            on="task_id",
            how="left",
        )
        frames.append(merged)
    if not frames:
        return tasks.assign(duration=[], es=[], ef=[], ls=[], lf=[], slack=[], critical=[])
    return pd.concat(frames, ignore_index=True)
