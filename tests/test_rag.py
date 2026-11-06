from __future__ import annotations

import pytest

from project_health.rag import RAG, RAGThresholds, explain_status, index_status, overall_status


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.10, RAG.GREEN),
        (0.95, RAG.GREEN),  # boundary is inclusive
        (0.949, RAG.AMBER),
        (0.85, RAG.AMBER),
        (0.849, RAG.RED),
        (None, RAG.GREEN),
    ],
)
def test_index_status_boundaries(value, expected):
    assert index_status(value, 0.95, 0.85) is expected


def test_overall_takes_worst_signal():
    assert overall_status(1.0, 1.0) is RAG.GREEN
    assert overall_status(0.9, 1.0) is RAG.AMBER
    assert overall_status(1.0, 0.8) is RAG.RED
    assert overall_status(0.9, 0.8) is RAG.RED


def test_overdue_count_escalates():
    th = RAGThresholds(overdue_amber=1, overdue_red=3)
    assert overall_status(1.0, 1.0, 0, th) is RAG.GREEN
    assert overall_status(1.0, 1.0, 1, th) is RAG.AMBER
    assert overall_status(1.0, 1.0, 3, th) is RAG.RED


def test_overdue_rule_can_be_disabled():
    th = RAGThresholds(overdue_amber=0, overdue_red=0)
    assert overall_status(1.0, 1.0, 10, th) is RAG.GREEN


def test_custom_thresholds_change_outcome():
    strict = RAGThresholds(cpi_green=1.0, cpi_amber=0.98)
    assert overall_status(0.97, 1.0, thresholds=strict) is RAG.RED
    assert overall_status(0.97, 1.0) is RAG.GREEN


@pytest.mark.parametrize(
    "kwargs",
    [
        {"cpi_green": 0.8, "cpi_amber": 0.9},
        {"spi_green": 0.8, "spi_amber": 0.9},
        {"cpi_amber": 0},
        {"overdue_amber": -1},
        {"overdue_amber": 5, "overdue_red": 2},
    ],
)
def test_invalid_thresholds_rejected(kwargs):
    with pytest.raises(ValueError):
        RAGThresholds(**kwargs)


def test_explain_status_lists_drivers():
    reasons = explain_status(0.8, 0.9, 2)
    assert reasons[0].startswith("over budget (CPI 0.80")
    assert reasons[1].startswith("behind schedule (SPI 0.90")
    assert reasons[2] == "2 overdue tasks"
    assert explain_status(1.0, 1.0, 0) == []
