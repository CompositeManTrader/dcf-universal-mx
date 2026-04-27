"""Inspecciona el modelo del analista (CUERVO - WIP.xlsx) para mapear sus hojas."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

WIP = ROOT / "data" / "raw_xbrl" / "CUERVO_WIP.xlsx"

xls = pd.ExcelFile(WIP, engine="openpyxl")
print(f"\n=== ARCHIVO: {WIP.name} ===")
print(f"Hojas ({len(xls.sheet_names)}):")
for n in xls.sheet_names:
    df = pd.read_excel(xls, sheet_name=n, header=None)
    print(f"  - {n!r:<35}  shape={df.shape}")

print("\n\n=== PREVIEW POR HOJA ===")
for n in xls.sheet_names:
    df = pd.read_excel(xls, sheet_name=n, header=None)
    print(f"\n----- HOJA: {n} (shape {df.shape}) -----")
    # Print first 5 rows x 8 cols
    rows_to_show = min(8, df.shape[0])
    cols_to_show = min(10, df.shape[1])
    for r in range(rows_to_show):
        row = []
        for c in range(cols_to_show):
            v = df.iloc[r, c]
            s = "" if pd.isna(v) else str(v)[:18]
            row.append(s)
        print(f"  r{r:2d}: {row}")
