"""Helper centralizado: parser + DCF para un ticker, devolviendo dict listo para tabla."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from ..parse import parse_xbrl
from ..config import (
    SectorDefaults,
    IssuerInfo,
    MarketDefaults,
    load_sectors,
    load_issuers,
    find_xbrl,
)
from .dcf_fcff import CompanyBase, DCFAssumptions, project_company


@dataclass
class ValuationRow:
    ticker: str
    name: str
    sector: str
    period_end: str
    is_financial: bool
    revenue: float
    ebit: float
    op_margin: float
    cash: float
    debt: float
    shares_mn: float
    market_price: float
    market_cap: float
    wacc: float
    levered_beta: float
    rating: str
    enterprise_value: float
    equity_value: float
    value_per_share: float
    upside_pct: float
    validation_ok: bool
    error: str = ""


def _resolve_target_margin(parsed_dcf, sector: SectorDefaults, override: Optional[dict]) -> float:
    """Margen target: 1) override > 2) margen actual del XBRL > 3) sector default."""
    if override and "target_op_margin" in override:
        return float(override["target_op_margin"])
    current = parsed_dcf.operating_margin
    # Si margen actual es razonable (5%-100%), usarlo. Si no, sector default.
    if 0.05 <= current <= 1.0:
        return current
    return sector.target_op_margin


def _resolve_s2c(parsed_dcf, sector: SectorDefaults, override: Optional[dict]) -> float:
    """Sales-to-Capital: 1) override > 2) actual del XBRL > 3) sector default."""
    if override and "sales_to_capital" in override:
        return float(override["sales_to_capital"])
    current = parsed_dcf.sales_to_capital
    # Si actual es razonable (0.2-8), usarlo. Si no, sector default.
    if 0.2 <= current <= 8.0:
        return current
    return sector.sales_to_capital


def _resolve_growth(market: MarketDefaults, override: Optional[dict]) -> float:
    if override and "revenue_growth_high" in override:
        return float(override["revenue_growth_high"])
    return market.revenue_growth_high


def assumptions_from_config(
    market: MarketDefaults,
    sector: SectorDefaults,
    issuer: IssuerInfo,
    parsed_dcf=None,
    revenue_growth_override: Optional[float] = None,
) -> DCFAssumptions:
    """Construye DCFAssumptions usando, en este orden de prioridad:
       1) issuer.dcf_override (per-emisora) > 2) parsed_dcf actual > 3) sector default."""
    override = issuer.dcf_override

    if parsed_dcf is not None:
        target_margin = _resolve_target_margin(parsed_dcf, sector, override)
        s2c = _resolve_s2c(parsed_dcf, sector, override)
    else:
        target_margin = (override.get("target_op_margin") if override else None) or sector.target_op_margin
        s2c = (override.get("sales_to_capital") if override else None) or sector.sales_to_capital

    if revenue_growth_override is not None:
        rev_growth = revenue_growth_override
    else:
        rev_growth = _resolve_growth(market, override)

    beta = float(override["unlevered_beta"]) if override and "unlevered_beta" in override else sector.beta_unlevered

    return DCFAssumptions(
        revenue_growth_high=rev_growth,
        terminal_growth=market.terminal_growth,
        target_op_margin=target_margin,
        sales_to_capital=s2c,
        effective_tax_base=market.marginal_tax,
        marginal_tax_terminal=market.marginal_tax,
        risk_free=market.risk_free,
        erp=market.erp,
        unlevered_beta=beta,
        terminal_wacc_override=market.terminal_wacc_override,
        market_price=issuer.market_price,
        forecast_years=market.forecast_years,
        high_growth_years=market.high_growth_years,
    )


def value_one(
    ticker: str,
    xbrl_path: Optional[Path] = None,
    revenue_growth_override: Optional[float] = None,
) -> ValuationRow:
    """Pipeline completo para un ticker. Devuelve un ValuationRow."""
    market, issuers = load_issuers()
    sectors = load_sectors()

    if ticker not in issuers:
        return ValuationRow(
            ticker=ticker, name="", sector="", period_end="", is_financial=False,
            revenue=0, ebit=0, op_margin=0, cash=0, debt=0, shares_mn=0,
            market_price=0, market_cap=0, wacc=0, levered_beta=0, rating="",
            enterprise_value=0, equity_value=0, value_per_share=0, upside_pct=0,
            validation_ok=False, error=f"Ticker {ticker} no esta en config/issuers.yaml",
        )

    issuer = issuers[ticker]
    sector = sectors.get(issuer.sector)
    if sector is None:
        return ValuationRow(
            ticker=ticker, name=issuer.name, sector=issuer.sector, period_end="",
            is_financial=False, revenue=0, ebit=0, op_margin=0, cash=0, debt=0,
            shares_mn=0, market_price=issuer.market_price, market_cap=0, wacc=0,
            levered_beta=0, rating="", enterprise_value=0, equity_value=0,
            value_per_share=0, upside_pct=0, validation_ok=False,
            error=f"Sector '{issuer.sector}' no esta en config/sectors.yaml",
        )

    # Localizar XBRL
    fp = xbrl_path or find_xbrl(ticker)
    if fp is None or not fp.exists():
        return ValuationRow(
            ticker=ticker, name=issuer.name, sector=sector.name, period_end="",
            is_financial=sector.is_financial, revenue=0, ebit=0, op_margin=0,
            cash=0, debt=0, shares_mn=0, market_price=issuer.market_price,
            market_cap=0, wacc=0, levered_beta=0, rating="",
            enterprise_value=0, equity_value=0, value_per_share=0, upside_pct=0,
            validation_ok=False,
            error=f"No se encontro XBRL para {ticker} en data/raw_xbrl/",
        )

    # Parser
    try:
        res = parse_xbrl(fp)
    except Exception as e:
        return ValuationRow(
            ticker=ticker, name=issuer.name, sector=sector.name, period_end="",
            is_financial=sector.is_financial, revenue=0, ebit=0, op_margin=0,
            cash=0, debt=0, shares_mn=0, market_price=issuer.market_price,
            market_cap=0, wacc=0, levered_beta=0, rating="",
            enterprise_value=0, equity_value=0, value_per_share=0, upside_pct=0,
            validation_ok=False, error=f"Parser error: {e}",
        )

    # Detectar moneda de reporte y aplicar FX si reporta en USD
    currency = (res.info.currency or "MXN").upper().strip()
    fx_mult = market.fx_rate_usdmxn if currency == "USD" else 1.0
    base = CompanyBase.from_parser_dcf(res.dcf, include_leases_as_debt=True,
                                         currency_multiplier=fx_mult)
    market_cap = issuer.market_price * base.shares_outstanding / 1e6  # MDP

    # Si es financiera, usar Justified P/B + Excess Returns (no FCFF DCF).
    if sector.is_financial:
        from .financial import value_financial_from_parser
        try:
            fo = value_financial_from_parser(
                res,
                market_price=issuer.market_price,
                risk_free=market.risk_free,
                erp=market.erp,
                levered_beta=sector.beta_unlevered,   # uso beta sectorial directa
                growth_terminal=market.terminal_growth,
            )
            return ValuationRow(
                ticker=ticker, name=issuer.name, sector=sector.name,
                period_end=res.info.period_end, is_financial=True,
                revenue=round(base.revenue, 1), ebit=round(base.ebit, 1),
                op_margin=round(base.ebit/base.revenue if base.revenue else 0, 4),
                cash=round(base.cash, 1), debt=round(base.financial_debt, 1),
                shares_mn=round(base.shares_outstanding/1e6, 2),
                market_price=issuer.market_price, market_cap=round(market_cap, 1),
                wacc=round(fo.cost_of_equity, 4), levered_beta=sector.beta_unlevered,
                rating="N/A (financial)",
                enterprise_value=round(fo.er_total_value, 1),
                equity_value=round(fo.er_total_value, 1),
                value_per_share=round(fo.er_value_per_share, 2),
                upside_pct=round(fo.er_upside * 100, 1),
                validation_ok=res.validation.ok,
                error="",
            )
        except Exception as e:
            return ValuationRow(
                ticker=ticker, name=issuer.name, sector=sector.name,
                period_end=res.info.period_end, is_financial=True,
                revenue=base.revenue, ebit=base.ebit,
                op_margin=base.ebit/base.revenue if base.revenue else 0,
                cash=base.cash, debt=base.financial_debt,
                shares_mn=base.shares_outstanding/1e6,
                market_price=issuer.market_price, market_cap=market_cap,
                wacc=0, levered_beta=0, rating="N/A",
                enterprise_value=0, equity_value=0, value_per_share=0, upside_pct=0,
                validation_ok=res.validation.ok,
                error=f"Financial valuation error: {e}",
            )

    # DCF (usa current values del XBRL via parsed_dcf)
    a = assumptions_from_config(market, sector, issuer,
                                  parsed_dcf=res.dcf,
                                  revenue_growth_override=revenue_growth_override)
    out = project_company(base, a)

    return ValuationRow(
        ticker=ticker,
        name=issuer.name,
        sector=sector.name,
        period_end=res.info.period_end,
        is_financial=False,
        revenue=round(base.revenue, 1),
        ebit=round(base.ebit, 1),
        op_margin=round(base.ebit/base.revenue if base.revenue else 0, 4),
        cash=round(base.cash, 1),
        debt=round(base.financial_debt, 1),
        shares_mn=round(base.shares_outstanding/1e6, 2),
        market_price=issuer.market_price,
        market_cap=round(market_cap, 1),
        wacc=round(out.wacc_result.wacc, 4),
        levered_beta=round(out.wacc_result.levered_beta, 3),
        rating=out.wacc_result.rating,
        enterprise_value=round(out.enterprise_value, 1),
        equity_value=round(out.equity_value, 1),
        value_per_share=round(out.value_per_share, 2),
        upside_pct=round(out.upside_pct * 100, 1),
        validation_ok=res.validation.ok,
    )
