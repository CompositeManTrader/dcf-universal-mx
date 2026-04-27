"""Inspecciona el fcffsimpleginzu.xlsx de Damodaran."""
import sys, warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
warnings.filterwarnings("ignore")
import pandas as pd

FP = ROOT / "data" / "raw_xbrl" / "fcffsimpleginzu.xlsx"
xls = pd.ExcelFile(FP, engine="openpyxl")
print(f"Hojas ({len(xls.sheet_names)}):")
for n in xls.sheet_names:
    df = pd.read_excel(xls, sheet_name=n, header=None)
    print(f"  {n!r:<40}  shape={df.shape}")

print("\n\n=== Hoja 'Valuation' (preview filas 0-80, cols 0-12) ===")
df = pd.read_excel(xls, sheet_name="Valuation", header=None, engine="openpyxl") if "Valuation" in xls.sheet_names else None
if df is None:
    print("No 'Valuation' sheet; probando primera hoja")
    df = pd.read_excel(xls, sheet_name=xls.sheet_names[0], header=None, engine="openpyxl")

rows_to_show = min(120, df.shape[0])
cols_to_show = min(15, df.shape[1])
for r in range(rows_to_show):
    row = []
    for c in range(cols_to_show):
        v = df.iloc[r, c]
        s = "" if pd.isna(v) else str(v)[:14]
        row.append(s)
    if any(s for s in row):
        print(f"  r{r:3d}: {row}")
