"""Plotly figure builders. Pure functions of DataFrames so they can be tested headless.

Colours come from a CVD-validated categorical palette. RAG uses a reserved status
palette that is never reused for series, and is always paired with a text label.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]
STATUS = {"Green": "#0ca30c", "Amber": "#fab219", "Red": "#d03b3b"}
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#fcfcfb"
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


def _base_layout(fig: go.Figure, title: str, height: int = 420) -> go.Figure:
    fig.update_layout(
        title={"text": title, "font": {"size": 16, "color": INK}, "x": 0, "xanchor": "left"},
        height=height,
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font={"family": "Inter, Segoe UI, sans-serif", "size": 12, "color": INK_2},
        margin={"l": 60, "r": 24, "t": 56, "b": 48},
        legend={"orientation": "h", "y": -0.18, "x": 0, "font": {"color": INK_2}},
        hoverlabel={"bgcolor": "white", "font": {"color": INK}},
    )
    fig.update_xaxes(gridcolor=GRID, linecolor=AXIS, zeroline=False, tickfont={"color": MUTED})
    fig.update_yaxes(gridcolor=GRID, linecolor=AXIS, zeroline=False, tickfont={"color": MUTED})
    return fig


def _status_line(fig: go.Figure, status_date: pd.Timestamp) -> None:
    fig.add_vline(x=pd.Timestamp(status_date), line={"color": MUTED, "width": 1, "dash": "dot"})
    fig.add_annotation(
        x=pd.Timestamp(status_date),
        y=1.02,
        yref="paper",
        text="Status date",
        showarrow=False,
        font={"color": MUTED, "size": 11},
    )


def cpi_spi_scatter(projects: pd.DataFrame, cpi_target: float = 0.95, spi_target: float = 0.95):
    """Performance quadrant: SPI on x, CPI on y, one labelled dot per project."""
    fig = go.Figure()
    df = projects.reset_index()
    for status, colour in STATUS.items():
        sub = df[df["rag"] == status]
        if sub.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=sub["spi"],
                y=sub["cpi"],
                mode="markers+text",
                name=status,
                text=sub["project_name"],
                textposition="top center",
                textfont={"color": INK_2, "size": 11},
                marker={"size": 14, "color": colour, "line": {"color": SURFACE, "width": 2}},
                customdata=sub[["project_id", "eac", "bac"]].values,
                hovertemplate=(
                    "<b>%{text}</b> (%{customdata[0]})<br>SPI %{x:.2f} | CPI %{y:.2f}"
                    "<br>EAC $%{customdata[1]:,.0f} vs BAC $%{customdata[2]:,.0f}"
                    f"<br>Status: {status}<extra></extra>"
                ),
            )
        )
    if not df.empty:
        xs = [*df["spi"].dropna(), spi_target]
        ys = [*df["cpi"].dropna(), cpi_target]
        fig.update_xaxes(range=[min(xs) - 0.06, max(xs) + 0.06])
        fig.update_yaxes(range=[min(ys) - 0.04, max(ys) + 0.06])
    fig.update_traces(cliponaxis=False)
    fig.add_hline(y=cpi_target, line={"color": AXIS, "width": 1, "dash": "dash"})
    fig.add_vline(x=spi_target, line={"color": AXIS, "width": 1, "dash": "dash"})
    _base_layout(fig, "Cost vs schedule performance")
    fig.update_xaxes(title="SPI (schedule)  <  behind | ahead  >")
    fig.update_yaxes(title="CPI (cost)  <  over | under budget  >")
    return fig


def evm_bars(projects: pd.DataFrame) -> go.Figure:
    """PV, EV, AC side by side per project."""
    df = projects.reset_index()
    fig = go.Figure()
    for i, (col, label) in enumerate(
        [("pv", "Planned value (PV)"), ("ev", "Earned value (EV)"), ("ac", "Actual cost (AC)")]
    ):
        fig.add_trace(
            go.Bar(
                x=df["project_id"],
                y=df[col],
                name=label,
                marker={"color": SERIES[i], "cornerradius": 4, "line": {"width": 0}},
                customdata=df["project_name"],
                hovertemplate=f"%{{customdata}}<br>{label}: $%{{y:,.0f}}<extra></extra>",
            )
        )
    _base_layout(fig, "Earned value by project")
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
    fig.update_yaxes(title="USD", tickprefix="$", tickformat="~s")
    return fig


def burn_chart(series: pd.DataFrame, status_date: pd.Timestamp, mode: str = "burnup"):
    """Burnup (cumulative work earned) or burndown (work remaining)."""
    if mode not in {"burnup", "burndown"}:
        raise ValueError("mode must be 'burnup' or 'burndown'")
    fig = go.Figure()
    if mode == "burnup":
        planned, actual, title = "planned", "actual", "Burnup: value earned vs plan"
        fig.add_trace(
            go.Scatter(
                x=series["date"],
                y=series["scope"],
                name="Scope (BAC)",
                mode="lines",
                line={"color": MUTED, "width": 2, "dash": "dash"},
                hovertemplate="Scope $%{y:,.0f}<extra></extra>",
            )
        )
    else:
        planned, actual = "planned_remaining", "actual_remaining"
        title = "Burndown: work remaining vs plan"
    fig.add_trace(
        go.Scatter(
            x=series["date"],
            y=series[planned],
            name="Planned",
            mode="lines",
            line={"color": SERIES[0], "width": 2},
            hovertemplate="Planned $%{y:,.0f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=series["date"],
            y=series[actual],
            name="Actual",
            mode="lines",
            line={"color": SERIES[1], "width": 2},
            hovertemplate="Actual $%{y:,.0f}<extra></extra>",
        )
    )
    _base_layout(fig, title)
    fig.update_layout(hovermode="x unified")
    fig.update_yaxes(title="Work (budget $)", tickprefix="$", tickformat="~s", rangemode="tozero")
    _status_line(fig, status_date)
    return fig


def gantt(tasks: pd.DataFrame, status_date: pd.Timestamp) -> go.Figure:
    """Planned schedule with the critical path highlighted and progress in hover."""
    df = tasks.sort_values(["planned_start", "task_id"]).reset_index(drop=True)
    df = df.assign(
        label=df["task_id"] + "  " + df["task_name"],
        days=(df["planned_finish"] - df["planned_start"]).dt.days + 1,
    )
    fig = go.Figure()
    for flag, name, colour in [(True, "Critical path", SERIES[1]), (False, "Has slack", SERIES[0])]:
        sub = df[df["critical"].astype(bool) == flag]
        if sub.empty:
            continue
        fig.add_trace(
            go.Bar(
                y=sub["label"],
                x=sub["days"] * 86_400_000,
                base=sub["planned_start"],
                orientation="h",
                name=name,
                marker={"color": colour, "cornerradius": 4, "line": {"color": SURFACE, "width": 2}},
                customdata=sub[
                    ["owner", "percent_complete", "slack", "status", "planned_finish"]
                ].values,
                hovertemplate=(
                    "<b>%{y}</b><br>Owner: %{customdata[0]}<br>%{customdata[1]:.0f}% complete"
                    "<br>Finish %{customdata[4]|%b %d}<br>Slack: %{customdata[2]} days"
                    "<br>Status: %{customdata[3]}<extra></extra>"
                ),
            )
        )
    _base_layout(fig, "Schedule and critical path", height=max(320, 34 * len(df) + 120))
    fig.update_yaxes(autorange="reversed", categoryorder="array", categoryarray=df["label"])
    fig.update_xaxes(type="date")
    _status_line(fig, status_date)
    return fig


def resource_heatmap(load: pd.DataFrame) -> go.Figure:
    """Owner by week utilisation. Values above 100% mean overallocation."""
    fig = go.Figure()
    if load.empty:
        _base_layout(fig, "Resource load (no open work)")
        return fig
    pivot = load.pivot_table(
        index="owner", columns="week_start", values="utilization", aggfunc="sum", fill_value=0
    )
    text = [[f"{v:.0%}" if v else "" for v in row] for row in pivot.values]
    fig.add_trace(
        go.Heatmap(
            z=pivot.where(pivot > 0).values,
            x=[d.strftime("%b %d") for d in pivot.columns],
            y=pivot.index,
            text=text,
            texttemplate="%{text}",
            colorscale=[[i / (len(SEQUENTIAL) - 1), c] for i, c in enumerate(SEQUENTIAL)],
            zmin=0,
            zmax=max(2.0, float(pivot.values.max())),
            xgap=2,
            ygap=2,
            colorbar={"title": "Load", "tickformat": ".0%"},
            hovertemplate="%{y}<br>Week of %{x}<br>Utilization %{z:.0%}<extra></extra>",
        )
    )
    _base_layout(
        fig, "Weekly resource load (100% = 5 task-days)", height=max(300, 120 + 34 * len(pivot))
    )
    fig.update_yaxes(autorange="reversed", gridcolor=SURFACE)
    fig.update_xaxes(gridcolor=SURFACE, title="Week starting")
    return fig
