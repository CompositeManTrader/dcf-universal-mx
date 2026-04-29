"""Lista TODAS las hojas del XBRL CUERVO + busca items de notas."""
import sys, warnings
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
warnings.filterwarnings("ignore")
import pandas as pd

fp = ROOT / "data" / "raw_xbrl" / "ifrsxbrl_CUERVO_2025-4.xls"
xls = pd.ExcelFile(fp, engine="openpyxl")

print("Todas las hojas del XBRL:")
for n in xls.sheet_names:
    df = pd.read_excel(xls, sheet_name=n, header=None)
    print(f"  {n!r:<20} shape={df.shape}")

# Buscar palabras clave en TODAS las hojas
KEYWORDS = [
    "intereses cobrados", "intereses recibidos",
    "diferido", "corriente", "current tax", "deferred tax",
    "exportacion", "exportación", "export",
    "empleados", "obreros", "personal",
    "dividendos por accion", "dividendos por acción",
    "tipo de cambio", "moneda extranjera", "foreign exchange",
    "depreciacion", "amortizacion",
]

for sheet_name in xls.sheet_names:
    df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
    print(f"\n=== {sheet_name} ===")
    found_in_sheet = []
    for r in range(df.shape[0]):
        lbl = df.iloc[r, 0]
        if pd.isna(lbl):
            continue
        lbl_s = str(lbl).strip().lower()
        for kw in KEYWORDS:
            if kw in lbl_s:
                # Tomar primer valor numerico de la fila
                val = ""
                for c in range(1, min(8, df.shape[1])):
                    v = df.iloc[r, c]
                    if pd.notna(v):
                        val = str(v)[:18]
                        break
                found_in_sheet.append((r, str(lbl).strip()[:60], val))
                break
    for r, lbl, val in found_in_sheet[:25]:
        print(f"  [{r:3d}] {lbl:<60} | {val}")
