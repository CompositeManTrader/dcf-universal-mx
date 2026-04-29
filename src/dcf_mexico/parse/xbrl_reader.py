"""
Parser robusto del XBRL de CNBV (formato Excel .xls/.xlsx).

Mejoras vs xbrl_parser_cnbv_v2.ipynb:
  1. Match EXACTO de etiquetas (no startswith) -> evita confundir "Total de activos"
     con "Total de activos circulantes".
  2. Normalizacion Unicode (NFC + lower) para tolerar variantes de acentos.
  3. Suma de TODAS las series accionarias en 700000 (no solo la primera).
  4. Conversion de unidades segun "Grado de redondeo" (Pesos/Miles/Millones) -> pesos.
  5. Separacion explicita de deuda financiera vs arrendamientos IFRS-16.
  6. Capex bruto y neto (resta venta de PPE) por separado.
  7. Tasa efectiva impositiva acotada a [0, 50%], default 30% si fuera de rango.
  8. Validacion contable A = L + E con tolerancia.
  9. Sin dependencias de google.colab; corre en cualquier entorno con pandas.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

from .schema import (
    BalanceSheet,
    CashFlow,
    CompanyInfo,
    DCFInputs,
    IncomeStatement,
    IncomeStatementQuarter,
    Informative,
    ValidationReport,
)
from .validators import merge_reports, validate_balance, validate_income


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and pd.isna(val):
        return ""
    return str(val).strip()


def _safe_num(val) -> Optional[float]:
    """Convierte a float; devuelve None si no es numerico (no 0.0, para distinguir)."""
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "").replace("$", "")
    if s == "":
        return None
    # Manejo de parentesis para negativos: (1,234) -> -1234
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


def _normalize(s: str) -> str:
    """NFC + lower + strip + colapsa espacios."""
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


# ---------------------------------------------------------------------------
# Indexador de hojas
# ---------------------------------------------------------------------------

class SheetIndex:
    """Indexa una hoja del XBRL para lookup por etiqueta exacta."""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self._index: dict[str, int] = {}
        for i in range(len(df)):
            lbl = _safe_str(df.iloc[i, 0])
            if not lbl:
                continue
            key = _normalize(lbl)
            # Solo guardamos la PRIMERA aparicion (la canonica).
            if key not in self._index:
                self._index[key] = i

    def get(self, label: str, col: int = 1) -> Optional[float]:
        key = _normalize(label)
        if key not in self._index:
            return None
        i = self._index[key]
        if col >= self.df.shape[1]:
            return None
        return _safe_num(self.df.iloc[i, col])

    def get_or(self, label: str, col: int = 1, default: float = 0.0) -> float:
        v = self.get(label, col)
        return default if v is None else v

    def get_first(self, *labels: str, col: int = 1, default: float = 0.0) -> float:
        for lbl in labels:
            v = self.get(lbl, col)
            if v is not None:
                return v
        return default

    def sum_row(self, label: str, start_col: int = 1) -> float:
        """Suma todos los valores numericos en la fila de `label` (desde start_col)."""
        key = _normalize(label)
        if key not in self._index:
            return 0.0
        i = self._index[key]
        total = 0.0
        for c in range(start_col, self.df.shape[1]):
            v = _safe_num(self.df.iloc[i, c])
            if v is not None:
                total += v
        return total

    def find_all_rows(self, label: str) -> list:
        """Devuelve TODOS los row indices que matchean el label.
        Util para CNBV CF donde 'Intereses pagados' aparece en CFO y Financing."""
        key = _normalize(label)
        rows = []
        for i in range(len(self.df)):
            lbl = _safe_str(self.df.iloc[i, 0])
            if _normalize(lbl) == key:
                rows.append(i)
        return rows

    def get_at_row(self, row_idx: int, col: int = 1) -> Optional[float]:
        """Get value at specific (row, col). Util cuando find_all_rows devuelve multiples."""
        if row_idx >= self.df.shape[0] or col >= self.df.shape[1]:
            return None
        return _safe_num(self.df.iloc[row_idx, col])

    def sum_across_series(self, label: str) -> float:
        """Para 700000 multi-serie: si el header indica 'Serie X [miembro]' / '[Eje]',
        suma todas las columnas. Si el header son periodos ('Trimestre Actual', etc.),
        toma solo la primera columna."""
        key = _normalize(label)
        if key not in self._index:
            return 0.0
        i = self._index[key]

        # Detectar modo: revisar las primeras 3 filas por keywords de series
        is_multi_series = False
        for r in range(min(3, self.df.shape[0])):
            row_txt = " ".join(_safe_str(self.df.iloc[r, c]) for c in range(self.df.shape[1])).lower()
            if "[miembro]" in row_txt or "[eje" in row_txt or " serie " in row_txt:
                is_multi_series = True
                break

        if is_multi_series:
            return self.sum_row(label, start_col=1)
        # Modo periodos -> solo col 1 (Trimestre Actual)
        return self.get_or(label, col=1, default=0.0)


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

@dataclass
class ParseResult:
    info: CompanyInfo
    balance: BalanceSheet
    income: IncomeStatement
    cashflow: CashFlow
    informative: Informative
    dcf: DCFInputs
    validation: ValidationReport
    income_quarter: IncomeStatementQuarter = None  # PURE 3-month quarter (col 1 XBRL)
    raw_sheets: dict = field(default_factory=dict)

    def summary(self) -> pd.DataFrame:
        """Series principales en MDP, formato analista."""
        m = 1_000_000
        rows = [
            ("Empresa", self.info.entity_name),
            ("Ticker", self.info.ticker),
            ("Periodo", self.info.period_end),
            ("Trimestre", self.info.quarter),
            ("Moneda / Unidades", f"{self.info.currency} / {self.info.rounding}"),
            ("---", "---"),
            ("Ingresos (acum)", f"{self.income.revenue / m:,.1f}"),
            ("EBIT (acum)", f"{self.income.ebit / m:,.1f}"),
            ("Margen operativo", f"{self.income.operating_margin:.2%}"),
            ("Utilidad neta", f"{self.income.net_income / m:,.1f}"),
            ("Tax rate efectivo", f"{self.income.effective_tax_rate:.2%}"),
            ("---", "---"),
            ("Activos totales", f"{self.balance.total_assets / m:,.1f}"),
            ("Capital controladora", f"{self.balance.equity_controlling / m:,.1f}"),
            ("Deuda financiera", f"{self.balance.total_financial_debt / m:,.1f}"),
            ("Arrendamientos", f"{self.balance.total_lease_debt / m:,.1f}"),
            ("Efectivo", f"{self.balance.cash / m:,.1f}"),
            ("Deuda neta", f"{self.balance.net_debt / m:,.1f}"),
            ("Capital invertido", f"{self.balance.invested_capital / m:,.1f}"),
            ("---", "---"),
            ("CFO", f"{self.cashflow.cfo / m:,.1f}"),
            ("Capex bruto", f"{self.cashflow.capex_gross / m:,.1f}"),
            ("Capex neto", f"{self.cashflow.capex_net / m:,.1f}"),
            ("---", "---"),
            ("Acciones (mn)", f"{self.informative.shares_outstanding / m:,.2f}"),
            ("D&A 12M", f"{self.informative.da_12m / m:,.1f}"),
            ("Ingresos 12M", f"{self.informative.revenue_12m / m:,.1f}"),
            ("Crecimiento ingresos 12M", f"{self.dcf.revenue_growth:.2%}"),
        ]
        return pd.DataFrame(rows, columns=["Concepto", "Valor"])


# ---------------------------------------------------------------------------
# Reader principal
# ---------------------------------------------------------------------------

# Codigos de hojas estandar CNBV
SHEET_INFO = "110000"
SHEET_BS = "210000"
SHEET_IS = "310000"
SHEET_CF = "520000"
SHEET_INFO_BS = "700000"
SHEET_INFO_DA = "700002"
SHEET_INFO_12M = "700003"
SHEET_NOTES_INC_EXP = "800200"   # Notas: ingresos/gastos breakdown (interes, FX, taxes)
SHEET_NOTES_REVENUE = "800005"   # Distribucion de ingresos por geografia
SHEET_NOTES_BS = "800100"        # Notas: Subclasificaciones de activos, pasivos, capital

# Tipos de emisora financiera (banco, casa de bolsa, sofol, aseguradora, fideicomiso)
FINANCIAL_ISSUER_TYPES = {"BM", "CB", "SF", "SA", "FI", "FFC"}

ROUNDING_FACTORS = {
    "pesos": 1.0,
    "miles de pesos": 1_000.0,
    "millones de pesos": 1_000_000.0,
}
# NOTA: aunque la metadata "Grado de redondeo" diga "Miles de pesos",
# en la practica el XBRL CNBV almacena los importes en PESOS RAW
# (verificado con CUERVO 2025-Q4 cuyos cells son 11,076,681,000 = 11.07B pesos).
# Por eso el factor real siempre es 1.
USE_ROUNDING_METADATA = False


class XBRLReader:
    def __init__(self, filepath: str | Path):
        self.filepath = Path(filepath)
        if not self.filepath.exists():
            raise FileNotFoundError(self.filepath)
        # Algunos XBRL CNBV vienen como .xls pero son xlsx (PK header).
        # pandas / openpyxl manejan ambos si el engine es correcto.
        try:
            xls = pd.ExcelFile(self.filepath, engine="openpyxl")
        except Exception:
            xls = pd.ExcelFile(self.filepath)
        self.sheet_names = list(xls.sheet_names)
        self.sheets: dict[str, pd.DataFrame] = {}
        for name in self.sheet_names:
            self.sheets[name] = pd.read_excel(xls, sheet_name=name, header=None)
        # Cerrar el handle del archivo (Windows lockea sino)
        try:
            xls.close()
        except Exception:
            pass

    # -----------------------------------------------------------------
    def _idx(self, sheet_code: str) -> Optional[SheetIndex]:
        if sheet_code not in self.sheets:
            return None
        return SheetIndex(self.sheets[sheet_code])

    # -----------------------------------------------------------------
    # 110000 - Informacion general
    # -----------------------------------------------------------------
    def _parse_info(self) -> CompanyInfo:
        info = CompanyInfo()
        idx = self._idx(SHEET_INFO)
        if idx is None:
            return info

        def _s(label: str) -> str:
            v = idx.get(label, col=1)
            if v is None:
                # campo string -> get devuelve None porque no es numerico; leer raw
                key = _normalize(label)
                if key in idx._index:
                    return _safe_str(idx.df.iloc[idx._index[key], 1])
                return ""
            return str(v)

        info.entity_name = _s("Nombre de la entidad que informa u otras formas de identificacion") or \
                           _s("Nombre de la entidad que informa u otras formas de identificación")
        info.ticker = _s("Clave de cotizacion") or _s("Clave de cotización")
        info.period_end = _s("Fecha de cierre del periodo sobre el que se informa")
        q_raw = _s("Numero De Trimestre") or _s("Número De Trimestre")
        # Cell viene como float "4.0" -> normalizar a "4"
        try:
            info.quarter = str(int(float(q_raw))) if q_raw else ""
        except ValueError:
            info.quarter = q_raw
        info.currency = _s("Descripcion de la moneda de presentacion") or \
                        _s("Descripción de la moneda de presentación") or "MXN"
        info.rounding = _s("Grado de redondeo utilizado en los estados financieros")
        info.issuer_type = _s("Tipo de emisora")

        # Derivados
        if info.period_end and len(info.period_end) >= 4:
            try:
                info.fiscal_year = int(info.period_end[:4])
            except ValueError:
                info.fiscal_year = 0
        info.is_financial = info.issuer_type.upper() in FINANCIAL_ISSUER_TYPES

        return info

    # -----------------------------------------------------------------
    def _rounding_factor(self, info: CompanyInfo) -> float:
        if not USE_ROUNDING_METADATA:
            return 1.0
        # Match en orden de mas largo a mas corto para evitar que "pesos" matchee "miles de pesos"
        key = _normalize(info.rounding) if info.rounding else "pesos"
        for k in sorted(ROUNDING_FACTORS, key=len, reverse=True):
            if k in key:
                return ROUNDING_FACTORS[k]
        return 1.0

    # -----------------------------------------------------------------
    # 210000 - Balance General
    # -----------------------------------------------------------------
    def _parse_balance(self, factor: float) -> BalanceSheet:
        bs = BalanceSheet()
        idx = self._idx(SHEET_BS)
        if idx is None:
            return bs

        # col=1 -> trimestre actual
        g = lambda *labels: idx.get_first(*labels, col=1, default=0.0) * factor

        # Activos circulantes
        bs.cash = g("Efectivo y equivalentes de efectivo")
        bs.accounts_receivable = g(
            "Clientes y otras cuentas por cobrar",
            "Clientes y otras cuentas por cobrar (corriente)",
        )
        bs.inventories = g("Inventarios")
        bs.other_current_assets = g(
            "Otros activos no financieros",
            "Otros activos no financieros (corrientes)",
            "Otros activos no financieros corrientes",
        )
        bs.total_current_assets = g("Total de activos circulantes")

        # Activos no circulantes
        bs.investments_in_associates = g(
            "Inversiones en subsidiarias, negocios conjuntos y asociadas",
            "Inversiones registradas por método de participación",
            "Inversiones contabilizadas utilizando el metodo de participacion",
            "Inversiones contabilizadas utilizando el método de participación",
        )
        bs.ppe = g("Propiedades, planta y equipo")
        bs.right_of_use_assets = g(
            "Activos por derechos de uso",   # CNBV: plural
            "Activos por derecho de uso",
        )
        bs.intangibles = g(
            "Activos intangibles distintos al crédito mercantil",  # CNBV: plural
            "Activo intangible distinto al credito mercantil",
            "Activo intangible distinto al crédito mercantil",
        )
        bs.goodwill = g("Crédito mercantil", "Credito mercantil")
        bs.deferred_tax_assets = g("Activos por impuestos diferidos")
        bs.other_non_current_assets = g(
            "Otros activos no financieros no circulantes",
            "Otros activos no circulantes",
        )
        bs.total_non_current_assets = g("Total de activos no circulantes")

        # Total activos (EXACTO, no startswith - este era el bug v2)
        bs.total_assets = g("Total de activos")

        # Pasivos circulantes
        bs.accounts_payable = g(
            "Proveedores y otras cuentas por pagar a corto plazo",
            "Proveedores y otras cuentas por pagar",
        )
        bs.short_term_debt = g("Otros pasivos financieros a corto plazo")
        bs.short_term_lease = g("Pasivos por arrendamientos a corto plazo")
        bs.other_current_liabilities = g(
            "Otros pasivos no financieros a corto plazo",
            "Otros pasivos circulantes",
        )
        bs.total_current_liabilities = g("Total de pasivos circulantes")

        # Pasivos largo plazo (en CNBV se llama "a Largo plazo", no "no circulantes")
        bs.long_term_debt = g("Otros pasivos financieros a largo plazo")
        bs.long_term_lease = g("Pasivos por arrendamientos a largo plazo")
        bs.deferred_tax_liabilities = g(
            "Pasivo por impuestos diferidos",
            "Pasivos por impuestos diferidos",
        )
        bs.other_non_current_liabilities = g(
            "Otros pasivos no financieros a largo plazo",
            "Otros pasivos no circulantes",
        )
        bs.total_non_current_liabilities = g(
            "Total de pasivos a Largo plazo",          # CNBV CUERVO
            "Total de pasivos a largo plazo",
            "Total de pasivos no circulantes",
        )

        bs.total_liabilities = g("Total pasivos", "Total de pasivos")

        # Capital
        bs.equity_controlling = g(
            "Total de la participación controladora",
            "Total de la participacion controladora",
        )
        bs.minority_interest = g(
            "Participación no controladora",
            "Participacion no controladora",
        )
        bs.total_equity = g(
            "Total de capital contable",   # CNBV: "de" no "del"
            "Total del capital contable",
            "Capital contable",
        )

        # ----- EQUITY BREAKDOWN (210000) -----
        bs.common_stock = g("Capital social")
        bs.additional_paid_in_capital = g("Prima en emisión de acciones",
                                            "Prima en emision de acciones")
        bs.treasury_stock = g("Acciones en tesorería", "Acciones en tesoreria")
        bs.retained_earnings = g("Utilidades acumuladas")
        bs.other_equity_reserves = g(
            "Otros resultados integrales acumulados",
        )

        # ----- ACTIVOS extra del 210000 -----
        bs.biological_assets_current = g("Activos biológicos", "Activos biologicos")
        bs.biological_assets_noncurrent = g(
            "Activos biológicos no circulantes",
            "Activos biologicos no circulantes",
        )
        bs.inventories_noncurrent = g("Inventarios no circulantes")
        bs.other_financial_assets_st = g(
            "Otros activos financieros",
        )
        bs.taxes_recoverable_st = g(
            "Impuestos por recuperar",
        )
        bs.accounts_receivable_lt = g(
            "Clientes y otras cuentas por cobrar no circulantes",
        )

        # ----- PASIVOS extra del 210000 -----
        bs.provisions_st = g(
            "Otras provisiones a corto plazo",
        )
        bs.provisions_lt = g(
            "Otras provisiones a largo plazo",
            "Otras provisiones a Largo plazo",
        )
        bs.employee_benefits_lt = g(
            "Provisiones por beneficios a los empleados a Largo plazo",
            "Provisiones por beneficios a los empleados a largo plazo",
        )

        # ----- BREAKDOWN DETALLADO del 800100 (Notas - Subclasificaciones) -----
        idxbs = self._idx(SHEET_NOTES_BS)
        if idxbs is not None:
            gn = lambda *labels: idxbs.get_first(*labels, col=1, default=0.0) * factor

            # Receivables breakdown
            bs.accounts_receivable_trade        = gn("Clientes")
            bs.accounts_receivable_related_st   = gn("Cuentas por cobrar circulantes a partes relacionadas")
            bs.other_receivables_st             = gn("Otras cuentas por cobrar circulantes")
            bs.prepaid_expenses_st              = gn("Gastos anticipados circulantes")
            # taxes_recoverable: si 210000 lo tiene en 0, usar 800100 (mas detallado)
            tax_rec_notes = gn("Cuentas por cobrar circulantes procedentes de impuestos distintos a los impuestos a las ganancias")
            if tax_rec_notes and not bs.taxes_recoverable_st:
                bs.taxes_recoverable_st = tax_rec_notes

            # Inventory breakdown (Q4 acum, snapshot a fin de periodo)
            bs.inventory_raw_materials = gn("Materias primas")
            bs.inventory_wip           = gn("Trabajo en curso circulante")
            bs.inventory_finished      = gn("Productos terminados circulantes")
            bs.inventory_supplies      = gn("Suministros de producción circulantes",
                                            "Suministros de produccion circulantes")
            bs.inventory_spare_parts   = gn("Piezas de repuesto circulantes")

            # Debt breakdown (CP + LP)
            bs.bank_loans_st   = gn("Créditos Bancarios a corto plazo",
                                     "Creditos Bancarios a corto plazo")
            bs.notes_payable_st= gn("Créditos Bursátiles a corto plazo",
                                     "Creditos Bursatiles a corto plazo")
            bs.bank_loans_lt   = gn("Créditos Bancarios a largo plazo",
                                     "Creditos Bancarios a largo plazo")
            bs.bonds_payable_lt= gn("Créditos Bursátiles a largo plazo",
                                     "Creditos Bursatiles a largo plazo")

            # Payables breakdown
            bs.accounts_payable_trade        = gn("Proveedores circulantes")
            bs.accounts_payable_related_st   = gn("Cuentas por pagar circulantes a partes relacionadas")

        return bs

    # -----------------------------------------------------------------
    # 310000 - Estado de Resultados (acumulado)
    # -----------------------------------------------------------------
    def _parse_income_at_col(self, factor: float, col: int, target_cls):
        """Parser generico de IS para una columna especifica.
        col=3 -> acumulado año actual; col=1 -> trimestre actual."""
        is_ = target_cls()
        idx = self._idx(SHEET_IS)
        if idx is None:
            return is_

        g = lambda *labels: idx.get_first(*labels, col=col, default=0.0) * factor

        is_.revenue = g(
            "Ingresos",
            "Ingresos por contratos con clientes",
            "Ventas netas",
        )
        is_.cost_of_sales = g("Costo de ventas")
        is_.gross_profit = g("Utilidad bruta")
        # Opex: en CNBV vienen separados "Gastos de venta" + "Gastos de administracion"
        gastos_venta = g("Gastos de venta")
        gastos_admin = g("Gastos de administración", "Gastos de administracion")
        gastos_grales = g("Gastos generales")
        is_.selling_expenses = gastos_venta
        is_.ga_expenses = gastos_admin
        is_.operating_expenses = gastos_venta + gastos_admin + gastos_grales
        # Otros operativos: ingresos menos gastos (CNBV los reporta separados)
        otros_ing = g("Otros ingresos")
        otros_gst = g("Otros gastos")
        is_.other_operating_income = otros_ing
        is_.other_operating_expense = otros_gst
        is_.other_operating = otros_ing - otros_gst
        is_.ebit = g(
            "Utilidad (pérdida) de operación",
            "Utilidad (perdida) de operacion",
            "Utilidad de operación",
            "Utilidad de operacion",
        )
        is_.interest_income = g("Ingresos financieros", "Productos financieros")
        is_.interest_expense = g("Gastos financieros")
        is_.fx_result = g(
            "Utilidad (pérdida) en cambio de moneda extranjera, neto",
            "Utilidad (perdida) en cambio de moneda extranjera, neto",
        )
        is_.associates_result = g(
            "Participación en la utilidad (pérdida) de asociadas y negocios conjuntos",
            "Participacion en la utilidad (perdida) de asociadas y negocios conjuntos",
            "Participación en la utilidad (pérdida) de asociadas y negocios conjuntos contabilizados utilizando el método de participación",
        )
        is_.pretax_income = g(
            "Utilidad (pérdida) antes de impuestos",
            "Utilidad (perdida) antes de impuestos",
            "Utilidad (pérdida) antes de impuestos a la utilidad",
            "Utilidad (perdida) antes de impuestos a la utilidad",
        )
        is_.tax_expense = g(
            "Impuestos a la utilidad",
            "(Ingreso) gasto por impuestos",
        )
        is_.net_income = g(
            "Utilidad (pérdida) neta",
            "Utilidad (perdida) neta",
        )
        is_.net_income_controlling = g(
            "Utilidad (pérdida) atribuible a la participación controladora",
            "Utilidad (perdida) atribuible a la participacion controladora",
        )
        is_.net_income_minority = g(
            "Utilidad (pérdida) atribuible a la participación no controladora",
            "Utilidad (perdida) atribuible a la participacion no controladora",
        )
        return is_

    def _parse_income(self, factor: float) -> IncomeStatement:
        """Income statement ACUMULADO (col 3 estandar CNBV)."""
        idx = self._idx(SHEET_IS)
        if idx is None:
            return IncomeStatement()
        col_acum = self._detect_acum_col(idx, default=3)
        return self._parse_income_at_col(factor, col_acum, IncomeStatement)

    def _parse_income_quarter(self, factor: float) -> IncomeStatementQuarter:
        """Income statement del TRIMESTRE PURO (col 1 'Trimestre Actual')."""
        return self._parse_income_at_col(factor, 1, IncomeStatementQuarter)

    # -----------------------------------------------------------------
    def _detect_acum_col(self, idx: SheetIndex, default: int = 3) -> int:
        """Detecta cual columna corresponde al acumulado del año actual.
        Si los headers tienen rangos de fechas como 'YYYY-01-01 al YYYY-12-31',
        identifica esa. Si no, usa el default."""
        for r in range(min(5, idx.df.shape[0])):
            for c in range(1, idx.df.shape[1]):
                txt = _safe_str(idx.df.iloc[r, c]).lower()
                if "01-01" in txt and " al " in txt:
                    return c
        return default

    # -----------------------------------------------------------------
    # 520000 - Flujo de Efectivo
    # -----------------------------------------------------------------
    def _parse_cashflow(self, factor: float) -> CashFlow:
        cf = CashFlow()
        idx = self._idx(SHEET_CF)
        if idx is None:
            return cf

        col = 1  # acumulado año actual
        g = lambda *labels: idx.get_first(*labels, col=col, default=0.0) * factor

        # CFO: el label real CNBV trae "de" entre "procedentes" y "(utilizados...)"
        cf.cfo = g(
            "Flujos de efectivo netos procedentes de (utilizados en) actividades de operación",
            "Flujos de efectivo netos procedentes de (utilizados en) actividades de operacion",
            "Flujos de efectivo netos procedentes (utilizados en) actividades de operación",
            "Flujos de efectivo netos procedentes (utilizados en) actividades de operacion",
        )
        # Capex: en CNBV viene con prefijo "- " literal en el label
        cf.capex_ppe = g(
            "- Compras de propiedades, planta y equipo",
            "Compras de propiedades, planta y equipo",
        )
        cf.capex_intangibles = g(
            "- Compras de activos intangibles",
            "Compras de activos intangibles",
        )
        cf.sales_of_ppe = g(
            "+ Importes procedentes de la venta de propiedades, planta y equipo",
            "Importes procedentes de la venta de propiedades, planta y equipo",
        )
        cf.acquisitions = g(
            "- Flujos de efectivo utilizados para obtener el control de subsidiarias u otros negocios",
            "+ Flujos de efectivo procedentes de la pérdida de control de subsidiarias u otros negocios",
        )
        cf.cfi = g(
            "Flujos de efectivo netos procedentes de (utilizados en) actividades de inversión",
            "Flujos de efectivo netos procedentes de (utilizados en) actividades de inversion",
        )
        cf.debt_issued = g(
            "+ Importes procedentes de préstamos",
            "+ Importes procedentes de prestamos",
            "Importes procedentes de préstamos",
        )
        cf.debt_repaid = g(
            "- Reembolsos de préstamos",
            "- Reembolsos de prestamos",
            "Reembolsos de préstamos",
        )
        cf.dividends_paid = g("- Dividendos pagados", "Dividendos pagados")
        cf.cff = g(
            "Flujos de efectivo netos procedentes de (utilizados en) actividades de financiamiento",
            "Flujos de efectivo netos procedentes (utilizados en) actividades de financiamiento",
        )
        cf.net_change_cash = g(
            "Incremento (disminución) neto de efectivo y equivalentes de efectivo",
            "Incremento (disminucion) neto de efectivo y equivalentes de efectivo",
        )
        # Disposal of Assets
        cf.disposal_loss_gain = g(
            "+ (-) Pérdida (utilidad) por la disposición de activos no circulantes",
            "+ (-) Pérdida (utilidad) por la disposicion de activos no circulantes",
            "Pérdida (utilidad) por la disposición de activos no circulantes",
        )

        # ---- NEW Bloomberg CF Standardized fields ----
        # CFO antes de interest/tax adjustments (BB usa este como "Cash from Operating")
        cf.cfo_pre_adj = g(
            "Flujos de efectivo netos procedentes (utilizados en) operaciones",
            "Flujos de efectivo netos procedentes de (utilizados en) operaciones",
        )

        # D&A en CF (puede diferir de informative.da_12m si hay impairments)
        cf.da_in_cf = g(
            "+ Gastos de depreciación y amortización",
            "Gastos de depreciación y amortización",
            "Gastos de depreciacion y amortizacion",
        )

        # Working capital changes
        cf.chg_inventories = g(
            "+ (-) Disminuciones (incrementos) en los inventarios",
            "+ (-) Disminuciones (incrementos) en inventarios",
        )
        cf.chg_receivables = g(
            "+ (-) Disminución (incremento) de clientes",
            "+ (-) Disminucion (incremento) de clientes",
        )
        cf.chg_other_receivables = g(
            "+ (-) Disminuciones (incrementos) en otras cuentas por cobrar derivadas de las actividades de operación",
            "+ (-) Disminuciones (incrementos) en otras cuentas por cobrar derivadas de las actividades de operacion",
        )
        cf.chg_payables = g(
            "+ (-) Incremento (disminución) de proveedores",
            "+ (-) Incremento (disminucion) de proveedores",
        )
        cf.chg_other_payables = g(
            "+ (-) Incrementos (disminuciones) en otras cuentas por pagar derivadas de las actividades de operación",
            "+ (-) Incrementos (disminuciones) en otras cuentas por pagar derivadas de las actividades de operacion",
        )

        # Non-cash items
        cf.other_non_cash_items_cf = g(
            "+ Otras partidas distintas al efectivo",
        )
        cf.provisions_cf = g("+ Provisiones")
        cf.fx_unrealized_cf = g(
            "+ (-) Pérdida (utilidad) de moneda extranjera no realizadas",
            "+ (-) Perdida (utilidad) de moneda extranjera no realizadas",
        )
        cf.associates_cf = g(
            "+ Participación en asociadas y negocios conjuntos",
            "+ Participacion en asociadas y negocios conjuntos",
        )

        # CF Investing
        cf.cash_from_loss_of_control = g(
            "+ Flujos de efectivo procedentes de la pérdida de control de subsidiarias u otros negocios",
            "+ Flujos de efectivo procedentes de la perdida de control de subsidiarias u otros negocios",
        )
        cf.cash_for_obtain_control = g(
            "- Flujos de efectivo utilizados para obtener el control de subsidiarias u otros negocios",
        )
        cf.sales_of_intangibles = g(
            "+ Importes procedentes de ventas de activos intangibles",
        )

        # CF Financing
        cf.lease_payments_cf = g(
            "- Pagos de pasivos por arrendamientos",
            "- Pagos de pasivos por arrendamientos financieros",
        )

        # ---- DUPLICATE LABELS (CFO + Financing) ----
        # Algunos labels aparecen MULTIPLES veces en hoja 520000:
        # "- Intereses pagados" -> row 33 (CFO), row 57 (Inv=0), row 75 (Financing)
        # Usamos find_all_rows para distinguir por orden de aparicion.
        int_paid_rows = idx.find_all_rows("- Intereses pagados")
        if len(int_paid_rows) >= 1:
            cf.interest_paid_cfo = (idx.get_at_row(int_paid_rows[0], col=col) or 0) * factor
        # Tomar la ULTIMA ocurrencia que sea no-cero como financing
        # (CUERVO: row 33=-828, row 57=0, row 75=+958)
        for r in reversed(int_paid_rows):
            v = idx.get_at_row(r, col=col)
            if v and abs(v) > 0.001:
                cf.interest_paid_financing = v * factor
                break
        cf.interest_received_cfo = g("+ Intereses recibidos")
        cf.taxes_paid_cfo = g(
            "+ (-) Impuestos a las utilidades reembolsados (pagados)",
        )

        # CFI: "+ Intereses cobrados" (row 58) — CUERVO espeja row 34 aqui;
        #      "+ Dividendos recibidos" puede aparecer 2x (row 32 CFO, row 56 CFI).
        cf.interest_received_in_cfi = g("+ Intereses cobrados")
        # dividendos_received CFI: tomar la SEGUNDA ocurrencia (CFI section)
        div_rec_rows = idx.find_all_rows("+ Dividendos recibidos")
        if len(div_rec_rows) >= 2:
            cf.dividends_received_cfi = (idx.get_at_row(div_rec_rows[1], col=col) or 0) * factor
        elif len(div_rec_rows) == 1:
            # Solo una ocurrencia; si esta en rango CFI (>= row 50), asignar
            if div_rec_rows[0] >= 50:
                cf.dividends_received_cfi = (idx.get_at_row(div_rec_rows[0], col=col) or 0) * factor

        # FX effect on cash
        cf.fx_effect_on_cash = g(
            "Efectos de la variación en la tasa de cambio sobre el efectivo y equivalentes al efectivo",
            "Efectos de la variacion en la tasa de cambio sobre el efectivo y equivalentes al efectivo",
        )

        return cf

    # -----------------------------------------------------------------
    # 700000 / 700002 / 700003 - Datos Informativos
    # -----------------------------------------------------------------
    def _parse_informative(self, factor: float) -> Informative:
        inf = Informative()

        # 700000 - Acciones (CNBV usa "Numero" sin acento + "circulación" CON acento)
        idx = self._idx(SHEET_INFO_BS)
        if idx is not None:
            inf.shares_outstanding = (
                idx.sum_across_series("Numero de acciones en circulación")
                or idx.sum_across_series("Número de acciones en circulación")
                or idx.sum_across_series("Numero de acciones en circulacion")
                or idx.sum_across_series("Número de acciones en circulacion")
            )
            inf.shares_by_series = self._extract_series_breakdown(idx)
            # Numero de empleados (col 1 = trim actual)
            inf.num_employees = idx.get_or("Numero de empleados", col=1, default=0.0)
            inf.num_workers = idx.get_or("Numero de obreros", col=1, default=0.0)

        # 700003 - Datos a 12 meses
        idx12 = self._idx(SHEET_INFO_12M)
        if idx12 is not None:
            inf.revenue_12m = idx12.get_or("Ingresos", col=1, default=0.0) * factor
            inf.revenue_12m_prior = idx12.get_or("Ingresos", col=2, default=0.0) * factor
            inf.ebit_12m = idx12.get_first(
                "Utilidad (pérdida) de operación",
                "Utilidad (perdida) de operacion",
                col=1, default=0.0,
            ) * factor
            inf.ebit_12m_prior = idx12.get_first(
                "Utilidad (pérdida) de operación",
                "Utilidad (perdida) de operacion",
                col=2, default=0.0,
            ) * factor
            inf.da_12m = idx12.get_first(
                "Depreciación y amortización operativa",
                "Depreciacion y amortizacion operativa",
                col=1, default=0.0,
            ) * factor

        # 700002 - D&A acumulada (fallback si 700003 vacio) + da_quarter (col 1)
        idxda = self._idx(SHEET_INFO_DA)
        if idxda is not None:
            if inf.da_12m == 0:
                col_acum = self._detect_acum_col(idxda, default=3)
                inf.da_12m = idxda.get_first(
                    "Depreciación y amortización operativa",
                    "Depreciacion y amortizacion operativa",
                    col=col_acum, default=0.0,
                ) * factor
            # D&A del trimestre puro (col 1)
            inf.da_quarter = idxda.get_first(
                "Depreciación y amortización operativa",
                "Depreciacion y amortizacion operativa",
                col=1, default=0.0,
            ) * factor

        # 800200 - Notas: Analisis de ingresos y gastos
        # cols: 1=Trim Actual, 2=Trim Anterior, 3=Acum Actual, 4=Acum Anterior
        idxnotes = self._idx(SHEET_NOTES_INC_EXP)
        if idxnotes is not None:
            col_acum_n = self._detect_acum_col(idxnotes, default=3)
            # Tax breakdown
            inf.current_tax_quarter = idxnotes.get_or("Impuesto causado", col=1, default=0.0) * factor
            inf.current_tax_acum    = idxnotes.get_or("Impuesto causado", col=col_acum_n, default=0.0) * factor
            inf.deferred_tax_quarter= idxnotes.get_or("Impuesto diferido", col=1, default=0.0) * factor
            inf.deferred_tax_acum   = idxnotes.get_or("Impuesto diferido", col=col_acum_n, default=0.0) * factor
            # Interest income breakdown
            inf.interest_earned_quarter = idxnotes.get_or("Intereses ganados", col=1, default=0.0) * factor
            inf.interest_earned_acum    = idxnotes.get_or("Intereses ganados", col=col_acum_n, default=0.0) * factor
            # FX gain breakdown (CNBV positivo = utilidad/gain; BB sign opuesto)
            inf.fx_gain_quarter = idxnotes.get_first(
                "Utilidad por fluctuación cambiaria",
                "Utilidad por fluctuacion cambiaria",
                col=1, default=0.0,
            ) * factor
            inf.fx_gain_acum = idxnotes.get_first(
                "Utilidad por fluctuación cambiaria",
                "Utilidad por fluctuacion cambiaria",
                col=col_acum_n, default=0.0,
            ) * factor

        # 800005 - Distribucion de ingresos por geografia (acumulado)
        # Layout: filas con paises, col 2 = Ingresos nacionales, col 3 = Exportacion, col 4 = Subsidiarias
        idxgeo = self._idx(SHEET_NOTES_REVENUE)
        if idxgeo is not None:
            df = idxgeo.df
            sales_local = 0.0
            sales_export = 0.0
            for r in range(df.shape[0]):
                lbl = _safe_str(df.iloc[r, 0]).lower()
                if "méxico" in lbl or "mexico" in lbl:
                    # Mexico = local sales (col 2 o el que tenga valor)
                    for c in range(1, df.shape[1]):
                        v = _safe_num(df.iloc[r, c])
                        if v and v > 0:
                            sales_local += v
                            break
                elif "estados unidos" in lbl or "resto del mundo" in lbl:
                    # Export: tomar el primer valor positivo
                    for c in range(1, df.shape[1]):
                        v = _safe_num(df.iloc[r, c])
                        if v and v > 0:
                            sales_export += v
                            break
            inf.sales_local_acum = sales_local * factor
            inf.sales_export_acum = sales_export * factor

        return inf

    # -----------------------------------------------------------------
    def _extract_series_breakdown(self, idx: SheetIndex) -> dict:
        """Si hay header con nombres de serie, devuelve {serie: shares}."""
        key = _normalize("Numero de acciones en circulacion")
        if key not in idx._index:
            key = _normalize("Número de acciones en circulación")
        if key not in idx._index:
            return {}
        i = idx._index[key]
        # Buscar la fila de header de series (busca arriba "[miembros]" o "Serie")
        header_row = None
        for r in range(max(0, i - 5), i):
            row_txt = " ".join(_safe_str(idx.df.iloc[r, c]) for c in range(idx.df.shape[1]))
            if "serie" in row_txt.lower() or "[miembros]" in row_txt.lower():
                header_row = r
                break
        out = {}
        if header_row is not None:
            for c in range(1, idx.df.shape[1]):
                series = _safe_str(idx.df.iloc[header_row, c])
                val = _safe_num(idx.df.iloc[i, c])
                if val is not None and series:
                    out[series] = val
        return out

    # -----------------------------------------------------------------
    # DCF Inputs
    # -----------------------------------------------------------------
    def _build_dcf(
        self,
        info: CompanyInfo,
        bs: BalanceSheet,
        is_: IncomeStatement,
        cf: CashFlow,
        inf: Informative,
    ) -> DCFInputs:
        m = 1_000_000  # convertir a MDP

        # Preferir datos 12M si disponibles, si no acumulado
        revenue = inf.revenue_12m or is_.revenue
        revenue_prior = inf.revenue_12m_prior
        ebit = inf.ebit_12m or is_.ebit
        da = inf.da_12m

        rev_growth = (revenue / revenue_prior - 1) if revenue_prior else 0.0
        op_margin = ebit / revenue if revenue else 0.0
        invested_capital = bs.invested_capital
        s2c = revenue / invested_capital if invested_capital else 0.0
        coverage = ebit / is_.interest_expense if is_.interest_expense else float("inf")

        return DCFInputs(
            ticker=info.ticker,
            period_end=info.period_end,
            currency=info.currency,
            units="MDP",
            revenue=round(revenue / m, 2),
            revenue_prior=round(revenue_prior / m, 2),
            revenue_growth=round(rev_growth, 4),
            ebit=round(ebit / m, 2),
            operating_margin=round(op_margin, 4),
            da=round(da / m, 2),
            capex_gross=round(cf.capex_gross / m, 2),
            capex_net=round(cf.capex_net / m, 2),
            interest_expense=round(is_.interest_expense / m, 2),
            pretax_income=round(is_.pretax_income / m, 2),
            tax_expense=round(is_.tax_expense / m, 2),
            effective_tax_rate=round(is_.effective_tax_rate, 4),
            marginal_tax_rate=0.30,
            net_income=round(is_.net_income / m, 2),
            cash=round(bs.cash / m, 2),
            financial_debt=round(bs.total_financial_debt / m, 2),
            lease_debt=round(bs.total_lease_debt / m, 2),
            total_debt=round(bs.total_debt_with_leases / m, 2),
            equity_bv=round(bs.equity_controlling / m, 2),
            minority_interest=round(bs.minority_interest / m, 2),
            non_operating_assets=round(bs.investments_in_associates / m, 2),
            total_assets=round(bs.total_assets / m, 2),
            invested_capital=round(invested_capital / m, 2),
            shares_outstanding=inf.shares_outstanding,
            sales_to_capital=round(s2c, 4),
            interest_coverage=round(coverage, 2) if coverage != float("inf") else 999.0,
        )

    # -----------------------------------------------------------------
    def parse(self) -> ParseResult:
        info = self._parse_info()
        factor = self._rounding_factor(info)
        bs = self._parse_balance(factor)
        is_ = self._parse_income(factor)
        is_q = self._parse_income_quarter(factor)
        cf = self._parse_cashflow(factor)
        inf = self._parse_informative(factor)
        dcf = self._build_dcf(info, bs, is_, cf, inf)
        validation = merge_reports(validate_balance(bs), validate_income(is_))
        return ParseResult(
            info=info,
            balance=bs,
            income=is_,
            income_quarter=is_q,
            cashflow=cf,
            informative=inf,
            dcf=dcf,
            validation=validation,
            raw_sheets=self.sheets,
        )


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------

def parse_xbrl(filepath: str | Path) -> ParseResult:
    """Parsea un XBRL CNBV y devuelve un ParseResult tipado."""
    return XBRLReader(filepath).parse()
