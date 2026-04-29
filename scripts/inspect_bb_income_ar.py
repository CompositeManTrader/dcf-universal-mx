"""Dump completo de Income - As Reported para mapear labels."""
import sys, warnings
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
warnings.filterwarnings("ignore")
import pandas as pd

fp = ROOT / "data" / "bloomberg" / "Edos_cuervo_anuales.xlsx"
xls = pd.ExcelFile(fp, engine="openpyxl")

for sheet in ["Income - As Reported", "Bal Sheet - As Reported", "Cash Flow - As Reported"]:
    df = pd.read_excel(xls, sheet_name=sheet, header=None)
    print(f"\n{'='*100}\n{sheet} (shape {df.shape})\n{'='*100}")
    # Find header row (the one with year labels)
    header_row = None
    for r in range(min(8, df.shape[0])):
        row_vals = [str(df.iloc[r, c]) for c in range(min(15, df.shape[1]))]
        if any("FY" in v for v in row_vals):
            header_row = r
            break
    print(f"Header row: {header_row}")
    if header_row is not None:
        print(f"Headers: {[str(df.iloc[header_row, c])[:18] for c in range(min(15, df.shape[1]))]}")
    # Print all rows with col 0 + col 1 (label + bbg ticker) + first FY value
    for i in range(df.shape[0]):
        lbl = df.iloc[i, 0]
        if pd.isna(lbl) or str(lbl).strip() == "":
            continue
        bbg = df.iloc[i, 1] if df.shape[1] > 1 else ""
        # last available year (rightmost non-na)
        last_val = ""
        for c in range(df.shape[1]-1, 1, -1):
            v = df.iloc[i, c]
            if pd.notna(v):
                last_val = str(v)[:14]
                break
        bbg_s = "" if pd.isna(bbg) else str(bbg)[:30]
        print(f"  [{i:3d}] {str(lbl).strip()[:55]:<55} | {bbg_s:<30} | last={last_val}")
