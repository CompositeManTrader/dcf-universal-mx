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

# Imports nuevos (defensivos: no rompen la app si fallan)
try:
    from dcf_mexico.valuation import dupont_from_parser
    HAS_DUPONT = True
except ImportError as _e:
    HAS_DUPONT = False
    _DUPONT_ERR = str(_e)

try:
    from dcf_mexico.valuation import export_dcf_to_excel
    HAS_EXCEL_EXPORT = True
except ImportError as _e:
    HAS_EXCEL_EXPORT = False
    _EXCEL_ERR = str(_e)

try:
    from dcf_mexico.historical import (
        load_historical,
        build_historical_bloomberg,
        build_metric_timeseries,
        compute_growth_stats,
    )
    HAS_HISTORICAL = True
except ImportError as _e:
    HAS_HISTORICAL = False
    _HIST_ERR = str(_e)

try:
    from dcf_mexico.validation import (
        compare_all_periods,
        find_bloomberg_file,
        CUERVO_INCOME_AR, CUERVO_BS_AR, CUERVO_CF_AR,
    )
    from dcf_mexico.config import find_all_xbrl, parse_period_tag
    HAS_VALIDATION = True
    # Registry de mappings disponibles
    BLOOMBERG_MAPPINGS = {
        "CUERVO": {
            "Income - As Reported":     CUERVO_INCOME_AR,
            "Bal Sheet - As Reported":  CUERVO_BS_AR,
            "Cash Flow - As Reported":  CUERVO_CF_AR,
        },
    }
except ImportError as _e:
    HAS_VALIDATION = False
    _VAL_ERR = str(_e)
    BLOOMBERG_MAPPINGS = {}

from dcf_mexico.view import build_all_sheets, BLOOMBERG_HEADER


