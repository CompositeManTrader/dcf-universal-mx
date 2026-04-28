"""Inspecciona la estructura Bloomberg de CUERVO (anual y trimestral)."""
import sys, warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
warnings.filterwarnings("ignore")
import pandas as pd

for fname in ["CUERVO_anual_bloomberg.xlsx", "CUERVO_trim_bloomberg.xlsx"]:
    fp = ROOT / "data" / "bloomberg_templates" / fname
    print(f"\n{'='*80}\n=== ARCHIVO: {fname} ===\n{'='*80}")
    xls = pd.ExcelFile(fp, engine="openpyxl")
    print(f"Hojas ({len(xls.sheet_names)}): {xls.sheet_names}")

    for n in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=n, header=None)
        print(f"\n----- HOJA: {n!r}  shape={df.shape} -----")
        rows_to_show = min(80, df.shape[0])
        cols_to_show = min(15, df.shape[1])
        for r in range(rows_to_show):
            row = []
            for c in range(cols_to_show):
                v = df.iloc[r, c]
                s = "" if pd.isna(v) else str(v)[:18]
                row.append(s)
            if any(s.strip() for s in row):
                print(f"  r{r:3d}: {row}")
