"""
build_report.py

Generates the MicroQC Insight Power BI report pages as PBIR (Power BI
Enhanced Report Format) JSON files, plus a small model tweak (a
'Login Month' calculated column), so the report is reproducible from code
instead of hand-dragged visuals.

Output layout mirrors the .pbip project on disk:
  out/MicroQC_Insight.Report/definition/pages/...
  out/MicroQC_Insight.SemanticModel/definition/tables/flagged_results.tmdl
"""

import json
import os
import shutil
import sys

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
VISUAL_SCHEMA = f"{SCHEMA}/visualContainer/2.13.0/schema.json"
PAGE_SCHEMA = f"{SCHEMA}/page/2.1.0/schema.json"
PAGES_SCHEMA = f"{SCHEMA}/pagesMetadata/1.1.0/schema.json"

OUT = "out"
REPORT_DIR = os.path.join(OUT, "MicroQC_Insight.Report", "definition", "pages")

# Reuse the existing page / visual names so the files PBI already has get
# overwritten instead of leaving orphans behind (the bridge can't delete).
FIRST_PAGE = "b76c36bea810fe1a6e89"
FIRST_VISUAL = "ff7c7e7dc6b3756d21d8"

W, H = 1920, 1080
M = 20  # margin / gutter


# ---------------------------------------------------------------- fields
def measure(name):
    return {
        "field": {"Measure": {"Expression": {"SourceRef": {"Entity": "_KPIs"}}, "Property": name}},
        "queryRef": f"_KPIs.{name}",
        "nativeQueryRef": name,
    }


def column(table, name, display=None):
    proj = {
        "field": {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}},
        "queryRef": f"{table}.{name}",
        "nativeQueryRef": name,
    }
    if display:
        proj["displayName"] = display
    return proj


def lit(value):
    return {"expr": {"Literal": {"Value": value}}}


def title_objects(text):
    return {
        "title": [{"properties": {"show": lit("true"), "text": lit(f"'{text}'")}}]
    }


# ---------------------------------------------------------------- visuals
_counter = [0]


def vid():
    _counter[0] += 1
    return f"v{_counter[0]:03d}microqc"


def visual(vtype, x, y, w, h, query, title=None, z=0, filters=None, objects=None):
    v = {
        "$schema": VISUAL_SCHEMA,
        "name": vid(),
        "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z},
        "visual": {
            "visualType": vtype,
            "query": {"queryState": query},
            "drillFilterOtherVisuals": True,
        },
    }
    if title:
        v["visual"]["visualContainerObjects"] = title_objects(title)
    if objects:
        v["visual"]["objects"] = objects
    if filters:
        v["filterConfig"] = {"filters": filters}
    return v


def card(x, y, w, h, m, title=None):
    return visual("card", x, y, w, h, {"Values": {"projections": [measure(m)]}}, title or m,
                  objects={"categoryLabels": [{"properties": {"show": lit("false")}}]})


