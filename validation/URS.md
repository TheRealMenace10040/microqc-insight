# User Requirements Specification (URS)

**System:** MicroQC Insight — LIMS Analytics & Automation Suite
**Scope:** A portfolio demonstration system that models a LabWare-LIMS-style
QC microbiology workflow (environmental monitoring, bioburden, endotoxin)
using 100% synthetic data, and automates OOS/Alert/OOT/TAT detection on top
of it.

**Document status:** Portfolio artifact. This is written in the format a
GxP validation package would use (URS → test evidence → traceability
matrix), but describes a personal project, not a system running in a
regulated environment. No real employer, patient or product
data is used anywhere in this project.

---

## 1. Purpose

Define what MicroQC Insight must do, so each requirement can be traced to
a specific automated test that proves it was built correctly.

## 2. Requirements

| ID | Requirement | Rationale |
|----|-------------|-----------|
| REQ-01 | The system shall reject an input file missing any required column, writing a `.ERR` copy of the file and a `.LOG` describing which columns were missing, and shall NOT produce a flagged-results output from a rejected file. | Mirrors LabWare's own CSV import behavior: a bad import fails loudly, not silently. |
| REQ-02 | The system shall reject an input file containing zero data rows, with the same `.ERR`/`.LOG` behavior as REQ-01. | Prevents a report from silently reflecting "zero issues" because nothing was actually loaded. |
| REQ-03 | The system shall accept a well-formed Stored-Query-style export and produce a flagged-results output with exactly one row per input row. | No rows should be silently dropped or duplicated during processing. |
| REQ-04 | The system shall flag any result whose numeric value is greater than or equal to `Result.Max_Limit` as **OOS** (out of specification). | Core QC rule: a value at or beyond the hard limit is non-conforming. |
| REQ-05 | The system shall flag any result whose numeric value is greater than or equal to `Result.Alert_Limit` AND less than `Result.Max_Limit` as **ALERT**, and this flag shall be mutually exclusive with OOS (an OOS result is never also labeled ALERT). | Alert levels exist to catch a trend before it becomes OOS; conflating the two would blur that signal. |
| REQ-06 | The system shall NOT flag OOS or ALERT for a result with a missing or non-numeric entry; such a result shall be treated as not evaluable, not as passing. | A null/garbled entry must not silently read as "in spec." |
| REQ-07 | The system shall flag a sample as a **TAT breach** when the elapsed time between `Sample.Login_Date` and `Sample.Date_Completed` exceeds the configured turnaround-time SLA (default 4 calendar days). | Lab turnaround time is a tracked KPI; late results need visibility. |
| REQ-08 | The system shall NOT flag a TAT breach for a sample with no completion date yet recorded (still in progress). | A sample mid-testing is not "late" — it's incomplete. The two states must not be conflated. |
| REQ-09 | The system shall flag a result as **OOT** (out of trend) when it exceeds its trailing baseline's mean plus 3 standard deviations, where the baseline is computed per (Sampling Point or Product, Analysis) group, using up to the prior 15 chronologically-ordered results, and only once at least 8 baseline points exist. | Statistical trend detection should catch drift before a hard limit is crossed, but must not fire on too little history. |
| REQ-10 | OOT evaluation shall be independent per sampling point / product and per analysis — a trend shift in one room or product shall never cause a flag in an unrelated room or product. | Cross-contamination of trend baselines between unrelated monitoring locations would produce false positives. |
| REQ-11 | The weekly automated report shall include, at minimum: total result count, OOS count and rate, Alert count and rate, OOT flag count, and TAT breach count. | These are the KPIs a QC lab manager reviews weekly. |
| REQ-12 | The weekly automated report shall break down flag counts by sampling point/location. | Supports root-cause triage — which room or product is driving excursions. |
| REQ-13 | The automation tool shall run end-to-end against the full synthetic dataset without manual intervention, producing both the flagged-results CSV (for the dashboard) and the weekly Excel report in a single invocation. | The tool must be usable as a scheduled/unattended job, not just a notebook exercise. |
| REQ-14 | All flagging logic shall be covered by automated unit tests, including boundary conditions (a value exactly at a limit; a sample with no completion date; insufficient OOT baseline history). | Boundary conditions are where flagging logic most commonly breaks; they must be explicitly tested, not just happy-path. |
| REQ-15 | No real employer data, real LabWare system access, or real patient/product data shall be used anywhere in this project; all data shall be synthetic and clearly labeled as such. | Ethical/legal boundary for a personal portfolio project. |

## 3. Out of scope

- Electronic signatures / Part 11 compliance (described conceptually in the
  README, not implemented).
- A production LabWare LIMS connection (no real system is targeted).
- Multi-user access control or row-level security (Power BI RLS is
  described as a stretch goal, not built in v1).
