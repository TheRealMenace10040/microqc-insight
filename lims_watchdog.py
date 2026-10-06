#!/usr/bin/env python3
"""
lims_watchdog.py

The automation piece of MicroQC Insight. Reads a "Stored Query" style CSV
export (the same TABLE.FIELD format LabWare's own CSV import/export uses),
validates its schema the way LabWare's importer would reject a bad file
(renaming it .ERR and writing a .LOG), applies the OOS/Alert/OOT/TAT rules
in rules_engine.py, and writes:

    - flagged_results.csv   -- every row, with flag columns, for Power BI
    - reports/weekly_summary_<date>.xlsx -- a manager-facing weekly report

Usage:
    python lims_watchdog.py --input stored_query_export.csv
    python lims_watchdog.py --input stored_query_export.csv --tat-sla 3
"""

import argparse
import os
import shutil
import sys
from datetime import datetime

import pandas as pd

from rules_engine import apply_all_rules

REQUIRED_COLUMNS = [
    "Sample.Sample_Number",
    "Sample.Sampling_Point",
    "Sample.Product",
    "Sample.Login_Date",
    "Sample.Date_Completed",
    "Test.Analysis",
    "Result.Numeric_Entry",
    "Result.Min_Limit",
    "Result.Max_Limit",
    "Result.Alert_Limit",
]


def validate_schema(df: pd.DataFrame, source_path: str) -> list[str]:
    """Returns a list of problems; empty list means the file is valid."""
    problems = []
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        problems.append(f"Missing required column(s): {', '.join(missing)}")
    if len(df) == 0:
        problems.append("File contains zero data rows.")
    return problems


def reject_file(source_path: str, problems: list[str]) -> None:
    """
    Mimics LabWare's own CSV-import failure behavior: rename the bad file
    to .ERR and write a .LOG describing what failed, rather than silently
    dropping or partially processing it.
    """
    err_path = source_path + ".ERR"
    log_path = source_path + ".LOG"
    shutil.copy(source_path, err_path)
    with open(log_path, "w") as f:
        f.write(f"Import rejected at {datetime.now().isoformat()}\n")
        f.write(f"Source file: {source_path}\n\n")
        for p in problems:
            f.write(f"  - {p}\n")
    print(f"REJECTED: {source_path}")
    print(f"  Wrote {err_path} and {log_path}")
    for p in problems:
        print(f"  - {p}")


def build_weekly_summary(flagged: pd.DataFrame) -> dict:
    """Returns a dict of small DataFrames, one per Excel sheet."""
    total = len(flagged)
    oos_rate = 100 * flagged["Flag_OOS"].sum() / total if total else 0
    alert_rate = 100 * flagged["Flag_Alert"].sum() / total if total else 0
    oot_count = flagged["Flag_OOT"].sum()
    tat_breach_count = flagged["Flag_TAT_Breach"].sum()

    kpi = pd.DataFrame([
        {"Metric": "Total results", "Value": total},
        {"Metric": "OOS count", "Value": int(flagged["Flag_OOS"].sum())},
        {"Metric": "OOS rate (%)", "Value": round(oos_rate, 2)},
        {"Metric": "Alert-level count", "Value": int(flagged["Flag_Alert"].sum())},
        {"Metric": "Alert rate (%)", "Value": round(alert_rate, 2)},
        {"Metric": "OOT (out-of-trend) flags", "Value": int(oot_count)},
        {"Metric": "TAT breaches", "Value": int(tat_breach_count)},
    ])

    by_location = (
        flagged.groupby("Sample.Sampling_Point", dropna=False)[
            ["Flag_OOS", "Flag_Alert", "Flag_OOT", "Flag_TAT_Breach"]
        ]
        .sum()
        .reset_index()
        .rename(columns={"Sample.Sampling_Point": "Sampling Point"})
    )

    flagged_only = flagged[flagged["Flagged"]][
        [
            "Sample.Sample_Number", "Sample.Sampling_Point", "Sample.Product",
            "Test.Analysis", "Result.Numeric_Entry", "Result.Max_Limit",
            "Sample.Login_Date", "Flag_Reasons",
        ]
    ].sort_values("Sample.Login_Date", ascending=False)

    return {
        "KPI Summary": kpi,
        "Flags by Location": by_location,
        "Flagged Results": flagged_only,
    }


def main():
    parser = argparse.ArgumentParser(description="MicroQC Insight LIMS watchdog")
    parser.add_argument("--input", default="stored_query_export.csv",
                         help="Path to the LabWare-style Stored Query CSV export")
    parser.add_argument("--tat-sla", type=int, default=4,
                         help="Turnaround-time SLA in calendar days (default 4)")
    parser.add_argument("--out-csv", default="flagged_results.csv")
    parser.add_argument("--report-dir", default="reports")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"ERROR: input file not found: {args.input}")
        sys.exit(1)

    df = pd.read_csv(args.input)

    problems = validate_schema(df, args.input)
    if problems:
        reject_file(args.input, problems)
        sys.exit(1)

    print(f"Loaded {len(df)} rows from {args.input}")

    flagged = apply_all_rules(df, tat_sla_days=args.tat_sla)
    flagged.to_csv(args.out_csv, index=False)
    print(f"Wrote {args.out_csv} ({flagged['Flagged'].sum()} of {len(flagged)} rows flagged)")

    os.makedirs(args.report_dir, exist_ok=True)
    report_date = datetime.now().strftime("%Y-%m-%d")
    report_path = os.path.join(args.report_dir, f"weekly_summary_{report_date}.xlsx")

    sheets = build_weekly_summary(flagged)
    with pd.ExcelWriter(report_path, engine="openpyxl") as writer:
        for sheet_name, sheet_df in sheets.items():
            sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)
    print(f"Wrote weekly report -> {report_path}")

    # Demo mode: no real SMTP credentials are used. In a real deployment
    # this is where you'd call smtplib / an email API to send report_path
    # to a distribution list, matching the pattern LIMS shops commonly use
    # for scheduled Crystal Reports emails.
    print("\n[demo mode] Would email this report to the QA distribution list here.")

    print("\nSummary:")
    print(sheets["KPI Summary"].to_string(index=False))


if __name__ == "__main__":
    main()
