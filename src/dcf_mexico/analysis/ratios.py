"""
Modulo de ratios financieros completo (~70 ratios) con explicaciones.

Categorias:
1. Profitability Margins (margenes de rentabilidad)
2. Returns (ROA, ROE, ROIC, ROCE)
3. DuPont Decomposition
4. Liquidity (corriente, acida, efectivo)
5. Leverage / Solvency (apalancamiento)
6. Efficiency / Activity (rotaciones)
7. Cash Flow Quality (calidad de flujo)
8. Per-Share Metrics
9. Valuation Multiples (requiere market price)
10. Growth (YoY)

Uso:
    from src.dcf_mexico.analysis import compute_all_ratios
    ratios = compute_all_ratios(series, fx_mult=1.0, market_price=None)
    for r in ratios:
        print(f"{r.category}: {r.name} = {r.value} ({r.unit})")
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List


# ============================================================================
# Tipos de datos
# ============================================================================

@dataclass
class RatioInfo:
    """Info completa de un ratio individual."""
    name: str               # Nombre display
    value: float            # Valor numerico (None si no calculable)
    formula: str            # Formula textual ej. "Net Income / Revenue"
    description: str        # Que mide (1-2 frases)
    interpretation: str     # Que significan los valores buenos/malos
    unit: str               # "%", "x", "days", "MDP", "pesos"
    category: str           # Categoria para agrupar


# ============================================================================
# Helpers
# ============================================================================

def _safe_div(num: float, den: float) -> float:
    """Division segura: retorna 0 si denom es 0."""
    try:
        if den is None or den == 0 or num is None:
            return 0.0
        return num / den
    except (ZeroDivisionError, TypeError):
        return 0.0


def _avg(curr: float, prev: float) -> float:
    """Promedio de balance al inicio y fin del periodo."""
    if prev is None or prev == 0:
        return curr
    if curr is None or curr == 0:
        return prev
    return (curr + prev) / 2.0


# ============================================================================
# CATEGORIA 1: PROFITABILITY MARGINS
# ============================================================================

def _profitability_margins(snap, ttm) -> List[RatioInfo]:
    """Margenes de rentabilidad usando TTM (12 meses) cuando aplica."""
    inc = snap.parsed.income
    cf = snap.parsed.cashflow
    inf = snap.parsed.informative

    rev = inc.revenue or 0
    rev_ttm = inf.revenue_12m or rev
    ebit_ttm = inf.ebit_12m or inc.ebit or 0
    da_ttm = inf.da_12m or 0
    ebitda_ttm = ebit_ttm + da_ttm

    out = []

    out.append(RatioInfo(
        name="Gross Margin",
        value=_safe_div(inc.gross_profit, rev) * 100,
        formula="Gross Profit / Revenue",
        description="Mide la rentabilidad despues de costo directo (COGS). "
                    "Refleja poder de pricing y eficiencia productiva.",
        interpretation="Sectores premium (lujo, software): >50%. "
                       "Bebidas premium (CUERVO): 50-60%. Retail: 20-30%. "
                       "Commodities: <20%.",
        unit="%", category="Profitability Margins"
    ))

    out.append(RatioInfo(
        name="Operating Margin (EBIT Margin)",
        value=_safe_div(ebit_ttm, rev_ttm) * 100,
        formula="EBIT TTM / Revenue TTM",
        description="Rentabilidad operativa despues de gastos de venta y administracion. "
                    "Mide eficiencia operativa antes de financiamiento e impuestos.",
        interpretation="Excelente: >20%. Bueno: 10-20%. Promedio mexicano: 8-15%. "
                       "Bajo: <5% indica presion competitiva o problemas operativos.",
        unit="%", category="Profitability Margins"
    ))

    out.append(RatioInfo(
        name="EBITDA Margin (TTM)",
        value=_safe_div(ebitda_ttm, rev_ttm) * 100,
        formula="(EBIT + D&A) TTM / Revenue TTM",
        description="Margen operativo PRE-depreciacion. Proxy de generacion de caja "
                    "operativa. Util para comparar empresas con distinta intensidad "
                    "de capital.",
        interpretation="Bebidas/Tequila: 20-30%. Retail: 8-12%. Software: 30-50%. "
                       "Telecom: 30-40%. Bancos: no aplica.",
        unit="%", category="Profitability Margins"
    ))

    out.append(RatioInfo(
        name="Pretax Margin",
        value=_safe_div(inc.pretax_income, rev) * 100,
        formula="Pretax Income / Revenue",
        description="Rentabilidad antes de impuestos, ya incluye costos financieros. "
                    "Mide la capacidad de generar utilidad antes del fisco.",
        interpretation="Refleja impacto de apalancamiento financiero. "
                       "Diferencia vs Operating Margin = costo neto financiero.",
        unit="%", category="Profitability Margins"
    ))

    out.append(RatioInfo(
        name="Net Margin",
        value=_safe_div(inc.net_income, rev) * 100,
        formula="Net Income / Revenue",
        description="Margen neto despues de TODO (operacion, finanzas, impuestos, "
                    "minoritarios). Es el peso final que llega al accionista.",
        interpretation="Excelente: >15%. Bueno: 10-15%. Promedio: 5-10%. "
                       "Bajo: <5% requiere alta rotacion para compensar.",
        unit="%", category="Profitability Margins"
    ))

    out.append(RatioInfo(
        name="Net Margin (Controlling)",
        value=_safe_div(inc.net_income_controlling, rev) * 100,
        formula="Net Income Controlling / Revenue",
        description="Margen neto EXCLUYENDO la porcion atribuible a minoritarios. "
                    "Es el margen 'real' del accionista de la controladora.",
        interpretation="Diferencia vs Net Margin total = peso de minoritarios. "
                       "Importante para grupos con subsidiarias parcialmente publicas.",
        unit="%", category="Profitability Margins"
    ))

    fcf = (cf.cfo or 0) - (cf.capex_ppe or 0)
    out.append(RatioInfo(
        name="FCF Margin",
        value=_safe_div(fcf, rev) * 100,
        formula="Free Cash Flow / Revenue",
        description="Que porcentaje de las ventas se convierte en cash libre real. "
                    "Mas robusto que Net Margin pues elimina contabilidad devengada.",
        interpretation="Excelente: >15%. Bueno: 10-15%. La diferencia FCF Margin vs "
                       "Net Margin revela calidad de la utilidad reportada.",
        unit="%", category="Profitability Margins"
    ))

    return out


# ============================================================================
# CATEGORIA 2: RETURNS (ROA, ROE, ROIC, ROCE)
# ============================================================================

def _returns(snap, prev_snap, ttm) -> List[RatioInfo]:
    """Returns sobre activos, capital propio, capital invertido."""
    inc = snap.parsed.income
    bs = snap.parsed.balance
    inf = snap.parsed.informative

    rev_ttm = inf.revenue_12m or inc.revenue or 0
    ebit_ttm = inf.ebit_12m or inc.ebit or 0
    ni = inc.net_income_controlling or inc.net_income or 0
    tax_rate = inc.effective_tax_rate or 0.30

    # Promedios usando snapshot anterior si disponible
    if prev_snap:
        prev_bs = prev_snap.parsed.balance
        avg_assets = _avg(bs.total_assets, prev_bs.total_assets)
        avg_equity = _avg(bs.equity_controlling, prev_bs.equity_controlling)
        avg_invested = _avg(bs.invested_capital, prev_bs.invested_capital)
        avg_capital_employed = _avg(
            bs.total_assets - bs.total_current_liabilities,
            prev_bs.total_assets - prev_bs.total_current_liabilities,
        )
    else:
        avg_assets = bs.total_assets
        avg_equity = bs.equity_controlling
        avg_invested = bs.invested_capital
        avg_capital_employed = bs.total_assets - bs.total_current_liabilities

    out = []

    out.append(RatioInfo(
        name="ROA (Return on Assets)",
        value=_safe_div(ni, avg_assets) * 100,
        formula="Net Income / Avg Total Assets",
        description="Cuanto genera la empresa en utilidad por cada peso de activos. "
                    "Mide eficiencia GLOBAL del uso de activos sin distinguir "
                    "fuente de financiamiento.",
        interpretation="Excelente: >10%. Bueno: 5-10%. Bajo: <3%. "
                       "Sectores intensivos en capital tienen ROA naturalmente bajos.",
        unit="%", category="Returns"
    ))

    out.append(RatioInfo(
        name="ROE (Return on Equity)",
        value=_safe_div(ni, avg_equity) * 100,
        formula="Net Income / Avg Equity (controlling)",
        description="Rendimiento sobre capital DEL ACCIONISTA. Es el ratio mas "
                    "importante para inversionistas. Refleja que tan bien la empresa "
                    "usa el capital propio.",
        interpretation="Excelente: >20%. Bueno: 15-20%. Promedio: 10-15%. "
                       "Pobre: <10%. Cuidado con ROE alto por excesivo apalancamiento.",
        unit="%", category="Returns"
    ))

    nopat = ebit_ttm * (1 - tax_rate)
    out.append(RatioInfo(
        name="ROIC (Return on Invested Capital)",
        value=_safe_div(nopat, avg_invested) * 100,
        formula="EBIT(1-t) / (Equity + Net Debt)",
        description="Rendimiento sobre el CAPITAL TOTAL invertido en el negocio "
                    "(equity + deuda neta). Es la metrica favorita de Damodaran y "
                    "Buffett porque mide el rendimiento del negocio independiente "
                    "de su estructura de capital.",
        interpretation="Excelente: >15%. Bueno: 10-15%. Sobre WACC = crea valor. "
                       "Bajo WACC = destruye valor. Es la metrica clave para DCF.",
        unit="%", category="Returns"
    ))

    out.append(RatioInfo(
        name="ROCE (Return on Capital Employed)",
        value=_safe_div(ebit_ttm, avg_capital_employed) * 100,
        formula="EBIT / (Total Assets - Current Liabilities)",
        description="Variante de ROIC usando EBIT pre-tax. Mide rendimiento "
                    "operativo sobre el capital de largo plazo (activos menos "
                    "pasivos circulantes que son financiamiento operativo gratuito).",
        interpretation="Excelente: >20%. Bueno: 15-20%. Refleja eficiencia "
                       "operativa pura. Ratio favorito de fondos value europeos.",
        unit="%", category="Returns"
    ))

    out.append(RatioInfo(
        name="Asset Turnover",
        value=_safe_div(rev_ttm, avg_assets),
        formula="Revenue TTM / Avg Total Assets",
        description="Cuantos pesos de venta genera cada peso de activos. "
                    "Mide la PRODUCTIVIDAD de los activos.",
        interpretation="Retail (Walmart): >2.0x. Manufactura: 1.0-1.5x. "
                       "Bebidas premium: 0.5-0.8x. Utilities: 0.3-0.5x.",
        unit="x", category="Returns"
    ))

    out.append(RatioInfo(
        name="Equity Multiplier (Financial Leverage)",
        value=_safe_div(avg_assets, avg_equity),
        formula="Avg Total Assets / Avg Equity",
        description="Cuantas veces el capital propio se multiplica via deuda. "
                    "Es la 3a pata del DuPont. Mide el apalancamiento financiero.",
        interpretation="Conservador: <2x. Normal: 2-3x. Apalancado: 3-5x. "
                       "Riesgoso: >5x. Bancos suelen estar 8-12x.",
        unit="x", category="Returns"
    ))

    return out


# ============================================================================
# CATEGORIA 3: DUPONT DECOMPOSITION
# ============================================================================

def _dupont(snap, prev_snap) -> List[RatioInfo]:
    """DuPont 3-step y 5-step decomposition de ROE."""
    inc = snap.parsed.income
    bs = snap.parsed.balance

    ni = inc.net_income_controlling or inc.net_income or 0
    rev = inc.revenue or 0
    ebit = inc.ebit or 0
    pretax = inc.pretax_income or 0

    if prev_snap:
        prev_bs = prev_snap.parsed.balance
        avg_assets = _avg(bs.total_assets, prev_bs.total_assets)
        avg_equity = _avg(bs.equity_controlling, prev_bs.equity_controlling)
    else:
        avg_assets = bs.total_assets
        avg_equity = bs.equity_controlling

    out = []

    # 3-step DuPont
    npm = _safe_div(ni, rev)            # Net Profit Margin
    ato = _safe_div(rev, avg_assets)    # Asset Turnover
    em = _safe_div(avg_assets, avg_equity)  # Equity Multiplier
    roe_3step = npm * ato * em

    out.append(RatioInfo(
        name="DuPont 3-Step: Net Margin",
        value=npm * 100,
        formula="Net Income / Revenue",
        description="PRIMERA componente del DuPont. Mide la eficiencia de "
                    "convertir ventas en utilidad neta.",
        interpretation="Calidad operativa + financiera. Diferencias intra-industria "
                       "muestran ventaja competitiva (moats).",
        unit="%", category="DuPont Decomposition"
    ))

    out.append(RatioInfo(
        name="DuPont 3-Step: Asset Turnover",
        value=ato,
        formula="Revenue / Avg Assets",
        description="SEGUNDA componente del DuPont. Productividad de activos. "
                    "Cuantas veces la empresa 'roto' sus activos al año en ventas.",
        interpretation="Trade-off con margen: alto turnover = bajo margen y "
                       "viceversa. Modelo Walmart vs Apple.",
        unit="x", category="DuPont Decomposition"
    ))

    out.append(RatioInfo(
        name="DuPont 3-Step: Equity Multiplier",
        value=em,
        formula="Avg Assets / Avg Equity",
        description="TERCERA componente del DuPont. Apalancamiento financiero. "
                    "Cuanto del balance se financia con deuda vs equity.",
        interpretation="Multiplica el ROE pero tambien el riesgo. Empresas con "
                       "EM > 4x requieren analizar coverage ratios.",
        unit="x", category="DuPont Decomposition"
    ))

    out.append(RatioInfo(
        name="ROE (DuPont 3-Step Reconstruction)",
        value=roe_3step * 100,
        formula="Net Margin × Asset Turnover × Equity Multiplier",
        description="ROE descompuesto. Permite identificar la PALANCA principal "
                    "de rentabilidad (margen, eficiencia operativa, o apalancamiento).",
        interpretation="Si difiere de ROE directo significa diferencias en "
                       "denominadores (snapshot vs avg).",
        unit="%", category="DuPont Decomposition"
    ))

    # 5-step DuPont (mas detallado)
    tax_burden = _safe_div(ni, pretax) if pretax > 0 else 0  # tax burden
    int_burden = _safe_div(pretax, ebit) if ebit > 0 else 0  # interest burden
    op_margin = _safe_div(ebit, rev)
    roe_5step = tax_burden * int_burden * op_margin * ato * em

    out.append(RatioInfo(
        name="DuPont 5-Step: Tax Burden",
        value=tax_burden,
        formula="Net Income / Pretax Income",
        description="Que porcentaje de la utilidad pretax SOBREVIVE despues de "
                    "impuestos. = 1 - tasa efectiva de impuestos.",
        interpretation="Ideal: >0.70 (tax rate <30%). Mexico estatutaria: 0.70 (30% ISR). "
                       "Empresas con creditos fiscales: >0.75.",
        unit="x", category="DuPont Decomposition"
    ))

    out.append(RatioInfo(
        name="DuPont 5-Step: Interest Burden",
        value=int_burden,
        formula="Pretax Income / EBIT",
        description="Que tanto de la utilidad operativa SOBREVIVE despues de gastos "
                    "financieros netos. Mide impacto del apalancamiento.",
        interpretation="Sin deuda: 1.0. Con deuda moderada: 0.85-0.95. "
                       "Empresa muy apalancada: <0.70 indica alta carga financiera.",
        unit="x", category="DuPont Decomposition"
    ))

    out.append(RatioInfo(
        name="DuPont 5-Step: Operating Margin",
        value=op_margin * 100,
        formula="EBIT / Revenue",
        description="Margen operativo puro (sin impacto de impuestos ni intereses).",
        interpretation="Mide eficiencia del CORE business. Aislado de financiamiento.",
        unit="%", category="DuPont Decomposition"
    ))

    out.append(RatioInfo(
        name="ROE (DuPont 5-Step Reconstruction)",
        value=roe_5step * 100,
        formula="Tax Burden × Int Burden × Op Margin × Asset Turn × Equity Mult",
        description="DuPont expandido a 5 palancas. Permite analisis FORENSE del "
                    "ROE: separa factores operativos (op margin, ato) de "
                    "financieros (int burden, em) y fiscales (tax burden).",
        interpretation="Es el framework analitico estandar de bancas de "
                       "inversion para entender FUENTES de ROE.",
        unit="%", category="DuPont Decomposition"
    ))

    return out


# ============================================================================
# CATEGORIA 4: LIQUIDITY RATIOS
# ============================================================================

def _liquidity(snap) -> List[RatioInfo]:
    """Ratios de liquidez de corto plazo."""
    bs = snap.parsed.balance

    cl = bs.total_current_liabilities or 0
    ca = bs.total_current_assets or 0
    inv = bs.inventories or 0
    cash = bs.cash or 0
    ar = bs.accounts_receivable or 0

    out = []

    out.append(RatioInfo(
        name="Current Ratio",
        value=_safe_div(ca, cl),
        formula="Total Current Assets / Total Current Liabilities",
        description="Capacidad de pagar pasivos circulantes con activos circulantes. "
                    "Es la metrica de liquidez mas basica.",
        interpretation="Saludable: 1.5-3.0x. Excesivo (>3x): activos ociosos. "
                       "Bajo (<1x): riesgo de iliquidez. Optimo varia por industria.",
        unit="x", category="Liquidity"
    ))

    out.append(RatioInfo(
        name="Quick Ratio (Acid Test)",
        value=_safe_div(ca - inv, cl),
        formula="(CA - Inventories) / CL",
        description="Variante mas estricta del Current Ratio: excluye inventarios "
                    "(menos liquidos). Util para empresas con inventarios pesados.",
        interpretation="Saludable: >1.0x. Si Quick < 1 pero Current > 1.5, la "
                       "liquidez depende del turn de inventarios.",
        unit="x", category="Liquidity"
    ))

    out.append(RatioInfo(
        name="Cash Ratio",
        value=_safe_div(cash, cl),
        formula="Cash / Total Current Liabilities",
        description="Liquidez ULTRA-conservadora: solo cash y equivalentes. "
                    "Mide capacidad de pago inmediato sin depender de cobranza ni venta.",
        interpretation="Excelente: >0.5x. Saludable: 0.2-0.5x. Bajo: <0.1x "
                       "indica dependencia operativa para pagar deudas.",
        unit="x", category="Liquidity"
    ))

    wc = ca - cl
    out.append(RatioInfo(
        name="Working Capital",
        value=wc / 1_000_000,    # raw pesos -> MDP
        formula="Current Assets - Current Liabilities",
        description="Capital de trabajo en valor absoluto (MDP). Recursos "
                    "disponibles para operacion despues de cubrir compromisos CP.",
        interpretation="Positivo = colchon. Negativo = deficit de capital de trabajo "
                       "(comun en retail con financiamiento de proveedores).",
        unit="MDP", category="Liquidity"
    ))

    out.append(RatioInfo(
        name="Working Capital / Revenue",
        value=_safe_div(wc, snap.parsed.income.revenue) * 100,
        formula="Working Capital / Revenue",
        description="Capital de trabajo como % de ventas. Mide cuanto capital de "
                    "trabajo necesita la empresa por peso de ventas.",
        interpretation="Bajo es mejor (eficiencia capital). Negativo en retail "
                       "es saludable (proveedores financian operacion).",
        unit="%", category="Liquidity"
    ))

    return out


# ============================================================================
# CATEGORIA 5: LEVERAGE / SOLVENCY
# ============================================================================

def _leverage(snap, ttm) -> List[RatioInfo]:
    """Ratios de apalancamiento y solvencia."""
    bs = snap.parsed.balance
    inc = snap.parsed.income
    inf = snap.parsed.informative

    debt = bs.total_debt_with_leases
    equity = bs.equity_controlling or 1e-9
    assets = bs.total_assets or 1e-9
    cash = bs.cash or 0
    net_debt = debt - cash

    ebit_ttm = inf.ebit_12m or inc.ebit or 0
    da_ttm = inf.da_12m or 0
    ebitda_ttm = ebit_ttm + da_ttm
    int_exp = abs(inc.interest_expense or 0)

    out = []

    out.append(RatioInfo(
        name="Debt / Equity",
        value=_safe_div(debt, equity),
        formula="Total Debt (incl leases) / Equity",
        description="Cuantos pesos de deuda por cada peso de equity. "
                    "El indicador mas clasico de apalancamiento.",
        interpretation="Conservador: <0.5x. Moderado: 0.5-1.5x. Apalancado: 1.5-3x. "
                       "Riesgoso: >3x (excepto bancos/utilities).",
        unit="x", category="Leverage"
    ))

    out.append(RatioInfo(
        name="Debt / Assets",
        value=_safe_div(debt, assets) * 100,
        formula="Total Debt / Total Assets",
        description="Que porcentaje del balance se financia con deuda. Equivalente "
                    "a Debt-to-Capitalization ajustado.",
        interpretation="Conservador: <30%. Normal: 30-50%. Alto: >50% requiere "
                       "scrutiny de coverage.",
        unit="%", category="Leverage"
    ))

    out.append(RatioInfo(
        name="Net Debt / EBITDA",
        value=_safe_div(net_debt, ebitda_ttm),
        formula="(Total Debt - Cash) / EBITDA TTM",
        description="Cuantos años de EBITDA tomaria pagar TODA la deuda neta. "
                    "Es EL ratio favorito de bancos para credit rating.",
        interpretation="Investment grade: <2.5x. High Yield: 2.5-4x. "
                       "Distressed: >5x. Tequila/bebidas suelen estar <2x.",
        unit="x", category="Leverage"
    ))

    out.append(RatioInfo(
        name="Total Debt / EBITDA",
        value=_safe_div(debt, ebitda_ttm),
        formula="Total Debt (incl leases) / EBITDA TTM",
        description="Variante de Net Debt/EBITDA pero sin restar cash. Mas estricto.",
        interpretation="Bancos suelen exigir <3-4x para nuevos creditos.",
        unit="x", category="Leverage"
    ))

    out.append(RatioInfo(
        name="Equity Ratio",
        value=_safe_div(equity, assets) * 100,
        formula="Equity / Total Assets",
        description="Que porcentaje del balance pertenece al accionista. Inverso "
                    "del leverage. Solidez patrimonial.",
        interpretation="Robusto: >50%. Normal: 30-50%. Apalancado: <30%.",
        unit="%", category="Leverage"
    ))

    out.append(RatioInfo(
        name="Interest Coverage (EBIT)",
        value=_safe_div(inc.ebit, int_exp),
        formula="EBIT / Interest Expense",
        description="Cuantas veces la utilidad operativa cubre los intereses. "
                    "Es el ratio mas usado por bancos para evaluar capacidad de pago.",
        interpretation="Investment grade: >5x. Cubre comodamente: 3-5x. "
                       "Justo: 1.5-3x. Stress: <1.5x.",
        unit="x", category="Leverage"
    ))

    out.append(RatioInfo(
        name="EBITDA Coverage",
        value=_safe_div(ebitda_ttm, int_exp),
        formula="EBITDA / Interest Expense",
        description="Variante de Interest Coverage usando EBITDA (proxy de cash). "
                    "Mas relevante para empresas intensivas en capital.",
        interpretation="Saludable: >5x. Investment grade tipicamente exige >7x.",
        unit="x", category="Leverage"
    ))

    out.append(RatioInfo(
        name="Capitalization Ratio",
        value=_safe_div(debt, debt + equity) * 100,
        formula="Debt / (Debt + Equity)",
        description="Peso de la deuda en la estructura de capital total. "
                    "Util para calcular WACC.",
        interpretation="Conservador: <30%. Optimo Damodaran: ~30-40%. "
                       "Apalancado: >50%.",
        unit="%", category="Leverage"
    ))

    return out


# ============================================================================
# CATEGORIA 6: EFFICIENCY / ACTIVITY (TURNOVERS)
# ============================================================================

def _efficiency(snap, prev_snap, ttm) -> List[RatioInfo]:
    """Ratios de rotacion (turnovers) y dias."""
    inc = snap.parsed.income
    bs = snap.parsed.balance
    inf = snap.parsed.informative

    rev_ttm = inf.revenue_12m or inc.revenue or 0
    cogs = inc.cost_of_sales or 0
    # COGS LTM aproximado: si ya estamos en Q4/4D, cogs YTD = LTM
    if snap.quarter in ("4", "4D"):
        cogs_ttm = cogs
    else:
        # Aproximacion simple
        mult = {"1": 4.0, "2": 2.0, "3": 4/3}.get(snap.quarter, 1.0)
        cogs_ttm = cogs * mult

    if prev_snap:
        prev_bs = prev_snap.parsed.balance
        avg_inv = _avg(bs.inventories, prev_bs.inventories)
        avg_ar = _avg(bs.accounts_receivable, prev_bs.accounts_receivable)
        avg_ap = _avg(bs.accounts_payable, prev_bs.accounts_payable)
        avg_assets = _avg(bs.total_assets, prev_bs.total_assets)
        avg_ppe = _avg(bs.ppe, prev_bs.ppe)
        avg_wc = _avg(bs.working_capital, prev_bs.working_capital)
    else:
        avg_inv = bs.inventories
        avg_ar = bs.accounts_receivable
        avg_ap = bs.accounts_payable
        avg_assets = bs.total_assets
        avg_ppe = bs.ppe
        avg_wc = bs.working_capital

    out = []

    inv_turn = _safe_div(cogs_ttm, avg_inv)
    out.append(RatioInfo(
        name="Inventory Turnover",
        value=inv_turn,
        formula="COGS TTM / Avg Inventory",
        description="Cuantas veces al año roto el inventario. Mide eficiencia "
                    "en gestion de inventarios.",
        interpretation="Retail rapido (Walmart): >10x. Manufactura: 4-8x. "
                       "Bebidas premium: 3-6x. Joyeria/lujo: <2x.",
        unit="x", category="Efficiency"
    ))

    out.append(RatioInfo(
        name="Days Inventory Outstanding (DIO)",
        value=_safe_div(365, inv_turn) if inv_turn else 0,
        formula="365 / Inventory Turnover",
        description="Dias promedio que el inventario permanece en almacen antes "
                    "de venderse.",
        interpretation="Retail rapido: <30 dias. Manufactura: 60-90 dias. "
                       "Tequila (envejecimiento): 100-180 dias justificable.",
        unit="days", category="Efficiency"
    ))

    ar_turn = _safe_div(rev_ttm, avg_ar)
    out.append(RatioInfo(
        name="Receivables Turnover",
        value=ar_turn,
        formula="Revenue TTM / Avg Accounts Receivable",
        description="Cuantas veces al año cobramos las cuentas por cobrar. "
                    "Mide velocidad de cobranza.",
        interpretation="Saludable: >6x. Indica disciplina credit-collections.",
        unit="x", category="Efficiency"
    ))

    out.append(RatioInfo(
        name="Days Sales Outstanding (DSO)",
        value=_safe_div(365, ar_turn) if ar_turn else 0,
        formula="365 / Receivables Turnover",
        description="Dias promedio para cobrar a clientes despues de venta. "
                    "Tambien llamado 'periodo medio de cobro'.",
        interpretation="Retail B2C (cash): <10 dias. B2B: 30-60 dias. "
                       "Crece DSO = problemas de cobranza o cambio de mix de clientes.",
        unit="days", category="Efficiency"
    ))

    ap_turn = _safe_div(cogs_ttm, avg_ap)
    out.append(RatioInfo(
        name="Payables Turnover",
        value=ap_turn,
        formula="COGS TTM / Avg Accounts Payable",
        description="Cuantas veces al año pagamos a proveedores. Inverso del DPO.",
        interpretation="Bajo es bueno para cash conversion (financiamos operacion "
                       "con proveedores). Pero muy bajo podria erosionar relaciones.",
        unit="x", category="Efficiency"
    ))

    dpo = _safe_div(365, ap_turn) if ap_turn else 0
    out.append(RatioInfo(
        name="Days Payable Outstanding (DPO)",
        value=dpo,
        formula="365 / Payables Turnover",
        description="Dias promedio que tomamos para pagar a proveedores. "
                    "Mas alto = mejor (financiamiento gratuito).",
        interpretation="Retail rapido: 30-45 dias. Promedio: 45-60. Walmart >90. "
                       "Si DPO > DIO+DSO, el ciclo de caja es NEGATIVO (Amazon).",
        unit="days", category="Efficiency"
    ))

    dio = _safe_div(365, inv_turn) if inv_turn else 0
    dso = _safe_div(365, ar_turn) if ar_turn else 0
    ccc = dio + dso - dpo
    out.append(RatioInfo(
        name="Cash Conversion Cycle (CCC)",
        value=ccc,
        formula="DIO + DSO - DPO",
        description="Dias entre que pagamos a proveedores y cobramos al cliente. "
                    "Es la METRICA REINA de eficiencia de capital de trabajo.",
        interpretation="Negativo (Amazon, Walmart): proveedores financian. "
                       "0-30 dias: muy eficiente. 30-90: normal. >90: capital "
                       "atrapado en operacion.",
        unit="days", category="Efficiency"
    ))

    out.append(RatioInfo(
        name="Total Asset Turnover",
        value=_safe_div(rev_ttm, avg_assets),
        formula="Revenue TTM / Avg Total Assets",
        description="Productividad GLOBAL de los activos. Cuantos pesos de venta "
                    "generamos por peso de activos invertidos.",
        interpretation="Retail: >2.0x. Industria: 0.7-1.5x. Utilities/REITs: <0.3x. "
                       "Aerolineas: 0.7-1.0x.",
        unit="x", category="Efficiency"
    ))

    out.append(RatioInfo(
        name="Fixed Asset Turnover",
        value=_safe_div(rev_ttm, avg_ppe),
        formula="Revenue TTM / Avg PPE",
        description="Productividad de la INVERSION en activos fijos productivos "
                    "(planta, equipo). Aisla del efecto de WC.",
        interpretation="Refleja eficiencia industrial. Comparar contra peers "
                       "es mas util que valor absoluto.",
        unit="x", category="Efficiency"
    ))

    out.append(RatioInfo(
        name="Working Capital Turnover",
        value=_safe_div(rev_ttm, avg_wc) if avg_wc > 0 else 0,
        formula="Revenue TTM / Avg Working Capital",
        description="Cuantas veces el WC se 'usa' en generar ventas al año. "
                    "Mide eficiencia del capital operativo.",
        interpretation="Mas alto = mejor (menos WC necesario). Empresas con WC "
                       "negativo (no calculable aqui) son super eficientes.",
        unit="x", category="Efficiency"
    ))

    return out


# ============================================================================
# CATEGORIA 7: CASH FLOW QUALITY
# ============================================================================

def _cash_flow_quality(snap) -> List[RatioInfo]:
    """Calidad del flujo de efectivo y conversion."""
    inc = snap.parsed.income
    cf = snap.parsed.cashflow
    bs = snap.parsed.balance
    inf = snap.parsed.informative

    cfo = cf.cfo or 0
    capex = cf.capex_ppe or 0
    capex_total = capex + (cf.capex_intangibles or 0)
    fcf = cfo - capex
    rev = inc.revenue or 0
    ni = inc.net_income or 0
    da = inf.da_12m or 0
    ebit_ttm = inf.ebit_12m or inc.ebit or 0
    ebitda_ttm = ebit_ttm + da
    debt = bs.total_debt_with_leases

    out = []

    out.append(RatioInfo(
        name="CFO / Net Income (Quality of Earnings)",
        value=_safe_div(cfo, ni),
        formula="Cash from Operations / Net Income",
        description="Mide la CALIDAD de la utilidad reportada. Si CFO > NI, "
                    "la utilidad esta respaldada por flujo real. Si CFO << NI, "
                    "RED FLAG (utilidad solo contable, no efectivo).",
        interpretation="Saludable: >1.0x. Bueno: 1.0-1.5x. Excelente: >1.5x. "
                       "RED FLAG: <0.5x (Enron, WorldCom tenian este patron).",
        unit="x", category="Cash Flow Quality"
    ))

    out.append(RatioInfo(
        name="CFO Margin",
        value=_safe_div(cfo, rev) * 100,
        formula="CFO / Revenue",
        description="Que porcentaje de las ventas se convierte en cash operativo. "
                    "Mas estable que Net Margin pues elimina contabilidad devengada.",
        interpretation="Excelente: >15%. Bueno: 10-15%. Promedio: 5-10%.",
        unit="%", category="Cash Flow Quality"
    ))

    out.append(RatioInfo(
        name="FCF Margin",
        value=_safe_div(fcf, rev) * 100,
        formula="(CFO - CapEx) / Revenue",
        description="Margen de cash libre real (despues de inversion de mantencion). "
                    "Es lo que queda DISPONIBLE para accionistas/deuda.",
        interpretation="Excelente: >10%. Bueno: 5-10%. Bajo: <3%.",
        unit="%", category="Cash Flow Quality"
    ))

    out.append(RatioInfo(
        name="FCF Conversion (FCF/EBITDA)",
        value=_safe_div(fcf, ebitda_ttm) * 100,
        formula="FCF / EBITDA TTM",
        description="Que porcentaje del EBITDA se convierte en cash libre real. "
                    "Mide la 'eficiencia de cash' del negocio.",
        interpretation="Excelente: >70%. Bueno: 50-70%. Pobre: <30%. Empresas "
                       "intensivas en capital tienen FCF Conversion bajo.",
        unit="%", category="Cash Flow Quality"
    ))

    out.append(RatioInfo(
        name="CapEx / Sales",
        value=_safe_div(capex_total, rev) * 100,
        formula="CapEx (PPE + Intangibles) / Revenue",
        description="Intensidad de inversion. Cuanto reinvierte la empresa de "
                    "cada peso vendido.",
        interpretation="Bajo (<3%): cash machine (Coca-Cola). Medio (3-7%): "
                       "industrias normales. Alto (>10%): expansion agresiva o "
                       "negocio de capital intensivo (telecom, utilities).",
        unit="%", category="Cash Flow Quality"
    ))

    out.append(RatioInfo(
        name="CapEx / D&A (Maintenance vs Growth)",
        value=_safe_div(capex_total, da),
        formula="CapEx / Depreciation & Amortization",
        description="Si <1: la empresa esta 'cosechando' (descapitalizandose). "
                    "Si =1: solo mantenimiento. Si >1: invierte para crecer.",
        interpretation="<0.7: descapitalizacion preocupante. 0.7-1.2: estable. "
                       ">1.5: expansion. Buffett prefiere ~1.0-1.3 (crecimiento "
                       "moderado, alta cash generation).",
        unit="x", category="Cash Flow Quality"
    ))

    out.append(RatioInfo(
        name="CFO / Total Debt",
        value=_safe_div(cfo, debt) * 100,
        formula="CFO / Total Debt",
        description="Capacidad de generar cash anual relativo a la deuda total. "
                    "Mide en cuantos años la operacion paga toda la deuda.",
        interpretation="Excelente: >40%. Bueno: 20-40%. Stress: <10% (mas de "
                       "10 años para pagar deuda).",
        unit="%", category="Cash Flow Quality"
    ))

    out.append(RatioInfo(
        name="FCF / Total Debt",
        value=_safe_div(fcf, debt) * 100,
        formula="FCF / Total Debt",
        description="Capacidad REAL (post-CapEx) de pagar deuda con cash libre. "
                    "Variante mas conservadora del CFO/Debt.",
        interpretation="Excelente: >25%. Saludable: 15-25%. Justo: 5-15%.",
        unit="%", category="Cash Flow Quality"
    ))

    return out


# ============================================================================
# CATEGORIA 8: PER-SHARE METRICS
# ============================================================================

def _per_share(snap) -> List[RatioInfo]:
    """Metricas por accion (per-share)."""
    inc = snap.parsed.income
    cf = snap.parsed.cashflow
    bs = snap.parsed.balance
    inf = snap.parsed.informative

    shares = inf.shares_outstanding or 0  # en unidades
    shares_m = shares / 1_000_000  # en millones para display

    if shares == 0:
        return []

    ni_ctrl = inc.net_income_controlling or inc.net_income or 0
    cfo = cf.cfo or 0
    fcf = cfo - (cf.capex_ppe or 0)
    div = abs(cf.dividends_paid or 0)
    bv = bs.equity_controlling or 0
    rev = inc.revenue or 0

    out = []

    out.append(RatioInfo(
        name="EPS Basic (TTM)",
        value=ni_ctrl / shares,
        formula="Net Income Controlling / Shares Outstanding",
        description="Utilidad por accion basica. La metrica MAS conocida del mercado. "
                    "Es lo que cada accion 'gano' en el periodo.",
        interpretation="Comparar con EPS prior periods (crecimiento) y con consensus.",
        unit="pesos", category="Per-Share"
    ))

    out.append(RatioInfo(
        name="Book Value Per Share (BVPS)",
        value=bv / shares,
        formula="Equity Controlling / Shares Outstanding",
        description="Valor en libros por accion. Es el patrimonio contable que "
                    "respalda cada accion.",
        interpretation="Comparar contra precio (P/B). BVPS creciente = empresa "
                       "creando valor patrimonial.",
        unit="pesos", category="Per-Share"
    ))

    out.append(RatioInfo(
        name="Cash Flow Per Share (CFPS)",
        value=cfo / shares,
        formula="CFO / Shares Outstanding",
        description="Cash operativo generado por accion. Variante MAS robusta "
                    "del EPS (sin contabilidad devengada).",
        interpretation="Crecimiento de CFPS > EPS sostenido = excelente calidad.",
        unit="pesos", category="Per-Share"
    ))

    out.append(RatioInfo(
        name="Free Cash Flow Per Share (FCFPS)",
        value=fcf / shares,
        formula="(CFO - CapEx PPE) / Shares Outstanding",
        description="FCF disponible por accion. Lo que TEORICAMENTE podria "
                    "regresarse a accionistas.",
        interpretation="Es la base del DCF. FCFPS sostenidamente creciente = "
                       "oro para inversionistas.",
        unit="pesos", category="Per-Share"
    ))

    out.append(RatioInfo(
        name="Dividend Per Share (DPS)",
        value=div / shares,
        formula="Dividends Paid / Shares Outstanding",
        description="Dividendo pagado por accion en el periodo.",
        interpretation="Comparar con FCFPS (sustainability) y con prior periods "
                       "(growth).",
        unit="pesos", category="Per-Share"
    ))

    out.append(RatioInfo(
        name="Sales Per Share",
        value=rev / shares,
        formula="Revenue / Shares Outstanding",
        description="Ventas anuales que respaldan cada accion.",
        interpretation="Util para empresas en perdidas (no aplica P/E). "
                       "Comparar con Price (P/S ratio).",
        unit="pesos", category="Per-Share"
    ))

    out.append(RatioInfo(
        name="Payout Ratio",
        value=_safe_div(div, ni_ctrl) * 100,
        formula="Dividends / Net Income Controlling",
        description="Que porcentaje de la utilidad se reparte como dividendo. "
                    "El resto se REINVIERTE en el negocio.",
        interpretation="Conservador: <30%. Balanceado: 30-60%. Maduro: 60-80%. "
                       ">100% es insostenible (paga con deuda o reservas).",
        unit="%", category="Per-Share"
    ))

    out.append(RatioInfo(
        name="Retention Ratio",
        value=(1 - _safe_div(div, ni_ctrl)) * 100,
        formula="1 - Payout Ratio",
        description="Que porcentaje de la utilidad se REINVIERTE. Junto con ROE "
                    "determina el growth sostenible (g = b × ROE).",
        interpretation="Mas alto = mayor reinversion (mayor crecimiento potencial). "
                       "Empresas en crecimiento retienen >70%.",
        unit="%", category="Per-Share"
    ))

    out.append(RatioInfo(
        name="Sustainable Growth Rate (g = b × ROE)",
        value=(1 - _safe_div(div, ni_ctrl)) * _safe_div(ni_ctrl, bs.equity_controlling) * 100,
        formula="Retention Ratio × ROE",
        description="Tasa de crecimiento que la empresa puede SOSTENER sin "
                    "endeudarse mas (ni emitir acciones). Formula clasica de Gordon.",
        interpretation="Si g real > g sostenible = empresa se apalanca/dilute. "
                       "Si g real < g sostenible = subutiliza capital propio.",
        unit="%", category="Per-Share"
    ))

    return out


# ============================================================================
# CATEGORIA 9: VALUATION MULTIPLES (requiere market_price)
# ============================================================================

def _valuation_multiples(snap, market_price: Optional[float]) -> List[RatioInfo]:
    """Multiplos de valuacion. Requieren precio de mercado."""
    if not market_price or market_price <= 0:
        return []

    inc = snap.parsed.income
    cf = snap.parsed.cashflow
    bs = snap.parsed.balance
    inf = snap.parsed.informative

    shares = inf.shares_outstanding or 1e-9
    ni_ctrl = inc.net_income_controlling or inc.net_income or 0
    rev_ttm = inf.revenue_12m or inc.revenue or 0
    ebit_ttm = inf.ebit_12m or inc.ebit or 0
    da_ttm = inf.da_12m or 0
    ebitda_ttm = ebit_ttm + da_ttm
    bv = bs.equity_controlling or 1e-9
    cfo = cf.cfo or 0
    fcf = cfo - (cf.capex_ppe or 0)

    market_cap = market_price * shares
    debt = bs.total_debt_with_leases
    cash = bs.cash or 0
    enterprise_value = market_cap + debt - cash

    eps = ni_ctrl / shares
    bvps = bv / shares
    sps = rev_ttm / shares
    fcfps = fcf / shares

    out = []

    out.append(RatioInfo(
        name="P/E Ratio",
        value=_safe_div(market_price, eps),
        formula="Price / Earnings Per Share",
        description="Cuantos pesos paga el mercado por cada peso de utilidad. "
                    "El multiplo MAS popular del mercado.",
        interpretation="Bajo (<10): value/distress. Promedio (10-20): mercado "
                       "neutro. Alto (>25): growth premium. Comparar vs sector + tasa.",
        unit="x", category="Valuation Multiples"
    ))

    out.append(RatioInfo(
        name="P/B Ratio",
        value=_safe_div(market_price, bvps),
        formula="Price / Book Value Per Share",
        description="Premium del precio sobre valor en libros. Refleja goodwill "
                    "intangible que el mercado asigna.",
        interpretation="<1: mercado desconfia (ROE bajo). 1-3: rango normal. "
                       ">3: alto premium (ROE alto). Bancos: <1 es value.",
        unit="x", category="Valuation Multiples"
    ))

    out.append(RatioInfo(
        name="P/S Ratio",
        value=_safe_div(market_price, sps),
        formula="Price / Sales Per Share",
        description="Cuantos pesos paga el mercado por cada peso de ventas. "
                    "Util cuando empresa no tiene utilidad.",
        interpretation="Software: 5-20x. Bebidas premium: 3-8x. Retail: 0.5-2x. "
                       "Industria: 0.5-1.5x.",
        unit="x", category="Valuation Multiples"
    ))

    out.append(RatioInfo(
        name="P/FCF Ratio",
        value=_safe_div(market_price, fcfps),
        formula="Price / FCF Per Share",
        description="P/E robusto que usa FCF en lugar de utilidad contable. "
                    "Es el multiplo favorito de Buffett.",
        interpretation="Bajo: value (cuidado con declining FCF). Promedio: 15-25x. "
                       "Alto: growth premium.",
        unit="x", category="Valuation Multiples"
    ))

    out.append(RatioInfo(
        name="EV / EBITDA",
        value=_safe_div(enterprise_value, ebitda_ttm),
        formula="(Market Cap + Debt - Cash) / EBITDA TTM",
        description="Multiplo que incorpora estructura de capital. Permite "
                    "comparar empresas con distintos niveles de deuda.",
        interpretation="Bajo (<6): value o cyclical low. Normal: 8-12x. "
                       "Premium: >15x. Es el multiplo estandar para M&A.",
        unit="x", category="Valuation Multiples"
    ))

    out.append(RatioInfo(
        name="EV / Sales",
        value=_safe_div(enterprise_value, rev_ttm),
        formula="Enterprise Value / Revenue TTM",
        description="Variante capital-structure-neutral del P/S. Util para "
                    "empresas con margenes volatiles o comparaciones M&A.",
        interpretation="Software: 5-15x. Bebidas premium: 3-6x. Retail: 0.5-2x.",
        unit="x", category="Valuation Multiples"
    ))

    out.append(RatioInfo(
        name="EV / EBIT",
        value=_safe_div(enterprise_value, ebit_ttm),
        formula="Enterprise Value / EBIT TTM",
        description="Variante de EV/EBITDA que penaliza empresas con CapEx alto "
                    "(porque ya descuenta D&A).",
        interpretation="Mas conservador que EV/EBITDA. Bueno: <12x. Promedio: 12-20x.",
        unit="x", category="Valuation Multiples"
    ))

    out.append(RatioInfo(
        name="Earnings Yield",
        value=_safe_div(eps, market_price) * 100,
        formula="EPS / Price (= 1/PE)",
        description="Inverso del P/E expresado como tasa. Comparable directamente "
                    "con tasas de bonos.",
        interpretation="Si > tasa libre de riesgo + premium = atractivo. "
                       "Famoso 'Fed Model' usa este vs 10Y T-bond.",
        unit="%", category="Valuation Multiples"
    ))

    div = abs(cf.dividends_paid or 0)
    dps = div / shares
    out.append(RatioInfo(
        name="Dividend Yield",
        value=_safe_div(dps, market_price) * 100,
        formula="Dividend Per Share / Price",
        description="Rendimiento por dividendos. Es el yield 'cash' que recibe "
                    "el accionista anualmente.",
        interpretation="Crecimiento (Apple, MSFT): <1%. Mature (KO, MMM): 2-4%. "
                       "REITs/Utilities: 4-7%. >8% sospechoso (insostenible?).",
        unit="%", category="Valuation Multiples"
    ))

    out.append(RatioInfo(
        name="FCF Yield",
        value=_safe_div(fcfps, market_price) * 100,
        formula="FCF Per Share / Price (= 1/PFCF)",
        description="Yield de cash libre. Lo que TEORICAMENTE podria regresarse "
                    "via dividendos + buybacks.",
        interpretation="FCF Yield > Dividend Yield + tasa = sustancial margen "
                       "para crecer dividendos / buybacks.",
        unit="%", category="Valuation Multiples"
    ))

    return out


# ============================================================================
# CATEGORIA 10: GROWTH (YoY)
# ============================================================================

def _growth(snap, prev_year_snap) -> List[RatioInfo]:
    """Growth YoY (mismo trimestre/año previo)."""
    if not prev_year_snap:
        return []

    inc = snap.parsed.income
    bs = snap.parsed.balance
    cf = snap.parsed.cashflow
    inf = snap.parsed.informative

    prev_inc = prev_year_snap.parsed.income
    prev_bs = prev_year_snap.parsed.balance
    prev_cf = prev_year_snap.parsed.cashflow
    prev_inf = prev_year_snap.parsed.informative

    def growth(curr, prev):
        if prev is None or prev == 0:
            return 0
        return (curr - prev) / abs(prev) * 100

    out = []

    out.append(RatioInfo(
        name="Revenue Growth YoY",
        value=growth(inc.revenue, prev_inc.revenue),
        formula="(Rev_curr - Rev_prev) / Rev_prev",
        description="Crecimiento de ventas vs mismo periodo año anterior. "
                    "El indicador #1 de momentum del negocio.",
        interpretation="Excelente: >15%. Bueno: 8-15%. Promedio MX: 5-10%. "
                       "Recesivo: <0%. Hyper-growth: >30%.",
        unit="%", category="Growth (YoY)"
    ))

    out.append(RatioInfo(
        name="EBIT Growth YoY",
        value=growth(inc.ebit, prev_inc.ebit),
        formula="(EBIT_curr - EBIT_prev) / |EBIT_prev|",
        description="Crecimiento de utilidad operativa. Si supera Revenue Growth "
                    "= operating leverage positivo (margenes expandiendo).",
        interpretation="EBIT Growth > Rev Growth = excelente (margen expanding). "
                       "EBIT Growth < Rev Growth = operating leverage negativo.",
        unit="%", category="Growth (YoY)"
    ))

    ebitda_curr = (inc.ebit or 0) + (inf.da_12m or 0)
    ebitda_prev = (prev_inc.ebit or 0) + (prev_inf.da_12m or 0)
    out.append(RatioInfo(
        name="EBITDA Growth YoY",
        value=growth(ebitda_curr, ebitda_prev),
        formula="(EBITDA_curr - EBITDA_prev) / |EBITDA_prev|",
        description="Crecimiento de EBITDA. Mide si el negocio core esta "
                    "expandiendose en terminos de generacion de cash.",
        interpretation="Comparar con Rev Growth para detectar margin expansion. "
                       "Comparar con NI Growth para detectar leverage cambios.",
        unit="%", category="Growth (YoY)"
    ))

    out.append(RatioInfo(
        name="Net Income Growth YoY",
        value=growth(inc.net_income, prev_inc.net_income),
        formula="(NI_curr - NI_prev) / |NI_prev|",
        description="Crecimiento de utilidad neta total. Es lo que la prensa "
                    "siempre reporta como 'creció X%'.",
        interpretation="Idealmente > Revenue Growth (margin expansion). "
                       "Volatil por one-offs (FX, impuestos, ventas activos).",
        unit="%", category="Growth (YoY)"
    ))

    cfo_curr = cf.cfo or 0
    cfo_prev = prev_cf.cfo or 0
    out.append(RatioInfo(
        name="CFO Growth YoY",
        value=growth(cfo_curr, cfo_prev),
        formula="(CFO_curr - CFO_prev) / |CFO_prev|",
        description="Crecimiento del cash operativo. Mas robusto que NI Growth "
                    "(no afectado por accruals).",
        interpretation="CFO Growth > NI Growth = mejorando calidad de utilidad. "
                       "CFO Growth << NI Growth = warning sign.",
        unit="%", category="Growth (YoY)"
    ))

    fcf_curr = cfo_curr - (cf.capex_ppe or 0)
    fcf_prev = cfo_prev - (prev_cf.capex_ppe or 0)
    out.append(RatioInfo(
        name="FCF Growth YoY",
        value=growth(fcf_curr, fcf_prev),
        formula="(FCF_curr - FCF_prev) / |FCF_prev|",
        description="Crecimiento del cash libre. La metrica MAS relevante para "
                    "valuacion DCF.",
        interpretation="Sostenibilidad >5% por años = empresa de calidad. "
                       "FCF Growth volatil = ciclica/commodity-like.",
        unit="%", category="Growth (YoY)"
    ))

    out.append(RatioInfo(
        name="Total Assets Growth YoY",
        value=growth(bs.total_assets, prev_bs.total_assets),
        formula="(Assets_curr - Assets_prev) / Assets_prev",
        description="Crecimiento del balance. Refleja inversion en operacion + "
                    "M&A + WC.",
        interpretation="Comparar con Revenue Growth: si Assets Growth >> Revenue "
                       "Growth = empresa esta sobre-invirtiendo (warning).",
        unit="%", category="Growth (YoY)"
    ))

    out.append(RatioInfo(
        name="Equity Growth YoY",
        value=growth(bs.equity_controlling, prev_bs.equity_controlling),
        formula="(Equity_curr - Equity_prev) / Equity_prev",
        description="Crecimiento del patrimonio del accionista. Refleja "
                    "utilidades retenidas + emisiones - dividendos.",
        interpretation="Equity Growth ≈ ROE × (1 - Payout). Sostenible >10% = "
                       "empresa creando valor consistentemente.",
        unit="%", category="Growth (YoY)"
    ))

    return out


# ============================================================================
# API PUBLICA
# ============================================================================

# Lista de categorias en orden de display
RATIO_CATEGORIES = [
    "Profitability Margins",
    "Returns",
    "DuPont Decomposition",
    "Liquidity",
    "Leverage",
    "Efficiency",
    "Cash Flow Quality",
    "Per-Share",
    "Valuation Multiples",
    "Growth (YoY)",
]


def compute_all_ratios(
    snap,
    prev_snap=None,            # snapshot del periodo anterior (para promedios y CCC)
    prev_year_snap=None,       # snapshot del mismo trimestre año anterior (para growth YoY)
    market_price: Optional[float] = None,  # precio de cierre para multiplos
) -> List[RatioInfo]:
    """Computa TODOS los ratios financieros para un snapshot.

    Args:
        snap: PeriodSnapshot del periodo a analizar
        prev_snap: snapshot inmediato anterior (para promedios de balance)
        prev_year_snap: snapshot mismo Q año previo (para Growth YoY)
        market_price: precio de cierre del periodo en pesos por accion

    Returns:
        Lista plana de RatioInfo con todos los ratios computados.
    """
    ttm = None  # placeholder; cada categoria usa inf.revenue_12m, ebit_12m, etc.
    all_ratios = []
    all_ratios.extend(_profitability_margins(snap, ttm))
    all_ratios.extend(_returns(snap, prev_snap, ttm))
    all_ratios.extend(_dupont(snap, prev_snap))
    all_ratios.extend(_liquidity(snap))
    all_ratios.extend(_leverage(snap, ttm))
    all_ratios.extend(_efficiency(snap, prev_snap, ttm))
    all_ratios.extend(_cash_flow_quality(snap))
    all_ratios.extend(_per_share(snap))
    all_ratios.extend(_valuation_multiples(snap, market_price))
    all_ratios.extend(_growth(snap, prev_year_snap))
    return all_ratios
