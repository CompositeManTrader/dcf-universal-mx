"""Inspecciona TRIM Bloomberg de CUERVO con foco en hojas Adjusted/Standardized."""
import sys, warnings
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
warnings.filterwarnings("ignore")
import pandas as pd

fp = ROOT / "data" / "bloomberg" / "Edos_cuervo_trim.xlsx"
xls = pd.ExcelFile(fp, engine="openpyxl")

print(f"Hojas en {fp.name}:")
for n in xls.sheet_names:
    df = pd.read_excel(xls, sheet_name=n, header=None)
    print(f"  - {n!r:<45} shape={df.shape}")

TARGETS = ["Income - Adjusted", "Bal Sheet - Standardized", "Cash Flow - Standardized"]

for sheet in TARGETS:
    if sheet not in xls.sheet_names:
        print(f"\n!! NO existe la hoja '{sheet}'")
        continue
    df = pd.read_excel(xls, sheet_name=sheet, header=None)
    print(f"\n{'='*100}\n{sheet} (shape {df.shape})\n{'='*100}")

    # Identificar header row (busca 'Q' o 'FQ')
    header_row = None
    for r in range(min(8, df.shape[0])):
        row_vals = [str(df.iloc[r, c]) for c in range(min(15, df.shape[1]))]
        if any(("Q" in v and "20" in v) or "FQ" in v for v in row_vals):
            header_row = r
            break

    print(f"Header row: {header_row}")
    if header_row is not None:
        headers = [str(df.iloc[header_row, c])[:14] for c in range(min(20, df.shape[1]))]
        print(f"Headers: {headers}")

    # Mostrar todas las labels + ultimo valor disponible
    for i in range(df.shape[0]):
        lbl = df.iloc[i, 0]
        if pd.isna(lbl) or str(lbl).strip() == "":
            continue
        bbg = df.iloc[i, 1] if df.shape[1] > 1 else ""
        # last available value
        last_val = ""
        last_col = ""
        for c in range(df.shape[1]-1, 1, -1):
            v = df.iloc[i, c]
            if pd.notna(v) and not (isinstance(v, str) and v.strip() in ("—", "-", "")):
                last_val = str(v)[:14]
                last_col = str(df.iloc[header_row, c])[:10] if header_row else f"c{c}"
                break
        bbg_s = "" if pd.isna(bbg) else str(bbg)[:32]
        print(f"  [{i:3d}] {str(lbl).strip()[:55]:<55} | {bbg_s:<32} | {last_col}={last_val}")
