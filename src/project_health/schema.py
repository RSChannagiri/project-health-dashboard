"""Input schema, loading, and validation for project task data.

One row is one task. Project level attributes (name, manager) repeat on every
task row so a single flat CSV or Excel sheet is enough to describe a portfolio.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

import pandas as pd

REQUIRED_COLUMNS: tuple[str, ...] = (
    "project_id",
    "project_name",
    "task_id",
    "task_name",
    "owner",
    "planned_start",
    "planned_finish",
    "budget",
    "percent_complete",
    "actual_cost",
)

OPTIONAL_COLUMNS: tuple[str, ...] = (
    "project_manager",
    "actual_start",
    "actual_finish",
    "dependencies",
)

DATE_COLUMNS: tuple[str, ...] = ("planned_start", "planned_finish", "actual_start", "actual_finish")
NUMERIC_COLUMNS: tuple[str, ...] = ("budget", "percent_complete", "actual_cost")
TEXT_COLUMNS: tuple[str, ...] = (
    "project_id",
    "project_name",
    "task_id",
    "task_name",
    "owner",
    "project_manager",
    "dependencies",
)

ALL_COLUMNS: tuple[str, ...] = REQUIRED_COLUMNS + OPTIONAL_COLUMNS
DEPENDENCY_SEPARATOR = ";"


class DataValidationError(ValueError):
    """Raised when input data cannot be used. Carries every problem found."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass
