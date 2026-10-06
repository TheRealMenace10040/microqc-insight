"""
test_rules_engine.py

Unit tests for rules_engine.py. These are the tests a validation package
would cite as evidence for a requirement like:

    REQ-05: The system shall flag any result >= Result.Max_Limit as OOS.
    REQ-06: The system shall flag any result >= Result.Alert_Limit and
            < Result.Max_Limit as an alert-level excursion, not OOS.
    REQ-07: The system shall flag samples whose completion date exceeds
            the turnaround-time SLA measured from login date.
    REQ-08: The system shall flag a result as out-of-trend when it
            exceeds its trailing baseline mean by more than 3 standard
            deviations, for at least 8 baseline points.

Run with:  pytest -v
"""

import pandas as pd
import pytest

from rules_engine import apply_all_rules, flag_alert, flag_oos, flag_oot, flag_tat

pytestmark = pytest.mark.filterwarnings("ignore")


def make_row(**overrides):
    """A minimal, valid row with sane defaults; overrides patch specific fields."""
    base = {
        "Sample.Sample_Number": 1,
        "Sample.Sampling_Point": "CR-101",
        "Sample.Product": None,
        "Sample.Login_Date": "2026-01-01T08:00:00",
        "Sample.Date_Completed": "2026-01-03T08:00:00",
        "Test.Analysis": "SETTLE_PLATE_TSA",
        "Result.Numeric_Entry": 0,
        "Result.Min_Limit": 0,
        "Result.Max_Limit": 1,
        "Result.Alert_Limit": 1,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------
# REQ-05: OOS boundary behavior
# ---------------------------------------------------------------------

def test_oos_flags_value_at_max_limit():
    """A result exactly AT the max limit is OOS (LabWare-style '>=' semantics)."""
    df = pd.DataFrame([make_row(**{"Result.Numeric_Entry": 1, "Result.Max_Limit": 1})])
    assert flag_oos(df).iloc[0] is True or flag_oos(df).iloc[0] == True  # noqa: E712


def test_oos_does_not_flag_value_just_below_max_limit():
    df = pd.DataFrame([make_row(**{"Result.Numeric_Entry": 0, "Result.Max_Limit": 1})])
    assert bool(flag_oos(df).iloc[0]) is False


def test_oos_flags_value_above_max_limit():
    df = pd.DataFrame([make_row(**{"Result.Numeric_Entry": 50, "Result.Max_Limit": 5})])
    assert bool(flag_oos(df).iloc[0]) is True


def test_oos_handles_missing_numeric_entry_gracefully():
    """A null/unparseable entry must not crash or be flagged as OOS."""
    df = pd.DataFrame([make_row(**{"Result.Numeric_Entry": None})])
    assert bool(flag_oos(df).iloc[0]) is False


# ---------------------------------------------------------------------
# REQ-06: Alert vs. OOS mutual exclusivity
# ---------------------------------------------------------------------

def test_alert_flags_value_between_alert_and_max():
    df = pd.DataFrame([make_row(**{
        "Result.Numeric_Entry": 3, "Result.Alert_Limit": 3, "Result.Max_Limit": 5,
    })])
    assert bool(flag_alert(df).iloc[0]) is True
    assert bool(flag_oos(df).iloc[0]) is False


def test_alert_does_not_fire_once_result_is_oos():
    """A result at/above Max_Limit should be OOS only, not also 'alert'."""
    df = pd.DataFrame([make_row(**{
        "Result.Numeric_Entry": 10, "Result.Alert_Limit": 3, "Result.Max_Limit": 5,
    })])
    assert bool(flag_oos(df).iloc[0]) is True
    assert bool(flag_alert(df).iloc[0]) is False


def test_alert_does_not_fire_below_alert_limit():
    df = pd.DataFrame([make_row(**{
        "Result.Numeric_Entry": 1, "Result.Alert_Limit": 3, "Result.Max_Limit": 5,
    })])
    assert bool(flag_alert(df).iloc[0]) is False


# ---------------------------------------------------------------------
# REQ-07: TAT breach
# ---------------------------------------------------------------------

def test_tat_breach_flagged_when_over_sla():
    df = pd.DataFrame([make_row(**{
        "Sample.Login_Date": "2026-01-01T08:00:00",
        "Sample.Date_Completed": "2026-01-10T08:00:00",  # 9 days later
    })])
    assert bool(flag_tat(df, sla_days=4).iloc[0]) is True


def test_tat_not_flagged_within_sla():
    df = pd.DataFrame([make_row(**{
        "Sample.Login_Date": "2026-01-01T08:00:00",
        "Sample.Date_Completed": "2026-01-02T08:00:00",  # 1 day later
    })])
    assert bool(flag_tat(df, sla_days=4).iloc[0]) is False


def test_tat_not_flagged_when_still_in_progress():
    """No completion date yet -- not a breach, it's just not done."""
    df = pd.DataFrame([make_row(**{"Sample.Date_Completed": None})])
    assert bool(flag_tat(df, sla_days=4).iloc[0]) is False


# ---------------------------------------------------------------------
# REQ-08: Out-of-trend detection
# ---------------------------------------------------------------------

def test_oot_flags_a_spike_after_a_stable_baseline():
    rows = []
    # 10 stable baseline points at ~0-1 CFU
    for day in range(10):
        rows.append(make_row(
            **{
                "Sample.Sample_Number": day,
                "Sample.Login_Date": f"2026-01-{day + 1:02d}T08:00:00",
                "Result.Numeric_Entry": 0 if day % 2 == 0 else 1,
            }
        ))
    # then an obvious spike, way outside baseline mean+3sigma
    rows.append(make_row(**{
        "Sample.Sample_Number": 99,
        "Sample.Login_Date": "2026-01-11T08:00:00",
        "Result.Numeric_Entry": 40,
    }))
    df = pd.DataFrame(rows)
    flags = flag_oot(df, window=15, sigma=3.0, min_baseline=8)
    assert bool(flags.iloc[-1]) is True
    # baseline points themselves should not retroactively be flagged
    assert flags.iloc[:10].sum() == 0


def test_oot_does_not_fire_with_insufficient_baseline():
    """Fewer than min_baseline points -> no OOT call yet, even if the value is high."""
    rows = [
        make_row(**{
            "Sample.Sample_Number": i,
            "Sample.Login_Date": f"2026-01-{i + 1:02d}T08:00:00",
            "Result.Numeric_Entry": 0,
        })
        for i in range(3)
    ]
    rows.append(make_row(**{
        "Sample.Sample_Number": 99,
        "Sample.Login_Date": "2026-01-05T08:00:00",
        "Result.Numeric_Entry": 40,
    }))
    df = pd.DataFrame(rows)
    flags = flag_oot(df, window=15, sigma=3.0, min_baseline=8)
    assert flags.sum() == 0


def test_oot_groups_are_independent_by_sampling_point():
    """A spike in one room's trend must not trigger a flag for another room."""
    rows = []
    for day in range(10):
        rows.append(make_row(**{
            "Sample.Sample_Number": day,
            "Sample.Sampling_Point": "CR-101",
            "Sample.Login_Date": f"2026-01-{day + 1:02d}T08:00:00",
            "Result.Numeric_Entry": 0,
        }))
    rows.append(make_row(**{
        "Sample.Sample_Number": 100,
        "Sample.Sampling_Point": "CR-101",
        "Sample.Login_Date": "2026-01-11T08:00:00",
        "Result.Numeric_Entry": 40,
    }))
    # unrelated room, single low-value point -- should never be flagged
    rows.append(make_row(**{
        "Sample.Sample_Number": 200,
        "Sample.Sampling_Point": "CR-999",
        "Sample.Login_Date": "2026-01-11T08:00:00",
        "Result.Numeric_Entry": 1,
    }))
    df = pd.DataFrame(rows)
    flags = flag_oot(df, window=15, sigma=3.0, min_baseline=8)
    cr999_idx = df.index[df["Sample.Sampling_Point"] == "CR-999"]
    assert flags.loc[cr999_idx].sum() == 0


# ---------------------------------------------------------------------
# Integration: apply_all_rules end to end
# ---------------------------------------------------------------------

def test_apply_all_rules_adds_expected_columns():
    df = pd.DataFrame([make_row()])
    out = apply_all_rules(df)
    for col in ["Flag_OOS", "Flag_Alert", "Flag_OOT", "Flag_TAT_Breach", "Flagged", "Flag_Reasons"]:
        assert col in out.columns


def test_apply_all_rules_reason_string_matches_flags():
    df = pd.DataFrame([make_row(**{
        "Result.Numeric_Entry": 10, "Result.Alert_Limit": 3, "Result.Max_Limit": 5,
        "Sample.Login_Date": "2026-01-01T08:00:00",
        "Sample.Date_Completed": "2026-01-10T08:00:00",
    })])
    out = apply_all_rules(df, tat_sla_days=4)
    row = out.iloc[0]
    assert row["Flag_OOS"] == True  # noqa: E712
    assert row["Flag_TAT_Breach"] == True  # noqa: E712
    assert "OOS" in row["Flag_Reasons"]
    assert "TAT_BREACH" in row["Flag_Reasons"]
    assert "ALERT" not in row["Flag_Reasons"]  # OOS suppresses ALERT
