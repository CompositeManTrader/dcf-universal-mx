"""
CLI: descarga XBRL para los 35 issuers configurados.

Uso:
  python scripts/download_all_xbrl.py                      # default period 2025-4
  python scripts/download_all_xbrl.py --period 2025-3      # otro trimestre
  python scripts/download_all_xbrl.py --overwrite          # forzar re-descarga
  python scripts/download_all_xbrl.py --only AC,FEMSA,KOF  # solo algunos tickers

Estrategia:
  1. Si el ticker tiene `xbrl_url` en config/issuers.yaml -> descarga directo.
  2. Si no, intenta scrapear https://www.bmv.com.mx/es/emisoras/perfil/{TICKER}.
  3. Si nada, imprime instrucciones de descarga manual.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dcf_mexico.config import load_issuers
from dcf_mexico.download import download_xbrl_for_ticker


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="2025-4", help="Tag periodo (ej: 2025-4)")
    ap.add_argument("--overwrite", action="store_true", help="Re-descargar aunque exista")
    ap.add_argument("--only", default="", help="Lista CSV de tickers (default: todos)")
    args = ap.parse_args()

    _, issuers = load_issuers()

    if args.only:
        wanted = {t.strip().upper() for t in args.only.split(",")}
        issuers = {k: v for k, v in issuers.items() if k.upper() in wanted}

    print(f"\n>>> Descargando {len(issuers)} XBRL para periodo {args.period}\n")

    n_ok = n_cached = n_manual = n_err = 0
    manual_list = []

    for ticker, issuer in sorted(issuers.items()):
        r = download_xbrl_for_ticker(
            ticker, period_tag=args.period, issuer=issuer, overwrite=args.overwrite,
        )
        if r.ok and r.method == "cached":
            n_cached += 1
            print(f"  {ticker:>10}  [CACHE]   {r.saved_path.name}")
        elif r.ok:
            n_ok += 1
            print(f"  {ticker:>10}  [DL {r.method:<10}]  {r.saved_path.name}")
        elif r.method == "manual_required":
            n_manual += 1
            manual_list.append(ticker)
            print(f"  {ticker:>10}  [MANUAL]  ver {r.error[:80]}")
        else:
            n_err += 1
            print(f"  {ticker:>10}  [ERROR]   {r.error[:80]}")

    print(f"\n=== Resumen ===")
    print(f"  En cache:        {n_cached}")
    print(f"  Descargados OK:  {n_ok}")
    print(f"  Manual required: {n_manual}")
    print(f"  Errores:         {n_err}")
    if manual_list:
        print(f"\nPara los tickers manuales, ve a https://www.bmv.com.mx/es/emisoras/perfil/<TICKER>")
        print(f"Descarga el ZIP del 'Anexo T' (Anexo de Informacion Financiera)")
        print(f"y ponlo en data/raw_xbrl/ con nombre: ifrsxbrl_<TICKER>_{args.period}.xls")
        print(f"\nO mejor: agrega `xbrl_url: https://...` a cada ticker en config/issuers.yaml")
        print(f"Tickers pendientes: {', '.join(manual_list)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
