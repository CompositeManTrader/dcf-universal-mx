"""Dump COMPLETO de hojas 800xxx del XBRL CUERVO Q4 2025."""
import sys, warnings
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
warnings.filterwarnings("ignore")
import pandas as pd

fp = ROOT / "data" / "raw_xbrl" / "ifrsxbrl_CUERVO_2025-4.xls"
xls = pd.ExcelFile(fp, engine="openpyxl")

TARGETS = ["800001", "800003", "800005", "800007", "800100", "800200",
            "800500", "800600", "813000"]

for sheet in TARGETS:
    if sheet not in xls.sheet_names:
        continue
    df = pd.read_excel(xls, sheet_name=sheet, header=None)
    print(f"\n{'='*100}\nHoja {sheet} (shape {df.shape})\n{'='*100}")
    # Mostrar todas las filas con valores numericos
    for i in range(df.shape[0]):
        lbl = df.iloc[i, 0]
        if pd.isna(lbl):
            continue
        # last numeric value
        last_val = ""
        cols_with_vals = []
        for c in range(1, df.shape[1]):
            v = df.iloc[i, c]
            if pd.notna(v):
                cols_with_vals.append((c, str(v)[:18]))
        if cols_with_vals:
            short_lbl = str(lbl).strip()[:75]
            cols_str = ", ".join(f"c{c}={v}" for c, v in cols_with_vals[:6])
            print(f"  [{i:3d}] {short_lbl:<75} | {cols_str}")
        else:
            short_lbl = str(lbl).strip()[:75]
            print(f"  [{i:3d}] {short_lbl}")
