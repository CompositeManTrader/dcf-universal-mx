"""
DCF Universal — Streamlit App (v2 con altair + conditional formatting + financieras)
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path
from dataclasses import asdict

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

warnings.filterwarnings("ignore")

import altair as alt
import pandas as pd
import streamlit as st

from dcf_mexico.parse import parse_xbrl
from dcf_mexico.config import load_issuers, load_sectors, find_xbrl
from dcf_mexico.valuation import (
    DCFAssumptions,
    CompanyBase,
    project_company,
    tornado,
    matrix,
    value_one,
    value_financial_from_parser,
    FinancialAssumptions,
    FinancialBase,
    value_financial,
)
from dcf_mexico.view import build_all_sheets, BLOOMBERG_HEADER


st.set_page_config(
    page_title="DCF Universal MX",
    page_icon=":bar_chart:",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _parse_cached(filepath: str):
    return parse_xbrl(filepath)


@st.cache_data(show_spinner=False)
def _list_local_xbrl_names() -> list[str]:
    raw = ROOT / "data" / "raw_xbrl"
    if not raw.exists():
        return []
    return sorted(p.name for p in raw.glob("ifrsxbrl_*.xls*"))


def _ticker_from_filename(name: str) -> str:
    parts = Path(name).stem.split("_")
    return parts[1] if len(parts) >= 2 else Path(name).stem


def _available_tickers() -> list[str]:
    return sorted({_ticker_from_filename(n) for n in _list_local_xbrl_names()})


# ---------------------------------------------------------------------------
# Helpers UI
# ---------------------------------------------------------------------------
def _style_upside_table(df: pd.DataFrame, upside_col: str = "upside_pct") -> pd.io.formats.style.Styler:
    """Conditional formatting: verde upside, rojo downside."""
    def color(v):
        if pd.isna(v):
            return ""
        if v > 0:
            intensity = min(1.0, v / 50.0)
            return f"background-color: rgba(46, 160, 67, {0.3 + 0.5 * intensity}); color: white"
        else:
            intensity = min(1.0, abs(v) / 50.0)
            return f"background-color: rgba(218, 54, 51, {0.3 + 0.5 * intensity}); color: white"
    # pandas 3.x: usar .map(); applymap fue removido
    styler = df.style
    if hasattr(styler, "map"):
        return styler.map(color, subset=[upside_col])
    return styler.applymap(color, subset=[upside_col])


def _style_bloomberg(df: pd.DataFrame, period_label: str = "FY 2025") -> "pd.io.formats.style.Styler":
    """Estilo Damodaran/Bloomberg:
       - header: azul oscuro, blanco, bold
       - total: gris claro, bold, borde superior
       - sub: italica suave
       - line: regular
       - format numerico: 1 decimal con separador miles
    """
    df_show = df.copy()
    df_show = df_show.rename(columns={"Valor (MDP)": period_label})

    def _fmt_num(v):
        if v is None:
            return "—"
        if isinstance(v, str):
            return v
        if isinstance(v, (int, float)):
            if v == 0:
                return "0.0"
            return f"{v:,.1f}"
        return str(v)

    df_show[period_label] = df_show[period_label].apply(_fmt_num)

    def _row_style(row):
        kind = row.get("Tipo", "")
        if kind == "header":
            return ["background-color: #1F4E79; color: white; font-weight: bold; "
                     "padding: 6px;"] * len(row)
        if kind == "total":
            return ["background-color: #E7EEF7; font-weight: bold; "
                     "border-top: 1px solid #1F4E79; padding: 4px;"] * len(row)
        if kind == "sub":
            return ["color: #4a5568; font-style: italic;"] * len(row)
        return [""] * len(row)

    styler = df_show.drop(columns=["Tipo"]).style.apply(
        lambda r: [_row_style(df_show.iloc[r.name])[i] for i in range(len(r))],
        axis=1,
    )
    # Right-align number column
    styler = styler.set_properties(subset=[period_label], **{"text-align": "right"})
    styler = styler.set_properties(subset=["Concepto"], **{"text-align": "left"})
    styler = styler.set_properties(subset=["BBG Code"], **{"color": "#9CA3AF",
                                                              "font-family": "monospace",
                                                              "font-size": "11px"})
    styler = styler.hide(axis="index")
    return styler


def _bar_chart_upside(df: pd.DataFrame) -> alt.Chart:
    df_chart = df.copy()
    df_chart["color"] = df_chart["upside_pct"].apply(lambda x: "Buy" if x > 0 else "Sell")
    chart = (
        alt.Chart(df_chart)
        .mark_bar()
        .encode(
            x=alt.X("upside_pct:Q", title="Upside / (Downside) %"),
            y=alt.Y("ticker:N", sort="-x", title=None),
            color=alt.Color(
                "color:N",
                scale=alt.Scale(domain=["Buy", "Sell"],
                                range=["#2EA043", "#DA3633"]),
                legend=alt.Legend(title=None, orient="top"),
            ),
            tooltip=["ticker", "name", "sector", "value_per_share",
                     "market_price", "upside_pct", "wacc"],
        )
        .properties(height=alt.Step(20))
    )
    return chart


def _projection_chart(out) -> alt.Chart:
    df = pd.DataFrame({
        "Year": out.years,
        "Revenue": out.revenue,
        "EBIT": out.ebit,
        "FCFF": out.fcff,
        "PV FCFF": out.pv_fcff,
    })
    df_long = df.melt("Year", var_name="Concepto", value_name="MDP")
    chart = (
        alt.Chart(df_long)
        .mark_line(point=True)
        .encode(
            x=alt.X("Year:O"),
            y=alt.Y("MDP:Q"),
            color=alt.Color("Concepto:N",
                            scale=alt.Scale(scheme="category10")),
            tooltip=["Year", "Concepto", alt.Tooltip("MDP:Q", format=",.0f")],
        )
        .properties(height=320)
    )
    return chart


def _tornado_chart(torn: pd.DataFrame) -> alt.Chart:
    df = torn.copy()
    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            y=alt.Y("Driver:N", sort="-x", title=None),
            x=alt.X("Δ Value (MXN):Q"),
            color=alt.condition(
                alt.datum["Δ Value (MXN)"] > 0,
                alt.value("#2EA043"),
                alt.value("#DA3633"),
            ),
            tooltip=["Driver", "Low input", "High input", "Δ Value (MXN)", "Δ Value %"],
        )
        .properties(height=alt.Step(28))
    )
    return chart


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.title("DCF Universal MX")
st.sidebar.markdown("Valuacion DCF • IPC 35 emisoras")

mode = st.sidebar.radio(
    "Modo",
    ["Single DCF", "Compare All", "Upload XBRL", "About"],
    index=0,
)

market, issuers_cfg = load_issuers()
sectors_cfg = load_sectors()

st.sidebar.markdown("---")
st.sidebar.subheader("Market defaults")
st.sidebar.write(f"Rf (M-BONO 10Y): **{market.risk_free:.2%}**")
st.sidebar.write(f"ERP MX:          **{market.erp:.2%}**")
st.sidebar.write(f"Tax marginal:    **{market.marginal_tax:.0%}**")
st.sidebar.write(f"Terminal g:      **{market.terminal_growth:.2%}**")
if market.terminal_wacc_override:
    st.sidebar.write(f"Terminal WACC:   **{market.terminal_wacc_override:.2%}**")

available = _available_tickers()
st.sidebar.markdown("---")
st.sidebar.metric("XBRL locales", f"{len(available)} / 35")
if available:
    with st.sidebar.expander("Tickers disponibles"):
        st.write(", ".join(available))


# ===========================================================================
# MODE 1: Single DCF
# ===========================================================================
if mode == "Single DCF":
    st.title("DCF — Valuacion individual")

    if not available:
        st.warning("No hay XBRLs en `data/raw_xbrl/`. Usa *Upload XBRL* para subir uno.")
        st.stop()

    col1, col2 = st.columns([1, 3])
    with col1:
        ticker = st.selectbox("Emisora", available,
                               index=available.index("CUERVO") if "CUERVO" in available else 0)

    issuer = issuers_cfg.get(ticker)
    if issuer is None:
        st.error(f"Ticker {ticker} no esta en config/issuers.yaml")
        st.stop()
    sector = sectors_cfg.get(issuer.sector)
    if sector is None:
        st.error(f"Sector '{issuer.sector}' no esta en config/sectors.yaml")
        st.stop()

    with col2:
        st.markdown(f"### {issuer.name}  `{ticker}`")
        st.caption(f"Sector: **{sector.name}**  •  Yahoo: `{issuer.yahoo or '-'}`")

    fp = find_xbrl(ticker)
    if fp is None:
        st.error("No XBRL para este ticker.")
        st.stop()

    res = _parse_cached(str(fp))

    # Snapshot
    with st.expander("Snapshot financiero", expanded=False):
        st.dataframe(res.summary(), hide_index=True, use_container_width=True)

    # ========================================================================
    # ESTADOS FINANCIEROS ESTILO BLOOMBERG (5 hojas)
    # ========================================================================
    period_label = f"FY {res.info.fiscal_year}" if res.info.fiscal_year else "Period"
    st.subheader("Estados Financieros (estilo Bloomberg)")
    st.caption(f"{BLOOMBERG_HEADER}  •  Periodo: {res.info.period_end} (Q{res.info.quarter})")
    bb_sheets = build_all_sheets(res, market_price=issuer.market_price)
    bb_tabs = st.tabs(list(bb_sheets.keys()))
    for tab, (sheet_name, sheet_df) in zip(bb_tabs, bb_sheets.items()):
        with tab:
            st.markdown(f"**{sheet_name}** — In Millions of MXN")
            try:
                st.dataframe(
                    _style_bloomberg(sheet_df, period_label),
                    use_container_width=True,
                    height=min(800, 35 + 35 * len(sheet_df)),
                )
            except Exception as e:
                # Fallback sin styling si falla
                st.warning(f"Styler error: {e}")
                st.dataframe(sheet_df, hide_index=True, use_container_width=True)

    # ----- FINANCIAL ISSUER (DDM/Excess Returns) -----
    if sector.is_financial:
        st.info("Financiera: usando **Justified P/B + Excess Returns**, no FCFF.")
        fbase = FinancialBase.from_parser_result(res)

        st.subheader("Inputs")
        c1, c2, c3 = st.columns(3)
        with c1:
            roe_in = st.slider("ROE current", 0.0, 0.45, fbase.roe, 0.005, format="%.3f")
            payout = st.slider("Payout ratio", 0.0, 0.95,
                                min(max(fbase.implied_payout, 0.20), 0.80),
                                0.05, format="%.2f")
        with c2:
            growth_high = st.slider("Growth Y1-5", 0.0, 0.20, 0.07, 0.005, format="%.3f")
            growth_term = st.slider("Terminal growth", 0.0, 0.06, 0.03, 0.005, format="%.3f")
        with c3:
            beta = st.slider("Beta levered", 0.3, 2.5, 1.10, 0.05)
            mkt_price = st.number_input("Precio mercado (MXN)",
                                         value=float(issuer.market_price), step=0.5)

        a = FinancialAssumptions(
            roe=roe_in,
            growth_high=growth_high,
            growth_terminal=growth_term,
            payout_ratio=payout,
            risk_free=market.risk_free,
            erp=market.erp,
            levered_beta=beta,
            market_price=mkt_price,
        )
        out = value_financial(fbase, a)

        st.subheader("Resultado")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Excess Returns Value", f"{out.er_value_per_share:,.2f} MXN",
                  f"{out.er_upside*100:+.1f}% vs mkt")
        k2.metric("Justified P/B Value", f"{out.pb_value_per_share:,.2f} MXN",
                  f"{out.pb_upside*100:+.1f}% vs mkt")
        k3.metric("Cost of Equity", f"{out.cost_of_equity:.2%}",
                  f"Justified P/B = {out.justified_pb:.2f}x")
        k4.metric("BV/share", f"{fbase.book_value_per_share:,.2f} MXN",
                  f"ROE = {fbase.roe:.2%}")

        st.markdown("**Componentes Excess Returns:**")
        st.dataframe(pd.DataFrame([
            ("BV equity (MDP)",            f"{fbase.book_value_equity:,.0f}"),
            ("Sum PV Excess Returns",      f"{out.sum_pv_excess:,.0f}"),
            ("PV Terminal",                f"{out.pv_terminal:,.0f}"),
            ("Total Equity Value",         f"{out.er_total_value:,.0f}"),
        ], columns=["Concepto", "MDP"]), hide_index=True, use_container_width=True)
        st.stop()

    # ----- NON-FINANCIAL: FCFF DCF -----
    base = CompanyBase.from_parser_dcf(res.dcf, include_leases_as_debt=True)

    st.subheader("Drivers DCF (editables)")
    c1, c2, c3 = st.columns(3)
    with c1:
        rev_growth = st.slider("Revenue growth Y1-Y5", 0.0, 0.20,
                                market.revenue_growth_high, 0.005, format="%.3f")
        terminal_g = st.slider("Terminal growth", 0.0, 0.06,
                                market.terminal_growth, 0.005, format="%.3f")
    with c2:
        op_margin = st.slider("Target op margin", 0.0, 0.60,
                               sector.target_op_margin, 0.005, format="%.3f")
        s2c = st.slider("Sales-to-Capital", 0.1, 6.0,
                         sector.sales_to_capital, 0.05, format="%.2f")
    with c3:
        beta_unlev = st.slider("Beta unlevered (sector)", 0.1, 2.0,
                                sector.beta_unlevered, 0.05, format="%.2f")
        market_price = st.number_input("Precio mercado (MXN)",
                                        value=float(issuer.market_price), step=0.5)

    c4, c5, c6 = st.columns(3)
    with c4:
        rf = st.number_input("Risk-free MX", value=market.risk_free,
                              step=0.0025, format="%.4f")
    with c5:
        erp = st.number_input("ERP MX", value=market.erp, step=0.0025, format="%.4f")
    with c6:
        terminal_wacc = st.number_input(
            "Terminal WACC override",
            value=market.terminal_wacc_override or 0.085,
            step=0.0025, format="%.4f",
        )

    a = DCFAssumptions(
        revenue_growth_high=rev_growth,
        terminal_growth=terminal_g,
        target_op_margin=op_margin,
        sales_to_capital=s2c,
        effective_tax_base=market.marginal_tax,
        marginal_tax_terminal=market.marginal_tax,
        risk_free=rf,
        erp=erp,
        unlevered_beta=beta_unlev,
        terminal_wacc_override=terminal_wacc,
        market_price=market_price,
    )
    out = project_company(base, a)

    st.subheader("Resultado")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Value/share", f"{out.value_per_share:,.2f} MXN",
              f"{out.upside_pct*100:+.1f}% vs mkt")
    k2.metric("Market price", f"{market_price:,.2f} MXN")
    k3.metric("Initial WACC", f"{out.wacc_result.wacc:.2%}",
              f"β L = {out.wacc_result.levered_beta:.2f}")
    k4.metric("Equity Value", f"{out.equity_value:,.0f} MDP",
              f"EV {out.enterprise_value:,.0f}")

    # Proyeccion grafico
    st.subheader("Proyeccion FCFF")
    st.altair_chart(_projection_chart(out), use_container_width=True)
    with st.expander("Tabla de proyeccion 10y"):
        st.dataframe(out.projection_table(), hide_index=True, use_container_width=True)

    # Tornado
    st.subheader("Tornado de sensibilidad")
    torn = tornado(base, a)
    st.altair_chart(_tornado_chart(torn), use_container_width=True)
    with st.expander("Tabla tornado"):
        st.dataframe(torn, hide_index=True, use_container_width=True)

    # ========================================================================
    # SECCIONES ESTILO DAMODARAN GINZU
    # ========================================================================
    st.divider()
    st.header("Damodaran-style outputs")

    # Helper: invested capital y ROIC implicitos (usando S2C constante)
    def _compute_ic_roic(out, base, a):
        """IC_0 = Revenue_0 / S2C; IC_t = IC_{t-1} + Reinv_t; ROIC_t = NOPAT_t / IC_{t-1}."""
        ic0 = base.revenue / a.sales_to_capital if a.sales_to_capital > 0 else 1.0
        ic_series = [ic0]
        roic_series = []
        for i in range(len(out.nopat)):
            prev_ic = ic_series[-1]
            roic_series.append(out.nopat[i] / prev_ic if prev_ic > 0 else 0)
            ic_series.append(prev_ic + out.reinvestment[i])
        return ic_series, roic_series

    ic_series, roic_series = _compute_ic_roic(out, base, a)

    # ---- 1) Valuation Output ----
    st.subheader("1. Valuation Output")
    st.caption("Snapshot por hito: año 1 (proyectado), año 5 (fin alto crecimiento), año 10 (estable), terminal.")
    idxs = [0, 4, 9]   # Y1, Y5, Y10
    val_rows = []
    for label, i in zip(["Y1", "Y5", "Y10"], idxs):
        val_rows.append({
            "Periodo":           label,
            "Revenue (MDP)":     round(out.revenue[i], 1),
            "Op Margin":         f"{out.op_margin[i]:.2%}",
            "EBIT (MDP)":        round(out.ebit[i], 1),
            "NOPAT (MDP)":       round(out.nopat[i], 1),
            "Reinversion (MDP)": round(out.reinvestment[i], 1),
            "FCFF (MDP)":        round(out.fcff[i], 1),
            "Inv. Capital":      round(ic_series[i], 1),
            "ROIC":              f"{roic_series[i]:.2%}",
            "WACC":              f"{out.wacc_yearly[i]:.2%}",
            "PV FCFF (MDP)":     round(out.pv_fcff[i], 1),
        })
    # Terminal
    rev_t11 = out.revenue[-1] * (1 + a.terminal_growth)
    ebit_t11 = rev_t11 * a.target_op_margin
    nopat_t11 = ebit_t11 * (1 - a.marginal_tax_terminal)
    reinv_t11 = (rev_t11 - out.revenue[-1]) / a.sales_to_capital if a.sales_to_capital > 0 else 0
    val_rows.append({
        "Periodo":           "Terminal (Y11+)",
        "Revenue (MDP)":     round(rev_t11, 1),
        "Op Margin":         f"{a.target_op_margin:.2%}",
        "EBIT (MDP)":        round(ebit_t11, 1),
        "NOPAT (MDP)":       round(nopat_t11, 1),
        "Reinversion (MDP)": round(reinv_t11, 1),
        "FCFF (MDP)":        round(out.terminal_fcff, 1),
        "Inv. Capital":      round(ic_series[-1], 1),
        "ROIC":              f"{nopat_t11 / ic_series[-1]:.2%}" if ic_series[-1] else "-",
        "WACC":              f"{out.terminal_wacc:.2%}",
        "PV FCFF (MDP)":     round(out.pv_terminal, 1),
    })
    st.dataframe(pd.DataFrame(val_rows), hide_index=True, use_container_width=True)

    # KPI strip de la valuation
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("PV FCFF (10y)",  f"{out.sum_pv_fcff:,.0f} MDP")
    c2.metric("PV Terminal",    f"{out.pv_terminal:,.0f} MDP",
              f"{out.pv_terminal/out.enterprise_value*100:.0f}% del EV")
    c3.metric("Enterprise Value", f"{out.enterprise_value:,.0f} MDP")
    c4.metric("Equity Value", f"{out.equity_value:,.0f} MDP",
              f"{out.value_per_share:.2f} MXN/sh")

    # ---- 2) Stories to Numbers ----
    st.subheader("2. Stories to Numbers")
    st.caption("Narrativa que conecta cada driver con la realidad del negocio.")

    current_margin = base.ebit / base.revenue if base.revenue else 0
    growth_5y = (1 + a.revenue_growth_high) ** 5 - 1
    margin_delta_pp = (a.target_op_margin - current_margin) * 100
    s2c_label = ("Capital-light (alto S2C)" if a.sales_to_capital > 2.5
                 else "Capital-intensive" if a.sales_to_capital < 1.0
                 else "Mid-range")
    roic_terminal = roic_series[-1] if roic_series else 0
    wacc_terminal = out.terminal_wacc
    value_creation = "**crea valor**" if roic_terminal > wacc_terminal else "**destruye valor**"

    st.markdown(f"""
