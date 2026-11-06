from __future__ import annotations

import pandas as pd
import pytest

from project_health import charts
from project_health.analysis import analyze
from project_health.burn import burn_series
from project_health.resources import weekly_load
from project_health.sample_data import SAMPLE_STATUS_DATE


@pytest.fixture(scope="module")
def analysis(sample_tasks):
    return analyze(sample_tasks, SAMPLE_STATUS_DATE)


def test_scatter_uses_status_colours_with_labels(analysis):
    fig = charts.cpi_spi_scatter(analysis.projects)
    names = {t.name for t in fig.data}
    assert names <= {"Green", "Amber", "Red"}
    for trace in fig.data:
        assert trace.marker.color == charts.STATUS[trace.name]
        assert "text" in trace.mode  # never colour alone


def test_evm_bars_has_three_series(analysis):
    fig = charts.evm_bars(analysis.projects)
    assert [t.name.split(" (")[1][:-1] for t in fig.data] == ["PV", "EV", "AC"]
    assert len(fig.data[0].x) == 5


@pytest.mark.parametrize("mode", ["burnup", "burndown"])
def test_burn_chart_modes(analysis, mode):
    series = burn_series(analysis.project_tasks("PRJ-102"), SAMPLE_STATUS_DATE)
    fig = charts.burn_chart(series, SAMPLE_STATUS_DATE, mode)
    names = [t.name for t in fig.data]
    assert "Planned" in names and "Actual" in names
    assert ("Scope (BAC)" in names) == (mode == "burnup")


def test_burn_chart_rejects_unknown_mode():
    with pytest.raises(ValueError):
        charts.burn_chart(pd.DataFrame(), SAMPLE_STATUS_DATE, "sideways")


def test_gantt_splits_critical_and_slack(analysis):
    fig = charts.gantt(analysis.project_tasks("PRJ-101"), SAMPLE_STATUS_DATE)
    by_name = {t.name: len(t.y) for t in fig.data}
    assert by_name == {"Critical path": 6, "Has slack": 3}


def test_heatmap_and_empty_heatmap(analysis):
    load = weekly_load(analysis.tasks, SAMPLE_STATUS_DATE)
    assert len(charts.resource_heatmap(load).data) == 1
    assert len(charts.resource_heatmap(load.iloc[0:0]).data) == 0
