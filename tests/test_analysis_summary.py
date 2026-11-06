from __future__ import annotations

import pandas as pd
import pytest

from project_health.analysis import analyze, rag_counts
from project_health.rag import RAGThresholds
from project_health.sample_data import SAMPLE_STATUS_DATE, generate
from project_health.summary import executive_summary, money, ratio


@pytest.fixture(scope="module")
def analysis(sample_tasks):
    return analyze(sample_tasks, SAMPLE_STATUS_DATE)


def test_one_row_per_project(analysis):
    assert len(analysis.projects) == 5
    assert set(analysis.projects["rag"]) <= {"Green", "Amber", "Red"}


def test_portfolio_totals_equal_sum_of_projects(analysis):
    p = analysis.portfolio
    for key in ("bac", "pv", "ev", "ac"):
        assert p[key] == pytest.approx(analysis.projects[key].sum())
    assert p["cpi"] == pytest.approx(p["ev"] / p["ac"])


def test_sample_has_a_mix_of_health(analysis):
    counts = rag_counts(analysis.projects)
    assert counts["Green"] >= 1 and counts["Red"] >= 1
    assert sum(counts.values()) == 5


def test_red_projects_explain_why(analysis):
    red = analysis.projects[analysis.projects["rag"] == "Red"]
    assert (red["rag_reasons"].str.len() > 0).all()


def test_loosening_thresholds_turns_everything_green(sample_tasks):
    lenient = RAGThresholds(
        cpi_green=0.5, cpi_amber=0.4, spi_green=0.5, spi_amber=0.4, overdue_amber=0, overdue_red=0
    )
    a = analyze(sample_tasks, SAMPLE_STATUS_DATE, lenient)
    assert set(a.projects["rag"]) == {"Green"}


def test_tasks_carry_cpm_and_risk_columns(analysis):
    for col in ("pv", "ev", "status", "reasons", "slack", "critical"):
        assert col in analysis.tasks.columns
    assert analysis.tasks.groupby("project_id")["critical"].any().all()


def test_project_tasks_filter(analysis):
    t = analysis.project_tasks("PRJ-101")
    assert set(t["project_id"]) == {"PRJ-101"} and len(t) == 9


def test_money_and_ratio_formatting():
    assert money(1_234_567) == "$1.23M"
    assert money(-45_600) == "-$45.6K"
    assert money(950) == "$950"
    assert money(None) == "n/a"
    assert ratio(0.876) == "0.88"
    assert ratio(None) == "n/a"


def test_executive_summary_content(analysis):
    md = executive_summary(analysis)
    assert md.startswith("# Portfolio Status Report: week of Oct 26, 2026")
    for heading in ("## Headline", "## Project scorecard", "## Top exceptions", "## Due next week"):
        assert heading in md
    for name in analysis.projects["project_name"]:
        assert name in md
    # Red projects are listed before green ones in the scorecard.
    table = md.split("## Project scorecard")[1]
    assert table.index("🔴") < table.index("🟢")
    assert "\u2014" not in md  # house style: no em dashes


def test_summary_handles_clean_portfolio(make):
    tasks = make(
        [
            {
                "planned_start": "2026-01-01",
                "planned_finish": "2026-01-05",
                "percent_complete": 100,
                "actual_cost": 1000,
                "actual_start": "2026-01-01",
                "actual_finish": "2026-01-05",
            }
        ]
    )
    md = executive_summary(analyze(tasks, pd.Timestamp("2026-01-20")))
    assert "No overdue or at-risk tasks" in md
    assert "Nothing scheduled to finish in the next 7 days" in md
    assert "1 Green, 0 Amber, 0 Red" in md


def test_summary_escapes_pipes(make):
    tasks = make(
        [
            {
                "task_name": "Build | test",
                "planned_start": "2026-01-01",
                "planned_finish": "2026-01-05",
            }
        ]
    )
    md = executive_summary(analyze(tasks, pd.Timestamp("2026-01-20")))
    assert "Build \\| test" in md


def test_sample_generation_is_deterministic():
    pd.testing.assert_frame_equal(generate(7), generate(7))
    assert not generate(7).equals(generate(8))


def test_sample_data_shape():
    df = generate()
    assert df["project_id"].nunique() == 5
    assert df["percent_complete"].between(0, 100).all()
    assert (df["budget"] > 0).all()


def test_committed_sample_matches_generator(sample_tasks):
    """data/sample_portfolio.csv must be regenerated whenever the generator changes."""
    fresh = generate()
    assert len(fresh) == len(sample_tasks)
    assert fresh["budget"].sum() == pytest.approx(sample_tasks["budget"].sum())
