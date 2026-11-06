"""Streamlit UI for the project health dashboard. All calculations live in project_health."""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from project_health import charts
from project_health.analysis import PortfolioAnalysis, analyze, rag_counts
from project_health.burn import burn_series
from project_health.cpm import critical_path
from project_health.rag import RAGThresholds
from project_health.resources import owner_summary, weekly_load
from project_health.risk import RiskRules
from project_health.sample_data import SAMPLE_STATUS_DATE
from project_health.schema import DataValidationError, load_tasks, template_frame
from project_health.summary import RAG_ICON, executive_summary, money, ratio

DATA_DIR = Path(__file__).parent / "data"
SAMPLE_FILE = DATA_DIR / "sample_portfolio.csv"

st.set_page_config(page_title="Project Health Dashboard", page_icon="📊", layout="wide")


@st.cache_data(show_spinner=False)
def load_from_bytes(content: bytes, filename: str) -> tuple[pd.DataFrame, list[str]]:
    df, report = load_tasks(io.BytesIO(content), filename)
    return df, report.warnings


def sidebar() -> tuple[bytes | None, str, date, RAGThresholds | None, RiskRules | None]:
    st.sidebar.title("📊 Project Health")
    source = st.sidebar.radio("Data source", ["Sample portfolio", "Upload file"], key="source")
    content: bytes | None = None
    filename = SAMPLE_FILE.name
    default_date = SAMPLE_STATUS_DATE.date()
    if source == "Sample portfolio":
        content = SAMPLE_FILE.read_bytes()
    else:
        upload = st.sidebar.file_uploader("CSV or Excel (.xlsx)", type=["csv", "xlsx"])
        if upload is not None:
            content, filename = upload.getvalue(), upload.name
        default_date = date.today()
    st.sidebar.download_button(
        "Download upload template",
        template_frame().to_csv(index=False).encode(),
        file_name="upload_template.csv",
        mime="text/csv",
    )
    status_date = st.sidebar.date_input("Status date", value=default_date, key="status_date")

    with st.sidebar.expander("RAG thresholds", expanded=False):
        c1, c2 = st.columns(2)
        cpi_g = c1.number_input("CPI green ≥", 0.01, 2.0, 0.95, 0.01, key="cpi_green")
        cpi_a = c2.number_input("CPI amber ≥", 0.01, 2.0, 0.85, 0.01, key="cpi_amber")
        spi_g = c1.number_input("SPI green ≥", 0.01, 2.0, 0.95, 0.01, key="spi_green")
        spi_a = c2.number_input("SPI amber ≥", 0.01, 2.0, 0.85, 0.01, key="spi_amber")
        od_a = c1.number_input("Overdue amber", 0, 50, 1, 1, key="overdue_amber")
        od_r = c2.number_input("Overdue red", 0, 50, 3, 1, key="overdue_red")
    with st.sidebar.expander("At-risk rules", expanded=False):
        gap = st.number_input("Points behind plan", 1.0, 100.0, 20.0, 5.0, key="gap")
        soon = st.number_input("Due soon window (days)", 0, 60, 7, 1, key="soon")
        soon_pct = st.number_input("Due soon minimum % done", 0.0, 100.0, 75.0, 5.0)
        overrun = st.number_input("Cost overrun ratio (AC / EV)", 1.0, 5.0, 1.2, 0.05)

    thresholds = rules = None
    try:
        thresholds = RAGThresholds(cpi_g, cpi_a, spi_g, spi_a, int(od_a), int(od_r))
        rules = RiskRules(gap, int(soon), soon_pct, overrun)
    except ValueError as exc:
        st.sidebar.error(f"Invalid settings: {exc}")
    return content, filename, status_date, thresholds, rules


def kpi_row(a: PortfolioAnalysis) -> None:
    p = a.portfolio
    counts = rag_counts(a.projects)
    row1 = st.columns(4)
    row1[0].metric("Projects", len(a.projects))
    row1[1].metric("🟢 Green", counts["Green"])
    row1[2].metric("🟠 Amber", counts["Amber"])
    row1[3].metric("🔴 Red", counts["Red"])
    row2 = st.columns(4)
    row2[0].metric("Budget (BAC)", money(p["bac"]))
    row2[1].metric(
        "Forecast (EAC)", money(p["eac"]), delta=f"{money(p['vac'])} VAC", delta_color="normal"
    )
    row2[2].metric("CPI", ratio(p["cpi"]))
    row2[3].metric("SPI", ratio(p["spi"]))


