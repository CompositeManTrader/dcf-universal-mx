"""Extrae los numeros FY2025 de la hoja 'Cuervo DCF' del WIP del analista."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import warnings
warnings.filterwarnings("ignore")

import pandas as pd

WIP = ROOT / "data" / "raw_xbrl" / "CUERVO_WIP.xlsx"
df = pd.read_excel(WIP, sheet_name="Cuervo DCF", header=None, engine="openpyxl")

print(f"shape: {df.shape}")

# Buscar la fila con headers de año y columna que dice 2025 o FY25
# r3 = años, r4 = quarters
year_row = 3
qtr_row = 4

print("\n=== Mapeo de columnas (cols 3..end) ===")
year_cols = {}  # year -> [cols]
fy_cols = {}    # year -> col (annual / FY)
for c in range(3, df.shape[1]):
    yr = str(df.iloc[year_row, c]).strip()
    qtr = str(df.iloc[qtr_row, c]).strip()
    if yr in ("nan", ""):
        continue
    year_cols.setdefault(yr, []).append((c, qtr))
    if qtr.lower().startswith("fy") or "annual" in qtr.lower() or qtr.lower() == yr or "year" in qtr.lower():
        fy_cols[yr] = c

# Imprimir 2024 y 2025 (todas las cols)
for yr in ("2023", "2024", "2025", "2026"):
    if yr in year_cols:
        cols = year_cols[yr]
        print(f"  {yr}: {cols}")
        if yr in fy_cols:
            print(f"     FY col -> {fy_cols[yr]}")

# Ahora buscar todas las filas que contengan keywords financieros
KEYWORDS = [
    "revenue", "sales", "ingresos", "ventas",
    "ebit", "operating income", "utilidad operac", "utilidad de operac",
    "ebitda",
    "net income", "utilidad neta", "net profit",
    "d&a", "depreciation", "depreciacion", "amortization",
    "capex", "capital expenditure",
    "total assets", "activos totales", "total activos",
    "cash", "efectivo",
    "debt", "deuda",
    "equity", "capital",
    "shares", "acciones",
    "tax",
    "fcf", "fcff", "free cash flow",
    "cogs", "cost of",
    "wacc", "discount",
    "target price", "precio objetivo",
]

print("\n=== Filas con keywords (col B = label) ===")
for i in range(df.shape[0]):
    lbl_b = str(df.iloc[i, 1]).strip().lower() if df.shape[1] > 1 else ""
    lbl_c = str(df.iloc[i, 2]).strip().lower() if df.shape[1] > 2 else ""
    label = lbl_b if lbl_b not in ("nan", "") else lbl_c
    if label in ("nan", ""):
        continue
    if any(k in label for k in KEYWORDS):
        # Mostrar valores en cols asociadas a 2024 y 2025
        vals_2024 = []
        vals_2025 = []
        for c, q in year_cols.get("2024", []):
            v = df.iloc[i, c]
            vals_2024.append(f"{q}={v}" if not pd.isna(v) else "")
        for c, q in year_cols.get("2025", []):
            v = df.iloc[i, c]
            vals_2025.append(f"{q}={v}" if not pd.isna(v) else "")
        # Solo imprime si hay valores
        if any(v for v in vals_2024) or any(v for v in vals_2025):
            label_orig = str(df.iloc[i, 1]).strip()
            if label_orig in ("nan", ""):
                label_orig = str(df.iloc[i, 2]).strip()
            print(f"\n  [{i:3d}] {label_orig[:60]}")
            print(f"        2024: {vals_2024}")
            print(f"        2025: {vals_2025}")
