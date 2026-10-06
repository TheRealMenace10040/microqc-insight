# Traceability Matrix

Maps each URS requirement to the test(s) that verify it, and the actual
result from the last test run. This is the document an auditor (or an
interviewer) would ask for first.

**Last verified:** 2026-10-06 (after regenerating data with the lot-release
fix), `pytest tests/ -v` → **19 passed, 0 failed**
(see `pytest_run_log.txt` in this folder for the full console output).

| Req ID | Test(s) | Result | Status |
|--------|---------|--------|--------|
| REQ-01 | `test_validate_schema_flags_missing_columns`, `test_reject_file_writes_err_and_log` | PASSED | ✅ Verified |
| REQ-02 | `test_validate_schema_flags_empty_file` | PASSED | ✅ Verified |
| REQ-03 | *(no automated test yet)* | Verified manually: ran `lims_watchdog.py` against the full 4,709-row export; `flagged_results.csv` also had 4,709 rows. | ⚠️ Gap — needs `test_flagged_output_row_count_matches_input` |
| REQ-04 | `test_oos_flags_value_at_max_limit`, `test_oos_does_not_flag_value_just_below_max_limit`, `test_oos_flags_value_above_max_limit` | PASSED | ✅ Verified |
| REQ-05 | `test_alert_flags_value_between_alert_and_max`, `test_alert_does_not_fire_once_result_is_oos`, `test_alert_does_not_fire_below_alert_limit` | PASSED | ✅ Verified |
| REQ-06 | `test_oos_handles_missing_numeric_entry_gracefully` | PASSED | ✅ Verified |
| REQ-07 | `test_tat_breach_flagged_when_over_sla`, `test_tat_not_flagged_within_sla` | PASSED | ✅ Verified |
| REQ-08 | `test_tat_not_flagged_when_still_in_progress` | PASSED | ✅ Verified |
| REQ-09 | `test_oot_flags_a_spike_after_a_stable_baseline`, `test_oot_does_not_fire_with_insufficient_baseline` | PASSED | ✅ Verified |
| REQ-10 | `test_oot_groups_are_independent_by_sampling_point` | PASSED | ✅ Verified |
| REQ-11 | *(no automated test yet)* | Verified manually: ran the full pipeline, confirmed the "KPI Summary" sheet contained all 7 required metrics. | ⚠️ Gap — needs `test_build_weekly_summary_has_required_kpis` |
| REQ-12 | *(no automated test yet)* | Verified manually: confirmed the "Flags by Location" sheet exists and sums correctly against `flagged_results.csv`. | ⚠️ Gap — needs `test_weekly_summary_location_breakdown` |
| REQ-13 | *(end-to-end, not a pytest case)* | Ran `python lims_watchdog.py --input stored_query_export.csv` against the full dataset: completed without error, produced both `flagged_results.csv` and `reports/weekly_summary_<date>.xlsx` in one invocation. | ✅ Verified manually |
| REQ-14 | Full suite: `tests/test_rules_engine.py` + `tests/test_lims_watchdog.py` | 19/19 PASSED | ✅ Verified |
| REQ-15 | Code review of `generate_mock_labware.py` — all values are drawn from Faker/NumPy/random distributions; no file I/O to any external or proprietary data source. | N/A — design verification | ✅ Verified |

## Open items (honest gap list)

Three requirements (REQ-03, REQ-11, REQ-12) are currently verified only by
manual inspection, not by an automated test. For a real GxP validation
package this would **not** be acceptable — manual verification isn't
repeatable and doesn't run in CI. Next additions to `tests/`:

```python
def test_flagged_output_row_count_matches_input():
    """REQ-03: apply_all_rules must not drop or duplicate rows."""
    ...

def test_build_weekly_summary_has_required_kpis():
    """REQ-11: the KPI Summary sheet must contain all required metrics."""
    ...

def test_weekly_summary_location_breakdown_sums_correctly():
    """REQ-12: per-location flag counts must sum to the overall flag counts."""
    ...
```

Flagging this gap explicitly, rather than quietly calling everything
"done," is itself part of what this document is meant to demonstrate.