**Crecimiento de ingresos:** **{a.revenue_growth_high:.1%}** anual entre Y1-Y5.
- Implica un acumulado de **+{growth_5y:.0%}** en 5 años.
- Crecimiento histórico 12M observado: **{res.dcf.revenue_growth:.1%}**.

**Margen operativo objetivo (Y10):** **{a.target_op_margin:.1%}**
- Margen actual reportado: **{current_margin:.1%}**.
- Movimiento implícito: **{margin_delta_pp:+.0f}pp** en 10 años. {'Expansion fuerte' if margin_delta_pp > 5 else 'Contraccion fuerte' if margin_delta_pp < -5 else 'Conservar margen'}.

**Sales-to-Capital:** **{a.sales_to_capital:.2f}** ({s2c_label})
- Por cada peso de reinversion, genera ${a.sales_to_capital:.2f} de revenue adicional.
- Determina cuanto necesita reinvertir la empresa para sostener el crecimiento.

**Beta:** unlevered **{a.unlevered_beta:.2f}** -> levered **{out.wacc_result.levered_beta:.2f}** (con D/E {out.wacc_result.debt_to_equity:.2f}).
- Cost of Equity = Rf + β × ERP = {a.risk_free:.2%} + {out.wacc_result.levered_beta:.2f} × {a.erp:.2%} = **{out.wacc_result.cost_equity:.2%}**.

