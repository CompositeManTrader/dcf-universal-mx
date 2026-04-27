"""
Verifica los XBRL en data/raw_xbrl/ contra el contenido REAL del archivo
(no contra el filename) y propone renombrar los que tengan nombre incorrecto.

Estrategia:
  1. Lista todos los .xls/.xlsx que empiezan con 'ifrsxbrl_'
  2. Para cada uno parsea 110000 -> ticker + period_end + quarter
  3. Calcula filename canonico: ifrsxbrl_<TICKER>_<YYYY>-<Q>.<ext>
  4. Si el filename no coincide -> propone rename
  5. Tambien marca:
     - Tickers no presentes en config/issuers.yaml
     - Tickers duplicados (mismo ticker en multiples archivos)
  6. Con --apply ejecuta los renames; sin --apply solo dry-run.
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")

import re
import pandas as pd
from dcf_mexico.parse import parse_xbrl
from dcf_mexico.config import load_issuers


RAW_DIR = ROOT / "data" / "raw_xbrl"


def _sanitize_ticker(t: str) -> str:
    """Normaliza tickers de XBRL para matchear keys de config:
       reemplaza '&' y espacios por '_', mayusculas, sin caracteres especiales."""
    t = t.strip().upper()
    t = re.sub(r"[&\s]+", "_", t)
    t = re.sub(r"[^A-Z0-9_]", "", t)
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                     help="Ejecutar los renames (default: dry-run)")
    args = ap.parse_args()

    _, issuers_cfg = load_issuers()
    config_tickers = set(issuers_cfg.keys())

    files = sorted(RAW_DIR.glob("ifrsxbrl_*.xls*"))
    print(f"\n>>> Verificando {len(files)} archivos XBRL en {RAW_DIR}\n")

    rows = []
    for fp in files:
        try:
            res = parse_xbrl(fp)
            raw_ticker = res.info.ticker
            ticker = _sanitize_ticker(raw_ticker)        # PE&OLES -> PE_OLES
            period_end = res.info.period_end
            quarter = res.info.quarter
            year = period_end[:4] if period_end else ""
            canonical = f"ifrsxbrl_{ticker}_{year}-{quarter}{fp.suffix}"
            rename_needed = (fp.name != canonical)
            in_config = ticker in config_tickers
            rows.append({
                "current_file": fp.name,
                "real_ticker":  ticker,
                "period_end":   period_end,
                "quarter":      quarter,
                "canonical":    canonical,
                "rename":       rename_needed,
                "in_config":    in_config,
                "_path":        fp,
            })
        except Exception as e:
            rows.append({
                "current_file": fp.name,
                "real_ticker":  "?",
                "period_end":   "?",
                "quarter":      "?",
                "canonical":    "?",
                "rename":       False,
                "in_config":    False,
                "_path":        fp,
                "error":        str(e)[:50],
            })

    df = pd.DataFrame(rows)

    # Reportes
    print("=== Status por archivo ===")
    print(df.drop(columns=["_path"]).to_string(index=False))

    print(f"\n=== Resumen ===")
    print(f"  Total archivos:         {len(df)}")
    print(f"  Necesitan rename:       {df['rename'].sum()}")
    print(f"  Tickers fuera de config:{(~df['in_config']).sum()}")
    print(f"  Tickers en config:      {df['in_config'].sum()}")

    # Tickers duplicados
    dup = df[df["real_ticker"].duplicated(keep=False) & (df["real_ticker"] != "?")]
    if not dup.empty:
        print(f"\n  WARN tickers duplicados:")
        print(dup[["current_file", "real_ticker", "period_end"]].to_string(index=False))

    # Tickers fuera de config
    out_of_config = df[~df["in_config"] & (df["real_ticker"] != "?")]
    if not out_of_config.empty:
        print(f"\n  Tickers NO en config/issuers.yaml:")
        print(out_of_config[["current_file", "real_ticker", "period_end"]].to_string(index=False))
        print(f"  -> Para incluirlos en el batch DCF, agregalos a config/issuers.yaml")

    # Faltantes (en config pero sin XBRL)
    have = set(df[df["in_config"]]["real_ticker"])
    missing = config_tickers - have
    if missing:
        print(f"\n  Tickers en config SIN XBRL local: {sorted(missing)}")

    # Renames
    to_rename = df[df["rename"] & (df["real_ticker"] != "?")]
    if not to_rename.empty:
        print(f"\n=== Renames propuestos ({len(to_rename)}) ===")
        for _, r in to_rename.iterrows():
            print(f"  {r['current_file']}  ->  {r['canonical']}")

        if args.apply:
            print("\n  Aplicando renames...")
            for _, r in to_rename.iterrows():
                src = r["_path"]
                dst = src.parent / r["canonical"]
                if dst.exists():
                    print(f"    [SKIP] destino ya existe: {dst.name}")
                    continue
                src.rename(dst)
                print(f"    OK: {src.name} -> {dst.name}")
        else:
            print(f"\n  (dry-run) Para aplicar: python {Path(__file__).name} --apply")

    return 0


if __name__ == "__main__":
    sys.exit(main())
