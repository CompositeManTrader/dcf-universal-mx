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
        # Disposal of Assets (CNBV: positivo=loss, negativo=gain)
        # Para Bloomberg "Disposal of Assets" (positivo = ganancia abnormal)
        # invertimos el signo abajo en el reclassifier
        cf.disposal_loss_gain = g(
            "+ (-) Pérdida (utilidad) por la disposición de activos no circulantes",
            "+ (-) Pérdida (utilidad) por la disposicion de activos no circulantes",
            "Pérdida (utilidad) por la disposición de activos no circulantes",
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