**WACC:** **{out.wacc_result.wacc:.2%}** inicial → **{out.terminal_wacc:.2%}** en estado estable.
- Synthetic rating de la deuda: **{out.wacc_result.rating}** (interest coverage {out.wacc_result.interest_coverage:.1f}x).
- Cost of Debt pretax: **{out.wacc_result.pretax_cost_debt:.2%}**.

**Crecimiento terminal:** **{a.terminal_growth:.1%}**.
- Cap a inflacion MX largo plazo. Empresa madura en perpetuidad.
- Verifica regla Gordon: terminal growth ({a.terminal_growth:.1%}) < risk-free ({a.risk_free:.2%}) ✓.

**ROIC vs WACC en estado estable:** {roic_terminal:.1%} vs {wacc_terminal:.1%} → la empresa {value_creation}.
""")

    # ---- 3) Valuation as Picture (waterfall) ----
    st.subheader("3. Valuation as Picture")
    st.caption("De Sum PV FCFF a Equity Value: bridge en cascada.")

    # Build waterfall data
    net_debt = base.financial_debt - base.cash
    items = [
        ("1. PV FCFF (10y)",      out.sum_pv_fcff,         "add"),
        ("2. + PV Terminal",      out.pv_terminal,         "add"),
        ("3. = Enterprise Value", None,                     "subtotal"),
        ("4. + Cash",             base.cash,                "add"),
        ("5. (-) Total Debt",     -base.financial_debt,    "subtract"),
        ("6. (-) Minority",       -base.minority_interest, "subtract"),
        ("7. (+) Non-op Assets",  base.non_operating_assets, "add"),
        ("8. = Equity Value",     None,                     "total"),
    ]
    cum = 0
    waterfall_rows = []
    for label, val, kind in items:
        if kind == "subtotal":
            waterfall_rows.append({"step": label, "start": 0, "end": cum, "delta": cum, "kind": kind})
        elif kind == "total":
            waterfall_rows.append({"step": label, "start": 0, "end": cum, "delta": cum, "kind": kind})
        else:
            new_cum = cum + val
            waterfall_rows.append({"step": label, "start": cum, "end": new_cum, "delta": val, "kind": kind})
            cum = new_cum

    wf_df = pd.DataFrame(waterfall_rows)
    color_scale = alt.Scale(
        domain=["add", "subtract", "subtotal", "total"],
        range=["#2EA043", "#DA3633", "#5B6B7E", "#1F4E79"],
    )
    waterfall_chart = (
        alt.Chart(wf_df)
        .mark_bar(size=40)
        .encode(
            x=alt.X("step:N", sort=None, title=None,
                    axis=alt.Axis(labelAngle=-30)),
            y=alt.Y("start:Q", title="MDP"),
            y2="end:Q",
            color=alt.Color("kind:N", scale=color_scale, legend=None),
            tooltip=[
                alt.Tooltip("step:N"),
                alt.Tooltip("delta:Q", title="Δ MDP", format=",.0f"),
                alt.Tooltip("end:Q",   title="Cumulative MDP", format=",.0f"),
            ],
        )
        .properties(height=400)
    )
    label_chart = (
        alt.Chart(wf_df)
        .mark_text(dy=-8, fontSize=11)
        .encode(x="step:N", y="end:Q",
                text=alt.Text("delta:Q", format=",.0f"))
    )
    st.altair_chart(waterfall_chart + label_chart, use_container_width=True)

    # ---- 4) Diagnostics ----
    st.subheader("4. Diagnostics")
    st.caption("Sanity checks sobre los supuestos y el output.")

    diag = []
    # ROIC vs WACC
    spread = roic_terminal - wacc_terminal
    diag.append({
        "Check": "ROIC > WACC (estado estable)",
        "Valor": f"{roic_terminal:.2%} vs {wacc_terminal:.2%}  (spread {spread*10000:+.0f}bps)",
        "Status": "OK" if spread > 0 else "WARN",
        "Comment": "Empresa crea valor" if spread > 0 else "Destruye valor en steady state - no debe sostenerse",
    })
    # Terminal growth < Rf
    diag.append({
        "Check": "Terminal growth < Risk-free",
        "Valor": f"{a.terminal_growth:.2%} vs {a.risk_free:.2%}",
        "Status": "OK" if a.terminal_growth < a.risk_free else "ERROR",
        "Comment": "Regla Gordon (sino terminal value explota)",
    })
    # Margin convergence
    margin_move_pp = abs(a.target_op_margin - current_margin) * 100
    diag.append({
        "Check": "Margin convergence vs current",
        "Valor": f"{current_margin:.1%} → {a.target_op_margin:.1%}  ({margin_move_pp:+.0f}pp)",
        "Status": "OK" if margin_move_pp < 5 else "WARN" if margin_move_pp < 10 else "AGGRESSIVE",
        "Comment": "Movimientos >10pp requieren tesis fuerte",
    })
    # Effective tax rate sanity
    etr = base.effective_tax_rate
    diag.append({
        "Check": "Effective tax rate en [10%, 40%]",
        "Valor": f"{etr:.2%}",
        "Status": "OK" if 0.10 <= etr <= 0.40 else "WARN",
        "Comment": "Marginal MX = 30%. Fuera de rango sugiere one-offs",
    })
    # Debt-to-Equity reasonable
    de = out.wacc_result.debt_to_equity
    diag.append({
        "Check": "Debt/Equity < 2.0",
        "Valor": f"{de:.2f}",
        "Status": "OK" if de < 2.0 else "WARN",
        "Comment": "Apalancamiento razonable. >2 sugiere distress o financiera",
    })
    # Reinvestment rate vs growth
    reinv_rate_y5 = out.reinvestment[4] / out.nopat[4] if out.nopat[4] else 0
    diag.append({
        "Check": "Reinvestment rate (Y5)",
        "Valor": f"{reinv_rate_y5:.0%} de NOPAT",
        "Status": "OK" if 0 <= reinv_rate_y5 <= 0.80 else "WARN",
        "Comment": ">80% es muy alto; <0% sugiere desinversion",
    })
    # Terminal value share of EV
    tv_share = out.pv_terminal / out.enterprise_value if out.enterprise_value else 0
    diag.append({
        "Check": "PV Terminal / EV",
        "Valor": f"{tv_share:.0%}",
        "Status": "OK" if tv_share < 0.75 else "WARN",
        "Comment": ">75% del valor en terminal sugiere supuestos finales muy sensibles",
    })
    # Interest coverage
    cov = out.wacc_result.interest_coverage
    diag.append({
        "Check": "Interest Coverage Ratio",
        "Valor": f"{cov:.1f}x  (rating {out.wacc_result.rating})",
        "Status": "OK" if cov >= 3.0 else "WARN" if cov >= 1.5 else "DISTRESS",
        "Comment": "<1.5x = riesgo de default. >5x = grado de inversion",
    })

    diag_df = pd.DataFrame(diag)
    # Color coding
    def _color_status(v):
        if v == "OK": return "background-color: rgba(46, 160, 67, 0.45); color: white"
        if v == "WARN": return "background-color: rgba(245, 158, 11, 0.55); color: white"
        if v in ("ERROR", "DISTRESS"): return "background-color: rgba(218, 54, 51, 0.65); color: white"
        if v == "AGGRESSIVE": return "background-color: rgba(245, 100, 11, 0.55); color: white"
        return ""
    styler = diag_df.style
    if hasattr(styler, "map"):
        styler = styler.map(_color_status, subset=["Status"])
    else:
        styler = styler.applymap(_color_status, subset=["Status"])
    st.dataframe(styler, hide_index=True, use_container_width=True)

    # ========================================================================
    # MATRIZ HEATMAP (mantener al final)
    # ========================================================================
    st.divider()
    st.subheader("Matriz growth × margin (heatmap)")
    grid_x = [0.02, 0.04, 0.05, 0.06, 0.08, 0.10]
    grid_y = [op_margin - 0.04, op_margin - 0.02, op_margin,
              op_margin + 0.02, op_margin + 0.04]
    mat = matrix(base, a, "revenue_growth_high", "target_op_margin", grid_x, grid_y)
    # Reshape para altair
    mat_long = mat.reset_index().melt(id_vars="index", var_name="growth", value_name="value")
    mat_long["margin"] = mat_long["index"].str.extract(r"=([\d.]+)").astype(float)
    mat_long["growth_n"] = mat_long["growth"].str.extract(r"=([\d.]+)").astype(float)
    heat = (
        alt.Chart(mat_long)
        .mark_rect()
        .encode(
            x=alt.X("growth_n:O", title="Revenue growth Y1-5"),
            y=alt.Y("margin:O", title="Target op margin", sort="descending"),
            color=alt.Color("value:Q", scale=alt.Scale(scheme="redyellowgreen"),
                             title="Value (MXN)"),
            tooltip=["growth_n", "margin", "value"],
        )
        .properties(height=240)
    )
    text = (
        alt.Chart(mat_long).mark_text(color="black")
        .encode(x="growth_n:O", y=alt.Y("margin:O", sort="descending"),
                text=alt.Text("value:Q", format=".1f"))
    )
    st.altair_chart(heat + text, use_container_width=True)


# ===========================================================================
# MODE 2: Compare All
# ===========================================================================
elif mode == "Compare All":
    st.title("Comparativo IPC — 35 emisoras")
    st.caption(
        "Corre el batch sobre todas las emisoras con XBRL disponible. "
        "Las 8 financieras usan Justified P/B + Excess Returns (no FCFF)."
    )

    st.info(f"XBRLs disponibles: **{len(available)}** de 35.")

    if not available:
        st.warning("Sin XBRLs. Sube via *Upload XBRL* o coloca en `data/raw_xbrl/`.")
        st.stop()

    if st.button("Correr batch", type="primary"):
        rows = []
        progress = st.progress(0, text="Iniciando...")
        for i, ticker in enumerate(sorted(issuers_cfg.keys())):
            row = value_one(ticker)
            rows.append(asdict(row))
            progress.progress((i+1) / len(issuers_cfg), text=f"Procesando {ticker}")
        progress.empty()
        st.session_state["batch_df"] = pd.DataFrame(rows)

    if "batch_df" in st.session_state:
        df = st.session_state["batch_df"]
        df_ok = df[df["error"].eq("")].copy()
        df_skip = df[~df["error"].eq("")].copy()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Cobertura",   f"{len(df_ok)} / {len(df)}")
        c2.metric("Financieras", int(df["is_financial"].sum()))
        c3.metric("FCFF DCF",    int((~df["is_financial"]).sum() - len(df_skip)))
        if not df_ok.empty:
            c4.metric("Avg upside", f"{df_ok['upside_pct'].mean():+.1f}%")

        st.subheader("Ranked by upside (verde = buy, rojo = sell)")
        if not df_ok.empty:
            cols_show = ["ticker", "name", "sector", "market_price",
                         "value_per_share", "upside_pct", "wacc",
                         "levered_beta", "rating", "is_financial"]
            df_show = df_ok[cols_show].sort_values("upside_pct", ascending=False).reset_index(drop=True)
            st.dataframe(_style_upside_table(df_show, "upside_pct"),
                          hide_index=True, use_container_width=True)

            st.subheader("Upside por emisora")
            chart = _bar_chart_upside(
                df_ok[["ticker", "name", "sector", "value_per_share",
                        "market_price", "upside_pct", "wacc"]]
            )
            st.altair_chart(chart, use_container_width=True)

            st.subheader("Resumen por sector")
            sector_agg = df_ok.groupby("sector").agg(
                n=("ticker", "count"),
                avg_upside_pct=("upside_pct", "mean"),
                avg_wacc=("wacc", "mean"),
                med_value_per_share=("value_per_share", "median"),
            ).round(3).sort_values("avg_upside_pct", ascending=False)
            st.dataframe(_style_upside_table(sector_agg.reset_index(), "avg_upside_pct"),
                          hide_index=True, use_container_width=True)

            st.subheader("Top 5 BUYS / Top 5 SELLS")
            cb, cs = st.columns(2)
            with cb:
                st.markdown("**Top 5 BUYS**")
                top_b = df_ok.nlargest(5, "upside_pct")[["ticker", "name", "value_per_share", "market_price", "upside_pct"]]
                st.dataframe(_style_upside_table(top_b, "upside_pct"),
                              hide_index=True, use_container_width=True)
            with cs:
                st.markdown("**Top 5 SELLS**")
                top_s = df_ok.nsmallest(5, "upside_pct")[["ticker", "name", "value_per_share", "market_price", "upside_pct"]]
                st.dataframe(_style_upside_table(top_s, "upside_pct"),
                              hide_index=True, use_container_width=True)

            # CSV export
            csv = df_ok.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Descargar resultados (.csv)",
                data=csv,
                file_name="ipc_dcf_results.csv",
                mime="text/csv",
            )

        if not df_skip.empty:
            with st.expander(f"Errores / skipped ({len(df_skip)})"):
                st.dataframe(df_skip[["ticker", "name", "error"]],
                              hide_index=True, use_container_width=True)


# ===========================================================================
# MODE 3: Upload XBRL
# ===========================================================================
elif mode == "Upload XBRL":
    st.title("Subir XBRL CNBV")
    st.caption(
        "Carga uno o varios .xls/.xlsx descargados de la BMV/CNBV. "
        "Naming convention: `ifrsxbrl_<TICKER>_<YYYY>-<Q>.xls`"
    )

    uploaded = st.file_uploader(
        "Archivo(s) XBRL", type=["xls", "xlsx"], accept_multiple_files=True,
    )
    if not uploaded:
        st.info("Sube uno o mas archivos para procesar.")
        st.stop()

    raw = ROOT / "data" / "raw_xbrl"
    raw.mkdir(parents=True, exist_ok=True)
    summaries = []

    for u in uploaded:
        path = raw / u.name
        path.write_bytes(u.getvalue())
        try:
            res = parse_xbrl(path)
            summaries.append({
                "Archivo": u.name,
                "Ticker": res.info.ticker,
                "Periodo": res.info.period_end,
                "Revenue (MDP)": round(res.income.revenue / 1e6, 1),
                "EBIT (MDP)":    round(res.income.ebit / 1e6, 1),
                "Validacion":    "OK" if res.validation.ok else "ISSUES",
            })
        except Exception as e:
            summaries.append({
                "Archivo": u.name, "Ticker": "?", "Periodo": "?",
                "Revenue (MDP)": 0, "EBIT (MDP)": 0,
                "Validacion": f"ERROR: {e}",
            })

    _list_local_xbrl_names.clear()
    _parse_cached.clear()
    st.success(f"Procesados {len(summaries)} archivos")
    st.dataframe(pd.DataFrame(summaries), hide_index=True, use_container_width=True)


# ===========================================================================
# MODE 4: About
# ===========================================================================
else:
    st.title("DCF Universal MX — About")
    st.markdown("""
