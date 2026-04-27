"""Diagnostico: imprime las etiquetas reales (col 0) de cada hoja del XBRL."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

FP = ROOT / "data" / "raw_xbrl" / "ifrsxbrl_CUERVO_2025-4.xls"

xls = pd.ExcelFile(FP, engine="openpyxl")
TARGETS = ["110000", "210000", "310000", "520000", "700000", "700002", "700003"]

for name in TARGETS:
    if name not in xls.sheet_names:
        print(f"\n=== {name} (NO EXISTE) ===")
        continue
    df = pd.read_excel(xls, sheet_name=name, header=None)
    print(f"\n=== {name}  shape={df.shape} ===")
    # Imprimir header rows (filas 0-2) completas
    for r in range(min(3, df.shape[0])):
        row = [str(df.iloc[r, c])[:50] for c in range(min(6, df.shape[1]))]
        print(f"  HDR r{r}: {row}")
    # Imprimir todas las labels no vacias de col 0 con valor en col 1
    print(f"  --- LABELS (col0 -> col1) ---")
    for i in range(len(df)):
        lbl = df.iloc[i, 0]
        if pd.isna(lbl) or str(lbl).strip() == "":
            continue
        v1 = df.iloc[i, 1] if df.shape[1] > 1 else ""
        v2 = df.iloc[i, 2] if df.shape[1] > 2 else ""
        v3 = df.iloc[i, 3] if df.shape[1] > 3 else ""
        v4 = df.iloc[i, 4] if df.shape[1] > 4 else ""
        # Solo filas con al menos un valor numerico
        has_num = any(isinstance(v, (int, float)) and not pd.isna(v) for v in [v1, v2, v3, v4])
        marker = "*" if has_num else " "
        lbl_s = str(lbl).strip()[:80]
        print(f"  {marker} [{i:3d}] {lbl_s:<82} | {str(v1)[:18]:<18} | {str(v2)[:18]:<18}")
