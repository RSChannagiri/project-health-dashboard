"""Weekly executive status summary rendered as Markdown."""

from __future__ import annotations

import pandas as pd

from project_health.analysis import PortfolioAnalysis, rag_counts

RAG_ICON = {"Green": "🟢", "Amber": "🟠", "Red": "🔴"}


def money(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1_000_000:
        return f"{sign}${v / 1_000_000:.2f}M"
    if v >= 10_000:
        return f"{sign}${v / 1_000:.1f}K"
    return f"{sign}${v:,.0f}"


def ratio(value: float | None) -> str:
    return "n/a" if value is None or pd.isna(value) else f"{value:.2f}"


def _md_escape(text: object) -> str:
    return str(text).replace("|", "\\|")


def executive_summary(analysis: PortfolioAnalysis, max_items: int = 5) -> str:
    """Build a one page Markdown status report for the week ending on the status date."""
    a = analysis
    status = a.status_date
    week_start = status - pd.Timedelta(days=status.weekday())
    p = a.portfolio
    counts = rag_counts(a.projects)
    lines: list[str] = [
        f"# Portfolio Status Report: week of {week_start:%b %d, %Y}",
        "",
        f"_Status date: {status:%A, %B %d, %Y}. {len(a.projects)} projects, {len(a.tasks)} tasks._",
        "",
        "## Headline",
        "",
        f"- **Health:** {counts['Green']} Green, {counts['Amber']} Amber, {counts['Red']} Red",
        f"- **Budget:** {money(p['bac'])} total, {money(p['ac'])} spent, "
        f"forecast {money(p['eac'])} at completion ({money(p['vac'])} variance)",
        f"- **Performance:** CPI {ratio(p['cpi'])}, SPI {ratio(p['spi'])}; "
        f"{p['percent_complete']:.0f}% earned vs {p['percent_planned']:.0f}% planned",
        f"- **Exceptions:** {int((a.tasks['status'] == 'Overdue').sum())} overdue and "
        f"{int((a.tasks['status'] == 'At risk').sum())} at-risk tasks",
        "",
        "## Project scorecard",
        "",
        "| Project | Status | % Done | CPI | SPI | BAC | EAC | VAC |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    if not a.projects.empty:
        severity = {"Red": 0, "Amber": 1, "Green": 2}
        ordered = a.projects.assign(_s=a.projects["rag"].map(severity)).sort_values(["_s", "spi"])
        for pid, r in ordered.iterrows():
            lines.append(
                f"| {_md_escape(r['project_name'])} ({pid}) | {RAG_ICON[r['rag']]} {r['rag']} "
                f"| {r['percent_complete']:.0f}% | {ratio(r['cpi'])} | {ratio(r['spi'])} "
                f"| {money(r['bac'])} | {money(r['eac'])} | {money(r['vac'])} |"
            )
        flagged = ordered[ordered["rag"] != "Green"]
        if not flagged.empty:
            lines += ["", "## Needs attention", ""]
            for _pid, r in flagged.iterrows():
                reason = r["rag_reasons"] or "see scorecard"
                lines.append(f"- **{_md_escape(r['project_name'])}** ({r['rag']}): {reason}")

    lines += ["", "## Top exceptions", ""]
    ex = a.exceptions.head(max_items)
    if ex.empty:
        lines.append("No overdue or at-risk tasks. 🎉")
    else:
        lines += ["| Task | Project | Owner | Status | Detail |", "|---|---|---|---|---|"]
        for r in ex.itertuples(index=False):
            crit = " (critical path)" if bool(getattr(r, "critical", False)) else ""
            lines.append(
                f"| {_md_escape(r.task_name)}{crit} | {r.project_id} | {_md_escape(r.owner)} "
                f"| {r.status} | {_md_escape(r.reasons)} |"
            )

    lines += ["", "## Due next week", ""]
    horizon = status + pd.Timedelta(days=7)
    upcoming = a.tasks[
        (a.tasks["percent_complete"] < 100)
        & (a.tasks["planned_finish"] > status)
        & (a.tasks["planned_finish"] <= horizon)
    ].sort_values("planned_finish")
    if upcoming.empty:
        lines.append("Nothing scheduled to finish in the next 7 days.")
    else:
        for r in upcoming.head(max_items * 2).itertuples(index=False):
            lines.append(
                f"- {r.planned_finish:%a %b %d}: {_md_escape(r.task_name)} "
                f"({r.project_id}, {_md_escape(r.owner)}, {r.percent_complete:.0f}% done)"
            )

    th = a.thresholds
    lines += [
        "",
        "---",
        f"_RAG rules: Green when CPI and SPI are at least {th.cpi_green:.2f} / "
        f"{th.spi_green:.2f}; Red below {th.cpi_amber:.2f} / {th.spi_amber:.2f}"
        + (f" or with {th.overdue_red}+ overdue tasks" if th.overdue_red else "")
        + "._",
        "",
    ]
    return "\n".join(lines)
