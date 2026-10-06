#!/usr/bin/env python3
"""
generate_mock_labware.py

Generates a synthetic, LabWare-LIMS-style relational dataset for a QC
microbiology lab (environmental monitoring, bioburden, endotoxin).

This is 100% synthetic data. Table/field names are modeled on publicly
documented LabWare LIMS structure (SAMPLE -> TEST -> RESULT hierarchy,
PRODUCT/PRODUCT_SPEC for limits) but do NOT represent any real LabWare
installation, and no real lab data (employer or otherwise) was used.

Output:
    - SQLite database:  mock_labware.db
    - "Stored Query" style CSV export (TABLE.FIELD headers), mimicking
      what you'd get exporting a LabWare Stored Query to CSV:
      stored_query_export.csv
    - Flat per-table CSVs in ./exports/ for easy Power BI import

Usage:
    pip install faker numpy pandas
    python generate_mock_labware.py --days 540 --seed 42

Author: Dennis Nguyen (portfolio project)
"""

import argparse
import csv
import os
import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker

# --------------------------------------------------------------------------
# Config / reference data
# --------------------------------------------------------------------------

# Grade A/B/C/D alert & action limits are standard EU GMP Annex 1 style
# public reference values used for illustration, expressed per plate/m3.
# (Real specs at a real site would live in PRODUCT_SPEC and vary by room.)
GRADE_LIMITS = {
    # grade: (alert_settle_cfu, action_settle_cfu, alert_air_cfu_m3, action_air_cfu_m3)
    "A": (1, 1, 1, 1),
    "B": (3, 5, 10, 20),
    "C": (25, 50, 100, 200),
    "D": (50, 100, 200, 400),
}

ROOMS = [
    # (room_id, grade, sampling_points)
    ("CR-101", "A", ["ISOLATOR_LEFT", "ISOLATOR_RIGHT", "FILL_NEEDLE"]),
    ("CR-102", "B", ["GOWNING_ROOM", "PASSTHROUGH", "CORRIDOR_B1"]),
    ("CR-103", "C", ["STAGING_AREA", "CORRIDOR_C1", "CORRIDOR_C2"]),
    ("CR-104", "D", ["WAREHOUSE_DOOR", "CORRIDOR_D1"]),
]

BIOBURDEN_PRODUCTS = ["VLV-2200", "VLV-2400", "CAT-1100"]
WATER_LOOPS = ["WFI-LOOP-1", "PURIFIED-LOOP-2"]

ANALYSES = {
    "VIABLE_AIR_USP": {"sample_type": "EM_AIR", "units": "CFU/m3"},
    "SETTLE_PLATE_TSA": {"sample_type": "EM_SURFACE", "units": "CFU/plate"},
    "GLOVE_FINGER_DAB": {"sample_type": "PERSONNEL", "units": "CFU/plate"},
    "BIOBURDEN_USP61": {"sample_type": "BIOBURDEN", "units": "CFU/device"},
    "LAL_KINETIC": {"sample_type": "ENDOTOXIN", "units": "EU/device"},
    "WATER_BIOBURDEN": {"sample_type": "WATER", "units": "CFU/mL"},
}

ANALYSTS = [
    ("jchen", "J. Chen"),
    ("mrodriguez", "M. Rodriguez"),
    ("dpatel", "D. Patel"),
    ("skwon", "S. Kwon"),
    ("anguyen", "A. Nguyen"),
    ("tolawale", "T. Olawale"),
]

INSTRUMENTS = [
    ("INCUBATOR-01", "Incubator", "2027-01-15"),
    ("INCUBATOR-02", "Incubator", "2026-11-02"),
    ("LAL-READER-01", "Kinetic LAL Reader", "2027-03-01"),
    ("AIR-SAMPLER-01", "Viable Air Sampler", "2026-12-10"),
    ("AIR-SAMPLER-02", "Viable Air Sampler", "2027-02-20"),
]

fake = Faker()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def business_days_between(start: datetime, end: datetime) -> float:
    """Rough TAT in business days (not calendar days)."""
    days = np.busday_count(start.date(), end.date())
    return max(days, 0)


