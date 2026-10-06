"""
rules_engine.py

The core flagging logic for MicroQC Insight, kept separate from the CLI
(lims_watchdog.py) so it can be unit-tested directly with pytest without
touching the filesystem.

Four checks, each returning a boolean Series aligned to the input frame:
    - flag_oos(df)   : result >= max limit (hard out-of-specification)
    - flag_alert(df) : result >= alert limit but < max limit (early warning)
    - flag_oot(df)   : statistical out-of-trend vs. a trailing baseline,
                       per (Sampling_Point, Analysis) group
    - flag_tat(df)   : turnaround-time breach (Date_Completed - Login_Date
                       exceeds the SLA for that sample type)

All four are deliberately simple, explainable rules -- the kind an auditor
or interviewer can read in five minutes -- rather than a black-box model.
That's the point for a GxP-adjacent portfolio piece: the logic must be
inspectable.
"""

from __future__ import annotations

import pandas as pd

# Business rule: routine EM/bioburden/endotoxin samples are expected to
# complete within this many calendar days of login. In a real lab this
# would come from a per-sample-type SLA table; kept simple here.
DEFAULT_TAT_SLA_DAYS = 4

# OOT detection: how many trailing points make up the "baseline" window,
# and how many standard deviations above that baseline mean counts as an
# out-of-trend signal. This is a 3-sigma / Western-Electric-style rule,
# not a formal statistical process control validation.
OOT_BASELINE_WINDOW = 15
OOT_SIGMA_THRESHOLD = 3.0
OOT_MIN_BASELINE_POINTS = 8


def flag_oos(df: pd.DataFrame) -> pd.Series:
    """Hard out-of-specification: numeric result at or above Max_Limit."""
    numeric = pd.to_numeric(df["Result.Numeric_Entry"], errors="coerce")
    max_limit = pd.to_numeric(df["Result.Max_Limit"], errors="coerce")
    return (numeric >= max_limit) & numeric.notna() & max_limit.notna()


def flag_alert(df: pd.DataFrame) -> pd.Series:
    """Alert-level excursion: at/above Alert_Limit but still under Max_Limit."""
    numeric = pd.to_numeric(df["Result.Numeric_Entry"], errors="coerce")
    alert_limit = pd.to_numeric(df["Result.Alert_Limit"], errors="coerce")
    max_limit = pd.to_numeric(df["Result.Max_Limit"], errors="coerce")
    is_oos = flag_oos(df)
    return (numeric >= alert_limit) & numeric.notna() & alert_limit.notna() & ~is_oos


def flag_tat(df: pd.DataFrame, sla_days: int = DEFAULT_TAT_SLA_DAYS) -> pd.Series:
    """
    Turnaround-time breach: Date_Completed - Login_Date > sla_days.
    Rows with a missing completion date are treated as still in progress
    and are NOT flagged (there's nothing to measure yet).
    """
    login = pd.to_datetime(df["Sample.Login_Date"], errors="coerce")
    completed = pd.to_datetime(df["Sample.Date_Completed"], errors="coerce")
    tat_days = (completed - login).dt.total_seconds() / 86400.0
    return (tat_days > sla_days) & completed.notna() & login.notna()


def flag_oot(
    df: pd.DataFrame,
    window: int = OOT_BASELINE_WINDOW,
    sigma: float = OOT_SIGMA_THRESHOLD,
    min_baseline: int = OOT_MIN_BASELINE_POINTS,
) -> pd.Series:
    """
    Out-of-trend: for each (Sampling_Point, Analysis) group, sort
    chronologically and flag a point whose value exceeds the trailing
    baseline's mean + sigma*std. The point being tested is excluded from
    its own baseline. Groups with no sampling point (bioburden/endotoxin,
    which key off Product instead) are grouped by Product instead.

    Returns a boolean Series aligned to df.index (not the sorted order).
    """
    out = pd.Series(False, index=df.index)
    numeric = pd.to_numeric(df["Result.Numeric_Entry"], errors="coerce")
    login = pd.to_datetime(df["Sample.Login_Date"], errors="coerce")

    group_key = df["Sample.Sampling_Point"].fillna(df["Sample.Product"])
    work = pd.DataFrame({
        "value": numeric,
        "login": login,
        "group": group_key,
        "analysis": df["Test.Analysis"],
    })

    for _, grp in work.groupby(["group", "analysis"]):
        grp_sorted = grp.sort_values("login")
        values = grp_sorted["value"].to_numpy()
        idx = grp_sorted.index.to_numpy()

        for i in range(len(values)):
            lo = max(0, i - window)
            baseline = values[lo:i]
            baseline = baseline[~pd.isna(baseline)]
            if len(baseline) < min_baseline or pd.isna(values[i]):
                continue
            mean = baseline.mean()
            std = baseline.std(ddof=0)
            if std == 0:
                continue
            if values[i] > mean + sigma * std:
                out.loc[idx[i]] = True

    return out


def apply_all_rules(df: pd.DataFrame, tat_sla_days: int = DEFAULT_TAT_SLA_DAYS) -> pd.DataFrame:
    """
    Runs all four checks and returns a copy of df with boolean flag
    columns added, plus a combined `Flagged` column and a human-readable
    `Flag_Reasons` column (comma-separated).
    """
    result = df.copy()
    result["Flag_OOS"] = flag_oos(df)
    result["Flag_Alert"] = flag_alert(df)
    result["Flag_OOT"] = flag_oot(df)
    result["Flag_TAT_Breach"] = flag_tat(df, sla_days=tat_sla_days)

    flag_cols = ["Flag_OOS", "Flag_Alert", "Flag_OOT", "Flag_TAT_Breach"]
    result["Flagged"] = result[flag_cols].any(axis=1)

    def reasons(row):
        labels = {
            "Flag_OOS": "OOS",
            "Flag_Alert": "ALERT",
            "Flag_OOT": "OOT",
            "Flag_TAT_Breach": "TAT_BREACH",
        }
        return ", ".join(labels[c] for c in flag_cols if row[c])

    result["Flag_Reasons"] = result.apply(reasons, axis=1)
    return result
