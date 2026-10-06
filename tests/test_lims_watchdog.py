"""
test_lims_watchdog.py

Tests the CLI-level behavior of lims_watchdog.py: schema validation and
the LabWare-style reject-with-.ERR-and-.LOG behavior for a malformed
input file.

    REQ-01: The system shall reject an input file missing required
            columns, writing a .ERR copy and a .LOG describing why,
            without producing a flagged-results output.
    REQ-02: The system shall accept a well-formed export and produce a
            flagged_results.csv with one row per input row.
"""

import os

import pandas as pd
import pytest

from lims_watchdog import REQUIRED_COLUMNS, validate_schema, reject_file


def test_validate_schema_passes_on_good_file():
    df = pd.DataFrame([{col: 1 for col in REQUIRED_COLUMNS}])
    assert validate_schema(df, "irrelevant.csv") == []


def test_validate_schema_flags_missing_columns():
    df = pd.DataFrame([{"Sample.Sample_Number": 1}])  # missing almost everything
    problems = validate_schema(df, "irrelevant.csv")
    assert len(problems) >= 1
    assert any("Missing required column" in p for p in problems)


def test_validate_schema_flags_empty_file():
    df = pd.DataFrame(columns=REQUIRED_COLUMNS)
    problems = validate_schema(df, "irrelevant.csv")
    assert any("zero data rows" in p for p in problems)


def test_reject_file_writes_err_and_log(tmp_path):
    bad_csv = tmp_path / "bad_export.csv"
    bad_csv.write_text("Sample.Sample_Number\n1\n")

    reject_file(str(bad_csv), ["Missing required column(s): Result.Numeric_Entry"])

    err_path = str(bad_csv) + ".ERR"
    log_path = str(bad_csv) + ".LOG"
    assert os.path.exists(err_path)
    assert os.path.exists(log_path)

    log_contents = open(log_path).read()
    assert "Missing required column(s)" in log_contents
    assert "Result.Numeric_Entry" in log_contents
