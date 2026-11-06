"""Streamlit AppTest smoke tests: the real script, run headless."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    return at


def test_app_renders_without_errors(app):
    assert not app.exception
    assert not app.error
    assert app.title[0].value == "Portfolio Project Health"
    assert len(app.tabs) == 6


def test_kpis_show_portfolio_counts(app):
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Projects"] == "5"
    assert int(metrics["🟢 Green"]) + int(metrics["🟠 Amber"]) + int(metrics["🔴 Red"]) == 5


def test_exec_summary_is_rendered(app):
    text = " ".join(md.value for md in app.markdown)
    assert "Portfolio Status Report" in text
    assert "Project scorecard" in text


def test_switching_project_updates_detail(app):
    app.selectbox(key="project").select("PRJ-103").run()
    assert not app.exception
    assert any("Vendor Onboarding Automation" in s.value for s in app.subheader)


def test_burndown_toggle(app):
    app.radio(key="burn_mode").set_value("burndown").run()
    assert not app.exception


def test_invalid_thresholds_show_error(app):
    app.number_input(key="cpi_amber").set_value(1.5).run()
    assert any("amber threshold cannot exceed green" in e.value for e in app.sidebar.error)


def test_strict_thresholds_change_rag(app):
    before = {m.label: m.value for m in app.metric}["🔴 Red"]
    app.number_input(key="spi_amber").set_value(1.5)
    app.number_input(key="spi_green").set_value(2.0)
    app.number_input(key="cpi_amber").set_value(1.5)
    app.number_input(key="cpi_green").set_value(2.0).run()
    after = {m.label: m.value for m in app.metric}["🔴 Red"]
    assert int(after) == 5 and int(after) > int(before)


def test_upload_mode_without_file_prompts(app):
    app.radio(key="source").set_value("Upload file").run()
    assert not app.exception
    assert any("Upload a CSV or Excel" in i.value for i in app.info)
