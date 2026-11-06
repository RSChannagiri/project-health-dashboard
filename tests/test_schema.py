from __future__ import annotations

import io

import pandas as pd
import pytest

from project_health.schema import (
    REQUIRED_COLUMNS,
    DataValidationError,
    coerce_types,
    load_tasks,
    parse_dependencies,
    template_frame,
    validate,
)


def _csv(df: pd.DataFrame) -> io.BytesIO:
    return io.BytesIO(df.to_csv(index=False).encode())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("T1;T2", ["T1", "T2"]),
        (" T1 ; T2 ", ["T1", "T2"]),
        ("T1, T2", ["T1", "T2"]),
        ("", []),
        (None, []),
        (float("nan"), []),
        (pd.NA, []),
    ],
)
def test_parse_dependencies(raw, expected):
    assert parse_dependencies(raw) == expected


def test_template_loads_cleanly():
    df, report = load_tasks(_csv(template_frame()), "template.csv")
    assert len(df) == 3
    assert report.ok and report.warnings == []
    assert df["planned_start"].dtype.kind == "M"
    assert df["budget"].dtype == "float64"


def test_headers_are_normalised():
    raw = template_frame().rename(columns={"percent_complete": "Percent Complete"})
    df, report = coerce_types(raw)
    assert report.ok and "percent_complete" in df.columns


def test_missing_required_column():
    raw = template_frame().drop(columns=["budget"])
    with pytest.raises(DataValidationError, match="Missing required columns: budget"):
        load_tasks(_csv(raw), "x.csv")


def test_optional_columns_may_be_absent():
    raw = template_frame()[list(REQUIRED_COLUMNS)]
    df, _ = load_tasks(_csv(raw), "x.csv")
    assert df["dependencies"].isna().all()


def test_bad_date_and_number_reported_with_row_numbers():
    raw = template_frame().astype(str)
    raw.loc[1, "planned_start"] = "not a date"
    raw.loc[2, "budget"] = "lots"
    with pytest.raises(DataValidationError) as exc:
        load_tasks(_csv(raw), "x.csv")
    joined = " ".join(exc.value.errors)
    assert "Row 3: 'not a date' is not a valid date in planned_start" in joined
    assert "Row 4: 'lots' is not a number in budget" in joined


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("percent_complete", 140, "percent_complete must be between 0 and 100"),
        ("budget", -5, "budget cannot be negative"),
        ("actual_cost", -1, "actual_cost cannot be negative"),
        ("planned_finish", "2025-01-01", "planned_finish is before planned_start"),
        ("dependencies", "T9", "unknown dependency 'T9'"),
        ("dependencies", "T2", "task depends on itself"),
        ("owner", None, "owner is blank"),
    ],
)
def test_business_rule_errors(column, value, message):
    df, _ = coerce_types(template_frame())
    df.loc[1, column] = value
    report = validate(df)
    assert not report.ok
    assert any(message in e for e in report.errors), report.errors


def test_duplicate_task_ids():
    raw = template_frame()
    raw.loc[2, "task_id"] = "T1"
    raw.loc[2, "dependencies"] = ""
    with pytest.raises(DataValidationError, match="duplicate task_id"):
        load_tasks(_csv(raw), "x.csv")


def test_cycle_is_a_validation_error():
    raw = template_frame()
    raw.loc[0, "dependencies"] = "T3"
    with pytest.raises(DataValidationError, match="circular dependency"):
        load_tasks(_csv(raw), "x.csv")


def test_same_task_id_allowed_in_different_projects():
    a = template_frame()
    b = template_frame().assign(project_id="P02", project_name="Second")
    df, report = load_tasks(_csv(pd.concat([a, b])), "x.csv")
    assert report.ok and df["project_id"].nunique() == 2


def test_warnings_do_not_block():
    raw = template_frame()
    raw.loc[0, "actual_finish"] = ""  # 100% complete with no finish date
    raw.loc[2, "actual_cost"] = 50  # cost with 0% progress
    df, report = load_tasks(_csv(raw), "x.csv")
    assert len(df) == 3
    assert any("actual_finish is blank" in w for w in report.warnings)
    assert any("cost recorded but 0% complete" in w for w in report.warnings)


def test_empty_file_rejected():
    raw = template_frame().iloc[0:0]
    with pytest.raises(DataValidationError, match="no task rows"):
        load_tasks(_csv(raw), "x.csv")


def test_blank_rows_are_dropped():
    raw = pd.concat(
        [template_frame(), pd.DataFrame([[None] * 14], columns=template_frame().columns)]
    )
    df, _ = load_tasks(_csv(raw), "x.csv")
    assert len(df) == 3


def test_excel_prefers_tasks_sheet(tmp_path):
    path = tmp_path / "book.xlsx"
    with pd.ExcelWriter(path) as xw:
        pd.DataFrame({"notes": ["readme"]}).to_excel(xw, sheet_name="About", index=False)
        template_frame().to_excel(xw, sheet_name="Tasks", index=False)
    df, report = load_tasks(path)
    assert report.ok and len(df) == 3


def test_unsupported_extension(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text("{}")
    with pytest.raises(DataValidationError, match="Unsupported file type"):
        load_tasks(path)


def test_garbage_bytes_raise_validation_error():
    with pytest.raises(DataValidationError):
        load_tasks(io.BytesIO(b"\x00\x01\x02 not a spreadsheet"), "broken.xlsx")