st.set_page_config(
    page_title="DCF Universal MX",
    page_icon=":bar_chart:",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Bloomberg-style CSS (custom theme on top of Streamlit)
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* Header / titles */
    h1, h2, h3, h4 {
        color: #0E2B45 !important;
        font-family: 'Segoe UI', 'Roboto', sans-serif;
        font-weight: 600 !important;
    }
    h1 { border-bottom: 3px solid #1F4E79; padding-bottom: 8px; }

    /* Bloomberg accent color */
    .stApp { background-color: #FAFBFC; }

    /* Metric cards */
    [data-testid="stMetricValue"] {
        font-size: 1.6rem !important;
        font-weight: 700 !important;
        color: #0E2B45 !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.85rem !important;
        color: #4A5568 !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    /* Tabs - Bloomberg style */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
        background-color: #0E2B45;
        padding: 8px;
        border-radius: 6px 6px 0 0;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: #1F4E79;
        color: #E8EDF2;
        border-radius: 4px;
        padding: 8px 18px;
        font-weight: 500;
        border: 0;
    }
    .stTabs [aria-selected="true"] {
        background-color: #FF8C00 !important;
        color: white !important;
        font-weight: 700 !important;
    }
    .stTabs [data-baseweb="tab-panel"] {
        background-color: white;
        padding: 20px;
        border: 1px solid #E0E5EB;
        border-top: none;
        border-radius: 0 0 6px 6px;
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background-color: #0E2B45;
    }
    [data-testid="stSidebar"] * {
        color: #E8EDF2 !important;
    }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] strong {
        color: #FF8C00 !important;
    }

    /* Dataframes */
    [data-testid="stDataFrame"] {
        border: 1px solid #D0D7DE;
        border-radius: 4px;
    }

    /* Input fields */
    .stNumberInput input, .stTextInput input, .stSelectbox > div > div {
        border-color: #1F4E79 !important;
    }

    /* Buttons */
    .stButton > button {
        background-color: #1F4E79;
        color: white;
        border: none;
        font-weight: 600;
    }
    .stButton > button:hover {
        background-color: #FF8C00;
        color: white;
    }

    /* Download button */
    .stDownloadButton > button {
        background-color: #2EA043;
        color: white;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)


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
    # TABS (Damodaran-style + Bloomberg + DuPont + Download)
    # ========================================================================
    st.divider()

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

    # Define tabs (each section becomes a tab via __enter__/__exit__ to avoid
    # massive re-indentation. This is equivalent to `with tab:` blocks).
    (tab_hist, tab_valid, tab_val, tab_stories, tab_pic,
     tab_sens, tab_dupont, tab_diag, tab_dl) = st.tabs([
        "📅 Historical",
        "🔍 Bloomberg Validation",
        "📈 Valuation Output",
        "📖 Stories to Numbers",
        "🎨 Valuation as Picture",
        "🎯 Sensitivity",
        "🔗 DuPont",
        "✅ Diagnostics",
        "💾 Download Excel",
    ])

    # ============================================================
    # TAB 0: HISTORICAL (multi-period XBRL evolution)
    # ============================================================
    tab_hist.__enter__()

    st.subheader(f"Historical Evolution — {issuer.ticker}")
    st.caption(
        "Carga TODOS los XBRL del ticker en `data/raw_xbrl/` y muestra la evolucion "
        "multi-periodo. Naming convention: `ifrsxbrl_<TICKER>_<YYYY>-<Q>.xls` "
        "(Q = `4D` para anual auditado, `1`/`2`/`3`/`4` para trimestrales)."
    )

    if not HAS_HISTORICAL:
        st.error(f"Historical module no disponible: {_HIST_ERR}")
    else:
        try:
            hs = load_historical(issuer.ticker, parse_func=lambda fp: _parse_cached(str(fp)))
        except Exception as e:
            st.error(f"Error cargando historico: {e}")
            hs = None

        if hs is not None:
            cov = hs.coverage_summary()
            colA, colB, colC, colD = st.columns(4)
            colA.metric("Periodos totales", hs.n_periods)
            colB.metric("Anuales (4D)", hs.n_annual)
            colC.metric("Trimestrales", hs.n_quarterly)
            if hs.latest:
                colD.metric("Latest", hs.latest.label)

            with st.expander("Cobertura de archivos"):
                st.dataframe(cov, hide_index=True, use_container_width=True)

            if hs.n_periods <= 1:
                st.warning(
                    "Solo hay 1 periodo de XBRL para este ticker. Para ver evolucion historica, "
                    "descarga mas XBRL desde la BMV (preferentemente trimestres dictaminados `4D` "
                    "para 5-10 años de historia anual) y guardalos en `data/raw_xbrl/` con la "
                    "convencion de nombre indicada arriba."
                )
            else:
                # Toggle: anual vs todos. Default OFF si no hay anuales.
                _has_annual = hs.n_annual > 0
                annual_only = st.toggle(
                    "Solo periodos anuales (4D)",
                    value=_has_annual,
                    help=f"Tienes {hs.n_annual} anuales y {hs.n_quarterly} trimestrales. "
                         f"Si lo apagas, incluye trimestres preliminares.",
                )
                if annual_only and not _has_annual:
                    st.warning(
                        "No tienes XBRLs anuales (4D) descargados para este ticker. "
                        "Apaga el toggle para usar los trimestrales, o descarga los `4D`."
                    )

                # Multi-period Bloomberg table
                st.markdown("### Multi-period financial panel")
                st.caption("Filas = metricas, columnas = periodos. Valores en MDP donde aplica (USD->MXN auto-detectado).")
                fx_rate = market.fx_rate_usdmxn
                bb_hist = build_historical_bloomberg(hs, fx_rate_usdmxn=fx_rate,
                                                       annual_only=annual_only)
                if not bb_hist.empty:
                    # Format
                    def _fmt_cell(v, row_label):
                        if pd.isna(v):
                            return "-"
                        is_pct = any(k in row_label for k in ["Margin", "Rate", "ROE", "ROA"])
                        is_mult = any(k in row_label for k in ["/ EBITDA", "/ Equity"])
                        if is_pct:
                            return f"{v:.2%}"
                        if is_mult:
                            return f"{v:.2f}x"
                        if "Shares" in row_label:
                            return f"{v:,.2f}"
                        return f"{v:,.1f}"
                    # Build formatted DF as object dtype directly (pandas 3.x strict)
                    fmt_df = pd.DataFrame(
                        {col: [_fmt_cell(bb_hist.loc[idx, col], idx)
                               for idx in bb_hist.index]
                         for col in bb_hist.columns},
                        index=bb_hist.index,
                        dtype=object,
                    )

                    def _hist_row_style(row):
                        label = row.name
                        if label in ("Revenue", "EBIT", "EBITDA", "Net Income",
                                      "Total Assets", "Equity (controll.)", "FCFF (simple)"):
                            return ["background-color: #DCEDC8; font-weight: 600;"] * len(row)
                        if label in ("Op Margin", "EBITDA Margin", "Net Margin",
                                      "ROE", "ROA", "Tax Rate"):
                            return ["background-color: #F1F8E9;"] * len(row)
                        return ["background-color: #F9FBF7;"] * len(row)
                    try:
                        styler = fmt_df.style.apply(_hist_row_style, axis=1)
                        styler = styler.set_properties(**{"text-align": "right", "padding": "4px 8px"})
                        st.dataframe(styler, use_container_width=True,
                                      height=min(750, 35 + 32 * len(fmt_df)))
                    except Exception:
                        st.dataframe(fmt_df, use_container_width=True)

                # Time series charts
                st.markdown("### Evolucion temporal")
                metrics_to_chart = st.multiselect(
                    "Metricas para graficar",
                    ["Revenue", "EBIT", "EBITDA", "Net Income", "FCFF (simple)",
                     "CFO", "Capex (gross)", "Total Debt", "Cash", "Net Debt",
                     "Op Margin", "EBITDA Margin", "Net Margin", "ROE", "ROA",
                     "Net Debt / EBITDA"],
                    default=["Revenue", "EBIT", "EBITDA"],
                )
                if metrics_to_chart:
                    chart_data = []
                    for m in metrics_to_chart:
                        ts = build_metric_timeseries(hs, m, fx_rate_usdmxn=fx_rate,
                                                       annual_only=annual_only)
                        for _, r in ts.iterrows():
                            chart_data.append({"label": r["label"], "year": r["year"],
                                                "metric": m, "value": r["value"]})
                    chart_df = pd.DataFrame(chart_data)
                    if not chart_df.empty:
                        # Separate absolute vs ratio metrics for dual chart
                        abs_metrics = [m for m in metrics_to_chart
                                        if not any(k in m for k in ["Margin", "Rate", "ROE", "ROA", "/ EBITDA"])]
                        ratio_metrics = [m for m in metrics_to_chart if m not in abs_metrics]

                        if abs_metrics:
                            abs_df = chart_df[chart_df["metric"].isin(abs_metrics)]
                            chart_abs = (
                                alt.Chart(abs_df)
                                .mark_line(point=True, strokeWidth=2.5)
                                .encode(
                                    x=alt.X("label:N", sort=None, title=None),
                                    y=alt.Y("value:Q", title="MDP"),
                                    color=alt.Color("metric:N",
                                                     scale=alt.Scale(scheme="category10"),
                                                     legend=alt.Legend(orient="top")),
                                    tooltip=["label", "metric",
                                              alt.Tooltip("value:Q", format=",.1f")],
                                )
                                .properties(height=320, title="Metricas absolutas (MDP)")
                            )
                            st.altair_chart(chart_abs, use_container_width=True)

                        if ratio_metrics:
                            ratio_df = chart_df[chart_df["metric"].isin(ratio_metrics)].copy()
                            chart_ratio = (
                                alt.Chart(ratio_df)
                                .mark_line(point=True, strokeWidth=2.5)
                                .encode(
                                    x=alt.X("label:N", sort=None, title=None),
                                    y=alt.Y("value:Q", title="Ratio", axis=alt.Axis(format=".1%")),
                                    color=alt.Color("metric:N",
                                                     scale=alt.Scale(scheme="set2"),
                                                     legend=alt.Legend(orient="top")),
                                    tooltip=["label", "metric",
                                              alt.Tooltip("value:Q", format=".2%")],
                                )
                                .properties(height=320, title="Ratios / margenes")
                            )
                            st.altair_chart(chart_ratio, use_container_width=True)

                # Growth stats summary
                st.markdown("### Quick stats (sobre periodos seleccionados)")
                stat_metrics = ["Revenue", "EBIT", "EBITDA", "Net Income"]
                stat_rows = []
                for m in stat_metrics:
                    ts = build_metric_timeseries(hs, m, fx_rate_usdmxn=fx_rate,
                                                   annual_only=annual_only)
                    # Guard contra DataFrame vacio o sin columna 'value'
                    vals = ts["value"].tolist() if (not ts.empty and "value" in ts.columns) else []
                    s = compute_growth_stats(vals)
                    stat_rows.append({
                        "Metric": m,
                        "N periods": s["n"],
                        "CAGR":   f"{s['cagr']*100:+.2f}%" if s["n"] > 1 else "—",
                        "Peak":   f"{s['peak']:,.1f}" if s["n"] else "—",
                        "Trough": f"{s['trough']:,.1f}" if s["n"] else "—",
                        "Mean":   f"{s['mean']:,.1f}" if s["n"] else "—",
                        "Vol (CV)": f"{s['vol']:.2%}" if s['vol'] else "—",
                    })
                st.dataframe(pd.DataFrame(stat_rows), hide_index=True,
                              use_container_width=True)

    # ----- TAB Historical close, TAB Bloomberg Validation open -----
    tab_hist.__exit__(None, None, None)
    tab_valid.__enter__()

    st.subheader(f"Bloomberg 'As Reported' Validation — {issuer.ticker}")
    st.caption(
        "Compara los valores parseados del XBRL CNBV contra el Bloomberg 'As Reported'. "
        "Si los conceptos coinciden ⟹ el parser es fiel al reporte oficial. Las "
        "diferencias se clasifican: **OK** (<0.5%), **WARN** (0.5%-5%), **ERROR** (>5%)."
    )

    if not HAS_VALIDATION:
        st.error(f"Validation module no disponible: {_VAL_ERR}")
    elif issuer.ticker not in BLOOMBERG_MAPPINGS:
        st.warning(
            f"No hay mapping Bloomberg definido para **{issuer.ticker}**. "
            f"Hoy disponible: {list(BLOOMBERG_MAPPINGS.keys())}.\n\n"
            f"Para agregar este ticker:\n"
            f"1. Sube `Edos_{issuer.ticker.lower()}_anuales.xlsx` a `data/bloomberg/`\n"
            f"2. Crea `src/dcf_mexico/validation/mappings/{issuer.ticker.lower()}.py` "
            f"con el mapping de labels Bloomberg → parser fields."
        )
    else:
        bb_fp = find_bloomberg_file(issuer.ticker, "anuales")
        if bb_fp is None:
            st.error(
                f"No se encontro el Bloomberg Excel. Ponlo en: "
                f"`data/bloomberg/Edos_{issuer.ticker.lower()}_anuales.xlsx`"
            )
        else:
            st.caption(f"Bloomberg file: `{bb_fp.name}`")
            mappings_avail = BLOOMBERG_MAPPINGS[issuer.ticker]

            # UI controls
            colA, colB = st.columns([2, 1])
            with colA:
                sheet_pick = st.selectbox(
                    "Hoja a validar",
                    list(mappings_avail.keys()),
                    key=f"valid_sheet_{issuer.ticker}",
                )
            with colB:
                rel_tol = st.number_input(
                    "Tolerancia % (OK)",
                    min_value=0.001, max_value=0.10,
                    value=0.005, step=0.001, format="%.3f",
                    help="Diff abs(parser-bb)/bb por debajo = OK",
                )

            # Parse all CUERVO XBRL Q4 (preliminary annual)
            with st.spinner("Parseando XBRLs Q4 disponibles..."):
                files_all = find_all_xbrl(issuer.ticker)
                parsed_q4_by_year = {}
                for fp_x in files_all:
                    year_x, q_x = parse_period_tag(fp_x)
                    if q_x in ("4", "4D"):
                        try:
                            parsed_q4_by_year[year_x] = _parse_cached(str(fp_x))
                        except Exception:
                            continue

            if not parsed_q4_by_year:
                st.warning(
                    f"No hay XBRL anuales/Q4 parseables para {issuer.ticker} en `data/raw_xbrl/`. "
                    f"Necesitas archivos `ifrsxbrl_{issuer.ticker}_<YYYY>-4.xls` o `4D`."
                )
            else:
                st.caption(f"Anios parseados (Q4/4D): {sorted(parsed_q4_by_year.keys())}")

                results = compare_all_periods(
                    bb_fp, sheet_pick, mappings_avail[sheet_pick],
                    parsed_q4_by_year,
                    sheet_label=sheet_pick.split(" - ")[0],
                    fx_rate=market.fx_rate_usdmxn,
                )

                if not results:
                    st.warning(f"Ningun periodo coincide entre Bloomberg y XBRL para {sheet_pick}.")
                else:
                    # Period selector
                    period_pick = st.selectbox(
                        "Periodo a inspeccionar",
                        sorted(results.keys(), reverse=True),
                        key=f"valid_period_{issuer.ticker}",
                    )
                    res_pick = results[period_pick]

                    # Status KPIs
                    cs1, cs2, cs3, cs4 = st.columns(4)
                    cs1.metric("OK (<0.5% diff)",  res_pick.n_ok)
                    cs2.metric("WARN (0.5-5%)",    res_pick.n_warn)
                    cs3.metric("ERROR (>5%)",      res_pick.n_error)
                    cs4.metric("N/A",               res_pick.n_na)

                    # Table with color coding
                    tbl = res_pick.table.copy()
                    # Format columns
                    fmt_tbl = pd.DataFrame({
                        "Concept":     tbl["Concept"],
                        "Parser path": tbl["Parser path"],
                        "Bloomberg":   tbl["Bloomberg"].apply(
                            lambda v: f"{v:,.2f}" if v is not None and not pd.isna(v) else "—"),
                        "Parser":      tbl["Parser"].apply(
                            lambda v: f"{v:,.2f}" if v is not None and not pd.isna(v) else "—"),
                        "Diff abs":    tbl["Diff abs"].apply(
                            lambda v: f"{v:+,.2f}" if v is not None and not pd.isna(v) else "—"),
                        "Diff %":      tbl["Diff %"].apply(
                            lambda v: f"{v*100:+.4f}%" if v is not None and not pd.isna(v) else "—"),
                        "Status":      tbl["Status"],
                        "Notes":       tbl["Notes"],
                    })

                    def _status_style(row):
                        s = row["Status"]
                        if s == "OK":
                            return ["background-color: rgba(46, 160, 67, 0.25)"] * len(row)
                        if s == "WARN":
                            return ["background-color: rgba(245, 158, 11, 0.30)"] * len(row)
                        if s == "ERROR":
                            return ["background-color: rgba(218, 54, 51, 0.35)"] * len(row)
                        return ["background-color: rgba(120, 120, 120, 0.15)"] * len(row)

                    try:
                        styler = fmt_tbl.style.apply(_status_style, axis=1).hide(axis="index")
                        styler = styler.set_properties(**{"padding": "4px 8px"})
                        styler = styler.set_properties(
                            subset=["Bloomberg", "Parser", "Diff abs", "Diff %"],
                            **{"text-align": "right"})
                        st.dataframe(styler, use_container_width=True,
                                      height=min(800, 35 + 35 * len(fmt_tbl)))
                    except Exception:
                        st.dataframe(fmt_tbl, hide_index=True, use_container_width=True)

                    # Multi-period summary heatmap
                    st.markdown("### Resumen multi-periodo")
                    summary_rows = []
                    for p, r in sorted(results.items()):
                        total = r.n_ok + r.n_warn + r.n_error + r.n_na
                        summary_rows.append({
                            "Periodo": p,
                            "OK":     r.n_ok,
                            "WARN":   r.n_warn,
                            "ERROR":  r.n_error,
                            "N/A":    r.n_na,
                            "% OK":   f"{(r.n_ok / total * 100) if total else 0:.0f}%",
                        })
                    sum_df = pd.DataFrame(summary_rows)
                    st.dataframe(sum_df, hide_index=True, use_container_width=True)

                    # Errors detail
                    errors = tbl[tbl["Status"] == "ERROR"]
                    if not errors.empty:
                        st.markdown("### ERRORS detail (>5% diff)")
                        st.caption(
                            "Revisa estos. Comunmente son: D&A (Bloomberg incluye write-offs/amort intangibles), "
                            "diferencias de presentacion, o ajustes Non-GAAP."
                        )
                        st.dataframe(errors[["Concept", "Bloomberg", "Parser",
                                              "Diff %", "Notes"]],
                                      hide_index=True, use_container_width=True)

    # ----- TAB Bloomberg Validation close, TAB Valuation Output open -----
    tab_valid.__exit__(None, None, None)
    tab_val.__enter__()

    # ---- 1) Valuation Output (Damodaran-style wide projection) ----
    st.subheader("1. Valuation Output")
    st.caption("Damodaran-style wide projection: Base year | Y1-Y10 | Terminal year")

    # Compute per-year revenue growth (incluye base->Y1 y Y10->terminal)
    base_rev = base.revenue
    base_margin = base.ebit / base.revenue if base.revenue else 0
    base_tax = base.effective_tax_rate
    base_nopat = base.ebit * (1 - base_tax)

    # Use BS-based invested capital if available
    ic_base = base.invested_capital if base.invested_capital > 0 else (base.revenue / a.sales_to_capital if a.sales_to_capital > 0 else 1.0)
    base_roic = base_nopat / ic_base if ic_base > 0 else 0

    # Recompute IC series anchored on BS IC_0
    ic_series_bs = [ic_base]
    roic_series_bs = []
    for i in range(len(out.nopat)):
        roic_series_bs.append(out.nopat[i] / ic_series_bs[-1] if ic_series_bs[-1] > 0 else 0)
        ic_series_bs.append(ic_series_bs[-1] + out.reinvestment[i])

    # Terminal year values
    rev_t = out.revenue[-1] * (1 + a.terminal_growth)
    margin_t = a.target_op_margin
    ebit_t = rev_t * margin_t
    tax_t = a.marginal_tax_terminal
    nopat_t = ebit_t * (1 - tax_t)
    delta_rev_t = rev_t - out.revenue[-1]
    reinv_t = delta_rev_t / a.sales_to_capital if a.sales_to_capital > 0 else 0
    fcff_t = out.terminal_fcff
    ic_t = ic_series_bs[-1] + reinv_t
    roic_t = nopat_t / ic_series_bs[-1] if ic_series_bs[-1] > 0 else 0

    # Revenue growth per year
    rev_growth_per_year = []
    rev_seq = [base_rev] + list(out.revenue) + [rev_t]
    for i in range(1, len(rev_seq)):
        g = (rev_seq[i] / rev_seq[i-1] - 1) if rev_seq[i-1] else 0
        rev_growth_per_year.append(g)
    # rev_growth_per_year[0..9] = Y1..Y10 growth, rev_growth_per_year[10] = Terminal growth

    year_cols = ["Base year"] + [str(i) for i in range(1, 11)] + ["Terminal year"]

    def _pct(v):  return f"{v*100:.2f}%" if v is not None else "—"
    def _num(v):  return f"{v:,.2f}" if v is not None else "—"

    # Build wide table - Damodaran exact rows
    wide_rows = [
        {"Concepto": "Revenue growth rate", **dict(zip(year_cols,
            [""] + [_pct(g) for g in rev_growth_per_year[:10]] + [_pct(rev_growth_per_year[10])]))},
        {"Concepto": "Revenues", **dict(zip(year_cols,
            [_num(base_rev)] + [_num(v) for v in out.revenue] + [_num(rev_t)]))},
        {"Concepto": "EBIT (Operating) margin", **dict(zip(year_cols,
            [_pct(base_margin)] + [_pct(v) for v in out.op_margin] + [_pct(margin_t)]))},
        {"Concepto": "EBIT (Operating income)", **dict(zip(year_cols,
            [_num(base.ebit)] + [_num(v) for v in out.ebit] + [_num(ebit_t)]))},
        {"Concepto": "Tax rate", **dict(zip(year_cols,
            [_pct(base_tax)] + [_pct(v) for v in out.tax_rate] + [_pct(tax_t)]))},
        {"Concepto": "EBIT(1-t)", **dict(zip(year_cols,
            [_num(base_nopat)] + [_num(v) for v in out.nopat] + [_num(nopat_t)]))},
        {"Concepto": " - Reinvestment", **dict(zip(year_cols,
            [""] + [_num(v) for v in out.reinvestment] + [_num(reinv_t)]))},
        {"Concepto": "FCFF", **dict(zip(year_cols,
            [""] + [_num(v) for v in out.fcff] + [_num(fcff_t)]))},
        {"Concepto": "NOL", **dict(zip(year_cols,
            ["—"] + ["—"]*10 + ["—"]))},
        {"Concepto": "", **dict(zip(year_cols, [""]*12))},
        {"Concepto": "Cost of capital", **dict(zip(year_cols,
            [""] + [_pct(v) for v in out.wacc_yearly] + [_pct(out.terminal_wacc)]))},
        {"Concepto": "Cumulated discount factor", **dict(zip(year_cols,
            [""] + [f"{v:.4f}" for v in out.discount_factor] + [""]))},
        {"Concepto": "PV(FCFF)", **dict(zip(year_cols,
            [""] + [_num(v) for v in out.pv_fcff] + [""]))},
    ]
    wide_df = pd.DataFrame(wide_rows)

    # Damodaran-style green styling
    def _style_damodaran_wide(df):
        styler = df.style
        # Highlight key rows
        def _row_highlight(row):
            concept = row.get("Concepto", "")
            if concept in ("Revenues", "EBIT (Operating income)", "FCFF", "PV(FCFF)"):
                return ["background-color: #DCEDC8; font-weight: 600;"] * len(row)
            if concept in ("Revenue growth rate", "EBIT (Operating) margin", "Tax rate", "Cost of capital"):
                return ["background-color: #F1F8E9;"] * len(row)
            if concept == "":
                return ["background-color: white;"] * len(row)
            return ["background-color: #F9FBF7;"] * len(row)
        styler = styler.apply(lambda r: _row_highlight(df.iloc[r.name]), axis=1)
        styler = styler.set_properties(**{"text-align": "right", "padding": "4px 8px"})
        styler = styler.set_properties(subset=["Concepto"], **{"text-align": "left", "font-weight": "500"})
        styler = styler.hide(axis="index")
        return styler

    try:
        st.dataframe(_style_damodaran_wide(wide_df),
                      use_container_width=True,
                      height=35 + 35 * len(wide_df))
    except Exception:
        st.dataframe(wide_df, hide_index=True, use_container_width=True)

    # ---- Bridge / Valuation summary (left) + Implied variables (bottom) ----
    bcol1, bcol2 = st.columns([1, 1])
    with bcol1:
        st.markdown("**Valuation Bridge**")
        net_debt = base.financial_debt - base.cash
        equity_value = out.equity_value
        bridge_rows = [
            ("Terminal cash flow",         f"{out.terminal_fcff:,.2f}"),
            ("Terminal cost of capital",   f"{out.terminal_wacc*100:.2f}%"),
            ("Terminal value",             f"{out.terminal_value:,.2f}"),
            ("PV(Terminal value)",         f"{out.pv_terminal:,.2f}"),
            ("PV (CF over next 10 years)", f"{out.sum_pv_fcff:,.2f}"),
            ("Sum of PV",                  f"{out.enterprise_value:,.2f}"),
            ("Probability of failure",     "0.00%"),
            ("Proceeds if firm fails",     f"{0.5 * base.equity_book:,.2f}"),
            ("Value of operating assets",  f"{out.enterprise_value:,.2f}"),
            (" - Debt",                    f"{base.financial_debt:,.2f}"),
            (" - Minority interests",      f"{base.minority_interest:,.2f}"),
            (" + Cash",                    f"{base.cash:,.2f}"),
            (" + Non-operating assets",    f"{base.non_operating_assets:,.2f}"),
            ("Value of equity",            f"{equity_value:,.2f}"),
            (" - Value of options",        "0.00"),
            ("Value of equity in common",  f"{equity_value:,.2f}"),
            ("Number of shares (mn)",      f"{base.shares_outstanding/1e6:,.2f}"),
            ("Estimated value /share",     f"{out.value_per_share:,.2f}"),
            ("Price",                      f"{a.market_price:,.2f}" if a.market_price else "—"),
            ("Price as % of value",        f"{(a.market_price/out.value_per_share*100):.2f}%" if (a.market_price and out.value_per_share) else "—"),
        ]
        bridge_df = pd.DataFrame(bridge_rows, columns=["Concepto", "Valor (MDP / MXN)"])
        # Styling
        def _bridge_style(row):
            c = row["Concepto"]
            if c in ("Sum of PV", "Value of operating assets", "Value of equity",
                     "Value of equity in common", "Estimated value /share"):
                return ["background-color: #DCEDC8; font-weight: 600;"] * len(row)
            return ["background-color: #F9FBF7;"] * len(row)
        try:
            styler = bridge_df.style.apply(_bridge_style, axis=1).hide(axis="index")
            styler = styler.set_properties(**{"padding": "4px 8px"})
            styler = styler.set_properties(subset=["Valor (MDP / MXN)"], **{"text-align": "right"})
            st.dataframe(styler, use_container_width=True, height=35 + 35 * len(bridge_df))
        except Exception:
            st.dataframe(bridge_df, hide_index=True, use_container_width=True)

    with bcol2:
        st.markdown("**Annotations**")
        st.info(
            f"📈 **Operating income growth (10y):** {(out.ebit[-1] - base.ebit):+,.0f} MDP\n\n"
            f"This is how much your operating income grew over the ten-year period."
        )
        st.info(
            f"💰 **Capital invested (10y):** {sum(out.reinvestment):+,.0f} MDP\n\n"
            f"This is how much capital you invested over the ten year period."
        )
        st.warning(
            f"⚠️ **Check these revenues against:**\n"
            f"a. Overall market size\n"
            f"b. Largest companies in this market\n\n"
            f"Y10 Revenue projected: **{out.revenue[-1]:,.0f} MDP**"
        )

    # Implied variables sub-table (Sales-to-capital, Invested capital, ROIC)
    st.markdown("**Implied variables**")
    implied_cols = [str(i) for i in range(1, 11)] + ["After year 10"]
    implied_rows = [
        {"Concepto": "Sales to capital ratio",
         **dict(zip(implied_cols, [f"{a.sales_to_capital:.2f}"] * 11))},
        {"Concepto": "Invested capital",
         **dict(zip(implied_cols,
            [_num(ic_series_bs[i]) for i in range(1, 11)] + [_num(ic_t)]))},
        {"Concepto": "ROIC",
         **dict(zip(implied_cols,
            [_pct(roic_series_bs[i]) for i in range(10)] + [_pct(roic_t)]))},
    ]
    implied_df = pd.DataFrame(implied_rows)

    def _style_implied(df):
        styler = df.style.set_properties(**{"text-align": "right", "padding": "4px 8px"})
        styler = styler.set_properties(subset=["Concepto"], **{"text-align": "left", "font-weight": "500"})
        styler = styler.hide(axis="index")
        return styler.apply(lambda r: ["background-color: #F1F8E9;"] * len(r), axis=1)

    try:
        st.dataframe(_style_implied(implied_df), use_container_width=True, height=35 + 35 * 3)
    except Exception:
        st.dataframe(implied_df, hide_index=True, use_container_width=True)

    # KPI strip
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("PV FCFF (10y)",  f"{out.sum_pv_fcff:,.0f} MDP")
    k2.metric("PV Terminal",    f"{out.pv_terminal:,.0f} MDP",
              f"{out.pv_terminal/out.enterprise_value*100:.0f}% del EV")
    k3.metric("Enterprise Value", f"{out.enterprise_value:,.0f} MDP")
    k4.metric("Equity Value", f"{out.equity_value:,.0f} MDP",
              f"{out.value_per_share:.2f} MXN/sh")

    # ----- TAB 1 close, TAB 2 open -----
    tab_val.__exit__(None, None, None)
    tab_stories.__enter__()

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

    # ---- Damodaran "The Assumptions" table ----
    st.markdown("##### The Assumptions")
    company_story_short = f"{issuer.name} continues operations in {sector.name}."
    assumption_rows = [
        ("Revenues (a)",
         f"{base.revenue:,.0f}",
         f"{a.revenue_growth_high*100:.1f}%",
         f"{a.revenue_growth_high*100:.1f}%",
         "Changes to",
         f"{a.terminal_growth*100:.2f}%",
         "Sustained growth driven by sector dynamics"),
        ("Operating margin (b)",
         f"{base.ebit/base.revenue*100:.2f}%" if base.revenue else "—",
         f"{(base.ebit/base.revenue + (a.target_op_margin - base.ebit/base.revenue)/10)*100:.1f}%" if base.revenue else "—",
         "Moves to",
         f"{a.target_op_margin*100:.2f}%",
         f"{a.target_op_margin*100:.2f}%",
         "Margin convergence to sector target"),
        ("Tax rate",
         f"{base.effective_tax_rate*100:.2f}%",
         f"{base.effective_tax_rate*100:.2f}%",
         f"{base.effective_tax_rate*100:.2f}%",
         "Changes to",
         f"{a.marginal_tax_terminal*100:.2f}%",
         "Marginal MX tax rate over time"),
        ("Sales to Capital (c)",
         "—",
         f"{a.sales_to_capital:.2f}",
         f"{a.sales_to_capital:.2f}",
         f"{a.sales_to_capital:.2f}",
         f"{a.sales_to_capital:.2f}",
         "Maintained at current capital efficiency"),
        ("Return on capital",
         f"{(base.ebit*(1-base.effective_tax_rate))/ic_base*100:.2f}%" if ic_base else "—",
         "Marginal ROIC =",
         f"{a.target_op_margin*(1-a.marginal_tax_terminal)*a.sales_to_capital*100:.2f}%",
         "",
         f"{wacc_terminal*100:.2f}%",
         "Strong competitive edges drive value"),
        ("Cost of capital (d)",
         "",
         f"{out.wacc_result.wacc*100:.2f}%",
         f"{out.wacc_result.wacc*100:.2f}%",
         "Changes to",
         f"{wacc_terminal*100:.2f}%",
         "Cost of capital fades to mature company level"),
    ]
    assumptions_df = pd.DataFrame(assumption_rows, columns=[
        "", "Base year", "Next year", "Years 2-5", "Years 6-10", "After year 10", "Link to story"
    ])
    try:
        styler = assumptions_df.style.apply(
            lambda r: ["background-color: #F1F8E9;"] * len(r), axis=1
        ).hide(axis="index")
        styler = styler.set_properties(**{"padding": "4px 8px"})
        st.dataframe(styler, use_container_width=True,
                      height=35 + 35 * len(assumptions_df))
    except Exception:
        st.dataframe(assumptions_df, hide_index=True, use_container_width=True)

    # ---- Damodaran "The Cash Flows" table ----
    st.markdown("##### The Cash Flows")
    cf_rows = []
    for i in range(len(out.years)):
        cf_rows.append({
            "Year":             str(out.years[i]),
            "Revenues":         f"{out.revenue[i]:,.2f}",
            "Operating Margin": f"{out.op_margin[i]*100:.2f}%",
            "EBIT":             f"{out.ebit[i]:,.2f}",
            "EBIT (1-t)":       f"{out.nopat[i]:,.2f}",
            "Reinvestment":     f"{out.reinvestment[i]:,.2f}",
            "FCFF":             f"{out.fcff[i]:,.2f}",
        })
    cf_rows.append({
        "Year":             "Terminal year",
        "Revenues":         f"{rev_t:,.2f}",
        "Operating Margin": f"{margin_t*100:.2f}%",
        "EBIT":             f"{ebit_t:,.2f}",
        "EBIT (1-t)":       f"{nopat_t:,.2f}",
        "Reinvestment":     f"{reinv_t:,.2f}",
        "FCFF":             f"{fcff_t:,.2f}",
    })
    cf_df = pd.DataFrame(cf_rows)
    try:
        styler = cf_df.style.apply(
            lambda r: (["background-color: #DCEDC8; font-weight: 600;"] * len(r)
                       if r["Year"] == "Terminal year"
                       else ["background-color: #F9FBF7;"] * len(r)),
            axis=1,
        ).hide(axis="index")
        styler = styler.set_properties(**{"text-align": "right", "padding": "4px 8px"})
        styler = styler.set_properties(subset=["Year"], **{"text-align": "left", "font-weight": "500"})
        st.dataframe(styler, use_container_width=True, height=35 + 35 * len(cf_df))
    except Exception:
        st.dataframe(cf_df, hide_index=True, use_container_width=True)

    # ---- Damodaran "The Value" table ----
    st.markdown("##### The Value")
    value_rows = [
        ("Terminal value",                            f"{out.terminal_value:,.2f}", ""),
        ("PV(Terminal value)",                        f"{out.pv_terminal:,.2f}", ""),
        ("PV (CF over next 10 years)",                f"{out.sum_pv_fcff:,.2f}", ""),
        ("Value of operating assets =",               f"{out.enterprise_value:,.2f}", ""),
        ("Adjustment for distress",                   "0.00", "Probability of failure = 0.00%"),
        (" - Debt & Minority Interests",              f"{base.financial_debt + base.minority_interest:,.2f}", ""),
        (" + Cash & Other Non-operating assets",      f"{base.cash + base.non_operating_assets:,.2f}", ""),
        ("Value of equity",                           f"{out.equity_value:,.2f}", ""),
        (" - Value of equity options",                "0.00", ""),
        ("Number of shares (mn)",                     f"{base.shares_outstanding/1e6:,.2f}", ""),
        ("Value per share (MXN)",                     f"{out.value_per_share:,.2f}",
         f"Stock was trading at = {a.market_price:,.2f}" if a.market_price else ""),
    ]
    value_df = pd.DataFrame(value_rows, columns=["Concepto", "Valor", "Nota"])

    def _value_style(row):
        c = row["Concepto"]
        if c in ("Value of operating assets =", "Value of equity", "Value per share (MXN)"):
            return ["background-color: #1F4E79; color: white; font-weight: 700;"] * len(row)
        return ["background-color: #F9FBF7;"] * len(row)

    try:
        styler = value_df.style.apply(_value_style, axis=1).hide(axis="index")
        styler = styler.set_properties(**{"padding": "4px 8px"})
        styler = styler.set_properties(subset=["Valor"], **{"text-align": "right"})
        st.dataframe(styler, use_container_width=True, height=35 + 35 * len(value_df))
    except Exception:
        st.dataframe(value_df, hide_index=True, use_container_width=True)

    # ----- TAB 2 close, TAB 3 open -----
    tab_stories.__exit__(None, None, None)
    tab_pic.__enter__()

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

    # ---- Damodaran Picture-style summary (Image 3 layout) ----
    st.markdown("##### Picture-style Valuation Summary")

    pic_col1, pic_col2 = st.columns([1, 2])

    # LEFT: Base Year & Comparison + Bridge
    with pic_col1:
        st.markdown("**Base Year and Comparison**")
        comp_rows = [
            ("Revenue Growth",   f"{res.dcf.revenue_growth*100:.2f}%",   f"{a.revenue_growth_high*100:.2f}%"),
            ("Revenue (MDP)",    f"{base.revenue:,.0f}",                  "—"),
            ("Operating Margin", f"{base.ebit/base.revenue*100:.2f}%" if base.revenue else "—",
                                  f"{a.target_op_margin*100:.2f}%"),
            ("Operating Income", f"{base.ebit:,.0f}",                     "—"),
            ("EBIT (1-t)",       f"{base.ebit*(1-base.effective_tax_rate):,.0f}", "—"),
        ]
        comp_df = pd.DataFrame(comp_rows, columns=["Concepto", "Company", "Sector target"])
        try:
            styler = comp_df.style.apply(
                lambda r: ["background-color: #F1F8E9;"] * len(r), axis=1
            ).hide(axis="index")
            styler = styler.set_properties(**{"padding": "4px 8px"})
            st.dataframe(styler, use_container_width=True, height=35 + 35 * len(comp_df))
        except Exception:
            st.dataframe(comp_df, hide_index=True, use_container_width=True)

        st.markdown("**Equity Bridge**")
        net_debt = base.financial_debt - base.cash
        bridge_rows = [
            ("PV(Terminal value)",         f"{out.pv_terminal:,.0f}"),
            ("PV (CF over next 10 years)", f"{out.sum_pv_fcff:,.0f}"),
            ("Probability of failure",     "0.00%"),
            ("Value of operating assets =",f"{out.enterprise_value:,.0f}"),
            (" - Debt",                    f"{base.financial_debt:,.0f}"),
            (" - Minority interests",      f"{base.minority_interest:,.0f}"),
            (" + Cash",                    f"{base.cash:,.0f}"),
            (" + Non-operating assets",    f"{base.non_operating_assets:,.0f}"),
            ("Value of equity",            f"{out.equity_value:,.0f}"),
            (" - Value of options",        "0"),
            ("Value of equity in common",  f"{out.equity_value:,.0f}"),
            ("Number of shares (mn)",      f"{base.shares_outstanding/1e6:,.2f}"),
            ("Estimated value /share",     f"{out.value_per_share:,.2f}"),
        ]
        bridge_pic_df = pd.DataFrame(bridge_rows, columns=["Concepto", "MDP / MXN"])

        def _pic_bridge_style(row):
            c = row["Concepto"]
            if c in ("Value of operating assets =", "Value of equity",
                     "Value of equity in common", "Estimated value /share"):
                return ["background-color: #1F4E79; color: white; font-weight: 700;"] * len(row)
            return ["background-color: #F9FBF7;"] * len(row)
        try:
            styler = bridge_pic_df.style.apply(_pic_bridge_style, axis=1).hide(axis="index")
            styler = styler.set_properties(**{"padding": "4px 8px"})
            styler = styler.set_properties(subset=["MDP / MXN"], **{"text-align": "right"})
            st.dataframe(styler, use_container_width=True, height=35 + 35 * len(bridge_pic_df))
        except Exception:
            st.dataframe(bridge_pic_df, hide_index=True, use_container_width=True)

        # Verdict
        if a.market_price:
            verdict_pct = (a.market_price / out.value_per_share - 1) * 100 if out.value_per_share else 0
            verdict_color = "#DA3633" if verdict_pct > 0 else "#2EA043"
            st.markdown(
                f"<div style='background-color:{verdict_color};color:white;padding:10px;"
                f"border-radius:6px;font-weight:700;text-align:center;'>"
                f"Price per share: {a.market_price:,.2f}  |  "
                f"% Under/Over Valued: {verdict_pct:+.2f}%</div>",
                unsafe_allow_html=True,
            )

    # RIGHT: Stories (text boxes) + Big projection table
    with pic_col2:
        st.markdown("**Story panels**")
        sb1, sb2, sb3 = st.columns(3)
        with sb1:
            st.info(f"**Growth Story**\n\n"
                     f"{a.revenue_growth_high*100:.1f}% growth driven by "
                     f"{sector.name} dynamics and market share gains.")
        with sb2:
            st.info(f"**Profitability Story**\n\n"
                     f"Margins {'improve' if a.target_op_margin > base.ebit/base.revenue else 'sustain'} "
                     f"toward {a.target_op_margin*100:.1f}% by Y10.")
        with sb3:
            st.info(f"**Growth Efficiency Story**\n\n"
                     f"Sales-to-Capital of {a.sales_to_capital:.2f} reflects "
                     f"{'capital-light' if a.sales_to_capital > 2.5 else 'capital-intensive' if a.sales_to_capital < 1 else 'mid-range'} model.")

        st.markdown("**Big Projection (Y1-Y10 + Terminal)**")
        big_rows = [
            ("Revenue Growth",   [_pct(g) for g in rev_growth_per_year[:10]] + [_pct(rev_growth_per_year[10])]),
            ("Revenue",          [_num(v) for v in out.revenue] + [_num(rev_t)]),
            ("Operating Margin", [_pct(v) for v in out.op_margin] + [_pct(margin_t)]),
            ("Operating Income", [_num(v) for v in out.ebit] + [_num(ebit_t)]),
            ("EBIT (1-t)",       [_num(v) for v in out.nopat] + [_num(nopat_t)]),
            ("Reinvestment",     [_num(v) for v in out.reinvestment] + [_num(reinv_t)]),
            ("FCFF",             [_num(v) for v in out.fcff] + [_num(fcff_t)]),
            ("Cost of Capital",  [_pct(v) for v in out.wacc_yearly] + [_pct(out.terminal_wacc)]),
            ("Cumulated WACC",   [f"{v:.4f}" for v in out.discount_factor] + [""]),
            ("Sales to Capital", [f"{a.sales_to_capital:.2f}"] * 10 + [""]),
            ("ROIC",             [_pct(roic_series_bs[i]) for i in range(10)] + [_pct(roic_t)]),
        ]
        big_data = []
        for label, vals in big_rows:
            big_data.append({"Concepto": label, **dict(zip(year_cols[1:], vals))})
        big_df = pd.DataFrame(big_data)

        def _big_style(row):
            c = row["Concepto"]
            if c in ("Revenue", "Operating Income", "FCFF"):
                return ["background-color: #DCEDC8; font-weight: 600;"] * len(row)
            return ["background-color: #F9FBF7;"] * len(row)

        try:
            styler = big_df.style.apply(_big_style, axis=1).hide(axis="index")
            styler = styler.set_properties(**{"text-align": "right", "padding": "4px 8px",
                                                "font-size": "11px"})
            styler = styler.set_properties(subset=["Concepto"],
                                              **{"text-align": "left", "font-weight": "500"})
            st.dataframe(styler, use_container_width=True,
                          height=35 + 32 * len(big_df))
        except Exception:
            st.dataframe(big_df, hide_index=True, use_container_width=True)

        # Risk Story / Competitive Advantages
        rs1, rs2 = st.columns(2)
        with rs1:
            st.warning(f"**Risk Story**\n\n"
                        f"WACC {out.wacc_result.wacc*100:.2f}% reflects synthetic rating "
                        f"{out.wacc_result.rating} with interest coverage "
                        f"{out.wacc_result.interest_coverage:.1f}x.")
        with rs2:
            spread = roic_terminal - wacc_terminal
            st.success(f"**Competitive Advantages**\n\n"
                        f"ROIC vs WACC spread: {spread*10000:+.0f}bps. "
                        f"{'Strong' if spread > 0.03 else 'Modest' if spread > 0 else 'Negative'} "
                        f"competitive moat.")

    # ----- TAB 3 close, TAB 4 (Sensitivity) open -----
    tab_pic.__exit__(None, None, None)
    tab_sens.__enter__()

    st.subheader("Sensitivity Analysis")
    st.caption("El tornado y el heatmap originales viven en este tab. La proyeccion FCFF y el tornado de arriba son redundantes.")
    st.markdown("**Tornado por driver:** ver impacto en value/share de mover cada driver low/high.")
    sens_torn = tornado(base, a)
    st.altair_chart(_tornado_chart(sens_torn), use_container_width=True)
    with st.expander("Tabla tornado"):
        st.dataframe(sens_torn, hide_index=True, use_container_width=True)
    st.divider()

    # ----- TAB 4 close, TAB 5 (DuPont) open -----
    tab_sens.__exit__(None, None, None)
    tab_dupont.__enter__()

    st.subheader("DuPont Analysis")
    st.caption("Descomposicion del ROE en sus componentes (3-step + 5-step extended).")

    try:
        if not HAS_DUPONT:
            raise ImportError(f"DuPont module not available: {_DUPONT_ERR}")
        # Calcular FX multiplier para emisoras USD
        currency = (res.info.currency or "MXN").upper().strip()
        fx_mult = market.fx_rate_usdmxn if currency == "USD" else 1.0
        # DuPont siempre con balance del periodo actual
        dp = dupont_from_parser(res, currency_multiplier=fx_mult / 1e6)  # convertir a MDP
        dp_table = dp.to_table()

        col_dp1, col_dp2 = st.columns([1, 1])
        with col_dp1:
            st.markdown("**Decomposition**")
            try:
                styler = dp_table.style.apply(
                    lambda r: (["background-color: #DCEDC8; font-weight: 700;"] * len(r)
                                if r["Component"].startswith("=") or r["Component"].startswith("---")
                                else ["background-color: #F9FBF7;"] * len(r)),
                    axis=1,
                ).hide(axis="index")
                styler = styler.set_properties(**{"padding": "4px 8px"})
                st.dataframe(styler, use_container_width=True, height=35 + 32 * len(dp_table))
            except Exception:
                st.dataframe(dp_table, hide_index=True, use_container_width=True)

        with col_dp2:
            st.markdown("**Components chart**")
            comp_df = dp.to_components()
            comp_df["Display"] = comp_df.apply(
                lambda r: f"{r['Value']:.2%}" if r["Type"] == "Pct" else f"{r['Value']:.3f}x",
                axis=1,
            )
            st.dataframe(comp_df[["Component", "Display"]], hide_index=True,
                          use_container_width=True)
            st.metric("ROE (5-step DuPont)", f"{dp.roe_5step:.2%}",
                      f"vs ROA {dp.roa:.2%}  |  ROIC {dp.roic:.2%}")
            if abs(dp.consistency_pp) > 0.001:
                st.warning(f"Consistency check off by {dp.consistency_pp*100:+.4f}pp")
            else:
                st.success("Consistency check OK (5-step product = ROE actual)")

        st.markdown("---")
        st.markdown("**Como leer DuPont:**")
        st.markdown(f"""
- **Tax Burden** ({dp.tax_burden:.2%}): que fraccion de la utilidad pre-tax queda despues de impuestos. <100% siempre.
- **Interest Burden** ({dp.interest_burden:.2%}): que fraccion del EBIT queda despues del costo financiero. >100% si hay otros ingresos no operativos netos positivos.
- **EBIT Margin** ({dp.ebit_margin:.2%}): margen operativo. Driver de profitabilidad pura.
- **Asset Turnover** ({dp.asset_turnover:.3f}x): cuantos pesos de venta genera cada peso de activos. Driver de eficiencia.
- **Equity Multiplier** ({dp.equity_multiplier:.3f}x): apalancamiento (assets/equity). >1 = uso de deuda.
""")
    except Exception as e:
        st.error(f"DuPont no disponible para esta emisora: {e}")

    # ----- TAB 5 close, TAB 6 (Diagnostics) open -----
    tab_dupont.__exit__(None, None, None)
    tab_diag.__enter__()

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

    # ----- TAB 6 close, jump back to Sensitivity tab to add heatmap -----
    tab_diag.__exit__(None, None, None)

    # Re-enter Sensitivity to add the heatmap (it logically belongs here)
    tab_sens.__enter__()
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

    # ----- TAB Sensitivity close, TAB Download Excel open -----
    tab_sens.__exit__(None, None, None)
    tab_dl.__enter__()

    st.subheader("Download DCF as Excel (con formulas reales)")
    st.caption(
        "Genera un .xlsx con 4 hojas: **Inputs** (drivers editables verde), "
        "**Projection** (proyeccion 10y con formulas live), **Bridge** "
        "(EV → Equity → Value/share) y **Audit** (compara Excel vs Python). "
        "Edita las celdas verdes y todo el modelo recalcula."
    )

    try:
        if not HAS_EXCEL_EXPORT:
            raise ImportError(f"Excel export not available: {_EXCEL_ERR}")
        excel_bytes = export_dcf_to_excel(base, a, out)
        st.download_button(
            label=f"📥 Descargar DCF Excel — {issuer.ticker}",
            data=excel_bytes,
            file_name=f"DCF_{issuer.ticker}_{res.info.period_end}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )
        st.success(
            "Estructura del Excel:\n"
            "1. **Inputs** — celdas verde claro = editables (Revenue growth, target margin, S2C, WACC, Rf, ERP, etc.).\n"
            "2. **Projection** — proyeccion 10y con FORMULAS reales (no valores estaticos). Cambia un input y todo recalcula.\n"
            "3. **Bridge** — Sum PV → Terminal Value → EV → Equity → Value/share.\n"
            "4. **Audit** — diffs entre Excel formulas y Python output. Idealmente cerca de 0."
        )
    except Exception as e:
        st.error(f"Error generando Excel: {e}")

    # ---- Per-year override (advanced) ----
    st.divider()
    st.subheader("Advanced: Per-year override")
    st.caption(
        "Por defecto, el modelo usa una **curva smooth** (revenue growth constante Y1-5, "
        "fade lineal Y6-10). Si quieres editar cada año por separado, activa per-year mode "
        "y edita los valores en la tabla. Los cambios solo aplican en la proxima ejecucion del modelo."
    )

    with st.expander("Editar drivers año por año (sobrescriben curva smooth)", expanded=False):
        st.markdown("Pega o edita los valores. Si dejas vacio, usa la curva smooth.")
        n = a.forecast_years
        years = list(range(1, n + 1))

        # Default values from current smooth curve
        default_growth = []
        for t in years:
            if t <= a.high_growth_years:
                default_growth.append(a.revenue_growth_high)
            else:
                step = t - a.high_growth_years
                steps_remaining = n - a.high_growth_years
                default_growth.append(
                    a.revenue_growth_high + (a.terminal_growth - a.revenue_growth_high) * step / steps_remaining
                )

        base_margin_v = base.ebit / base.revenue if base.revenue else 0
        default_margin = [base_margin_v + (a.target_op_margin - base_margin_v) * t / n for t in years]
        default_tax = [base.effective_tax_rate + (a.marginal_tax_terminal - base.effective_tax_rate) * t / n for t in years]
        default_wacc = list(out.wacc_yearly)

        py_df = pd.DataFrame({
            "Year": years,
            "Revenue growth": default_growth,
            "Op margin":     default_margin,
            "Tax rate":      default_tax,
            "WACC":          default_wacc,
        })
        edited = st.data_editor(
            py_df,
            num_rows="fixed",
            column_config={
                "Year": st.column_config.NumberColumn("Year", disabled=True),
                "Revenue growth": st.column_config.NumberColumn("Revenue growth", format="%.4f", min_value=-0.50, max_value=0.50),
                "Op margin":      st.column_config.NumberColumn("Op margin", format="%.4f", min_value=-0.20, max_value=0.80),
                "Tax rate":       st.column_config.NumberColumn("Tax rate", format="%.4f", min_value=0.0, max_value=0.50),
                "WACC":           st.column_config.NumberColumn("WACC", format="%.4f", min_value=0.04, max_value=0.30),
            },
            use_container_width=True,
            key="per_year_editor",
        )

        if st.button("Aplicar per-year override y re-valuar"):
            a_override = DCFAssumptions(
                revenue_growth_high=a.revenue_growth_high,
                terminal_growth=a.terminal_growth,
                target_op_margin=a.target_op_margin,
                sales_to_capital=a.sales_to_capital,
                effective_tax_base=a.effective_tax_base,
                marginal_tax_terminal=a.marginal_tax_terminal,
                risk_free=a.risk_free,
                erp=a.erp,
                unlevered_beta=a.unlevered_beta,
                terminal_wacc_override=a.terminal_wacc_override,
                market_price=a.market_price,
                revenue_growth_per_year=edited["Revenue growth"].tolist(),
                op_margin_per_year=edited["Op margin"].tolist(),
                tax_rate_per_year=edited["Tax rate"].tolist(),
                wacc_per_year=edited["WACC"].tolist(),
            )
            out_override = project_company(base, a_override)
            st.metric(
                "Value/share (override per-year)",
                f"{out_override.value_per_share:,.2f} MXN",
                f"{(out_override.value_per_share / out.value_per_share - 1)*100:+.2f}% vs smooth",
            )
            st.dataframe(out_override.projection_table(), hide_index=True, use_container_width=True)

    tab_dl.__exit__(None, None, None)


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
