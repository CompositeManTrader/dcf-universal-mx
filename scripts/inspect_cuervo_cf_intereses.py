"""Inspecciona rows con 'Intereses' en CF de CUERVO."""
import sys, warnings
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
warnings.filterwarnings("ignore")
import pandas as pd

fp = ROOT / "data" / "raw_xbrl" / "ifrsxbrl_CUERVO_2025-4.xls"
df = pd.read_excel(fp, sheet_name="520000", header=None, engine="openpyxl")
print("Rows con 'Intereses' en label:")
for r in range(df.shape[0]):
    lbl = df.iloc[r, 0]
    if pd.isna(lbl):
        continue
    s = str(lbl)
    if "Intereses" in s or "intereses" in s:
        v = df.iloc[r, 1] if df.shape[1] > 1 else None
        print(f"  [{r:3d}] {repr(s)[:90]:<90} | val={v}")
