"""One call that runs every calculation, so the UI and reports share one source of truth."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from project_health.cpm import attach_cpm, critical_path
from project_health.evm import portfolio_metrics, project_metrics
from project_health.rag import RAG, RAGThresholds, explain_status, overall_status
from project_health.risk import RiskRules, exceptions, flag_tasks, overdue_counts


@dataclass(frozen=True)
class PortfolioAnalysis:
    status_date: pd.Timestamp
    thresholds: RAGThresholds
    tasks: pd.DataFrame  # tasks with EV, risk status, and CPM columns
    projects: pd.DataFrame  # one row per project with EV metrics, RAG, and dates
    portfolio: dict[str, float | None]
    exceptions: pd.DataFrame

    def project_tasks(self, project_id: str) -> pd.DataFrame:
        return self.tasks[self.tasks["project_id"] == project_id].reset_index(drop=True)


def analyze(
    tasks: pd.DataFrame,
    status_date: pd.Timestamp,
    thresholds: RAGThresholds | None = None,
    rules: RiskRules | None = None,
) -> PortfolioAnalysis:
    th = thresholds or RAGThresholds()
    status = pd.Timestamp(status_date).normalize()
    flagged = attach_cpm(flag_tasks(tasks, status, rules))
    projects = portfolio_metrics(tasks, status)
    if not projects.empty:
        overdue = overdue_counts(flagged).reindex(projects.index, fill_value=0)
        at_risk = (
            flagged[flagged["status"] == "At risk"]
            .groupby("project_id")
            .size()
            .reindex(projects.index, fill_value=0)
        )
        projects["overdue_tasks"] = overdue.astype(int)
        projects["at_risk_tasks"] = at_risk.astype(int)
        projects["rag"] = [
            overall_status(r.cpi, r.spi, int(r.overdue_tasks), th).value
            for r in projects.itertuples()
        ]
        projects["rag_reasons"] = [
            "; ".join(explain_status(r.cpi, r.spi, int(r.overdue_tasks), th))
            for r in projects.itertuples()
        ]
        dates = tasks.groupby("project_id").agg(
            planned_start=("planned_start", "min"), planned_finish=("planned_finish", "max")
        )
        projects = projects.join(dates)
        projects["cpm_duration_days"] = [
            critical_path(tasks[tasks["project_id"] == pid]).project_duration
            for pid in projects.index
        ]
    total = project_metrics(tasks, status).as_dict()
    return PortfolioAnalysis(
        status_date=status,
        thresholds=th,
        tasks=flagged,
        projects=projects,
        portfolio=total,
        exceptions=exceptions(flagged),
    )


def rag_counts(projects: pd.DataFrame) -> dict[str, int]:
    counts = {s.value: 0 for s in RAG}
    if not projects.empty:
        for k, v in projects["rag"].value_counts().items():
            counts[str(k)] = int(v)
    return counts
