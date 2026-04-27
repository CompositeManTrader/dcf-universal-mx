"""Busca los supuestos DCF del analista en el WIP para calibracion inversa."""
import sys, warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
warnings.filterwarnings("ignore")

import pandas as pd

WIP = ROOT / "data" / "raw_xbrl" / "CUERVO_WIP.xlsx"
df = pd.read_excel(WIP, sheet_name="Cuervo DCF", header=None, engine="openpyxl")
print(f"shape: {df.shape}")

# Buscar keywords de DCF/valuacion en TODA la hoja (cols B-D)
KEYWORDS = [
    "wacc", "discount rate", "cost of capital", "cost of equity",
    "cost of debt", "beta", "risk-free", "risk free", "risk premium", "erp",
    "country risk", "crp",
    "target price", "precio objetivo", "fair value", "intrinsic value",
    "terminal", "perpetuity", "exit multiple", "stable growth",
    "valuation", "ev/ebitda", "p/e", "p / e",
    "growth rate", "g rate",
    "free cash flow", "fcff", "fcf",
    "enterprise value", "equity value", "market cap",
    "share price", "precio accion",
    "ke ", "kd ", " ke", " kd",
    "tax rate", "marginal", "effective",
    "dcf summary", "valuacion summary",
    "% of e&p", "as a % of",
    "summary", "dcf",
]

print("\n=== Filas con keywords (cols A-D) ===")
hits = []
for i in range(df.shape[0]):
    for c in range(0, min(5, df.shape[1])):
        v = df.iloc[i, c]
        if pd.isna(v):
            continue
        s = str(v).strip().lower()
        if any(k in s for k in KEYWORDS) and len(s) < 80 and len(s) > 2:
            label = str(df.iloc[i, c]).strip()
            # Capturar primeros 6 valores siguientes
            row_vals = []
            for nc in range(c+1, min(c+8, df.shape[1])):
                vv = df.iloc[i, nc]
                if pd.notna(vv):
                    row_vals.append(f"col{nc}={str(vv)[:18]}")
            # Tambien buscar valores en cols 50-60 (rango FY 2025)
            fy_vals = []
            for nc in range(50, min(60, df.shape[1])):
                vv = df.iloc[i, nc]
                if pd.notna(vv):
                    fy_vals.append(f"c{nc}={str(vv)[:14]}")
            print(f"  [{i:3d}, c{c}] {label[:55]:<55}")
            if row_vals: print(f"          near: {row_vals[:5]}")
            if fy_vals:  print(f"          fy25: {fy_vals[:6]}")
            hits.append((i, c, label))
            break  # uno por fila ya basta
print(f"\nTotal hits: {len(hits)}")