def scorecard_table(a: PortfolioAnalysis) -> pd.DataFrame:
    df = a.projects.reset_index()
    df["Status"] = df["rag"].map(lambda r: f"{RAG_ICON[r]} {r}")
    return df[
        [
            "project_id", "project_name", "project_manager", "Status", "percent_complete",
            "percent_planned", "cpi", "spi", "bac", "ac", "eac", "vac", "tcpi",
            "overdue_tasks", "at_risk_tasks", "rag_reasons",
        ]
    ].rename(
        columns={
            "project_id": "ID", "project_name": "Project", "project_manager": "Manager",
            "percent_complete": "% Earned", "percent_planned": "% Planned", "cpi": "CPI",
            "spi": "SPI", "bac": "BAC ($)", "ac": "AC ($)", "eac": "EAC ($)", "vac": "VAC ($)",
            "tcpi": "TCPI", "overdue_tasks": "Overdue", "at_risk_tasks": "At risk",
            "rag_reasons": "Drivers",
        }
    )  # fmt: skip


MONEY_COLS = {
    c: st.column_config.NumberColumn(format="%,.0f")
    for c in ("BAC ($)", "AC ($)", "EAC ($)", "VAC ($)")
}
RATIO_COLS = {c: st.column_config.NumberColumn(format="%.2f") for c in ("CPI", "SPI", "TCPI")}
PCT_COLS = {c: st.column_config.NumberColumn(format="%.0f%%") for c in ("% Earned", "% Planned")}


TASK_COLS = {
    "task_id": st.column_config.TextColumn("Task"),
    "task_name": st.column_config.TextColumn("Name"),
    "project_id": st.column_config.TextColumn("Project"),
    "owner": st.column_config.TextColumn("Owner"),
    "planned_start": st.column_config.DateColumn("Planned start", format="MMM D"),
    "planned_finish": st.column_config.DateColumn("Planned finish", format="MMM D"),
    "percent_complete": st.column_config.ProgressColumn(
        "% Complete", format="%.0f%%", min_value=0, max_value=100
    ),
    "budget": st.column_config.NumberColumn("Budget ($)", format="%,.0f"),
    "actual_cost": st.column_config.NumberColumn("Actual cost ($)", format="%,.0f"),
    "status": st.column_config.TextColumn("Status"),
    "reasons": st.column_config.TextColumn("Why", width="large"),
    "critical": st.column_config.CheckboxColumn("Critical"),
    "dependencies": st.column_config.TextColumn("Depends on"),
    "slack": st.column_config.NumberColumn("Slack (days)"),
    "duration": st.column_config.NumberColumn("Duration (days)"),
    "es": st.column_config.NumberColumn("ES"),
    "ef": st.column_config.NumberColumn("EF"),
    "ls": st.column_config.NumberColumn("LS"),
    "lf": st.column_config.NumberColumn("LF"),
}


def portfolio_tab(a: PortfolioAnalysis) -> None:
    kpi_row(a)
    st.dataframe(
        scorecard_table(a),
        hide_index=True,
        width="stretch",
        column_config={**MONEY_COLS, **RATIO_COLS, **PCT_COLS},
    )
    left, right = st.columns(2)
    left.plotly_chart(
        charts.cpi_spi_scatter(a.projects, a.thresholds.cpi_green, a.thresholds.spi_green),
        width="stretch",
    )
    right.plotly_chart(charts.evm_bars(a.projects), width="stretch")


def project_tab(a: PortfolioAnalysis, project_id: str) -> None:
    row = a.projects.loc[project_id]
    tasks = a.project_tasks(project_id)
    st.subheader(f"{RAG_ICON[row['rag']]} {row['project_name']} ({project_id})")
    st.caption(
        f"Manager: {row['project_manager']} | Planned {row['planned_start']:%b %d} to "
        f"{row['planned_finish']:%b %d, %Y} | {row['rag_reasons'] or 'On track'}"
    )
    labels = [
        ("PV", money(row["pv"])), ("EV", money(row["ev"])), ("AC", money(row["ac"])),
        ("CV", money(row["cv"])), ("SV", money(row["sv"])), ("CPI", ratio(row["cpi"])),
        ("SPI", ratio(row["spi"])), ("EAC", money(row["eac"])), ("ETC", money(row["etc"])),
        ("VAC", money(row["vac"])), ("TCPI", ratio(row["tcpi"])), ("BAC", money(row["bac"])),
    ]  # fmt: skip
    for start in (0, 6):
        cols = st.columns(6)
        for col, (k, v) in zip(cols, labels[start : start + 6], strict=True):
            col.metric(k, v)
    series = burn_series(tasks, a.status_date)
    mode = st.radio("Chart", ["burnup", "burndown"], horizontal=True, key="burn_mode")
    st.plotly_chart(charts.burn_chart(series, a.status_date, mode), width="stretch")
    st.dataframe(
        tasks[
            ["task_id", "task_name", "owner", "planned_start", "planned_finish",
             "percent_complete", "budget", "actual_cost", "status", "reasons"]
        ],
        hide_index=True,
        width="stretch",
        column_config=TASK_COLS,
    )  # fmt: skip


