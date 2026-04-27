"""
Parsea UN XBRL y genera:
  - Excel multi-hoja (Resumen, BS, IS, CF, Informativos, DCF Inputs)
  - Parquet (BS/IS/CF/DCF en data/parsed/)
  - Print del resumen y validaciones en consola

Uso desde Spyder:  ejecutar este archivo (F5).
Uso desde CLI:     python scripts/run_parse_one.py [path_al_xls]

Sin argumento usa el fixture CUERVO incluido en data/raw_xbrl/.
"""
from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

# Asegurar que src/ este en path cuando se ejecuta directamente
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pandas as pd

from dcf_mexico.parse import parse_xbrl


DEFAULT_XBRL = ROOT / "data" / "raw_xbrl" / "ifrsxbrl_CUERVO_2025-4.xls"


def _bs_to_df(bs) -> pd.DataFrame:
    d = asdict(bs)
    rows = [(k, v) for k, v in d.items()]
    df = pd.DataFrame(rows, columns=["Concepto", "Valor (pesos)"])
    df["Valor (MDP)"] = df["Valor (pesos)"] / 1_000_000
    return df


def _to_df(obj) -> pd.DataFrame:
    d = asdict(obj)
    rows = [(k, v) for k, v in d.items()]
    df = pd.DataFrame(rows, columns=["Concepto", "Valor (pesos)"])
    df["Valor (MDP)"] = pd.to_numeric(df["Valor (pesos)"], errors="coerce") / 1_000_000
    return df


def main(filepath: Path | None = None) -> int:
    fp = Path(filepath) if filepath else DEFAULT_XBRL
    print(f"\n>>> Parseando: {fp.name}")
    print("-" * 70)

    res = parse_xbrl(fp)

    print(f"Empresa:    {res.info.entity_name}")
    print(f"Ticker:     {res.info.ticker}")
    print(f"Periodo:    {res.info.period_end} (Q{res.info.quarter})")
    print(f"Moneda:     {res.info.currency}  |  Unidad: {res.info.rounding}")
    print(f"Tipo:       {res.info.issuer_type}  (financiera={res.info.is_financial})")
    print()
    print("RESUMEN (en MDP donde aplica):")
    print(res.summary().to_string(index=False))
    print()

    print("VALIDACION CONTABLE:")
    if not res.validation.issues:
        print("  [OK] Sin observaciones.")
    else:
        for it in res.validation.issues:
            print(f"  {it}")
    print()

    # Output Excel
    out_dir = ROOT / "data" / "parsed"
    out_dir.mkdir(parents=True, exist_ok=True)
    period_tag = res.info.period_end.replace("-", "") if res.info.period_end else "PERIOD"
    ticker = res.info.ticker or "EMISORA"
    out_xlsx = out_dir / f"{ticker}_{period_tag}.xlsx"

    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as w:
        res.summary().to_excel(w, sheet_name="Resumen", index=False)
        _to_df(res.balance).to_excel(w, sheet_name="Balance General", index=False)
        _to_df(res.income).to_excel(w, sheet_name="Estado Resultados", index=False)
        _to_df(res.cashflow).to_excel(w, sheet_name="Flujo Efectivo", index=False)
        _to_df(res.informative).to_excel(w, sheet_name="Informativos", index=False)
        res.dcf.to_series().to_frame("Valor").to_excel(w, sheet_name="DCF Inputs")

    print(f"Excel generado: {out_xlsx}")

    # Parquet (DCF inputs como fila unica)
    pq_path = out_dir / f"{ticker}_{period_tag}_dcf.parquet"
    pd.DataFrame([asdict(res.dcf)]).to_parquet(pq_path)
    print(f"Parquet DCF:    {pq_path}")

    return 0 if res.validation.ok else 1


if __name__ == "__main__":
    arg = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    sys.exit(main(arg))
