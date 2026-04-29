"""Inspecciona el Bloomberg Excel de CUERVO (anuales + trimestral)."""
import sys, warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
warnings.filterwarnings("ignore")
import pandas as pd

FILES = [
    ROOT / "data" / "bloomberg" / "Edos_cuervo_anuales.xlsx",
    ROOT / "data" / "bloomberg" / "Edos_cuervo_trim.xlsx",
]

for fp in FILES:
    if not fp.exists():
        print(f"!! NO EXISTE: {fp}")
        continue
    print(f"\n{'='*80}\n{fp.name}\n{'='*80}")
    xls = pd.ExcelFile(fp, engine="openpyxl")
    print(f"Hojas ({len(xls.sheet_names)}):")
    for n in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=n, header=None)
        print(f"  - {n!r:<45} shape={df.shape}")

    # Para cada hoja, mostrar las primeras 15 filas y 8 cols
    for n in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=n, header=None)
        print(f"\n--- HOJA: {n} (shape {df.shape}) ---")
        rows_to_show = min(15, df.shape[0])
        cols_to_show = min(10, df.shape[1])
        for r in range(rows_to_show):
            row = []
            for c in range(cols_to_show):
                v = df.iloc[r, c]
                s = "" if pd.isna(v) else str(v)[:18]
                row.append(s)
            print(f"  r{r:2d}: {row}")