def seasonal_multiplier(day_of_year: int) -> float:
    """Mild seasonal bump in bioburden — e.g. humidity-driven summer rise."""
    return 1.0 + 0.25 * np.sin(2 * np.pi * (day_of_year - 172) / 365)


def poisson_cfu(lam: float) -> int:
    return int(np.random.poisson(max(lam, 0.01)))


# --------------------------------------------------------------------------
# Generators
# --------------------------------------------------------------------------

@dataclass
class Counters:
    sample_number: int = 100000
    test_number: int = 500000
    result_number: int = 900000
    inv_id: int = 1


def generate_dataset(start_date: datetime, n_days: int, oot_room: str = "CR-102",
                      oot_start_frac: float = 0.75):
    """
    Build SAMPLE, TEST, RESULT, PRODUCT_SPEC, LOT, INSTRUMENTS,
    LIMS_USERS, AUDIT_TRAIL, INVESTIGATION as a dict of DataFrames.

    An out-of-trend (OOT) drift is injected into `oot_room` starting at
    `oot_start_frac` of the way through the date range, so the dashboard
    has something real to catch.
    """
    c = Counters()
    samples, tests, results = [], [], []
    audit_trail, investigations = [], []
    product_specs, lots = [], []

    # --- PRODUCT_SPEC (static reference table) --------------------------
    spec_id = 1
    for room_id, grade, _ in ROOMS:
        alert_settle, action_settle, alert_air, action_air = GRADE_LIMITS[grade]
        product_specs.append({
            "SPEC_ID": spec_id, "PRODUCT": None, "PRODUCT_GRADE": grade,
            "SAMPLING_POINT": room_id, "ANALYSIS": "SETTLE_PLATE_TSA",
            "SPEC_TYPE": "ALERT", "MIN_VALUE": 0, "MAX_VALUE": alert_settle,
        })
        spec_id += 1
        product_specs.append({
            "SPEC_ID": spec_id, "PRODUCT": None, "PRODUCT_GRADE": grade,
            "SAMPLING_POINT": room_id, "ANALYSIS": "SETTLE_PLATE_TSA",
            "SPEC_TYPE": "ACTION", "MIN_VALUE": 0, "MAX_VALUE": action_settle,
        })
        spec_id += 1
        product_specs.append({
            "SPEC_ID": spec_id, "PRODUCT": None, "PRODUCT_GRADE": grade,
            "SAMPLING_POINT": room_id, "ANALYSIS": "VIABLE_AIR_USP",
            "SPEC_TYPE": "ALERT", "MIN_VALUE": 0, "MAX_VALUE": alert_air,
        })
        spec_id += 1
        product_specs.append({
            "SPEC_ID": spec_id, "PRODUCT": None, "PRODUCT_GRADE": grade,
            "SAMPLING_POINT": room_id, "ANALYSIS": "VIABLE_AIR_USP",
            "SPEC_TYPE": "ACTION", "MIN_VALUE": 0, "MAX_VALUE": action_air,
        })
        spec_id += 1
    # Bioburden / endotoxin / water release specs
    for prod in BIOBURDEN_PRODUCTS:
        product_specs.append({
            "SPEC_ID": spec_id, "PRODUCT": prod, "PRODUCT_GRADE": None,
            "SAMPLING_POINT": None, "ANALYSIS": "BIOBURDEN_USP61",
            "SPEC_TYPE": "RELEASE", "MIN_VALUE": 0, "MAX_VALUE": 100,
        })
        spec_id += 1
        product_specs.append({
            "SPEC_ID": spec_id, "PRODUCT": prod, "PRODUCT_GRADE": None,
            "SAMPLING_POINT": None, "ANALYSIS": "LAL_KINETIC",
            "SPEC_TYPE": "RELEASE", "MIN_VALUE": 0, "MAX_VALUE": 20,
        })
        spec_id += 1
    for loop in WATER_LOOPS:
        product_specs.append({
            "SPEC_ID": spec_id, "PRODUCT": loop, "PRODUCT_GRADE": None,
            "SAMPLING_POINT": None, "ANALYSIS": "WATER_BIOBURDEN",
            "SPEC_TYPE": "ACTION", "MIN_VALUE": 0, "MAX_VALUE": 10,
        })
        spec_id += 1
    spec_df = pd.DataFrame(product_specs)

    # --- LOT table --------------------------------------------------------
    lot_id = 1
    for prod in BIOBURDEN_PRODUCTS:
        for _ in range(n_days // 20 + 1):
            mfg_date = start_date + timedelta(days=random.randint(0, n_days))
            lots.append({
                "LOT_NUMBER": f"L{lot_id:06d}", "PRODUCT": prod,
                "MFG_DATE": mfg_date.date().isoformat(),
                "DISPOSITION": None, "RELEASED_ON": None,
            })
            lot_id += 1
    lot_df = pd.DataFrame(lots)

    oot_start_day = int(n_days * oot_start_frac)

    # --- Daily sample generation -------------------------------------------
    for day_offset in range(n_days):
        current_date = start_date + timedelta(days=day_offset)
        doy = current_date.timetuple().tm_yday
        season = seasonal_multiplier(doy)
        is_oot_period = day_offset >= oot_start_day

        # ---- Environmental monitoring: one settle + one air sample/room/day
        for room_id, grade, points in ROOMS:
            alert_settle, action_settle, alert_air, action_air = GRADE_LIMITS[grade]
            point = random.choice(points)

            for analysis, base_units, cfu_scale in [
                ("SETTLE_PLATE_TSA", "CFU/plate", action_settle * 0.05),
                ("VIABLE_AIR_USP", "CFU/m3", action_air * 0.05),
            ]:
                lam = cfu_scale * season
                if is_oot_period and room_id == oot_room:
                    # linear drift up to ~1.8x action limit by end of window
                    progress = (day_offset - oot_start_day) / max(n_days - oot_start_day, 1)
                    lam = lam * (1 + 3.5 * progress)

                cfu = poisson_cfu(lam)
                sample_id = c.sample_number
                c.sample_number += 1
                login_dt = current_date + timedelta(hours=random.randint(6, 10))
                analyst_id, analyst_name = random.choice(ANALYSTS)
                due_dt = login_dt + timedelta(days=3)

                # TAT behavior: usually on time, occasionally late
                late = random.random() < 0.06
                complete_dt = login_dt + timedelta(
                    days=random.randint(2, 3) if not late else random.randint(5, 9),
                    hours=random.randint(0, 8),
                )
                review_dt = complete_dt + timedelta(hours=random.randint(2, 30))

                spec_row = spec_df[
                    (spec_df.SAMPLING_POINT == room_id)
                    & (spec_df.ANALYSIS == analysis)
                    & (spec_df.SPEC_TYPE == "ACTION")
                ].iloc[0]
                action_limit = spec_row.MAX_VALUE
                alert_limit = alert_settle if analysis == "SETTLE_PLATE_TSA" else alert_air
                in_spec = cfu < action_limit
                status = "A" if not late else "A"  # still authorized, just late

                samples.append({
                    "SAMPLE_NUMBER": sample_id,
                    "TEXT_ID": f"S{sample_id}",
                    "STATUS": status,
                    "OLD_STATUS": "U",
                    "LOGIN_DATE": login_dt.isoformat(),
                    "LOGIN_BY": analyst_id,
                    "CHANGED_ON": review_dt.isoformat(),
                    "SAMPLE_TYPE": "EM_AIR" if analysis == "VIABLE_AIR_USP" else "EM_SURFACE",
                    "DESCRIPTION": f"{room_id} {point} routine EM",
                    "LOCATION": room_id,
                    "PRODUCT": None,
                    "PRODUCT_GRADE": grade,
                    "SAMPLING_POINT": point,
                    "SPEC_TYPE": "ACTION",
                    "LOT": None,
                    "STANDARD": "F",
                    "ASSIGNED_OPERATOR": analyst_id,
                    "PRIORITY": "ROUTINE",
                    "DUE_DATE": due_dt.isoformat(),
                    "DATE_RECEIVED": login_dt.isoformat(),
                    "DATE_COMPLETED": complete_dt.isoformat(),
                    "DATE_REVIEWED": review_dt.isoformat(),
                    "REVIEWER": random.choice(ANALYSTS)[0],
                })

                test_id = c.test_number
                c.test_number += 1
                instrument = "AIR-SAMPLER-01" if analysis == "VIABLE_AIR_USP" else None
                tests.append({
                    "TEST_NUMBER": test_id,
                    "SAMPLE_NUMBER": sample_id,
                    "ANALYSIS": analysis,
                    "VERSION": 1,
                    "REPLICATE_COUNT": 1,
                    "STATUS": "A",
                    "INSTRUMENT": instrument,
                    "DATE_RECEIVED": login_dt.isoformat(),
                    "DATE_STARTED": login_dt.isoformat(),
                    "DATE_COMPLETED": complete_dt.isoformat(),
                    "ASSIGNED_OPERATOR": analyst_id,
                    "RETEST_OF": None,
                })

                result_id = c.result_number
                c.result_number += 1
                results.append({
                    "RESULT_NUMBER": result_id,
                    "TEST_NUMBER": test_id,
                    "NAME": analysis,
                    "REPLICATE_NUMBER": 0,
                    "ENTRY": str(cfu),
                    "FORMATTED_ENTRY": str(cfu),
                    "NUMERIC_ENTRY": cfu,
                    "UNITS": base_units,
                    "MIN_LIMIT": 0,
                    "MAX_LIMIT": action_limit,
                    "ALERT_LIMIT": alert_limit,
                    "IN_SPEC": "T" if in_spec else "F",
                    "STATUS": "A",
                    "ENTERED_BY": analyst_id,
                    "ENTERED_ON": complete_dt.isoformat(),
                    "REVIEWED_BY": random.choice(ANALYSTS)[0],
                    "REVIEWED_ON": review_dt.isoformat(),
                    "REPORTABLE": "T",
                })

                # audit trail: occasional post-review value correction
                if random.random() < 0.02:
                    audit_trail.append({
                        "TABLE_NAME": "RESULT", "RECORD_KEY": result_id,
                        "FIELD": "ENTRY", "OLD_VALUE": str(cfu - 1),
                        "NEW_VALUE": str(cfu), "CHANGED_BY": analyst_id,
                        "CHANGED_ON": (review_dt + timedelta(hours=2)).isoformat(),
                        "REASON": "Transcription correction after review",
                    })

                # OOS/OOT investigation if over action limit
                if not in_spec:
                    investigations.append({
                        "INV_ID": c.inv_id, "RESULT_NUMBER": result_id,
                        "PHASE": "I", "ASSIGNABLE_CAUSE": None,
                        "OPENED": complete_dt.isoformat(),
                        "CLOSED": (complete_dt + timedelta(days=random.randint(2, 7))).isoformat(),
                        "CAPA_ID": f"CAPA-{c.inv_id:04d}" if random.random() < 0.4 else None,
                    })
                    c.inv_id += 1

        # ---- Bioburden / endotoxin: a handful of device samples per week ---
        if day_offset % 7 == 0:
            for _ in range(random.randint(2, 5)):
                prod = random.choice(BIOBURDEN_PRODUCTS)
                # Only test lots that already exist (manufactured on/before
                # today, within the last 45 days) and haven't been released yet.
                today_iso = current_date.date().isoformat()
                window_iso = (current_date - timedelta(days=45)).date().isoformat()
                eligible = lot_df[
                    (lot_df.PRODUCT == prod)
                    & (lot_df.MFG_DATE <= today_iso)
                    & (lot_df.MFG_DATE >= window_iso)
                    & (lot_df.DISPOSITION.isna())
                ]
                if eligible.empty:
                    continue
                lot_row = eligible.sample(1).iloc[0]
                lot_last_complete = None
                for analysis in ["BIOBURDEN_USP61", "LAL_KINETIC"]:
                    sample_id = c.sample_number
                    c.sample_number += 1
                    login_dt = current_date + timedelta(hours=random.randint(6, 10))
                    analyst_id, _ = random.choice(ANALYSTS)
                    complete_dt = login_dt + timedelta(days=random.randint(2, 4))
                    review_dt = complete_dt + timedelta(hours=random.randint(2, 20))
                    lot_last_complete = max(filter(None, [lot_last_complete, review_dt]))
                    spec_row = spec_df[
                        (spec_df.PRODUCT == prod) & (spec_df.ANALYSIS == analysis)
                    ].iloc[0]
                    limit = spec_row.MAX_VALUE
                    if analysis == "BIOBURDEN_USP61":
                        val = poisson_cfu(limit * 0.04)
                        units = "CFU/device"
                    else:
                        val = round(np.random.gamma(2, limit * 0.03), 2)
                        units = "EU/device"
                    in_spec = val < limit

                    samples.append({
                        "SAMPLE_NUMBER": sample_id, "TEXT_ID": f"S{sample_id}",
                        "STATUS": "A", "OLD_STATUS": "U",
                        "LOGIN_DATE": login_dt.isoformat(), "LOGIN_BY": analyst_id,
                        "CHANGED_ON": review_dt.isoformat(),
                        "SAMPLE_TYPE": "BIOBURDEN" if analysis == "BIOBURDEN_USP61" else "ENDOTOXIN",
                        "DESCRIPTION": f"{prod} release testing",
                        "LOCATION": "MICRO-LAB",
                        "PRODUCT": prod, "PRODUCT_GRADE": None,
                        "SAMPLING_POINT": None, "SPEC_TYPE": "RELEASE",
                        "LOT": lot_row.LOT_NUMBER, "STANDARD": "F",
                        "ASSIGNED_OPERATOR": analyst_id, "PRIORITY": "ROUTINE",
                        "DUE_DATE": (login_dt + timedelta(days=5)).isoformat(),
                        "DATE_RECEIVED": login_dt.isoformat(),
                        "DATE_COMPLETED": complete_dt.isoformat(),
                        "DATE_REVIEWED": review_dt.isoformat(),
                        "REVIEWER": random.choice(ANALYSTS)[0],
                    })
                    test_id = c.test_number
                    c.test_number += 1
                    instrument = "LAL-READER-01" if analysis == "LAL_KINETIC" else None
                    tests.append({
                        "TEST_NUMBER": test_id, "SAMPLE_NUMBER": sample_id,
                        "ANALYSIS": analysis, "VERSION": 1, "REPLICATE_COUNT": 1,
                        "STATUS": "A", "INSTRUMENT": instrument,
                        "DATE_RECEIVED": login_dt.isoformat(),
                        "DATE_STARTED": login_dt.isoformat(),
                        "DATE_COMPLETED": complete_dt.isoformat(),
                        "ASSIGNED_OPERATOR": analyst_id, "RETEST_OF": None,
                    })
                    result_id = c.result_number
                    c.result_number += 1
                    results.append({
                        "RESULT_NUMBER": result_id, "TEST_NUMBER": test_id,
                        "NAME": analysis, "REPLICATE_NUMBER": 0,
                        "ENTRY": str(val), "FORMATTED_ENTRY": str(val),
                        "NUMERIC_ENTRY": val, "UNITS": units,
                        "MIN_LIMIT": 0, "MAX_LIMIT": limit, "ALERT_LIMIT": limit * 0.5,
                        "IN_SPEC": "T" if in_spec else "F", "STATUS": "A",
                        "ENTERED_BY": analyst_id, "ENTERED_ON": complete_dt.isoformat(),
                        "REVIEWED_BY": random.choice(ANALYSTS)[0],
                        "REVIEWED_ON": review_dt.isoformat(), "REPORTABLE": "T",
                    })

                    if not in_spec:
                        # Retest chain: simulate an FDA-style Phase I lab
                        # investigation that finds an assignable cause and
                        # invalidates the original, OR confirms it.
                        lab_error_found = random.random() < 0.5
                        investigations.append({
                            "INV_ID": c.inv_id, "RESULT_NUMBER": result_id,
                            "PHASE": "I", "ASSIGNABLE_CAUSE": "Sample handling error" if lab_error_found else None,
                            "OPENED": complete_dt.isoformat(),
                            "CLOSED": (complete_dt + timedelta(days=random.randint(3, 10))).isoformat(),
                            "CAPA_ID": f"CAPA-{c.inv_id:04d}",
                        })
                        c.inv_id += 1
                        if lab_error_found:
                            results[-1]["STATUS"] = "X"  # invalidated
                            for _ in range(random.randint(1, 2)):
                                rt_val = poisson_cfu(limit * 0.08) if analysis == "BIOBURDEN_USP61" \
                                    else round(np.random.gamma(2, limit * 0.06), 2)
                                rt_test_id = c.test_number
                                c.test_number += 1
                                tests.append({
                                    "TEST_NUMBER": rt_test_id, "SAMPLE_NUMBER": sample_id,
                                    "ANALYSIS": analysis, "VERSION": 1, "REPLICATE_COUNT": 1,
                                    "STATUS": "A", "INSTRUMENT": instrument,
                                    "DATE_RECEIVED": complete_dt.isoformat(),
                                    "DATE_STARTED": complete_dt.isoformat(),
                                    "DATE_COMPLETED": (complete_dt + timedelta(days=2)).isoformat(),
                                    "ASSIGNED_OPERATOR": analyst_id, "RETEST_OF": test_id,
                                })
                                rt_result_id = c.result_number
                                c.result_number += 1
                                results.append({
                                    "RESULT_NUMBER": rt_result_id, "TEST_NUMBER": rt_test_id,
                                    "NAME": analysis, "REPLICATE_NUMBER": 0,
                                    "ENTRY": str(rt_val), "FORMATTED_ENTRY": str(rt_val),
                                    "NUMERIC_ENTRY": rt_val, "UNITS": units,
                                    "MIN_LIMIT": 0, "MAX_LIMIT": limit, "ALERT_LIMIT": limit * 0.5,
                                    "IN_SPEC": "T", "STATUS": "A",
                                    "ENTERED_BY": analyst_id,
                                    "ENTERED_ON": (complete_dt + timedelta(days=2)).isoformat(),
                                    "REVIEWED_BY": random.choice(ANALYSTS)[0],
                                    "REVIEWED_ON": (complete_dt + timedelta(days=2, hours=6)).isoformat(),
                                    "REPORTABLE": "T",
                                })
                                lot_last_complete = max(
                                    lot_last_complete, complete_dt + timedelta(days=2, hours=6)
                                )

                # lot disposition once all tests for it look done (simplified)
                # A lot is dispositioned once; release always follows its last test.
                if random.random() < 0.3:
                    lot_df.loc[lot_df.LOT_NUMBER == lot_row.LOT_NUMBER, "DISPOSITION"] = "RELEASED"
                    lot_df.loc[lot_df.LOT_NUMBER == lot_row.LOT_NUMBER, "RELEASED_ON"] = \
                        (lot_last_complete + timedelta(days=random.randint(1, 3))).isoformat()

    sample_df = pd.DataFrame(samples)
    test_df = pd.DataFrame(tests)
    result_df = pd.DataFrame(results)
    audit_df = pd.DataFrame(audit_trail)
    inv_df = pd.DataFrame(investigations)
    instr_df = pd.DataFrame(INSTRUMENTS, columns=["NAME", "TYPE", "CALIB_DUE"])
    users_df = pd.DataFrame(ANALYSTS, columns=["USER_NAME", "FULL_NAME"])

    # --- inject a few deliberate data-quality defects for the QA-toolkit demo
    if len(result_df) > 20:
        dup_idx = result_df.sample(3, random_state=1).index
        result_df = pd.concat([result_df, result_df.loc[dup_idx]], ignore_index=True)
        null_idx = result_df.sample(5, random_state=2).index
        result_df.loc[null_idx, "REVIEWED_BY"] = None

    return {
        "SAMPLE": sample_df,
        "TEST": test_df,
        "RESULT": result_df,
        "PRODUCT_SPEC": spec_df,
        "LOT": lot_df,
        "INSTRUMENTS": instr_df,
        "LIMS_USERS": users_df,
        "AUDIT_TRAIL": audit_df,
        "INVESTIGATION": inv_df,
    }


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------

def export_sqlite(tables: dict, db_path: str):
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    for name, df in tables.items():
        df.to_sql(name, conn, index=False)
    conn.close()


def export_flat_csvs(tables: dict, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(os.path.join(out_dir, f"{name}.csv"), index=False)


def export_stored_query_csv(tables: dict, out_path: str):
    """
    Mimic a LabWare "Stored Query" export: a flat CSV whose header uses
    TABLE.FIELD naming, joining Sample -> Test -> Result the way a real
    LabWare export would (this is the format your rules-engine/watchdog
    script should be built to ingest).
    """
    sample_df = tables["SAMPLE"]
    test_df = tables["TEST"]
    result_df = tables["RESULT"]

    merged = result_df.merge(test_df, on="TEST_NUMBER", suffixes=("_res", "_test"))
    merged = merged.merge(sample_df, on="SAMPLE_NUMBER", suffixes=("", "_sample"))

    header_map = {
        "SAMPLE_NUMBER": "Sample.Sample_Number",
        "TEXT_ID": "Sample.Text_Id",
        "SAMPLE_TYPE": "Sample.Sample_Type",
        "LOCATION": "Sample.Location",
        "SAMPLING_POINT": "Sample.Sampling_Point",
        "PRODUCT": "Sample.Product",
        "LOT": "Sample.Lot",
        "LOGIN_DATE": "Sample.Login_Date",
        "DUE_DATE": "Sample.Due_Date",
        "DATE_COMPLETED": "Sample.Date_Completed",
        "DATE_REVIEWED": "Sample.Date_Reviewed",
        "TEST_NUMBER": "Test.Test_Number",
        "ANALYSIS": "Test.Analysis",
        "INSTRUMENT": "Test.Instrument",
        "NAME": "Result.Name",
        "ENTRY": "Result.Entry",
        "NUMERIC_ENTRY": "Result.Numeric_Entry",
        "UNITS": "Result.Units",
        "MIN_LIMIT": "Result.Min_Limit",
        "MAX_LIMIT": "Result.Max_Limit",
        "ALERT_LIMIT": "Result.Alert_Limit",
        "IN_SPEC": "Result.In_Spec",
        "STATUS": "Result.Status",
        "ENTERED_BY": "Result.Entered_By",
        "ENTERED_ON": "Result.Entered_On",
        "REVIEWED_BY": "Result.Reviewed_By",
        "REVIEWED_ON": "Result.Reviewed_On",
    }
    cols = [c for c in header_map if c in merged.columns]
    export_df = merged[cols].rename(columns=header_map)
    export_df.to_csv(out_path, index=False, quoting=csv.QUOTE_MINIMAL)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate mock LabWare-style LIMS data.")
    parser.add_argument("--days", type=int, default=540, help="Number of days of data (default 540 ~ 18 months)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--start-date", type=str, default=None,
                         help="YYYY-MM-DD; defaults to N days before today")
    parser.add_argument("--out-db", type=str, default="mock_labware.db")
    parser.add_argument("--out-dir", type=str, default="exports")
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    Faker.seed(args.seed)

    if args.start_date:
        start = datetime.fromisoformat(args.start_date)
    else:
        start = datetime.now() - timedelta(days=args.days)

    print(f"Generating {args.days} days of mock LIMS data starting {start.date()} (seed={args.seed})...")
    tables = generate_dataset(start, args.days)

    for name, df in tables.items():
        print(f"  {name}: {len(df)} rows")

    export_sqlite(tables, args.out_db)
    print(f"Wrote SQLite DB -> {args.out_db}")

    export_flat_csvs(tables, args.out_dir)
    print(f"Wrote flat per-table CSVs -> {args.out_dir}/")

    export_stored_query_csv(tables, "stored_query_export.csv")
    print("Wrote LabWare-style Stored Query export -> stored_query_export.csv")

    print("\nDone. Point Power BI at mock_labware.db (or the CSVs in exports/),")
    print("and point your rules-engine script at stored_query_export.csv.")


if __name__ == "__main__":
    main()
