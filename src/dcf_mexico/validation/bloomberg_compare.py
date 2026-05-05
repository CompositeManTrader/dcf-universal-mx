"""
Validador: compara los datos parseados del XBRL CNBV vs Bloomberg "As Reported".

Bloomberg Excel layout (anual):
  - Hoja "Income - As Reported": ~110 filas, cols [Concept, BBG_Field, FY 2013...FY 2025]
  - Hoja "Bal Sheet - As Reported": ~157 filas
  - Hoja "Cash Flow - As Reported": ~78 filas

Cada fila tiene un label como 'Total Revenue' y un BBG field como 'ARD_TOTAL_REVENUES'.
Usamos el label como llave de mapeo (mas estable que el BBG field).

Por cada periodo (year), comparamos:
  - Bloomberg value (de la columna FY YYYY)
  - Parser value (del XBRL del mismo año)
  - Diff abs y diff %

Output: tabla con cada concepto x periodo, con flag de status (OK/WARN/ERROR/N/A).
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Any

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class LineMapping:
    """Mapea un label Bloomberg a un campo del parser.

    bloomberg_label: el label EXACTO en Bloomberg (col 0)
    parser_path:     ruta al campo en ParseResult (e.g. 'income.revenue', 'balance.cash')
    sign_flip:       multiplicador para alinear convencion (e.g. -1 si BB lo muestra negativo)
    scale:           multiplicador adicional (default 1)
    notes:           comentario para el usuario
    """
    bloomberg_label: str
    parser_path: str
    sign_flip: float = 1.0
    scale: float = 1.0
    notes: str = ""


@dataclass
class BloombergMapping:
    """Conjunto de mappings por hoja para una emisora."""
    ticker: str
    income_ar: list[LineMapping] = field(default_factory=list)
    bs_ar:     list[LineMapping] = field(default_factory=list)
    cf_ar:     list[LineMapping] = field(default_factory=list)


@dataclass
class BloombergCompareResult:
    """Resultado de comparacion para 1 hoja."""
    sheet_name: str       # "Income", "Balance", "CashFlow"
    period_label: str     # "FY 2025"
    table: pd.DataFrame   # cols: Concept, Bloomberg, Parser, Diff abs, Diff %, Status
    n_ok: int = 0
    n_warn: int = 0
    n_error: int = 0
    n_na: int = 0


# ---------------------------------------------------------------------------
# Reading Bloomberg
# ---------------------------------------------------------------------------

def find_bloomberg_file(ticker: str, kind: str = "anuales",
                         base_dir: Optional[Path] = None) -> Optional[Path]:
    """Busca el Bloomberg Excel para un ticker.

    Convencion: data/bloomberg/Edos_<ticker_lower>_<kind>.xlsx
    """
    base = base_dir or Path(__file__).resolve().parents[3] / "data" / "bloomberg"
    if not base.exists():
        return None
    candidates = list(base.glob(f"Edos_{ticker.lower()}_{kind}.xlsx"))
    return candidates[0] if candidates else None


def read_bloomberg_sheet(filepath: Path, sheet_name: str) -> pd.DataFrame:
    """Lee una hoja Bloomberg y devuelve DataFrame indexado por concepto.

    Cols: ['BBG_Field', 'FY 2013', ..., 'FY 2025']
    Index: el label en col 0 (e.g. 'Total Revenue')
    """
    df_raw = pd.read_excel(filepath, sheet_name=sheet_name, header=None, engine="openpyxl")

    # Find header row (la que tiene 'FY YYYY')
    header_row = None
    for r in range(min(10, df_raw.shape[0])):
        for c in range(df_raw.shape[1]):
            v = df_raw.iloc[r, c]
            if pd.notna(v) and isinstance(v, str) and v.startswith("FY "):
                header_row = r
                break
        if header_row is not None:
            break
    if header_row is None:
        raise ValueError(f"No header row found in {sheet_name}")

    # Build columns: Concept (col 0), BBG_Field (col 1), then FY 2013... cols
    headers = ["Concept", "BBG_Field"] + [
        str(df_raw.iloc[header_row, c]) for c in range(2, df_raw.shape[1])
    ]

    rows = []
    for r in range(header_row + 1, df_raw.shape[0]):
        concept = df_raw.iloc[r, 0]
        if pd.isna(concept) or str(concept).strip() == "":
            continue
        concept = str(concept).strip()
        # Skip section headers (no BBG field, no values)
        bbg = df_raw.iloc[r, 1] if df_raw.shape[1] > 1 else ""
        bbg = "" if pd.isna(bbg) else str(bbg).strip()
        row_data = {"Concept": concept, "BBG_Field": bbg}
        for c in range(2, min(df_raw.shape[1], len(headers))):
            col_name = headers[c]
            val = df_raw.iloc[r, c]
            # Bloomberg muestra "—" para missing
            if pd.isna(val) or (isinstance(val, str) and val.strip() in ("—", "-", "")):
                row_data[col_name] = None
            else:
                try:
                    row_data[col_name] = float(val)
                except (ValueError, TypeError):
                    row_data[col_name] = None
        rows.append(row_data)

    df = pd.DataFrame(rows).set_index("Concept")
    return df


# ---------------------------------------------------------------------------
# Field accessors
# ---------------------------------------------------------------------------

def _get_parser_value(parsed, path: str, fx_mult: float = 1.0) -> Optional[float]:
    """Extrae un valor del ParseResult navegando por la ruta 'income.revenue'.

    Convierte raw_pesos -> MDP y aplica fx_mult si reporta en USD.
    """
    parts = path.split(".")
    obj = parsed
    for p in parts:
        obj = getattr(obj, p, None)
        if obj is None:
            return None
    try:
        v = float(obj)
    except (TypeError, ValueError):
        return None
    # Convertir a MDP (asumimos que values en raw pesos del XBRL)
    return (v * fx_mult) / 1_000_000


def _detect_fx(parsed, fx_rate: float = 19.5) -> float:
    """fx_mult basado en moneda del XBRL."""
    cur = (parsed.info.currency or "MXN").upper().strip()
    return fx_rate if cur == "USD" else 1.0


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def _classify_diff(bb: Optional[float], pa: Optional[float],
                    abs_tol: float = 1.0, rel_tol: float = 0.005) -> tuple[str, float, float]:
    """Devuelve (status, diff_abs, diff_pct).

    Status:
      'OK'    si diff < max(abs_tol, rel_tol * |bb|)
      'WARN'  si diff < 5% (advertir pero plausible)
      'ERROR' si diff >= 5%
      'N/A'   si bb o pa es None
    """
    if bb is None or pa is None:
        return ("N/A", 0.0, 0.0)
    diff_abs = pa - bb
    if abs(bb) < 0.001:
        # Bloomberg = 0; check parser tambien chico
        if abs(pa) < abs_tol:
            return ("OK", 0.0, 0.0)
        return ("ERROR", diff_abs, float("inf"))
    diff_pct = diff_abs / abs(bb)
    if abs(diff_abs) <= max(abs_tol, rel_tol * abs(bb)):
        return ("OK", diff_abs, diff_pct)
    if abs(diff_pct) < 0.05:
        return ("WARN", diff_abs, diff_pct)
    return ("ERROR", diff_abs, diff_pct)


def compare_period(
    bb_df: pd.DataFrame,
    period_col: str,
    parsed,
    mappings: list[LineMapping],
    sheet_name: str = "Income",
    fx_rate: float = 19.5,
    abs_tol: float = 1.0,
    rel_tol: float = 0.005,
) -> BloombergCompareResult:
    """Compara los valores de Bloomberg vs parser para UN periodo (1 año)."""
    fx_mult = _detect_fx(parsed, fx_rate)
    rows = []
    for m in mappings:
        # Bloomberg value
        bb_val = None
        if m.bloomberg_label in bb_df.index:
            row = bb_df.loc[m.bloomberg_label]
            # Si hay duplicados (raro pero posible), tomar el primero numerico
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            v = row.get(period_col)
            if v is not None and not pd.isna(v):
                bb_val = float(v) * m.sign_flip * m.scale

        # Parser value
        pa_val = _get_parser_value(parsed, m.parser_path, fx_mult)

        status, diff_abs, diff_pct = _classify_diff(bb_val, pa_val, abs_tol, rel_tol)
        rows.append({
            "Concept":     m.bloomberg_label,
            "Parser path": m.parser_path,
            "Bloomberg":   bb_val,
            "Parser":      pa_val,
            "Diff abs":    diff_abs if status != "N/A" else None,
            "Diff %":      diff_pct if status != "N/A" else None,
            "Status":      status,
            "Notes":       m.notes,
        })

    table = pd.DataFrame(rows)
    n_ok    = (table["Status"] == "OK").sum()
    n_warn  = (table["Status"] == "WARN").sum()
    n_error = (table["Status"] == "ERROR").sum()
    n_na    = (table["Status"] == "N/A").sum()

    return BloombergCompareResult(
        sheet_name=sheet_name,
        period_label=period_col,
        table=table,
        n_ok=int(n_ok),
        n_warn=int(n_warn),
        n_error=int(n_error),
        n_na=int(n_na),
    )


def compare_all_periods(
    bb_filepath: Path,
    bb_sheet_name: str,
    mappings: list[LineMapping],
    parsed_by_year: dict[int, Any],   # {2022: parsed, 2023: parsed, ...}
    sheet_label: str = "Income",
    fx_rate: float = 19.5,
) -> dict[str, BloombergCompareResult]:
    """Compara TODOS los periodos disponibles entre Bloomberg y los parseados.

    parsed_by_year: dict de year -> ParseResult (del XBRL del Q4/4D de ese año).

    Returns: dict de "FY YYYY" -> BloombergCompareResult
    """
    bb_df = read_bloomberg_sheet(bb_filepath, bb_sheet_name)
    results = {}

    # Para cada año disponible en parsed_by_year, buscar columna en BB
    for year, parsed in parsed_by_year.items():
        period_col = f"FY {year}"
        if period_col not in bb_df.columns:
            continue
        results[period_col] = compare_period(
            bb_df=bb_df,
            period_col=period_col,
            parsed=parsed,
            mappings=mappings,
            sheet_name=sheet_label,
            fx_rate=fx_rate,
        )

    return results