**Pipeline end-to-end:**

```
XBRL CNBV → Parser → EEFF estructurados → DCF Damodaran (FCFF + Justified P/B) → Streamlit UI
```

**Cobertura:** 35 emisoras del IPC mexicano.

- **27 emisoras industriales/comerciales** → DCF FCFF estilo Damodaran "Ginzu" (10 anios + terminal Gordon).
- **8 emisoras financieras** (BBAJIO, BOLSA, ELEKTRA, GENTERA, GFINBUR, GFNORTE, Q, RA) → Justified P/B + Excess Returns Model.

**Calibrado:** WACC 11.4% / 8.5% terminal, replicando un modelo de equity research (CUERVO target 21 MXN).

**Drivers sectoriales:** 17 sectores con beta unlev, S2C y target margin de Damodaran Industry Averages.

**Stack:** Python + pandas + Streamlit + Altair. Tests con pytest.
    """)

    st.divider()
    st.subheader("Sectores configurados")
    sec_df = pd.DataFrame([
        {
            "key": k,
            "name": v.name,
            "beta_unlev": v.beta_unlevered,
            "S2C": v.sales_to_capital,
            "target_margin": v.target_op_margin,
            "is_financial": v.is_financial,
        }
        for k, v in sectors_cfg.items()
    ])
    st.dataframe(sec_df, hide_index=True, use_container_width=True)

    st.subheader("Issuers configurados")
    iss_df = pd.DataFrame([
        {
            "ticker": k,
            "name": v.name,
            "sector": v.sector,
            "market_price": v.market_price,
            "yahoo": v.yahoo,
            "has_local_xbrl": k in available,
        }
        for k, v in sorted(issuers_cfg.items())
    ])
    st.dataframe(iss_df, hide_index=True, use_container_width=True)