def critical_path_tab(a: PortfolioAnalysis, project_id: str) -> None:
    tasks = a.project_tasks(project_id)
    result = critical_path(tasks)
    names = dict(zip(tasks["task_id"], tasks["task_name"], strict=True))
    st.markdown(
        f"**Critical path ({result.project_duration} days):** "
        + " → ".join(f"{t} {names[t]}" for t in result.critical_path)
    )
    st.plotly_chart(charts.gantt(tasks, a.status_date), width="stretch")
    st.caption("ES/EF/LS/LF are day offsets from project start. Slack = LS - ES.")
    st.dataframe(
        tasks[["task_id", "task_name", "dependencies", "duration", "es", "ef", "ls", "lf",
               "slack", "critical"]],
        hide_index=True,
        width="stretch",
        column_config=TASK_COLS,
    )  # fmt: skip


def resources_tab(a: PortfolioAnalysis) -> None:
    summary = owner_summary(a.tasks, a.status_date)
    st.dataframe(
        summary.rename(columns=lambda c: c.replace("_", " ").capitalize()),
        hide_index=True,
        width="stretch",
        column_config={
            "Remaining budget": st.column_config.NumberColumn(
                "Remaining budget ($)", format="%,.0f"
            ),
            "Peak utilization": st.column_config.NumberColumn(format="percent"),
        },
    )
    load = weekly_load(a.tasks, a.status_date)
    st.plotly_chart(charts.resource_heatmap(load), width="stretch")


def risks_tab(a: PortfolioAnalysis) -> None:
    ex = a.exceptions
    c1, c2 = st.columns(2)
    c1.metric("Overdue tasks", int((ex["status"] == "Overdue").sum()))
    c2.metric("At-risk tasks", int((ex["status"] == "At risk").sum()))
    if ex.empty:
        st.success("No overdue or at-risk tasks.")
        return
    st.dataframe(
        ex[["project_id", "task_id", "task_name", "owner", "status", "planned_finish",
            "percent_complete", "critical", "reasons"]],
        hide_index=True,
        width="stretch",
        column_config=TASK_COLS,
    )  # fmt: skip


def summary_tab(a: PortfolioAnalysis) -> None:
    md = executive_summary(a)
    st.download_button(
        "Download summary (.md)",
        md.encode(),
        file_name=f"status_report_{a.status_date:%Y-%m-%d}.md",
        mime="text/markdown",
    )
    st.markdown(md)


def main() -> None:
    content, filename, status_date, thresholds, rules = sidebar()
    st.title("Portfolio Project Health")
    if content is None:
        st.info("Upload a CSV or Excel file of tasks, or switch to the sample portfolio.")
        st.stop()
    try:
        tasks, warnings = load_from_bytes(content, filename)
    except DataValidationError as exc:
        st.error(f"The file has {len(exc.errors)} problem(s). Fix them and upload again.")
        st.markdown("\n".join(f"- {e}" for e in exc.errors[:50]))
        st.stop()
    if thresholds is None or rules is None:
        st.stop()
    if warnings:
        with st.expander(f"⚠️ {len(warnings)} data warning(s)"):
            st.markdown("\n".join(f"- {w}" for w in warnings))

    a = analyze(tasks, pd.Timestamp(status_date), thresholds, rules)
    tabs = st.tabs(
        ["Portfolio", "Project detail", "Critical path", "Resources", "Risks", "Exec summary"]
    )
    project_ids = list(a.projects.index)
    label = {pid: f"{pid}  {a.projects.at[pid, 'project_name']}" for pid in project_ids}
    with tabs[0]:
        portfolio_tab(a)
    with tabs[1]:
        pid = st.selectbox("Project", project_ids, format_func=label.get, key="project")
        project_tab(a, pid)
    with tabs[2]:
        pid_cp = st.selectbox("Project", project_ids, format_func=label.get, key="project_cp")
        critical_path_tab(a, pid_cp)
    with tabs[3]:
        resources_tab(a)
    with tabs[4]:
        risks_tab(a)
    with tabs[5]:
        summary_tab(a)


main()