def textbox(x, y, w, h, text, size="20pt"):
    v = {
        "$schema": VISUAL_SCHEMA,
        "name": vid(),
        "position": {"x": x, "y": y, "z": 0, "height": h, "width": w, "tabOrder": 0},
        "visual": {
            "visualType": "textbox",
            "objects": {
                "general": [
                    {
                        "properties": {
                            "paragraphs": [
                                {
                                    "textRuns": [
                                        {
                                            "value": text,
                                            "textStyle": {"fontWeight": "bold", "fontSize": size},
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ]
            },
        },
    }
    return v


def slicer(x, y, w, h, table, col, label):
    return visual("slicer", x, y, w, h,
                  {"Values": {"projections": [column(table, col, label)]}}, label,
                  objects={"data": [{"properties": {"mode": lit("'Dropdown'")}}]})


def flagged_only_filter():
    return {
        "name": "flaggedOnly",
        "field": {"Column": {"Expression": {"SourceRef": {"Entity": "flagged_results"}}, "Property": "Flagged"}},
        "type": "Categorical",
        "filter": {
            "Version": 2,
            "From": [{"Name": "f", "Entity": "flagged_results", "Type": 0}],
            "Where": [
                {
                    "Condition": {
                        "In": {
                            "Expressions": [
                                {"Column": {"Expression": {"SourceRef": {"Source": "f"}}, "Property": "Flagged"}}
                            ],
                            "Values": [[{"Literal": {"Value": "true"}}]],
                        }
                    }
                }
            ],
        },
    }


def card_row(y, h, measures):
    n = len(measures)
    w = (W - M * (n + 1)) // n
    out = []
    for i, m in enumerate(measures):
        m, t = m if isinstance(m, tuple) else (m, None)
        out.append(card(M + i * (w + M), y, w, h, m, t))
    return out


# ---------------------------------------------------------------- pages
TITLE_Y, TITLE_H = 10, 60
CARD_Y, CARD_H = 80, 130
ROW1_Y = CARD_Y + CARD_H + M          # 230
HALF_W = (W - 3 * M) // 2              # 930
ROW_H = (H - ROW1_Y - 2 * M) // 2      # ~405
ROW2_Y = ROW1_Y + ROW_H + M

LOC = ("flagged_results", "Sample.Location")
MONTH = ("flagged_results", "Login Month")

pages = []

# 1. Quality Overview ----------------------------------------------------
p1 = [
    textbox(M, TITLE_Y, 1400, TITLE_H, "MicroQC Insight — Quality Overview (synthetic data)"),
    slicer(W - 420 - M, TITLE_Y, 420, TITLE_H + 10, "flagged_results", "Sample.Sample_Type", "Sample type"),
    *card_row(CARD_Y, CARD_H, ["Total Results", "OOS Rate", "Alert Count", "OOT Count", "Right First Time %"]),
    visual("clusteredColumnChart", M, ROW1_Y, HALF_W, ROW_H,
           {"Category": {"projections": [column(*LOC, "Location")]},
            "Y": {"projections": [measure("OOS Count"), measure("Alert Count"), measure("OOT Count")]}},
           "Excursions by location (OOS / Alert / OOT)"),
    visual("lineChart", 2 * M + HALF_W, ROW1_Y, HALF_W, ROW_H,
           {"Category": {"projections": [column(*MONTH, "Month")]},
            "Y": {"projections": [measure("OOS Count"), measure("OOT Count")]}},
           "OOS and OOT flags by month"),
    visual("tableEx", M, ROW2_Y, W - 2 * M, ROW_H,
           {"Values": {"projections": [
               column("flagged_results", "Sample.Text_Id", "Sample"),
               column("flagged_results", "Sample.Login_Date", "Logged in"),
               column("flagged_results", "Sample.Location", "Location"),
               column("flagged_results", "Sample.Sampling_Point", "Sampling point"),
               column("flagged_results", "Test.Analysis", "Analysis"),
               column("flagged_results", "Result.Numeric_Entry", "Result"),
               column("flagged_results", "Result.Alert_Limit", "Alert limit"),
               column("flagged_results", "Result.Max_Limit", "Action limit"),
               column("flagged_results", "Flag_Reasons", "Flag reasons"),
           ]}},
           "Flagged results (rules engine output)",
           filters=[flagged_only_filter()]),
]
pages.append((FIRST_PAGE, "Quality Overview", p1))

# 2. Lab Ops ----------------------------------------------------------------
THIRD_W = (W - 4 * M) // 3
p2 = [
    textbox(M, TITLE_Y, 1400, TITLE_H, "Lab Ops — turnaround time & workload"),
    *card_row(CARD_Y, CARD_H, ["Avg TAT (days)", "Median TAT (days)", "On-Time %", "TAT Breach Count", "Samples Logged"]),
    visual("lineChart", M, ROW1_Y, W - 2 * M, ROW_H,
           {"Category": {"projections": [column(*MONTH, "Month")]},
            "Y": {"projections": [measure("TAT Breach Rate")]}},
           "TAT breach rate by month (SLA = 4 days)"),
    visual("clusteredColumnChart", M, ROW2_Y, THIRD_W, ROW_H,
           {"Category": {"projections": [column("flagged_results", "Result.Entered_By", "Analyst")]},
            "Y": {"projections": [measure("Total Results")]}},
           "Analyst workload (results entered)"),
    visual("clusteredBarChart", 2 * M + THIRD_W, ROW2_Y, THIRD_W, ROW_H,
           {"Category": {"projections": [column("flagged_results", "Test.Analysis", "Analysis")]},
            "Y": {"projections": [measure("Avg TAT (days)")]}},
           "Average TAT by analysis"),
    visual("clusteredBarChart", 3 * M + 2 * THIRD_W, ROW2_Y, THIRD_W, ROW_H,
           {"Category": {"projections": [column(*LOC, "Location")]},
            "Y": {"projections": [measure("TAT Breach Count")]}},
           "TAT breaches by location"),
]
pages.append(("p2labops00000000000", "Lab Ops", p2))

# 3. EM Trending --------------------------------------------------------------
p3 = [
    textbox(M, TITLE_Y, 1400, TITLE_H, "Environmental Monitoring — trending & out-of-trend"),
    slicer(W - 420 - M, TITLE_Y, 420, TITLE_H + 10, "flagged_results", "Test.Analysis", "Analysis"),
    *card_row(CARD_Y, CARD_H, ["OOT Count", "Alert Count", "OOS Count", "Avg % of Action Limit"]),
    visual("lineChart", M, ROW1_Y, W - 2 * M, ROW_H,
           {"Category": {"projections": [column(*MONTH, "Month")]},
            "Y": {"projections": [measure("Avg % of Action Limit")]},
            "Series": {"projections": [column(*LOC, "Location")]}},
           "Results as % of action limit, by month and location — note CR-102 drifting upward"),
    visual("columnChart", M, ROW2_Y, W - 2 * M, ROW_H,
           {"Category": {"projections": [column(*MONTH, "Month")]},
            "Y": {"projections": [measure("OOT Count")]},
            "Series": {"projections": [column(*LOC, "Location")]}},
           "Out-of-trend flags by month and location"),
]
pages.append(("p3trending000000000", "EM Trending", p3))

# 4. Lot Release & Investigations --------------------------------------------
p4 = [
    textbox(M, TITLE_Y, 1400, TITLE_H, "Lot Release, Investigations & Data Integrity"),
    *card_row(CARD_Y, CARD_H, [
        "Lots Released", ("Avg Mfg to Release (days)", "Mfg → release (days)"),
        ("Avg Last Sample to Release (days)", "Last sample → release (days)"),
        "Investigations", "CAPA Rate", ("Duplicate Result Rows", "Duplicate result rows"),
        ("Results Missing Reviewer", "Missing reviewer"),
    ]),
    visual("clusteredBarChart", M, ROW1_Y, THIRD_W, ROW_H,
           {"Category": {"projections": [column("LOT", "PRODUCT", "Product")]},
            "Y": {"projections": [measure("Avg Mfg to Release (days)")]}},
           "Avg manufacture-to-release days by product"),
    visual("tableEx", 2 * M + THIRD_W, ROW1_Y, W - 3 * M - THIRD_W, ROW_H,
           {"Values": {"projections": [
               column("LOT", "LOT_NUMBER", "Lot"),
               column("LOT", "PRODUCT", "Product"),
               column("LOT", "MFG_DATE", "Manufactured"),
               column("LOT", "DISPOSITION", "Disposition"),
               column("LOT", "RELEASED_ON", "Released"),
               measure("Avg Last Sample to Release (days)"),
           ]}},
           "Released lots"),
    visual("tableEx", M, ROW2_Y, W - 2 * M, ROW_H,
           {"Values": {"projections": [
               column("INVESTIGATION", "INV_ID", "Investigation"),
               column("INVESTIGATION", "RESULT_NUMBER", "Result #"),
               column("INVESTIGATION", "PHASE", "Phase"),
               column("INVESTIGATION", "OPENED", "Opened"),
               column("INVESTIGATION", "CLOSED", "Closed"),
               column("INVESTIGATION", "CAPA_ID", "CAPA"),
               column("INVESTIGATION", "ASSIGNABLE_CAUSE", "Assignable cause"),
           ]}},
           "OOS investigations (Phase I)"),
]
pages.append(("p4lotrelease0000000", "Lot Release & Investigations", p4))


# ---------------------------------------------------------------- write
def main():
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(REPORT_DIR)

    with open(os.path.join(REPORT_DIR, "pages.json"), "w") as f:
        json.dump({"$schema": PAGES_SCHEMA, "pageOrder": [p[0] for p in pages],
                   "activePageName": pages[0][0]}, f, indent=2)

    for page_name, display, visuals in pages:
        pdir = os.path.join(REPORT_DIR, page_name)
        os.makedirs(os.path.join(pdir, "visuals"))
        with open(os.path.join(pdir, "page.json"), "w") as f:
            json.dump({"$schema": PAGE_SCHEMA, "name": page_name, "displayName": display,
                       "displayOption": "FitToPage", "height": H, "width": W}, f, indent=2)
        for i, v in enumerate(visuals):
            if page_name == FIRST_PAGE and i == 0:
                v["name"] = FIRST_VISUAL  # overwrite the template visual
            # keep layering sane
            v["position"]["z"] = i * 1000
            v["position"]["tabOrder"] = i * 1000
            vdir = os.path.join(pdir, "visuals", v["name"])
            os.makedirs(vdir)
            with open(os.path.join(vdir, "visual.json"), "w") as f:
                json.dump(v, f, indent=2)

    # ---- model tweak: Login Month calculated column on flagged_results
    src = sys.argv[1]
    tmdl = open(src, encoding="utf-8").read()
    if "column 'Login Month'" not in tmdl:
        col = (
            "\tcolumn 'Login Month' = DATE(YEAR(flagged_results[Sample.Login_Date]), MONTH(flagged_results[Sample.Login_Date]), 1)\n"
            "\t\tdataType: dateTime\n"
            "\t\tformatString: mmm yyyy\n"
            "\t\tsummarizeBy: none\n\n"
            "\t\tannotation SummarizationSetBy = Automatic\n\n"
        )
        if "\r\n" in tmdl:
            col = col.replace("\n", "\r\n")
        tmdl = tmdl.replace("\tpartition flagged_results = m", col + "\tpartition flagged_results = m", 1)
    mdir = os.path.join(OUT, "MicroQC_Insight.SemanticModel", "definition", "tables")
    os.makedirs(mdir)
    with open(os.path.join(mdir, "flagged_results.tmdl"), "w", encoding="utf-8", newline="") as f:
        f.write(tmdl)

    # ---- model tweak: normalized trending measure on _KPIs
    kpis = open(sys.argv[2], encoding="utf-8").read()
    if "measure 'Avg % of Action Limit'" not in kpis:
        meas = (
            "\tmeasure 'Avg % of Action Limit' = AVERAGEX(FILTER(flagged_results, flagged_results[Result.Max_Limit] > 0), "
            "DIVIDE(flagged_results[Result.Numeric_Entry], flagged_results[Result.Max_Limit]))\n"
            "\t\tformatString: 0.0%\n"
            "\t\tdisplayFolder: Trending\n\n"
        )
        kpis = kpis.replace("\tcolumn Value", meas + "\tcolumn Value", 1)
    with open(os.path.join(mdir, "_KPIs.tmdl"), "w", encoding="utf-8", newline="") as f:
        f.write(kpis)

    n = sum(len(v) for _, _, v in pages)
    print(f"Wrote {len(pages)} pages, {n} visuals")


if __name__ == "__main__":
    main()