class ValidationReport:
    """Outcome of validating a task table."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_dependencies(value: object) -> list[str]:
    """Split a dependency cell such as ``"T1; T2"`` into ``["T1", "T2"]``."""
    if value is None or (not isinstance(value, list | tuple) and pd.isna(value)):
        return []
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return []
    parts = text.replace(",", DEPENDENCY_SEPARATOR).split(DEPENDENCY_SEPARATOR)
    return [p.strip() for p in parts if p.strip()]


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    renamed = {c: str(c).strip().lower().replace(" ", "_").replace("%", "percent") for c in df}
    return df.rename(columns=renamed)


def coerce_types(raw: pd.DataFrame) -> tuple[pd.DataFrame, ValidationReport]:
    """Normalise headers and coerce dtypes, recording anything that fails to parse."""
    report = ValidationReport()
    df = _normalise_columns(raw.copy())

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        report.errors.append(f"Missing required columns: {', '.join(missing)}")
        return df, report

    for col in OPTIONAL_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    df = df.dropna(how="all", subset=list(REQUIRED_COLUMNS)).reset_index(drop=True)

    for col in TEXT_COLUMNS:
        df[col] = df[col].astype("string").str.strip()
        df.loc[df[col].isin(["", "nan", "NaN", "None"]), col] = pd.NA

    for col in DATE_COLUMNS:
        original = df[col]
        parsed = pd.to_datetime(original, errors="coerce")
        bad = original.notna() & parsed.isna() & (original.astype("string").str.strip() != "")
        for idx in df.index[bad]:
            report.errors.append(f"Row {idx + 2}: '{original[idx]}' is not a valid date in {col}")
        df[col] = parsed.astype("datetime64[ns]").dt.normalize()

    for col in NUMERIC_COLUMNS:
        original = df[col]
        parsed = pd.to_numeric(original, errors="coerce")
        bad = original.notna() & parsed.isna()
        for idx in df.index[bad]:
            report.errors.append(f"Row {idx + 2}: '{original[idx]}' is not a number in {col}")
        df[col] = parsed.astype("float64")

    return df[list(ALL_COLUMNS)], report


def validate(df: pd.DataFrame, report: ValidationReport | None = None) -> ValidationReport:
    """Check business rules on a type-coerced task table."""
    report = report or ValidationReport()
    if df.empty:
        report.errors.append("The file contains no task rows")
        return report

    def row(idx: int) -> str:
        return f"Row {idx + 2} ({df.at[idx, 'project_id']}/{df.at[idx, 'task_id']})"

    for col in ("project_id", "project_name", "task_id", "task_name", "owner"):
        for idx in df.index[df[col].isna()]:
            report.errors.append(f"Row {idx + 2}: {col} is blank")
    for col in ("planned_start", "planned_finish", "budget", "percent_complete", "actual_cost"):
        for idx in df.index[df[col].isna()]:
            report.errors.append(f"{row(idx)}: {col} is blank")

    for idx in df.index[df["budget"] < 0]:
        report.errors.append(f"{row(idx)}: budget cannot be negative")
    for idx in df.index[df["actual_cost"] < 0]:
        report.errors.append(f"{row(idx)}: actual_cost cannot be negative")
    pct = df["percent_complete"]
    for idx in df.index[(pct < 0) | (pct > 100)]:
        report.errors.append(f"{row(idx)}: percent_complete must be between 0 and 100")
    for idx in df.index[df["planned_finish"] < df["planned_start"]]:
        report.errors.append(f"{row(idx)}: planned_finish is before planned_start")
    for idx in df.index[df["actual_finish"] < df["actual_start"]]:
        report.errors.append(f"{row(idx)}: actual_finish is before actual_start")

    dupes = df[df.duplicated(subset=["project_id", "task_id"], keep="first")]
    for idx in dupes.index:
        report.errors.append(f"{row(idx)}: duplicate task_id within project")

    names = df.groupby("project_id")["project_name"].nunique()
    for pid in names[names > 1].index:
        report.warnings.append(f"Project {pid} has more than one project_name; the first is used")

    tasks_by_project = df.groupby("project_id")["task_id"].apply(set).to_dict()
    for idx, r in df.iterrows():
        deps = parse_dependencies(r["dependencies"])
        known = tasks_by_project.get(r["project_id"], set())
        for dep in deps:
            if dep == r["task_id"]:
                report.errors.append(f"{row(idx)}: task depends on itself")
            elif dep not in known:
                report.errors.append(f"{row(idx)}: unknown dependency '{dep}'")

    done = df["percent_complete"] >= 100
    for idx in df.index[done & df["actual_finish"].isna()]:
        report.warnings.append(f"{row(idx)}: 100% complete but actual_finish is blank")
    for idx in df.index[~done & df["actual_finish"].notna()]:
        report.warnings.append(f"{row(idx)}: has actual_finish but is under 100% complete")
    started = df["percent_complete"] > 0
    for idx in df.index[started & df["actual_start"].isna()]:
        report.warnings.append(f"{row(idx)}: has progress but actual_start is blank")
    for idx in df.index[(df["actual_cost"] > 0) & (df["percent_complete"] == 0)]:
        report.warnings.append(f"{row(idx)}: cost recorded but 0% complete")

    if report.ok:
        from project_health.cpm import CycleError, critical_path

        for pid, group in df.groupby("project_id"):
            try:
                critical_path(group)
            except CycleError as exc:
                report.errors.append(f"Project {pid}: {exc}")
    return report


def read_table(source: str | Path | BinaryIO, filename: str | None = None) -> pd.DataFrame:
    """Read a CSV or Excel file (path or uploaded buffer) into a raw DataFrame.

    For Excel workbooks a sheet named ``tasks`` is used when present, otherwise
    the first sheet.
    """
    name = (filename or getattr(source, "name", None) or str(source)).lower()
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        sheets = pd.read_excel(source, sheet_name=None)
        if not sheets:
            raise DataValidationError(["The workbook has no sheets"])
        lowered = {str(k).lower(): v for k, v in sheets.items()}
        return lowered.get("tasks", next(iter(sheets.values())))
    if name.endswith(".csv") or not isinstance(source, str | Path):
        return pd.read_csv(source, dtype=str, keep_default_na=True)
    raise DataValidationError([f"Unsupported file type: {name}. Use .csv or .xlsx"])


def load_tasks(
    source: str | Path | BinaryIO, filename: str | None = None
) -> tuple[pd.DataFrame, ValidationReport]:
    """Read, coerce, and validate. Raises DataValidationError on blocking problems."""
    try:
        raw = read_table(source, filename)
    except DataValidationError:
        raise
    except Exception as exc:  # pandas raises many parser-specific errors
        raise DataValidationError([f"Could not read file: {exc}"]) from exc
    df, report = coerce_types(raw)
    if report.ok:
        report = validate(df, report)
    if not report.ok:
        raise DataValidationError(report.errors)
    return df, report


def template_frame() -> pd.DataFrame:
    """A small example table that doubles as the upload template."""
    rows = [
        ["P01", "Example CRM Rollout", "A. Manager", "T1", "Requirements", "Owner One",
         "2026-01-05", "2026-01-16", 10000, 100, 9500, "2026-01-05", "2026-01-15", ""],
        ["P01", "Example CRM Rollout", "A. Manager", "T2", "Build", "Owner Two",
         "2026-01-19", "2026-02-13", 40000, 50, 22000, "2026-01-20", "", "T1"],
        ["P01", "Example CRM Rollout", "A. Manager", "T3", "Go live", "Owner One",
         "2026-02-16", "2026-02-20", 5000, 0, 0, "", "", "T2"],
    ]  # fmt: skip
    cols = [
        "project_id", "project_name", "project_manager", "task_id", "task_name", "owner",
        "planned_start", "planned_finish", "budget", "percent_complete", "actual_cost",
        "actual_start", "actual_finish", "dependencies",
    ]  # fmt: skip
    return pd.DataFrame(rows, columns=cols)
