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
        build_income_panel,
        build_bs_panel,
        build_cf_panel,
        format_panel,
        build_income_adjusted_panel,
        build_bs_standardized_panel,
        build_cf_standardized_panel,
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
# AUTO-RESTORE de XBRLs persistidos en session_state al inicio de la app
# (Streamlit Cloud filesystem es efímero — se borra entre reruns/deploys)
# ---------------------------------------------------------------------------
if "uploaded_xbrls" not in st.session_state:
    st.session_state["uploaded_xbrls"] = {}

# Re-escribir a disco TODOS los archivos persistidos en session_state si no existen
_raw_dir = ROOT / "data" / "raw_xbrl"
_raw_dir.mkdir(parents=True, exist_ok=True)
for _fname, _fbytes in st.session_state["uploaded_xbrls"].items():
    _fpath = _raw_dir / _fname
    if not _fpath.exists():
        try:
            _fpath.write_bytes(_fbytes)
        except Exception:
            pass


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
# Cache  (versionado para invalidar tras cambios de schema)
# ---------------------------------------------------------------------------
_PARSE_CACHE_VERSION = "v11-cf-bb-reclass"   # bump cuando cambies ParseResult schema

@st.cache_data(show_spinner=False)
def _parse_cached(filepath: str, _v: str = _PARSE_CACHE_VERSION):
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

    period_label = f"FY {res.info.fiscal_year}" if res.info.fiscal_year else "Period"
    # NOTA: Snapshot financiero ahora vive dentro del tab '📷 Snapshot'
    # NOTA: Bloomberg single-period sheets viven dentro del tab "Estados Financieros".

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

    # ========================================================================
    # TABS DEFINITION (movida desde abajo - ahora la pagina arranca con tabs)
    # ========================================================================
    # ============================================================
    # ESTRUCTURA DE TABS:
    #   - 1 tab padre "💎 DCF Damodaran" agrupa 7 sub-tabs (Input Sheet,
    #     Cost of Capital, Proyección FCFF, Valuation Output, Stories,
    #     Valuation as Picture, Sensitivity)
    #   - El resto de tabs (Estados, Historical, Bloomberg, etc.) viven
    #     al nivel principal sin cambios
    # ============================================================
    (tab_snapshot, tab_inputs_sug, tab_quality, tab_dcf,
     tab_estados, tab_hist, tab_valid, tab_forecast, tab_intel,
     tab_dupont, tab_ratios, tab_diag, tab_dl) = st.tabs([
        "📷 Snapshot",
        "💡 Inputs Sugeridos",
        "🎯 Quality Audit + Scenarios",
        "💎 DCF Damodaran",            # ← TAB PADRE consolidado
        # Otros tabs:
        "📊 Estados Financieros",
        "📅 Historical",
        "🔍 Bloomberg Validation",
        "🔮 Forecast EEFF",
        "🎙️ Investor Intel",
        "🔗 DuPont",
        "📐 Ratios & Metrics",
        "✅ Diagnostics",
        "💾 Download Excel",
    ])

    # Sub-tabs dentro de DCF Damodaran (orden estilo Damodaran fcffsimpleginzu)
    with tab_dcf:
        (sub_input, sub_coc, sub_proj, sub_val,
         sub_stories, sub_pic, sub_sens, sub_worksheets) = st.tabs([
            "📋 1. Input Sheet",
            "💰 2. Cost of Capital",
            "📈 3. Proyección FCFF",
            "🎯 4. Valuation Output",
            "📖 5. Stories to Numbers",
            "🎨 6. Valuation as Picture",
            "📊 7. Sensitivity",
            "🔧 8. Supporting Worksheets",
        ])

    # Helper: wraps un sub-tab con su parent para que el patrón
    # __enter__()/__exit__() existente siga funcionando sin cambios.
    class _SubTab:
        def __init__(self, parent, child):
            self.parent = parent
            self.child = child
        def __enter__(self):
            self.parent.__enter__()
            self.child.__enter__()
            return self.child
        def __exit__(self, exc_type, exc_val, exc_tb):
            self.child.__exit__(exc_type, exc_val, exc_tb)
            self.parent.__exit__(exc_type, exc_val, exc_tb)

    tab_dam_input  = _SubTab(tab_dcf, sub_input)
    tab_coc        = _SubTab(tab_dcf, sub_coc)
    tab_proj       = _SubTab(tab_dcf, sub_proj)
    tab_val        = _SubTab(tab_dcf, sub_val)
    tab_stories    = _SubTab(tab_dcf, sub_stories)
    tab_pic        = _SubTab(tab_dcf, sub_pic)
    tab_sens       = _SubTab(tab_dcf, sub_sens)
    tab_worksheets = _SubTab(tab_dcf, sub_worksheets)

    # ============================================================
    # TAB 1: 📷 SNAPSHOT (movido desde header de pagina)
    # ============================================================
    tab_snapshot.__enter__()
    st.subheader(f"📷 Snapshot Financiero — {issuer.ticker}")
    st.caption(f"Resumen de las metricas clave de {issuer.name} al cierre del ultimo periodo reportado.")
    st.dataframe(res.summary(), hide_index=True, use_container_width=True)
    tab_snapshot.__exit__(None, None, None)

    # ============================================================
    # TAB 2: 💡 INPUTS SUGERIDOS desde histórico
    # ============================================================
    tab_inputs_sug.__enter__()
    with st.expander("💡 **Inputs sugeridos desde el histórico** — entiende cada driver", expanded=True):
        st.caption(
            "Cada input del DCF se calcula automáticamente desde tus datos parseados. "
            "Te explica qué significa, cómo se calcula y qué número usar."
        )
        try:
            from src.dcf_mexico.analysis import compute_all_input_suggestions

            # Cargar serie historica AQUI (hs se define mas abajo en otro tab)
            hs_for_suggest = load_historical(
                issuer.ticker,
                parse_func=lambda fp: _parse_cached(str(fp)),
            )
            if not hs_for_suggest.snapshots:
                st.info(
                    "No hay XBRL históricos en `data/raw_xbrl/` para esta emisora. "
                    "Sugerencias usarán defaults Damodaran."
                )

            # Calcular sugerencias del histórico anual
            curr = (res.info.currency or "MXN").upper().strip()
            fx_for_suggest = market.fx_rate_usdmxn if curr == "USD" else 1.0
            suggestions = compute_all_input_suggestions(hs_for_suggest, fx_mult=fx_for_suggest)

            # Inicializar session_state con sugerencias si NO existen ya
            for key, sug in suggestions.items():
                ss_key = f"sug_{issuer.ticker}_{key}"
                if ss_key not in st.session_state:
                    st.session_state[ss_key] = sug.value_suggested

            # Boton global "Usar todas las sugerencias"
            colb1, colb2 = st.columns([1, 3])
            with colb1:
                if st.button("⚡ Usar todas las sugerencias", key=f"apply_sug_all_{issuer.ticker}"):
                    for key, sug in suggestions.items():
                        ss_key = f"sug_{issuer.ticker}_{key}"
                        st.session_state[ss_key] = sug.value_suggested
                    st.success("Sugerencias aplicadas. Los sliders abajo ya están actualizados.")
                    st.rerun()
            with colb2:
                st.caption("Setea TODOS los sliders del DCF al valor calculado del histórico.")

            # Render cada sugerencia como card
            cards_per_row = 2
            sug_items = list(suggestions.items())
            for i in range(0, len(sug_items), cards_per_row):
                cols = st.columns(cards_per_row)
                for j, col in enumerate(cols):
                    if i + j >= len(sug_items):
                        continue
                    key, sug = sug_items[i + j]
                    with col:
                        # Card header con nombre + valor + warnings
                        warn_badge = "⚠️" if sug.warnings else "✅"
                        st.markdown(
                            f"##### {warn_badge} {sug.name}  →  **{sug.value_suggested}{sug.unit}**"
                        )
                        st.caption(f"📐 *{sug.value_method}*")

                        # Comparativos
                        cmp_lines = []
                        if sug.damodaran_default is not None:
                            cmp_lines.append(
                                f"• Damodaran default: **{sug.damodaran_default}{sug.unit}** ({sug.damodaran_default_note})"
                            )
                        if sug.sector_benchmark is not None:
                            cmp_lines.append(
                                f"• Sector benchmark: **{sug.sector_benchmark}{sug.unit}** ({sug.sector_note})"
                            )
                        if cmp_lines:
                            st.markdown("\n".join(cmp_lines))

                        # Warnings
                        if sug.warnings:
                            for w in sug.warnings:
                                st.warning(f"⚠️ {w}")

                        # Expander con detalle
                        with st.expander("📚 Ver detalle (formula, breakdown, explicación)"):
                            st.markdown(f"**Fórmula:**")
                            st.code(sug.formula, language="text")
                            st.markdown(f"**¿Qué significa?**")
                            st.markdown(sug.explanation)
                            st.markdown(f"**Interpretación:**")
                            st.markdown(sug.interpretation)
                            if sug.breakdown is not None and not sug.breakdown.empty:
                                st.markdown(f"**Cálculo año a año:**")
                                st.dataframe(sug.breakdown, hide_index=True, use_container_width=True)

        except Exception as e:
            st.error(f"Error calculando sugerencias: {e}")
            import traceback
            st.code(traceback.format_exc())

    tab_inputs_sug.__exit__(None, None, None)

    # ============================================================
    # TAB 3: 🎯 QUALITY AUDIT + 3 ESCENARIOS Bear/Base/Bull
    # (la "lección Damodaran" automatizada)
    # ============================================================
    tab_quality.__enter__()
    with st.expander("🎯 **Quality Audit + 3 Escenarios** — auditoria automática Damodaran-style",
                     expanded=True):
        st.caption(
            "Cada input se valida contra: (1) histórico de la empresa, "
            "(2) benchmark sectorial Damodaran, (3) rangos razonables. "
            "Genera 3 escenarios Bear/Base/Bull con weighted expected value."
        )
        try:
            from src.dcf_mexico.analysis import (
                validate_all_inputs, generate_scenarios, get_sector
            )

            # Reload series si no se cargó arriba
            if 'hs_for_suggest' not in dir():
                hs_for_suggest = load_historical(
                    issuer.ticker,
                    parse_func=lambda fp: _parse_cached(str(fp)),
                )

            # Sector identificado
            sector_obj = get_sector(issuer.ticker)
            if sector_obj:
                st.info(f"🏭 **Sector identificado:** {sector_obj.sector_name_es} "
                        f"({sector_obj.sector_name})\n\n📚 *{sector_obj.description}*")
            else:
                st.warning(f"⚠️ Ticker `{issuer.ticker}` no mapeado a un sector. "
                           "Validación usará solo histórico empresa, sin benchmarks sectoriales.")

            # ============================================================
            # PARTE 1: VALIDACION DE INPUTS ACTUALES
            # ============================================================
            st.markdown("### 📋 Validación de tus inputs actuales")
            # Sliders ya leen de session_state. Construir user_inputs desde defaults
            # que se calcularán abajo (estimación)
            try_user_inputs = {
                'revenue_growth_y1': st.session_state.get(
                    f"sug_{issuer.ticker}_revenue_growth_y1",
                    market.revenue_growth_high * 100
                ) / 100,
                'revenue_growth_y2y5': st.session_state.get(
                    f"sug_{issuer.ticker}_revenue_growth_y2y5",
                    market.revenue_growth_high * 100
                ) / 100,
                'op_margin_target': st.session_state.get(
                    f"sug_{issuer.ticker}_op_margin_target",
                    sector.target_op_margin * 100
                ) / 100,
                'sales_to_capital': st.session_state.get(
                    f"sug_{issuer.ticker}_sales_to_capital",
                    sector.sales_to_capital
                ),
                'beta_unlevered': sector.beta_unlevered,
                'effective_tax': st.session_state.get(
                    f"sug_{issuer.ticker}_effective_tax_rate",
                    market.marginal_tax * 100
                ) / 100,
            }

            validations = validate_all_inputs(hs_for_suggest, issuer.ticker, try_user_inputs)

            # Color por quality score
            def _quality_color(score_value: str) -> str:
                if "Excellent" in score_value: return "#16A34A"
                if "Defensible" in score_value: return "#16A34A"
                if "Aggressive" in score_value: return "#EAB308"
                if "Optimistic" in score_value or "Pessimistic" in score_value: return "#DC2626"
                return "#6B7280"

            # 2 columns layout
            v_per_row = 2
            for i in range(0, len(validations), v_per_row):
                cols = st.columns(v_per_row)
                for j, col in enumerate(cols):
                    if i + j >= len(validations):
                        continue
                    v = validations[i + j]
                    with col:
                        score_color = _quality_color(v.quality_score.value)
                        # Header
                        st.markdown(
                            f"<div style='border-left:4px solid {score_color}; padding-left:10px; margin-bottom:5px;'>"
                            f"<strong>{v.name}</strong><br>"
                            f"<span style='font-size:18px; color:{score_color};'>"
                            f"{v.quality_score.value}</span>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                        # Comparativos
                        u_str = (f"{v.user_value*100:.2f}%" if v.unit == "%" and v.user_value is not None
                                 else (f"{v.user_value:.3f}" if v.user_value is not None else "—"))
                        h_str = (f"{v.historical_value*100:.2f}%" if v.unit == "%" and v.historical_value is not None
                                 else (f"{v.historical_value:.3f}" if v.historical_value is not None else "—"))
                        s_str = (f"{v.sector_value*100:.2f}%" if v.unit == "%" and v.sector_value is not None
                                 else (f"{v.sector_value:.3f}" if v.sector_value is not None else "—"))
                        st.markdown(
                            f"**Tu input:** `{u_str}`  •  **Hist:** `{h_str}`  •  **Sector:** `{s_str}`"
                        )
                        # Bear/Base/Bull suggested
                        bear_str = (f"{v.bear_value*100:+.1f}%" if v.unit == "%"
                                    else f"{v.bear_value:.2f}")
                        base_str = (f"{v.base_value*100:+.1f}%" if v.unit == "%"
                                    else f"{v.base_value:.2f}")
                        bull_str = (f"{v.bull_value*100:+.1f}%" if v.unit == "%"
                                    else f"{v.bull_value:.2f}")
                        st.markdown(
                            f"🎯 **Sugerido:** "
                            f"Bear `{bear_str}` • Base `{base_str}` • Bull `{bull_str}`"
                        )
                        # Warnings
                        if v.warnings:
                            for w in v.warnings:
                                st.warning(f"⚠️ {w}")
                        # Detalle
                        with st.expander("📚 Ver narrativa completa"):
                            st.markdown(v.rationale)
                            if v.historical_breakdown is not None and not v.historical_breakdown.empty:
                                st.markdown("**Breakdown histórico:**")
                                st.dataframe(v.historical_breakdown, hide_index=True,
                                             use_container_width=True)

            # ============================================================
            # PARTE 2: 3 ESCENARIOS + WEIGHTED EV
            # ============================================================
            st.markdown("---")
            st.markdown("### 🎰 3 Escenarios automáticos (Bear / Base / Bull)")

            sc_c1, sc_c2, sc_c3 = st.columns(3)
            with sc_c1:
                p_bear = st.slider("Probabilidad Bear", 0.0, 1.0, 0.30, 0.05,
                                    key=f"p_bear_{issuer.ticker}")
            with sc_c2:
                p_base = st.slider("Probabilidad Base", 0.0, 1.0, 0.50, 0.05,
                                    key=f"p_base_{issuer.ticker}")
            with sc_c3:
                p_bull = st.slider("Probabilidad Bull", 0.0, 1.0, 0.20, 0.05,
                                    key=f"p_bull_{issuer.ticker}")

            # Normalizar probabilidades
            p_total = p_bear + p_base + p_bull
            if p_total > 0 and abs(p_total - 1.0) > 0.01:
                p_bear, p_base, p_bull = p_bear/p_total, p_base/p_total, p_bull/p_total
                st.caption(f"Probabilidades normalizadas: Bear {p_bear*100:.0f}% / Base {p_base*100:.0f}% / Bull {p_bull*100:.0f}%")

            # Generar escenarios
            try:
                scenarios = generate_scenarios(
                    hs_for_suggest, issuer.ticker, base,
                    market_price=float(issuer.market_price),
                    p_bear=p_bear, p_base=p_base, p_bull=p_bull,
                )

                # Tabla resumen
                summary = scenarios.summary_table(float(issuer.market_price))

                # Display con cards visuales
                st.markdown("#### 💎 Resumen de escenarios")
                m_c1, m_c2, m_c3, m_c4, m_c5 = st.columns(5)
                with m_c1:
                    st.metric(f"🐻 Bear (P={p_bear*100:.0f}%)",
                              f"${scenarios.bear.value_per_share:.2f}",
                              f"{scenarios.bear.upside_pct*100:+.1f}%",
                              delta_color="inverse")
                with m_c2:
                    st.metric(f"🟡 Base (P={p_base*100:.0f}%)",
                              f"${scenarios.base.value_per_share:.2f}",
                              f"{scenarios.base.upside_pct*100:+.1f}%",
                              delta_color="inverse")
                with m_c3:
                    st.metric(f"🐂 Bull (P={p_bull*100:.0f}%)",
                              f"${scenarios.bull.value_per_share:.2f}",
                              f"{scenarios.bull.upside_pct*100:+.1f}%",
                              delta_color="inverse")
                with m_c4:
                    st.metric(f"⚖️ Weighted EV",
                              f"${scenarios.weighted_expected_value:.2f}",
                              f"{scenarios.weighted_upside*100:+.1f}%",
                              delta_color="inverse")
                with m_c5:
                    st.metric(f"📈 Market",
                              f"${float(issuer.market_price):.2f}", "")

                # Drivers usados
                st.markdown("#### 🎛️ Drivers de cada escenario")
                drivers_rows = []
                for sc in [scenarios.bear, scenarios.base, scenarios.bull]:
                    row = {"Escenario": f"{sc.name}"}
                    row.update(sc.drivers)
                    row["Value/Share"] = f"${sc.value_per_share:.2f}"
                    row["Upside"] = f"{sc.upside_pct*100:+.1f}%"
                    drivers_rows.append(row)
                drivers_df = pd.DataFrame(drivers_rows)
                st.dataframe(drivers_df, hide_index=True, use_container_width=True)

                # Veredicto
                st.markdown("#### 🎯 Veredicto Damodaran")
                w_up = scenarios.weighted_upside
                if w_up > 0.20:
                    st.success(
                        f"✅ **COMPRA** — Weighted EV (${scenarios.weighted_expected_value:.2f}) "
                        f"está {w_up*100:+.1f}% arriba del precio. Margen de seguridad amplio."
                    )
                elif w_up > 0.05:
                    st.success(
                        f"🟢 **COMPRA MODERADA** — Weighted EV {w_up*100:+.1f}% arriba del precio."
                    )
                elif w_up > -0.05:
                    st.info(
                        f"⚪ **FAIR VALUE** — Weighted EV "
                        f"(${scenarios.weighted_expected_value:.2f}) cerca del precio "
                        f"({float(issuer.market_price):.2f})."
                    )
                elif w_up > -0.20:
                    st.warning(
                        f"🟡 **SOBREVALORADA MODERADA** — Weighted EV "
                        f"{abs(w_up)*100:.1f}% por debajo del precio. "
                        f"Probabilidad de retorno positivo: ~{p_bull*100:.0f}% (solo Bull)."
                    )
                else:
                    st.error(
                        f"🔴 **SOBREVALORADA** — Weighted EV "
                        f"{abs(w_up)*100:.1f}% por debajo del precio. "
                        f"Solo Bull case justifica entrar (P={p_bull*100:.0f}%)."
                    )

            except Exception as e_sc:
                st.error(f"Error generando escenarios: {e_sc}")
                import traceback
                st.code(traceback.format_exc())

        except Exception as e_qa:
            st.error(f"Error en Quality Audit: {e_qa}")
            import traceback
            st.code(traceback.format_exc())

    tab_quality.__exit__(None, None, None)

    # ============================================================
    # DCF INPUTS (auto desde Input Sheet · session_state)
    #
    # El antiguo tab "Drivers DCF" fue eliminado. Ahora todos los inputs
    # del modelo se leen desde el Input Sheet (Damodaran) — claves
    # `dam_in_*` que las widgets del tab escriben automáticamente.
    # En el primer render, session_state aún no tiene esas claves, así
    # que usamos defaults (market / sector / suggestions del histórico).
    # ============================================================
    def _sug_or_default(key, default, vmin, vmax, scale=1.0):
        ss_key = f"sug_{issuer.ticker}_{key}"
        v = st.session_state.get(ss_key)
        if v is None:
            return default
        v_scaled = v * scale
        return max(vmin, min(vmax, v_scaled))

    _default_rev_growth = _sug_or_default(
        "revenue_growth_y2y5", market.revenue_growth_high,
        0.0, 0.20, scale=0.01)
    _default_op_margin = _sug_or_default(
        "op_margin_target", sector.target_op_margin,
        0.0, 0.60, scale=0.01)
    _default_s2c = _sug_or_default(
        "sales_to_capital", sector.sales_to_capital, 0.1, 6.0)

    def _ss_pct(key_suffix, default):
        """Lee key 'dam_in_<key>_<ticker>' (UI guarda en %) → decimal."""
        v = st.session_state.get(f"dam_in_{key_suffix}_{issuer.ticker}",
                                  default * 100)
        return float(v) / 100.0

    def _ss_num(key_suffix, default):
        return st.session_state.get(
            f"dam_in_{key_suffix}_{issuer.ticker}", default)

    def _ss_yes(key_suffix):
        return st.session_state.get(
            f"dam_in_{key_suffix}_{issuer.ticker}", "No") == "Yes"

    # === Inputs básicos (Input Sheet sec C/D/E) ===
    rev_growth   = _ss_pct("g_y2y5", _default_rev_growth)
    op_margin    = _ss_pct("m_target", _default_op_margin)
    s2c          = float(_ss_num("s2c_15", _default_s2c))
    market_price = float(_ss_num("price", float(issuer.market_price or 0.0)))
    rf           = _ss_pct("rf", market.risk_free)

    # Risk inputs ahora editables en Input Sheet sec E
    beta_unlev    = float(_ss_num("beta_u", sector.beta_unlevered))
    erp           = _ss_pct("erp", market.erp)
    terminal_wacc = _ss_pct("term_wacc",
                              market.terminal_wacc_override or 0.085)

    # === Y1 separado de Y2-Y5 (Input Sheet sec D) ===
    rev_growth_y1 = _ss_pct("g_y1", rev_growth)
    op_margin_y1  = _ss_pct(
        "m_y1",
        base.ebit / base.revenue if base.revenue else op_margin)
    year_conv     = int(_ss_num("yconv", 5))
    use_y1_growth = abs(rev_growth_y1 - rev_growth) > 1e-6
    use_y1_margin = abs(op_margin_y1 - op_margin) > 1e-6

    # === S2C split Y1-5 vs Y6-10 (Input Sheet sec D) ===
    s2c_y1_5      = float(_ss_num("s2c_15", s2c))
    s2c_y6_10     = float(_ss_num("s2c_610", s2c))
    use_s2c_split = abs(s2c_y1_5 - s2c_y6_10) > 1e-6

    # === Sec G overrides (Yes/No selectboxes) ===
    override_term_roic = _ss_yes("ov_roic")
    terminal_roic_val  = _ss_pct("roic10", 0.15)

    override_pf            = _ss_yes("ov_fail")
    prob_failure           = _ss_pct("pfail", 0.0) if override_pf else 0.0
    _basis_str             = st.session_state.get(
        f"dam_in_basis_{issuer.ticker}", "V")
    failure_proceeds_basis = "B" if str(_basis_str).startswith("B") else "V"
    failure_proceeds_pct   = float(_ss_num("proc", 50.0)) / 100.0

    override_nol = _ss_yes("ov_nol")
    nol_cf       = float(_ss_num("nol", 0.0)) if override_nol else 0.0

    override_lag = _ss_yes("ov_lag")
    reinvest_lag = int(_ss_num("lag", 1)) if override_lag else 0

    override_tc  = _ss_yes("ov_tc")
    trapped      = float(_ss_num("tc", 0.0)) if override_tc else 0.0
    trapped_tax  = (_ss_pct("tc_tax", 0.15)
                     if (override_tc and trapped > 0) else 0.0)

    override_g = _ss_yes("ov_g")
    terminal_g = (_ss_pct("g_term", market.terminal_growth)
                   if override_g else market.terminal_growth)

    a = DCFAssumptions(
        # ===== Inputs basicos =====
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
        # ===== Damodaran Hoja 1 (advanced) =====
        revenue_growth_y1=rev_growth_y1 if use_y1_growth else None,
        op_margin_y1=op_margin_y1 if use_y1_margin else None,
        year_of_margin_convergence=year_conv,
        sales_to_capital_y1_5=s2c_y1_5 if use_s2c_split else None,
        sales_to_capital_y6_10=s2c_y6_10 if use_s2c_split else None,
        override_terminal_roic=override_term_roic,
        terminal_roic_override=terminal_roic_val,
        probability_of_failure=prob_failure,
        failure_proceeds_pct=failure_proceeds_pct,
        failure_proceeds_basis=failure_proceeds_basis,
        nol_carryforward=nol_cf,
        reinvestment_lag=reinvest_lag,
        trapped_cash=trapped,
        trapped_cash_tax_rate=trapped_tax,
    )
    out = project_company(base, a)

    # ============================================================
    # TAB 4-bis: 📋 DAMODARAN INPUT SHEET (replica exacta del Excel)
    # Estructura idéntica a fcffsimpleginzu.xlsx hoja "Input sheet"
    # Pre-poblado con datos de la emisora desde el parser.
    # ============================================================
    tab_dam_input.__enter__()
    st.subheader(f"📋 Damodaran Input Sheet — {issuer.ticker}")

    from datetime import date as _date, datetime as _datetime

    # ============================================================
    # "Last 10K before LTM" + "Years since 10K"
    # Lógica OFICIAL Damodaran (notas celdas C10/D10 del Excel):
    #
    # > C10: "If your last twelve months of data come from a 10K or
    #   Annual Report, the last 10K will be the previous year's 10K.
    #   If your last twelve months are midway through a fiscal year,
    #   this will be the previous fiscal year."
    #
    # > D10: "If your most recent 12 months of data represent the most
    #   recent fiscal year, enter 1.00. If midway through, enter the
    #   fraction: Q3=0.75, Q2=0.50, Q1=0.25."
    #
    # Implementación: buscar el último anual cuyo period_end sea
    # ESTRICTAMENTE ANTERIOR al period_end del snapshot cargado.
    # Years since 10K = (LTM_end_date − last_10K_date) / 365.25
    # ============================================================
    last_10k = {}
    years_since_10k = None
    prev_snap = None
    eff_tax_history_years = []   # tuples (year, eff_tax) últimos 3-5 anuales
    eff_tax_avg = None
    try:
        from src.dcf_mexico.historical.series import load_historical
        _hs = load_historical(issuer.ticker,
                              parse_func=lambda fp: _parse_cached(str(fp)))
        d_recent = _datetime.strptime(res.info.period_end, "%Y-%m-%d")
        for snap in reversed(_hs.annual):
            try:
                snap_date = _datetime.strptime(snap.period_end, "%Y-%m-%d")
            except Exception:
                continue
            if snap_date < d_recent:
                prev_snap = snap
                break

        if prev_snap is not None:
            ppd = prev_snap.parsed.dcf
            ppi = prev_snap.parsed.informative
            # B14 Damodaran: BV equity = total (controlling + minority)
            _equity_total_prior = (
                (getattr(ppd, "equity_bv", 0) or 0) +
                (getattr(ppd, "minority_interest", 0) or 0)
            )
            last_10k = {
                "revenue":         getattr(ppd, "revenue", None),
                "ebit":            getattr(ppd, "ebit", None),
                "intexp":          getattr(ppd, "interest_expense", None),
                "equity_bv":       getattr(ppd, "equity_bv", None),         # controladora
                "equity_bv_total": _equity_total_prior,                       # ← Damodaran (incl minority)
                "debt":            getattr(ppd, "total_debt", None),
                "cash":            getattr(ppd, "cash", None),
                "minority":        getattr(ppd, "minority_interest", None),
                "nonop":           getattr(ppd, "non_operating_assets", None),
                "shares":          getattr(ppi, "shares_outstanding", None),
                "eff_tax":         getattr(ppd, "effective_tax_rate", None),
            }
            try:
                d_prev = _datetime.strptime(prev_snap.period_end, "%Y-%m-%d")
                years_since_10k = round(
                    (d_recent - d_prev).days / 365.25, 2)
            except Exception:
                years_since_10k = None

        # B23 Damodaran: effective tax rate puede usarse promedio multi-año
        # Tomamos los últimos 5 anuales (excluyendo años con tasas anómalas <0 o >50%)
        for snap in _hs.annual[-5:]:
            try:
                rate = getattr(snap.parsed.dcf, "effective_tax_rate", None)
                if rate is not None and 0.0 < rate < 0.50:
                    eff_tax_history_years.append((snap.year, rate))
            except Exception:
                continue
        if eff_tax_history_years:
            eff_tax_avg = sum(r for _, r in eff_tax_history_years) / len(eff_tax_history_years)
    except Exception:
        pass

    # ==== Equity total — Damodaran B14 ====
    # base.equity_book ya viene como TOTAL (controladora + minority) desde
    # CompanyBase.from_parser_dcf (fix Nov 2025).
    equity_bv_total_recent = base.equity_book

    # ==== Risk-free clean — Damodaran B34 ====
    # Clean Rf = local bond yield − country default spread
    cds_mx = getattr(market, "country_default_spread_mx", 0.025)
    rf_clean = max(0.0, market.risk_free - cds_mx)

    # Caption + 3 KPIs explicativos arriba del Input Sheet
    _last10k_label = (
        f"FY {prev_snap.period_end}"
        if prev_snap is not None else "—"
    )
    st.caption(
        "Réplica de la hoja **Input sheet** de `fcffsimpleginzu.xlsx` "
        "con notas oficiales de Damodaran en cada celda. "
        "Auto-poblado desde XBRL parseado."
    )
    cols_info = st.columns(3)
    cols_info[0].metric("Most Recent 12M",
                          res.info.period_end,
                          help="Período del snapshot que cargaste arriba "
                               "(LTM end date)")
    cols_info[1].metric("Last 10K before LTM",
                          _last10k_label,
                          help="Último anual auditado cuyo period_end es "
                               "ESTRICTAMENTE ANTERIOR al LTM. Si tu LTM "
                               "es FY 2025, este será FY 2024. Si tu LTM "
                               "es Q3 2025, este será FY 2024 (no FY 2023).")
    cols_info[2].metric("Years since 10K",
                          f"{years_since_10k:.2f}"
                            if years_since_10k is not None else "—",
                          help=("Fracción del año fiscal en curso cubierta "
                                "por el LTM. Convención Damodaran (D10): "
                                "1.00 = LTM es el FY completo · "
                                "0.75 = LTM hasta Q3 · "
                                "0.50 = LTM hasta Q2 · "
                                "0.25 = LTM hasta Q1"))

    # Helper: muestra una fila del Input Sheet con etiqueta + valor + nota
    def _ds_row(label: str, val_recent, val_prior=None, note: str = "",
                  unit: str = "", is_input: bool = True):
        """Renderiza una fila estilo Damodaran Excel."""
        cols = st.columns([3.2, 1.4, 1.4, 3.0])
        cols[0].markdown(f"**{label}**" if is_input else label)
        # Format
        def _fmt(v):
            if v is None or v == "":
                return "—"
            if isinstance(v, (int, float)):
                if unit == "%":
                    return f"{v*100:,.2f}%"
                if unit == "x":
                    return f"{v:,.2f}x"
                if abs(v) >= 1000:
                    return f"{v:,.1f}"
                return f"{v:,.4f}" if abs(v) < 1 else f"{v:,.2f}"
            return str(v)
        cols[1].markdown(f"`{_fmt(val_recent)}`")
        cols[2].markdown(f"`{_fmt(val_prior)}`" if val_prior is not None else "")
        if note:
            cols[3].caption(note)

    # Datos del parser (CompanyBase ya esta calculado arriba)
    dcf_p = res.dcf
    rev_recent = base.revenue
    ebit_recent = base.ebit
    intexp_recent = base.interest_expense
    cash_recent = base.cash
    debt_recent = base.financial_debt
    equity_bv_recent = base.equity_book
    minority_recent = base.minority_interest
    nonop_recent = base.non_operating_assets
    shares_recent = base.shares_outstanding
    eff_tax_recent = base.effective_tax_rate
    price_recent = float(issuer.market_price or 0.0)

    # ----- SECCION A: Identificacion -----
    with st.expander("**🆔 A · Identificación**", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.text_input("Date of valuation",
                          value=_date.today().isoformat(),
                          key=f"dam_in_date_{issuer.ticker}")
            st.text_input("Company name",
                          value=issuer.name,
                          key=f"dam_in_name_{issuer.ticker}", disabled=True)
        with c2:
            st.text_input("Country of incorporation",
                          value="Mexico",
                          key=f"dam_in_country_{issuer.ticker}")
            st.text_input("Industry (Global)",
                          value=getattr(issuer, "sector", "—"),
                          key=f"dam_in_industry_{issuer.ticker}")

    # ----- SECCION B: Base year numbers -----
    with st.expander("**📊 B · Base year numbers** (units: MDP)",
                       expanded=True):
        st.caption(
            "💬 **Damodaran (nota celda C10):** *Si tu LTM viene del 10K, "
            "el Last 10K será el del año previo. Si tu LTM va a la mitad "
            "del fiscal year, el Last 10K será el último FY completo "
            "anterior al LTM.* — Implementado: busca el último anual "
            "con period_end estrictamente anterior al LTM cargado."
        )
        h = st.columns([3.2, 1.4, 1.4, 1.0, 2.4])
        h[0].markdown("**Concept**")
        h[1].markdown("**Most Recent 12M**")
        h[2].markdown("**Last 10K before LTM**")
        h[3].markdown("**Years since 10K**")
        h[4].markdown("**Source / Note**")
        st.divider()

        # Helper actualizado que acepta col extra "Years since"
        def _ds_row5(label, val_recent, val_prior=None,
                       val_years=None, note="", unit=""):
            cols = st.columns([3.2, 1.4, 1.4, 1.0, 2.4])
            cols[0].markdown(f"**{label}**")
            def _fmt(v):
                if v is None or v == "":
                    return "—"
                if isinstance(v, (int, float)):
                    if unit == "%":
                        return f"{v*100:,.2f}%"
                    if unit == "x":
                        return f"{v:,.2f}x"
                    if abs(v) >= 1000:
                        return f"{v:,.1f}"
                    return f"{v:,.4f}" if abs(v) < 1 else f"{v:,.2f}"
                return str(v)
            cols[1].markdown(f"`{_fmt(val_recent)}`")
            cols[2].markdown(f"`{_fmt(val_prior)}`" if val_prior is not None else "—")
            if val_years is not None:
                cols[3].markdown(f"`{val_years}`")
            else:
                cols[3].markdown("")
            if note:
                cols[4].caption(note)

        _ds_row5("Revenues", rev_recent, last_10k.get("revenue"),
                   years_since_10k,
                   "TTM. Auto desde income.revenue")
        _ds_row5("Operating income (EBIT)", ebit_recent, last_10k.get("ebit"),
                   None,
                   "EBIT TTM. Si negativo → review")
        _ds_row5("Interest expense", intexp_recent, last_10k.get("intexp"),
                   None,
                   "Auto desde income.interest_expense")
        _ds_row5("Book value of equity", equity_bv_total_recent,
                   last_10k.get("equity_bv_total"), None,
                   "TOTAL = controladora + minority (B14 Damodaran)")
        _ds_row5("Book value of debt", debt_recent, last_10k.get("debt"),
                   None,
                   "total_debt = financial + lease (IFRS 16)")
        _ds_row5("Cash and Marketable Securities", cash_recent,
                   last_10k.get("cash"), None,
                   "balance.cash + marketable_securities")
        _ds_row5("Cross holdings & non-operating assets",
                   nonop_recent, last_10k.get("nonop"), None,
                   "Auto desde dcf.non_operating_assets")
        _ds_row5("Minority interests", minority_recent,
                   last_10k.get("minority"), None,
                   "balance.minority_interest")
        st.markdown("")
        c_rd, c_ol = st.columns(2)
        with c_rd:
            st.selectbox("R&D expenses to capitalize?",
                         ["No", "Yes"], index=0,
                         key=f"dam_in_rd_{issuer.ticker}",
                         help="Para CUERVO/Beverages → siempre No")
        with c_ol:
            st.selectbox("Operating lease commitments?",
                         ["No (ya capitalizadas)", "Yes"], index=0,
                         key=f"dam_in_ol_{issuer.ticker}",
                         help="MX-IFRS 16: ya están en total_debt → No")

    # ----- SECCION C: Market data -----
    with st.expander("**💹 C · Market data**", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.number_input("Number of shares outstanding (millones)",
                            value=float(shares_recent or 0.0),
                            step=1.0, format="%.2f",
                            key=f"dam_in_shares_{issuer.ticker}",
                            help="B21 Damodaran: agregar todas las series. "
                                 "Incluir RSUs, NO incluir shares underlying "
                                 "employee options.")
            st.number_input("Current stock price (MXN)",
                            value=float(price_recent),
                            step=0.5, format="%.2f",
                            key=f"dam_in_price_{issuer.ticker}",
                            help="B22 Damodaran: precio de hoy.")

        # Effective tax rate: ahora ofrecemos 1Y vs avg multi-año (B23 Damodaran)
        with c2:
            # Construir opciones del selectbox según haya history
            tax_method_opts = ["Current year (LTM)"]
            if eff_tax_avg is not None and len(eff_tax_history_years) >= 2:
                yrs = ", ".join(str(y) for y, _ in eff_tax_history_years)
                tax_method_opts.append(
                    f"Avg {len(eff_tax_history_years)}y ({yrs})")
            tax_method = st.radio(
                "Effective tax rate · método",
                tax_method_opts, horizontal=True,
                key=f"dam_in_tax_method_{issuer.ticker}",
                help="B23 Damodaran: 'If your effective tax rate varies "
                     "across years, you can use an average.'")
            if tax_method.startswith("Avg") and eff_tax_avg is not None:
                _eff_tax_default = eff_tax_avg * 100
                _eff_tax_help = (
                    f"Promedio multi-año: "
                    + " · ".join(f"{y}={r*100:.2f}%"
                                   for y, r in eff_tax_history_years)
                    + f" → avg = {eff_tax_avg*100:.2f}%"
                )
            else:
                _eff_tax_default = eff_tax_recent * 100
                _eff_tax_help = ("Tax expense / Pretax income del LTM "
                                 "actual. CUERVO LTM ≈ 24-27%.")
            st.number_input("Effective tax rate (%)",
                            value=float(_eff_tax_default),
                            step=0.5, format="%.2f",
                            key=f"dam_in_eff_tax_{issuer.ticker}",
                            help=_eff_tax_help)
            st.number_input("Marginal tax rate (%)",
                            value=30.0, step=0.5, format="%.2f",
                            key=f"dam_in_marg_tax_{issuer.ticker}",
                            help="B24 Damodaran: statutory tax rate del país. "
                                 "México ISR corporativo = 30%.")

    # ----- SECCION D: Value drivers -----
    with st.expander("**🚀 D · Value drivers** (Damodaran growth/margin levers)",
                       expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.number_input("Revenue growth Y1 (%)",
                            value=float(rev_growth * 100), step=0.25,
                            format="%.2f",
                            key=f"dam_in_g_y1_{issuer.ticker}")
            st.number_input("Operating margin Y1 (%)",
                            value=float((base.ebit / base.revenue * 100)
                                          if base.revenue else 22.0),
                            step=0.5, format="%.2f",
                            key=f"dam_in_m_y1_{issuer.ticker}")
            st.number_input("CAGR revenue Y2-Y5 (%)",
                            value=float(rev_growth * 100), step=0.25,
                            format="%.2f",
                            key=f"dam_in_g_y2y5_{issuer.ticker}")
        with c2:
            st.number_input("Target pre-tax operating margin (%)",
                            value=float(op_margin * 100), step=0.5,
                            format="%.2f",
                            key=f"dam_in_m_target_{issuer.ticker}")
            st.number_input("Year of convergence for margin",
                            value=5, min_value=1, max_value=10, step=1,
                            key=f"dam_in_yconv_{issuer.ticker}")
            st.number_input("Sales-to-Capital Y1-Y5",
                            value=float(s2c), step=0.05, format="%.2f",
                            key=f"dam_in_s2c_15_{issuer.ticker}")
            st.number_input("Sales-to-Capital Y6-Y10",
                            value=float(s2c), step=0.05, format="%.2f",
                            key=f"dam_in_s2c_610_{issuer.ticker}")

    # ----- SECCION E: Market parameters + Risk inputs -----
    with st.expander("**🌎 E · Market parameters & Risk inputs**",
                       expanded=True):
        st.caption(
            "💬 **Damodaran B34:** *'If you are working with a currency "
            "where the government has default risk, **clean up the bond "
            "rate by subtracting the country default spread**.'* "
            f"MX bono M 10Y ≈ {market.risk_free*100:.2f}% − "
            f"CDS MX ({cds_mx*100:.2f}%) = "
            f"**{rf_clean*100:.2f}%** (clean Rf)"
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            st.number_input("Risk-free rate MX (%)",
                            value=float(rf * 100), step=0.05, format="%.4f",
                            key=f"dam_in_rf_{issuer.ticker}",
                            help=(f"Tasa que entra al CAPM. Default: bono M "
                                  f"10Y RAW ({market.risk_free*100:.2f}%). "
                                  f"Damodaran sugiere usar CLEAN "
                                  f"({rf_clean*100:.2f}%) cuando el ERP ya "
                                  f"incluye CRP MX (caso actual)."))
            st.number_input("MX Country Default Spread (%)",
                            value=float(cds_mx * 100), step=0.05,
                            format="%.4f",
                            key=f"dam_in_cds_{issuer.ticker}",
                            help="Default spread del soberano MX. "
                                 "Damodaran tablas: MX rated BBB ≈ 2-3%.")
            st.number_input("Equity Risk Premium MX (%)",
                            value=float(erp * 100), step=0.05, format="%.4f",
                            key=f"dam_in_erp_{issuer.ticker}",
                            help="Mature ERP (US ≈ 4.6%) + Country Risk "
                                 "Premium MX")
        with c2:
            st.number_input("β unlevered (sector Damodaran)",
                            value=float(beta_unlev), step=0.05, format="%.3f",
                            key=f"dam_in_beta_u_{issuer.ticker}",
                            help="Beta de la industria sin apalancar. "
                                 "Damodaran tables → buscar tu sector global")
            st.number_input("Terminal WACC override (%)",
                            value=float(terminal_wacc * 100), step=0.05,
                            format="%.4f",
                            key=f"dam_in_term_wacc_{issuer.ticker}",
                            help="WACC en estado estable (año 10+). "
                                 "Default = max(WACC inicial, riskfree + ERP)")
        with c3:
            st.number_input("Initial cost of capital (WACC) (%)",
                            value=float(out.wacc_result.wacc * 100),
                            step=0.10, format="%.4f", disabled=True,
                            key=f"dam_in_wacc_init_{issuer.ticker}",
                            help="Calculado en Cost of Capital sheet (WACC)")
            st.number_input("Synthetic Rating · Default Spread (%)",
                            value=float(out.wacc_result.default_spread * 100),
                            step=0.05, format="%.4f", disabled=True,
                            key=f"dam_in_def_spread_{issuer.ticker}",
                            help=f"Auto desde rating sintético "
                                 f"({out.wacc_result.rating}) "
                                 f"basado en interest coverage")

    # ----- SECCION F: Other inputs (employee options) -----
    with st.expander("**🎫 F · Other inputs** (employee options)",
                       expanded=False):
        opt_yn = st.selectbox("Employee options outstanding?",
                                ["No", "Yes"], index=0,
                                key=f"dam_in_opt_yn_{issuer.ticker}")
        if opt_yn == "Yes":
            o1, o2, o3, o4 = st.columns(4)
            with o1:
                st.number_input("# options (M)", value=0.0, step=0.1,
                                key=f"dam_in_opt_n_{issuer.ticker}")
            with o2:
                st.number_input("Avg strike (MXN)", value=0.0, step=0.5,
                                key=f"dam_in_opt_strike_{issuer.ticker}")
            with o3:
                st.number_input("Avg maturity (yr)", value=7.0, step=0.5,
                                key=f"dam_in_opt_mat_{issuer.ticker}")
            with o4:
                st.number_input("Stock stdev", value=0.45, step=0.05,
                                key=f"dam_in_opt_std_{issuer.ticker}")

    # ----- SECCION G: Default-assumption overrides -----
    with st.expander(
        "**⚙️ G · Default assumption overrides** (rows 42-71 del Excel)",
        expanded=False):

        st.markdown("**Stable-growth cost of capital**")
        oc1, oc2 = st.columns([1, 2])
        with oc1:
            ov_coc = st.selectbox("Override cost of capital después año 10?",
                                    ["No", "Yes"], index=0,
                                    key=f"dam_in_ov_coc_{issuer.ticker}")
        with oc2:
            st.number_input("Cost of capital after year 10 (%)",
                            value=float(out.wacc_result.wacc * 100),
                            step=0.10, format="%.4f",
                            disabled=(ov_coc == "No"),
                            key=f"dam_in_coc10_{issuer.ticker}")

        st.markdown("**Stable-growth ROIC**")
        or1, or2 = st.columns([1, 2])
        with or1:
            ov_roic = st.selectbox("Override ROIC después año 10?",
                                     ["No", "Yes"], index=0,
                                     key=f"dam_in_ov_roic_{issuer.ticker}")
        with or2:
            st.number_input("ROIC after year 10 (%)",
                            value=15.0, step=0.5, format="%.2f",
                            disabled=(ov_roic == "No"),
                            key=f"dam_in_roic10_{issuer.ticker}")

        st.markdown("**Probability of failure**")
        of1, of2, of3, of4 = st.columns(4)
        with of1:
            ov_fail = st.selectbox("Override probability of failure?",
                                     ["No", "Yes"], index=0,
                                     key=f"dam_in_ov_fail_{issuer.ticker}")
        with of2:
            st.number_input("Probability of failure (%)",
                            value=12.0, step=1.0, format="%.2f",
                            disabled=(ov_fail == "No"),
                            key=f"dam_in_pfail_{issuer.ticker}")
        with of3:
            st.selectbox("Tie proceeds in failure to:",
                         ["V (fair value)", "B (book value of capital)"],
                         index=0, key=f"dam_in_basis_{issuer.ticker}")
        with of4:
            st.number_input("Distress proceeds (% of book/value)",
                            value=50.0, step=5.0, format="%.1f",
                            key=f"dam_in_proc_{issuer.ticker}")

        st.markdown("**Reinvestment lag**")
        ol1, ol2 = st.columns([1, 2])
        with ol1:
            ov_lag = st.selectbox("Override reinvestment lag?",
                                    ["No", "Yes"], index=0,
                                    key=f"dam_in_ov_lag_{issuer.ticker}")
        with ol2:
            st.number_input("Reinvestment lag (años, 0-3)",
                            value=1, min_value=0, max_value=3, step=1,
                            disabled=(ov_lag == "No"),
                            key=f"dam_in_lag_{issuer.ticker}")

        st.markdown("**Effective vs marginal tax convergence**")
        ot = st.selectbox("Override effective→marginal tax convergence?",
                            ["No", "Yes"], index=0,
                            key=f"dam_in_ov_tax_{issuer.ticker}")

        st.markdown("**NOL carryforward**")
        on1, on2 = st.columns([1, 2])
        with on1:
            ov_nol = st.selectbox("Override NOL?",
                                    ["No", "Yes"], index=0,
                                    key=f"dam_in_ov_nol_{issuer.ticker}")
        with on2:
            st.number_input("NOL into year 1 (MDP)",
                            value=0.0, step=100.0, format="%.1f",
                            disabled=(ov_nol == "No"),
                            key=f"dam_in_nol_{issuer.ticker}")

        st.markdown("**Risk-free rate / terminal growth**")
        ot1, ot2 = st.columns([1, 2])
        with ot1:
            ov_rf = st.selectbox("Override risk-free después año 10?",
                                   ["No", "Yes"], index=1,
                                   key=f"dam_in_ov_rf_{issuer.ticker}",
                                   help="MX usualmente: Yes (rf actual ≈ 9% vs estable ≈ 6%)")
        with ot2:
            st.number_input("Risk-free after year 10 (%)",
                            value=6.0, step=0.25, format="%.4f",
                            disabled=(ov_rf == "No"),
                            key=f"dam_in_rf10_{issuer.ticker}")
        og1, og2 = st.columns([1, 2])
        with og1:
            ov_g = st.selectbox("Override terminal growth?",
                                  ["No", "Yes"], index=1,
                                  key=f"dam_in_ov_g_{issuer.ticker}",
                                  help="MX usualmente: Yes (g ≈ 3.5% inflación)")
        with og2:
            st.number_input("Terminal growth (%)",
                            value=float(terminal_g * 100), step=0.05,
                            format="%.4f", disabled=(ov_g == "No"),
                            key=f"dam_in_g_term_{issuer.ticker}")

        st.markdown("**Trapped cash (foreign markets)**")
        oc1, oc2, oc3 = st.columns([1, 1, 1])
        with oc1:
            ov_tc = st.selectbox("Override trapped cash?",
                                   ["No", "Yes"], index=0,
                                   key=f"dam_in_ov_tc_{issuer.ticker}")
        with oc2:
            st.number_input("Trapped cash (MDP)",
                            value=0.0, step=100.0, format="%.1f",
                            disabled=(ov_tc == "No"),
                            key=f"dam_in_tc_{issuer.ticker}")
        with oc3:
            st.number_input("Avg foreign tax rate (%)",
                            value=15.0, step=1.0, format="%.2f",
                            disabled=(ov_tc == "No"),
                            key=f"dam_in_tc_tax_{issuer.ticker}")

    st.divider()
    st.success(
        "✅ **Cómo se conecta este sheet con el modelo:** los inputs de las "
        "secciones B, C, D y E ya están alimentando al motor de DCF "
        "(`project_company`). Las secciones F y G capturan los overrides "
        "avanzados que ya existen en *Drivers DCF → Damodaran Advanced*. "
        "Esta vista es la **réplica visual del Excel** para validar campo "
        "por campo contra `fcffsimpleginzu.xlsx`."
    )

    tab_dam_input.__exit__(None, None, None)

    # ============================================================
    # SUB-TAB 2: 💰 COST OF CAPITAL (réplica hoja COC de Damodaran)
    # ============================================================
    tab_coc.__enter__()
    st.subheader(f"💰 Cost of Capital — {issuer.ticker}")
    st.caption(
        "Réplica de la hoja **Cost of Capital** del modelo "
        "`fcffsimpleginzu.xlsx`. Construye paso a paso: "
        "**β unlevered → β levered → Ke (CAPM) + Kd after-tax → WACC**."
    )

    wr = out.wacc_result

    # ---- Resumen ejecutivo ----
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("WACC", f"{wr.wacc:.2%}",
              f"βL = {wr.levered_beta:.2f}")
    k2.metric("Cost of Equity", f"{wr.cost_equity:.2%}",
              f"Weight {wr.weight_equity:.0%}")
    k3.metric("After-tax Cost of Debt", f"{wr.aftertax_cost_debt:.2%}",
              f"Weight {wr.weight_debt:.0%}")
    k4.metric("Synthetic Rating", wr.rating,
              f"Spread {wr.default_spread:.2%}")

    st.divider()

    # ---- Bloque A: Cost of Equity (CAPM) ----
    with st.expander("**🟦 A · Cost of Equity (CAPM)**", expanded=True):
        st.markdown(
            f"""
            **CAPM:** `Ke = Rf + βL × ERP`

            | Componente | Valor | Notas |
            |---|---:|---|
            | Risk-free rate (México) | **{wr.risk_free:.4%}** | CETES 10Y o Bono M 10Y |
            | Equity Risk Premium (ERP) | **{wr.erp:.4%}** | Damodaran ERP MX (mature + country risk) |
            | Beta unlevered (sector) | **{wr.unlevered_beta:.3f}** | Promedio sector Damodaran (sin apalancar) |
            | Debt-to-Equity ratio (D/E) | **{wr.debt_to_equity:.3f}x** | Total Debt ÷ Market Cap |
            | Tax rate | **{market.marginal_tax:.2%}** | ISR corporativo MX |
            | **Beta levered (Hamada)** | **{wr.levered_beta:.3f}** | `βU × (1 + (1-T) × D/E)` |
            | **Cost of Equity** | **{wr.cost_equity:.4%}** | `Rf + βL × ERP` |
            """
        )
        # Verificación numérica
        ke_check = wr.risk_free + wr.levered_beta * wr.erp
        if abs(ke_check - wr.cost_equity) > 0.0001:
            st.warning(f"⚠️ Verificación CAPM: {ke_check:.4%} vs {wr.cost_equity:.4%}")
        else:
            st.success(
                f"✅ CAPM check: {wr.risk_free:.4%} + "
                f"{wr.levered_beta:.3f} × {wr.erp:.4%} = "
                f"**{wr.cost_equity:.4%}**"
            )

    # ---- Bloque B: Cost of Debt (Synthetic Rating) ----
    with st.expander("**🟥 B · Cost of Debt (Synthetic Rating)**",
                       expanded=True):
        st.markdown(
            f"""
            **Método Damodaran:** rating sintético basado en Interest Coverage Ratio
            (EBIT / Interest Expense), luego rating → default spread → Kd.

            | Componente | Valor | Notas |
            |---|---:|---|
            | Interest Coverage Ratio | **{wr.interest_coverage:.2f}x** | EBIT ÷ Interest Expense |
            | Synthetic Rating | **{wr.rating}** | Mapeo Damodaran (tabla) |
            | Default Spread | **{wr.default_spread:.4%}** | Premium sobre risk-free por riesgo crediticio |
            | Risk-free rate | **{wr.risk_free:.4%}** | Misma base que Ke |
            | **Pre-tax Cost of Debt** | **{wr.pretax_cost_debt:.4%}** | `Rf + Default Spread` |
            | Tax rate | **{market.marginal_tax:.2%}** | ISR corporativo MX |
            | **After-tax Cost of Debt** | **{wr.aftertax_cost_debt:.4%}** | `Kd × (1 - T)` — escudo fiscal |
            """
        )

    # ---- Bloque C: WACC weighted ----
    with st.expander("**🟩 C · WACC weighted**", expanded=True):
        # Tabla pesos
        import pandas as _pd
        weights_df = _pd.DataFrame([
            {"Source": "Equity", "Weight": wr.weight_equity,
             "Cost (after-tax)": wr.cost_equity,
             "Contribution": wr.weight_equity * wr.cost_equity},
            {"Source": "Debt", "Weight": wr.weight_debt,
             "Cost (after-tax)": wr.aftertax_cost_debt,
             "Contribution": wr.weight_debt * wr.aftertax_cost_debt},
            {"Source": "TOTAL (WACC)",
             "Weight": wr.weight_equity + wr.weight_debt,
             "Cost (after-tax)": float("nan"),
             "Contribution": wr.wacc},
        ])
        st.dataframe(
            weights_df.style.format({
                "Weight": "{:.2%}",
                "Cost (after-tax)": "{:.4%}",
                "Contribution": "{:.4%}",
            }, na_rep="—"),
            hide_index=True, use_container_width=True,
        )
        st.markdown(
            f"""
            **Fórmula:** `WACC = Wₑ × Ke + Wd × Kd(after-tax)`
            = {wr.weight_equity:.2%} × {wr.cost_equity:.4%}
            + {wr.weight_debt:.2%} × {wr.aftertax_cost_debt:.4%}
            = **{wr.wacc:.4%}**
            """
        )

    # ---- Bloque D: WACC en estado estable (Damodaran terminal) ----
    with st.expander("**🟪 D · Terminal Cost of Capital (año 10+)**",
                       expanded=False):
        st.markdown(
            f"""
            En estado estable (después del año 10), Damodaran asume que la
            empresa converge a un perfil de riesgo más promedio. Por defecto:

            - **Cost of Capital terminal** = max(WACC inicial, riskfree + ERP × 1.0)
            - Si activaste *override* en Input Sheet sec G, se usa ese valor.

            | Concepto | Valor |
            |---|---:|
            | WACC inicial (Y1) | **{wr.wacc:.4%}** |
            | WACC terminal usado | **{out.terminal_wacc:.4%}** |
            | Terminal growth (g) | **{a.terminal_growth:.4%}** |
            | β terminal (asume → 1.0) | 1.000 |
            """
        )

    st.info(
        "📐 **Cómo se conecta:** este WACC alimenta el descuento de los "
        "FCFF anuales en *Proyección FCFF* y la perpetuidad terminal. "
        "Inputs editables (riskfree) están en *Input Sheet → sec E*; "
        "los demás (β, ERP, terminal) heredan defaults sector/market."
    )

    tab_coc.__exit__(None, None, None)

    # ============================================================
    # SUB-TAB 3: 📈 PROYECCIÓN FCFF (Resultado + Damodaran outputs + Chart)
    # ============================================================
    tab_proj.__enter__()

    st.subheader("Resultado")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Value/share", f"{out.value_per_share:,.2f} MXN",
              f"{out.upside_pct*100:+.1f}% vs mkt")
    k2.metric("Market price", f"{market_price:,.2f} MXN")
    k3.metric("Initial WACC", f"{out.wacc_result.wacc:.2%}",
              f"β L = {out.wacc_result.levered_beta:.2f}")
    k4.metric("Equity Value", f"{out.equity_value:,.0f} MDP",
              f"EV {out.enterprise_value:,.0f}")

    # ============================================================
    # 🎯 Damodaran outputs (Hoja 1) — visible siempre que activan controles
    # ============================================================
    show_damodaran_panel = (
        a.revenue_growth_y1 is not None or a.op_margin_y1 is not None or
        a.year_of_margin_convergence != 5 or a.override_terminal_roic or
        a.probability_of_failure > 0 or a.nol_carryforward > 0 or
        a.reinvestment_lag > 0 or a.trapped_cash > 0 or
        a.sales_to_capital_y1_5 is not None or a.sales_to_capital_y6_10 is not None
    )

    with st.expander(
        f"🎯 Damodaran outputs (Hoja 1) {'• ⚡ ACTIVO' if show_damodaran_panel else '• defaults'}",
        expanded=show_damodaran_panel,
    ):
        st.markdown("**Inputs Damodaran efectivos:**")
        d_col1, d_col2 = st.columns(2)
        with d_col1:
            eff_y1_g = a.revenue_growth_y1 if a.revenue_growth_y1 is not None else a.revenue_growth_high
            eff_y1_m = a.op_margin_y1 if a.op_margin_y1 is not None else (base.ebit / base.revenue if base.revenue else 0)
            st.markdown(
                f"- **Revenue growth Y1:** {eff_y1_g:.2%}  "
                f"{' *(override)*' if a.revenue_growth_y1 is not None else ' *(default = Y2-Y5)*'}"
            )
            st.markdown(
                f"- **Op margin Y1:** {eff_y1_m:.2%}  "
                f"{' *(override)*' if a.op_margin_y1 is not None else ' *(default = current)*'}"
            )
            st.markdown(
                f"- **Year of margin convergence:** Y{a.year_of_margin_convergence}  "
                f"{' *(Damodaran default = 5)*' if a.year_of_margin_convergence == 5 else ' *(override)*'}"
            )
            s2c_y1_5_eff = a.sales_to_capital_y1_5 if a.sales_to_capital_y1_5 is not None else a.sales_to_capital
            s2c_y6_10_eff = a.sales_to_capital_y6_10 if a.sales_to_capital_y6_10 is not None else a.sales_to_capital
            st.markdown(
                f"- **Sales-to-Capital:** Y1-5 = {s2c_y1_5_eff:.2f}x  /  Y6-10 = {s2c_y6_10_eff:.2f}x"
            )
        with d_col2:
            terminal_roic_used = a.terminal_roic_override if a.override_terminal_roic else out.terminal_wacc
            terminal_reinv_rate = a.terminal_growth / terminal_roic_used if terminal_roic_used > 0 else 0
            st.markdown(
                f"- **Terminal ROIC usado:** {terminal_roic_used:.2%}  "
                f"{' *(OVERRIDE)*' if a.override_terminal_roic else ' *(Damodaran = WACC_terminal)*'}"
            )
            st.markdown(
                f"- **Terminal Reinvestment Rate:** {terminal_reinv_rate:.2%}  "
                f"*(= g_terminal / ROIC_terminal)*"
            )
            st.markdown(
                f"- **Probability of failure:** {a.probability_of_failure:.2%}  "
                f"basis={a.failure_proceeds_basis}  recover={a.failure_proceeds_pct:.0%}"
            )
            if a.nol_carryforward > 0:
                st.markdown(f"- **NOL carryforward:** {a.nol_carryforward:,.1f} MDP")
            if a.trapped_cash > 0:
                st.markdown(
                    f"- **Trapped Cash:** {a.trapped_cash:,.1f} MDP @ tax {a.trapped_cash_tax_rate:.0%} "
                    f"→ haircut {a.trapped_cash * a.trapped_cash_tax_rate:,.1f} MDP"
                )

        # Failure adjustment breakdown
        if a.probability_of_failure > 0:
            st.markdown("---")
            st.markdown("**🔻 Failure Adjustment Bridge:**")
            dcf_op_value = out.sum_pv_fcff + out.pv_terminal
            if a.failure_proceeds_basis == "B":
                book_cap = base.equity_book + base.financial_debt
                distress = book_cap * a.failure_proceeds_pct
                basis_label = f"Book Capital ({book_cap:,.1f})"
            else:
                distress = dcf_op_value * a.failure_proceeds_pct
                basis_label = f"DCF Fair Value ({dcf_op_value:,.1f})"

            st.markdown(
                f"- DCF Operating Value (pre-failure): **{dcf_op_value:,.1f} MDP**\n"
                f"- Distress Proceeds: {basis_label} × {a.failure_proceeds_pct:.0%} = **{distress:,.1f} MDP**\n"
                f"- Final EV = (1-{a.probability_of_failure:.0%}) × {dcf_op_value:,.1f} + "
                f"{a.probability_of_failure:.0%} × {distress:,.1f} = **{out.enterprise_value:,.1f} MDP**"
            )

    # Proyeccion grafico
    st.subheader("Proyeccion FCFF")
    st.altair_chart(_projection_chart(out), use_container_width=True)
    with st.expander("Tabla de proyeccion 10y"):
        st.dataframe(out.projection_table(), hide_index=True, use_container_width=True)

    # NOTA: Tornado de sensibilidad eliminado de pagina principal.
    # Sigue disponible en tab '🎯 Sensitivity'.

    tab_proj.__exit__(None, None, None)

    # ========================================================================
    # Helper: invested capital y ROIC implicitos (usando S2C constante)
    # Necesario para tabs subsiguientes (Estados, Bloomberg Validation, etc.)
    # ========================================================================
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

    # ============================================================
    # TAB 6: ESTADOS FINANCIEROS (Income + BS + CF historicos, estilo Bloomberg)
    # ============================================================
    tab_estados.__enter__()

    st.subheader(f"Estados Financieros — {issuer.ticker}")
    st.caption(
        "Vista historica multi-periodo estilo Bloomberg. "
        "Selecciona Anual o Trimestral, navega entre Income / Balance / Cash Flow. "
        "Valores en MDP (USD->MXN auto-convertido)."
    )

    if not HAS_HISTORICAL:
        st.error(f"Historical module no disponible: {_HIST_ERR}")
    else:
        try:
            hs_ef = load_historical(issuer.ticker,
                                      parse_func=lambda fp: _parse_cached(str(fp)))
        except Exception as e:
            st.error(f"Error cargando: {e}")
            hs_ef = None

        if hs_ef is None or hs_ef.n_periods == 0:
            st.warning(f"No hay XBRLs disponibles para {issuer.ticker}.")
        else:
            # Toggle Anual vs Trimestral
            view_col1, view_col2, view_col3 = st.columns([2, 1, 1])
            with view_col1:
                view_mode = st.radio(
                    "Vista",
                    ["Anual", "Trimestral"],
                    horizontal=True,
                    key=f"ef_view_{issuer.ticker}",
                )
            with view_col2:
                max_periods_pick = st.selectbox(
                    "Mostrar últimos N",
                    [4, 8, 12, 16, 20, "Todos"],
                    index=3,
                    key=f"ef_npick_{issuer.ticker}",
                )
            with view_col3:
                st.metric("Periodos disponibles", hs_ef.n_periods,
                          f"Anuales: {hs_ef.n_annual}")

            annual_only_ef = view_mode.startswith("Anual")
            max_n = None if max_periods_pick == "Todos" else int(max_periods_pick)

            # Si se pide Anual pero no hay 4D, fallback automatico a "solo Q4 preliminares"
            if annual_only_ef and hs_ef.n_annual == 0:
                # Filtrar a Q4 preliminares como aproximacion anual
                hs_ef_view = type(hs_ef)(
                    ticker=hs_ef.ticker,
                    snapshots=[s for s in hs_ef.snapshots if s.quarter == "4"],
                )
                if hs_ef_view.n_periods == 0:
                    st.warning(
                        "No hay XBRLs anuales (4D) ni Q4 preliminares. "
                        "Usa vista trimestral o descarga los 4D."
                    )
                    hs_ef_view = hs_ef
                else:
                    st.info(
                        f"No hay 4D (anuales auditados) — usando {hs_ef_view.n_periods} "
                        f"Q4 preliminares como proxy anual."
                    )
                use_annual_flag = False  # ya filtramos manualmente
            else:
                hs_ef_view = hs_ef
                use_annual_flag = annual_only_ef

            fx_rate = market.fx_rate_usdmxn

            # Sub-tabs Income / Balance / CashFlow / Vertical & Horizontal
            sub_is, sub_bs, sub_cf, sub_vh = st.tabs([
                "Income Statement",
                "Balance Sheet",
                "Cash Flow",
                "📐 Vertical & Horizontal",
            ])

            def _render_panel(panel_df, kinds_list, title):
                """Renderiza tabla estilo Bloomberg con HTML puro (full styling)."""
                if panel_df.empty or panel_df.shape[1] == 0:
                    st.warning(f"Sin datos para {title}.")
                    return
                fmt_df = format_panel(panel_df, kinds_list)
                import html as _html

                # CSS Bloomberg-grade con STICKY first column + sticky header
                css = """
                <style>
                .bb-wrap {
                    overflow-x: auto;
                    overflow-y: visible;
                    margin: 4px 0 18px 0;
                    max-width: 100%;
                    position: relative;
                }
                .bb-table {
                    border-collapse: separate;          /* requerido para sticky */
                    border-spacing: 0;
                    width: 100%;
                    font-family: "Segoe UI","Arial","Helvetica Neue",sans-serif;
                    font-size: 12.5px;
                    table-layout: auto;
                }
                .bb-table th, .bb-table td {
                    padding: 4px 12px;
                    border-bottom: 1px solid #E5E7EB;
                }
                /* Column headers (top row) - sticky en eje Y */
                .bb-col-head {
                    text-align: right;
                    background: #F9FAFB;
                    color: #111827;
                    font-weight: 700;
                    border-bottom: 2px solid #1F4E79 !important;
                    position: sticky; top: 0; z-index: 2;
                }
                /* PRIMERA COLUMNA (concepto) - STICKY en eje X */
                .bb-row-head {
                    text-align: left;
                    white-space: pre;
                    padding-left: 12px;
                    font-weight: inherit;
                    color: inherit;
                    position: sticky;
                    left: 0;
                    z-index: 1;                           /* arriba de td normales */
                    box-shadow: 2px 0 4px -2px rgba(0,0,0,0.15);  /* sombra sutil al scroll */
                    min-width: 280px;
                    max-width: 380px;
                }
                /* Esquina top-left (intersección sticky row + col) - z-index mas alto */
                .bb-col-head.bb-row-head {
                    z-index: 3;
                }
                .bb-table td { text-align: right; font-variant-numeric: tabular-nums; }
                /* Row variants - aplicar bg a TH sticky tambien para que tape al hacer scroll */
                .bb-r-header   { background: #1F4E79; color: #FFFFFF; font-weight: 700; }
                .bb-r-header   td, .bb-r-header   th { color: #FFFFFF !important; font-weight: 700 !important; background: #1F4E79; }
                .bb-r-subtotal { background: #DCEDC8; color: #14532D; font-weight: 700; }
                .bb-r-subtotal td, .bb-r-subtotal th { font-weight: 700 !important; background: #DCEDC8; }
                .bb-r-section  { background: #4B5563; color: #FFFFFF; font-weight: 600; font-style: italic; }
                .bb-r-section  td, .bb-r-section  th { color: #FFFFFF !important; background: #4B5563; }
                .bb-r-ratio    { background: #F1F8E9; color: #1F2937; font-style: italic; }
                .bb-r-ratio    td, .bb-r-ratio    th { background: #F1F8E9; }
                .bb-r-ratio_eps{ background: #FFF8E1; color: #1F2937; font-style: italic; }
                .bb-r-ratio_eps td, .bb-r-ratio_eps th { background: #FFF8E1; }
                .bb-r-ratio_x  { background: #FFF3E0; color: #1F2937; font-style: italic; }
                .bb-r-ratio_x  td, .bb-r-ratio_x  th { background: #FFF3E0; }
                .bb-r-raw_days { background: #FCE7F3; color: #1F2937; font-style: italic; }
                .bb-r-raw_days td, .bb-r-raw_days th { background: #FCE7F3; }
                .bb-r-raw      { background: #F9FBF7; color: #1F2937; }
                .bb-r-raw      td, .bb-r-raw      th { background: #F9FBF7; }
                .bb-r-string   { background: #F3F4F6; color: #374151; font-style: italic; }
                .bb-r-string   td, .bb-r-string   th { background: #F3F4F6; }
                .bb-r-sub      { background: #FAFCFA; color: #4B5563; font-size: 11.5px; }
                .bb-r-sub      td, .bb-r-sub      th { background: #FAFCFA; }
                .bb-r-bold_line{ background: #F9FBF7; color: #111827; font-weight: 700; }
                .bb-r-bold_line td, .bb-r-bold_line th { font-weight: 700 !important; background: #F9FBF7; }
                .bb-r-spacer   { background: #FFFFFF; height: 8px; }
                .bb-r-spacer td, .bb-r-spacer th { padding: 0 12px; border-bottom: none; background: #FFFFFF; }
                .bb-r-line     { background: #FFFFFF; color: #1F2937; }
                .bb-r-line     td, .bb-r-line     th { background: #FFFFFF; }
                </style>
                """

                # Build HTML
                rows_html = []
                # Header
                head_cells = "".join(
                    f'<th class="bb-col-head">{_html.escape(str(c))}</th>'
                    for c in fmt_df.columns
                )
                rows_html.append(f'<tr><th class="bb-col-head bb-row-head">&nbsp;</th>{head_cells}</tr>')

                for i, (idx, row) in enumerate(fmt_df.iterrows()):
                    kind = kinds_list[i] if i < len(kinds_list) else "line"
                    css_cls = f"bb-r-{kind}"
                    # Preservar leading spaces convirtiendolos a &nbsp; (white-space:pre tambien aplica)
                    label_html = _html.escape(str(idx)).replace(" ", "&nbsp;")
                    cells = "".join(
                        f'<td>{_html.escape(str(row[c])) if row[c] is not None else ""}</td>'
                        for c in fmt_df.columns
                    )
                    rows_html.append(
                        f'<tr class="{css_cls}"><th class="bb-row-head">{label_html}</th>{cells}</tr>'
                    )

                table_html = (
                    f'{css}<div class="bb-wrap"><table class="bb-table">'
                    + "".join(rows_html)
                    + "</table></div>"
                )
                st.markdown(table_html, unsafe_allow_html=True)

            with sub_is:
                df_is, kinds_is = build_income_adjusted_panel(
                    hs_ef_view, annual_only=use_annual_flag,
                    fx_rate_usdmxn=fx_rate, max_periods=max_n,
                )
                vista_label = "FY (12M)" if use_annual_flag else "3M Quarter Pure"
                st.markdown(f"#### Income — Adjusted (Bloomberg style) "
                             f"• {df_is.shape[1]} periodos • {vista_label} • In MDP")
                _render_panel(df_is, kinds_is, "Income")

            with sub_bs:
                df_bs, kinds_bs = build_bs_standardized_panel(
                    hs_ef_view, annual_only=use_annual_flag,
                    fx_rate_usdmxn=fx_rate, max_periods=max_n,
                )
                st.markdown(f"#### Balance Sheet — Standardized (Bloomberg style) "
                             f"• {df_bs.shape[1]} periodos • In MDP")
                _render_panel(df_bs, kinds_bs, "Balance")

            with sub_cf:
                df_cf, kinds_cf = build_cf_standardized_panel(
                    hs_ef_view, annual_only=use_annual_flag,
                    fx_rate_usdmxn=fx_rate, max_periods=max_n,
                )
                vista_cf = "FY accumulated" if use_annual_flag else "3M Quarter (derived)"
                st.markdown(f"#### Cash Flow — Standardized (Bloomberg style) "
                             f"• {df_cf.shape[1]} periodos • {vista_cf} • In MDP")
                _render_panel(df_cf, kinds_cf, "Cash Flow")

            # ============================================================
            # 📐 SUB-TAB: VERTICAL & HORIZONTAL ANALYSIS + RED FLAGS
            # ============================================================
            with sub_vh:
                st.markdown("### 📐 Análisis Vertical & Horizontal")
                st.caption(
                    "**Análisis Vertical:** cada línea como % de un total (Revenue para IS, "
                    "Total Assets para BS). **Análisis Horizontal:** cambios YoY entre 2 periodos. "
                    "**Detección automática:** red flags (deteriorios) y mejoras (improvements)."
                )

                try:
                    from src.dcf_mexico.analysis import (
                        vertical_income, vertical_balance, vertical_cashflow,
                        horizontal_income, horizontal_balance, horizontal_cashflow,
                        detect_changes, categorize_changes, changes_to_table,
                        Significance, Direction,
                    )

                    snaps_avail = hs_ef_view.snapshots
                    if len(snaps_avail) < 2:
                        st.warning("Necesitas al menos 2 periodos para análisis horizontal.")
                    else:
                        # Selectores de periodo
                        sel_c1, sel_c2 = st.columns(2)
                        with sel_c1:
                            curr_idx = st.selectbox(
                                "Periodo Actual",
                                options=range(len(snaps_avail)),
                                index=len(snaps_avail) - 1,
                                format_func=lambda i: snaps_avail[i].label,
                                key=f"vh_curr_{issuer.ticker}",
                            )
                        with sel_c2:
                            # Default: mismo Q año anterior si existe, sino periodo prior
                            curr_snap = snaps_avail[curr_idx]
                            prior_default_idx = max(0, curr_idx - 1)
                            # Buscar mismo Q año previo
                            for i, s in enumerate(snaps_avail):
                                if (s.year == curr_snap.year - 1 and
                                    s.quarter == curr_snap.quarter):
                                    prior_default_idx = i
                                    break
                            prior_idx = st.selectbox(
                                "Periodo Comparación (Prior)",
                                options=range(len(snaps_avail)),
                                index=prior_default_idx,
                                format_func=lambda i: snaps_avail[i].label,
                                key=f"vh_prior_{issuer.ticker}",
                            )

                        curr_snap = snaps_avail[curr_idx]
                        prior_snap = snaps_avail[prior_idx]

                        st.markdown(f"**Comparando:** `{curr_snap.label}` vs `{prior_snap.label}`")

                        # ============================================================
                        # 🚨 RED FLAGS & IMPROVEMENTS (lo más importante - arriba)
                        # ============================================================
                        st.markdown("---")
                        st.markdown("#### 🎯 Cambios Significativos Detectados (auto)")

                        changes = detect_changes(curr_snap, prior_snap, fx_mult=fx_rate)
                        cat = categorize_changes(changes)

                        rf_col1, rf_col2, rf_col3 = st.columns(3)
                        with rf_col1:
                            st.metric("🔴 Red Flags",
                                      len(cat["red_flags"]),
                                      help="Deterioros importantes que requieren atención")
                        with rf_col2:
                            st.metric("🟢 Improvements",
                                      len(cat["improvements"]),
                                      help="Mejoras estructurales positivas")
                        with rf_col3:
                            st.metric("🔴 Alta significancia",
                                      len(cat["all_high_sig"]),
                                      help="Cambios > 25%")

                        if cat["red_flags"]:
                            st.markdown("##### 🔴 RED FLAGS")
                            for c in cat["red_flags"]:
                                st.error(
                                    f"**{c.metric}** ({c.category}): {c.narrative}\n\n"
                                    f"💡 *{c.interpretation}*"
                                )

                        if cat["improvements"]:
                            st.markdown("##### 🟢 IMPROVEMENTS")
                            for c in cat["improvements"]:
                                st.success(
                                    f"**{c.metric}** ({c.category}): {c.narrative}\n\n"
                                    f"💡 *{c.interpretation}*"
                                )

                        # Tabla completa de cambios
                        if changes:
                            with st.expander(f"📋 Ver TODOS los {len(changes)} cambios detectados"):
                                df_changes = changes_to_table(changes)
                                st.dataframe(
                                    df_changes, hide_index=True,
                                    use_container_width=True,
                                )

                        # ============================================================
                        # ANÁLISIS VERTICAL (3 columnas: IS / BS / CF)
                        # ============================================================
                        st.markdown("---")
                        st.markdown(f"#### 📊 Análisis Vertical (`{curr_snap.label}`)")

                        v_tab_is, v_tab_bs, v_tab_cf = st.tabs([
                            "📈 Income Statement",
                            "💰 Balance Sheet",
                            "💵 Cash Flow",
                        ])
                        with v_tab_is:
                            v_inc = vertical_income(curr_snap, fx_mult=fx_rate)
                            if not v_inc.empty:
                                st.caption("Cada línea como % de Revenue. Útil para detectar "
                                           "expansión/contracción de márgenes y mix de costos.")
                                st.dataframe(v_inc, hide_index=True, use_container_width=True)
                        with v_tab_bs:
                            v_bs = vertical_balance(curr_snap, fx_mult=fx_rate)
                            if not v_bs.empty:
                                st.caption("Cada línea como % de Total Assets. Útil para ver "
                                           "estructura de capital, mix de activos.")
                                st.dataframe(v_bs, hide_index=True, use_container_width=True)
                        with v_tab_cf:
                            v_cf = vertical_cashflow(curr_snap, fx_mult=fx_rate)
                            if not v_cf.empty:
                                st.caption("Cada línea como % de Revenue. Útil para ver "
                                           "intensidad de CapEx, dividendos, financiamiento.")
                                st.dataframe(v_cf, hide_index=True, use_container_width=True)

                        # ============================================================
                        # ANÁLISIS HORIZONTAL (3 columnas: IS / BS / CF)
                        # ============================================================
                        st.markdown("---")
                        st.markdown(f"#### 🔄 Análisis Horizontal "
                                    f"(`{curr_snap.label}` vs `{prior_snap.label}`)")

                        h_tab_is, h_tab_bs, h_tab_cf = st.tabs([
                            "📈 Income Statement",
                            "💰 Balance Sheet",
                            "💵 Cash Flow",
                        ])
                        with h_tab_is:
                            h_inc = horizontal_income(curr_snap, prior_snap, fx_mult=fx_rate)
                            if not h_inc.empty:
                                st.dataframe(h_inc, hide_index=True, use_container_width=True)
                        with h_tab_bs:
                            h_bs = horizontal_balance(curr_snap, prior_snap, fx_mult=fx_rate)
                            if not h_bs.empty:
                                st.dataframe(h_bs, hide_index=True, use_container_width=True)
                        with h_tab_cf:
                            h_cf = horizontal_cashflow(curr_snap, prior_snap, fx_mult=fx_rate)
                            if not h_cf.empty:
                                st.dataframe(h_cf, hide_index=True, use_container_width=True)

                        # ============================================================
                        # 📈 MULTI-PERIOD TRENDS (CAGR 3y / 5y / all + classification)
                        # ============================================================
                        st.markdown("---")
                        st.markdown("#### 📈 Análisis Multi-Period (Tendencias seculares)")
                        st.caption(
                            "Más allá del simple YoY: detecta CAGR de 3y/5y/all, "
                            "aceleración o desaceleración, reversiones de tendencia, "
                            "persistencia (años consecutivos), y clasifica cada métrica "
                            "como secular_growth/decline/cyclical/recovery/etc."
                        )

                        try:
                            from src.dcf_mexico.analysis import (
                                compute_all_trends, trends_to_table, categorize_trends,
                                TrendClassification,
                            )
                            trends_all = compute_all_trends(hs_ef_view, fx_mult=fx_rate)

                            if not trends_all:
                                st.warning("Necesitas al menos 2 años anuales para calcular trends.")
                            else:
                                trend_cat = categorize_trends(trends_all)

                                # Resumen de classifications
                                tc1, tc2, tc3, tc4, tc5 = st.columns(5)
                                with tc1:
                                    st.metric("🚀 Secular Growth",
                                              len(trend_cat["secular_growth"]),
                                              help="Crecimiento sostenido + persistente")
                                with tc2:
                                    st.metric("📉 Secular Decline",
                                              len(trend_cat["secular_decline"]),
                                              help="Caída sostenida")
                                with tc3:
                                    st.metric("⚠️ Deterioration",
                                              len(trend_cat["deterioration"]),
                                              help="Empeorando 3+ años consecutivos")
                                with tc4:
                                    st.metric("🔄🟢 Reversión Positiva",
                                              len(trend_cat["reversal_positive"]),
                                              help="Cambió de baja a alta")
                                with tc5:
                                    st.metric("🔄🔴 Reversión Negativa",
                                              len(trend_cat["reversal_negative"]),
                                              help="Cambió de alta a baja")

                                # Highlights por categoria (los mas importantes)
                                if trend_cat["deterioration"]:
                                    st.markdown("##### ⚠️ DETERIORATION — RED FLAGS de tendencia")
                                    for t in trend_cat["deterioration"]:
                                        st.error(
                                            f"**{t.metric}** ({t.category}): {t.narrative}\n\n"
                                            f"💡 *{t.interpretation}*"
                                        )

                                if trend_cat["secular_growth"]:
                                    st.markdown("##### 🚀 SECULAR GROWTH — Tendencias positivas")
                                    for t in trend_cat["secular_growth"]:
                                        st.success(
                                            f"**{t.metric}** ({t.category}): {t.narrative}\n\n"
                                            f"💡 *{t.interpretation}*"
                                        )

                                if trend_cat["secular_decline"]:
                                    st.markdown("##### 📉 SECULAR DECLINE — caída persistente")
                                    st.caption(
                                        "Nota: para algunas métricas (DIO, DSO, CCC, "
                                        "Inventories, Debt) bajar es **POSITIVO** — no "
                                        "siempre red flag."
                                    )
                                    for t in trend_cat["secular_decline"]:
                                        # Métricas donde "decline" es bueno
                                        good_decline_metrics = (
                                            "DIO", "DSO", "DPO", "Cash Conversion",
                                            "Inventories", "Total Debt", "Net Debt"
                                        )
                                        is_good = any(m in t.metric for m in good_decline_metrics)
                                        if is_good:
                                            st.success(
                                                f"**{t.metric}** ({t.category}): {t.narrative}\n\n"
                                                f"💡 *Bajada es POSITIVA en esta métrica.*"
                                            )
                                        else:
                                            st.warning(
                                                f"**{t.metric}** ({t.category}): {t.narrative}\n\n"
                                                f"💡 *{t.interpretation}*"
                                            )

                                # Reversiones (importantes pq son cambios de regimen)
                                if trend_cat["reversal_positive"]:
                                    with st.expander(
                                        f"🔄🟢 Reversiones POSITIVAS ({len(trend_cat['reversal_positive'])})",
                                        expanded=False,
                                    ):
                                        for t in trend_cat["reversal_positive"]:
                                            st.info(
                                                f"**{t.metric}** ({t.category}): {t.narrative}"
                                            )
                                if trend_cat["reversal_negative"]:
                                    with st.expander(
                                        f"🔄🔴 Reversiones NEGATIVAS ({len(trend_cat['reversal_negative'])})",
                                        expanded=False,
                                    ):
                                        for t in trend_cat["reversal_negative"]:
                                            st.info(
                                                f"**{t.metric}** ({t.category}): {t.narrative}"
                                            )

                                # Tabla completa
                                with st.expander(
                                    f"📋 Ver tabla completa de los {len(trends_all)} trends",
                                    expanded=False,
                                ):
                                    df_trends = trends_to_table(trends_all)
                                    st.dataframe(
                                        df_trends, hide_index=True,
                                        use_container_width=True,
                                        height=min(700, 50 + 35 * len(df_trends)),
                                    )

                                # Visualización: serie temporal de métricas seleccionadas
                                with st.expander(
                                    "📊 Ver gráficas de evolución (selecciona métricas)",
                                    expanded=False,
                                ):
                                    metric_names = [t.metric for t in trends_all]
                                    selected_metrics = st.multiselect(
                                        "Métricas a graficar",
                                        options=metric_names,
                                        default=["Revenue", "EBIT", "Net Income", "Free Cash Flow"]
                                                if all(m in metric_names for m in
                                                       ["Revenue", "EBIT", "Net Income", "Free Cash Flow"])
                                                else metric_names[:3],
                                        key=f"vh_trend_select_{issuer.ticker}",
                                    )
                                    if selected_metrics:
                                        chart_data = []
                                        for t in trends_all:
                                            if t.metric not in selected_metrics:
                                                continue
                                            for year, val in t.values:
                                                chart_data.append({
                                                    "Year": year,
                                                    "Métrica": t.metric,
                                                    "Valor": val,
                                                })
                                        if chart_data:
                                            chart_df = pd.DataFrame(chart_data)
                                            line_chart = (
                                                alt.Chart(chart_df)
                                                .mark_line(point=True, strokeWidth=2)
                                                .encode(
                                                    x=alt.X("Year:O", title="Año",
                                                            axis=alt.Axis(labelColor='black')),
                                                    y=alt.Y("Valor:Q", title="Valor",
                                                            axis=alt.Axis(labelColor='black')),
                                                    color=alt.Color("Métrica:N", legend=alt.Legend(orient="bottom")),
                                                    tooltip=["Year:O", "Métrica:N", "Valor:Q"],
                                                )
                                                .properties(height=350)
                                            )
                                            st.altair_chart(line_chart, use_container_width=True)

                        except Exception as e_t:
                            st.error(f"Error en multi-period trends: {e_t}")
                            import traceback
                            st.code(traceback.format_exc())

                except Exception as e_vh:
                    st.error(f"Error en análisis vertical/horizontal: {e_vh}")
                    import traceback
                    st.code(traceback.format_exc())

    # ----- TAB Estados close, TAB Historical open -----
    tab_estados.__exit__(None, None, None)
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
    tab_forecast.__enter__()

    # ============================================================
    # 🔮 TAB FORECAST EEFF — proyección driver-based integrada con DCF
    # ============================================================
    st.subheader(f"🔮 Forecast Estados Financieros — {issuer.ticker}")
    st.caption(
        "Proyección driver-based estilo Damodaran. Los DRIVERS (revenue growth, "
        "EBIT margin, CapEx %, etc.) se calculan automáticamente del histórico — "
        "puedes editarlos. Los 3 EEFF (Income, Balance, Cash Flow) se proyectan "
        "consistentemente y el FCFF resultante alimenta el DCF."
    )

    try:
        from src.dcf_mexico.projection import (
            BaseFinancials, ProjectionDrivers, project_financials, run_backtest
        )

        # 1) Cargar histórico
        hs_fc = load_historical(
            issuer.ticker,
            parse_func=lambda fp: _parse_cached(str(fp)),
        )
        if not hs_fc.snapshots or len(hs_fc.annual) < 2:
            st.warning(
                f"Necesitas al menos 2 años anuales de XBRL parseados. "
                f"Actualmente: {len(hs_fc.annual)} años. "
                "Sube más archivos a `data/raw_xbrl/`."
            )
        else:
            # 2) Configuración
            cfg_c1, cfg_c2, cfg_c3 = st.columns([1, 1, 1])
            with cfg_c1:
                horizon = st.slider("Horizonte (años)", 3, 10, 5, key=f"fc_horizon_{issuer.ticker}")
            with cfg_c2:
                smoothing = st.selectbox(
                    "Método de drivers",
                    ["median", "avg", "last"],
                    index=0,
                    format_func=lambda x: {"median": "Mediana (robusto)",
                                            "avg": "Promedio",
                                            "last": "Último observado"}[x],
                    key=f"fc_smoothing_{issuer.ticker}",
                )
            with cfg_c3:
                show_bs = st.checkbox("Mostrar Balance Sheet proyectado", value=True,
                                       key=f"fc_show_bs_{issuer.ticker}")

            # 3) Calcular drivers desde histórico
            curr_fc = (res.info.currency or "MXN").upper().strip()
            fx_fc = market.fx_rate_usdmxn if curr_fc == "USD" else 1.0
            base_fc = BaseFinancials.from_snapshot(hs_fc.annual[-1], fx_mult=fx_fc)
            drivers_fc = ProjectionDrivers.from_history(
                hs_fc, horizon=horizon, fx_mult=fx_fc, smoothing=smoothing
            )

            # 4) Editor de drivers (data_editor para edición año a año)
            st.markdown("##### 🎛️ Drivers (auto-calculados, editables)")
            st.caption("Edita cualquier celda para sensibilizar la proyección. Tax y CapEx % "
                       "están en decimal (0.27 = 27%). Días son enteros.")

            year_labels = [f"Y{i+1} ({base_fc.year + i + 1})" for i in range(horizon)]
            drivers_data = {
                "Driver": [
                    "Revenue Growth",
                    "Gross Margin",
                    "OpEx % Rev (display)",
                    "EBIT Margin (PRIMARIO)",
                    "D&A % Rev",
                    "Tax Rate",
                    "CapEx % Rev",
                    "DIO (days)",
                    "DSO (days)",
                    "DPO (days)",
                    "Payout Ratio",
                ],
            }
            for i in range(horizon):
                drivers_data[year_labels[i]] = [
                    round(drivers_fc.revenue_growth_path[i], 4),
                    round(drivers_fc.gross_margin_path[i], 4),
                    round(drivers_fc.opex_pct_revenue_path[i], 4),
                    round(drivers_fc.ebit_margin_path[i], 4),
                    round(drivers_fc.da_pct_revenue_path[i], 4),
                    round(drivers_fc.tax_rate_path[i], 4),
                    round(drivers_fc.capex_pct_revenue_path[i], 4),
                    int(round(drivers_fc.dio_days_path[i])),
                    int(round(drivers_fc.dso_days_path[i])),
                    int(round(drivers_fc.dpo_days_path[i])),
                    round(drivers_fc.payout_ratio_path[i], 4) if drivers_fc.payout_ratio_path else 0.30,
                ]
            df_drivers = pd.DataFrame(drivers_data)
            edited = st.data_editor(
                df_drivers, hide_index=True, use_container_width=True,
                key=f"fc_drivers_editor_{issuer.ticker}_{horizon}_{smoothing}",
            )

            # Reconstruir drivers desde lo editado
            edited_drivers = ProjectionDrivers(
                horizon=horizon,
                revenue_growth_path=[float(edited.iloc[0][year_labels[i]]) for i in range(horizon)],
                gross_margin_path=[float(edited.iloc[1][year_labels[i]]) for i in range(horizon)],
                opex_pct_revenue_path=[float(edited.iloc[2][year_labels[i]]) for i in range(horizon)],
                ebit_margin_path=[float(edited.iloc[3][year_labels[i]]) for i in range(horizon)],
                da_pct_revenue_path=[float(edited.iloc[4][year_labels[i]]) for i in range(horizon)],
                tax_rate_path=[float(edited.iloc[5][year_labels[i]]) for i in range(horizon)],
                capex_pct_revenue_path=[float(edited.iloc[6][year_labels[i]]) for i in range(horizon)],
                dio_days_path=[float(edited.iloc[7][year_labels[i]]) for i in range(horizon)],
                dso_days_path=[float(edited.iloc[8][year_labels[i]]) for i in range(horizon)],
                dpo_days_path=[float(edited.iloc[9][year_labels[i]]) for i in range(horizon)],
                interest_rate_on_debt=0.10,
                payout_ratio_path=[float(edited.iloc[10][year_labels[i]]) for i in range(horizon)],
            )

            # 5) Proyectar
            result_fc = project_financials(base_fc, edited_drivers, horizon=horizon)

            # 6) Display: 3 tablas
            st.markdown("---")
            st.markdown("##### 📊 Income Statement Proyectado")
            st.dataframe(result_fc.income_statement_table(), use_container_width=True)

            st.markdown("##### 💵 Cash Flow Proyectado")
            st.dataframe(result_fc.cash_flow_table(), use_container_width=True)

            if show_bs:
                st.markdown("##### 💰 Balance Sheet Proyectado (simplificado)")
                st.dataframe(result_fc.balance_sheet_table(), use_container_width=True)

            # 7) Métricas resumen
            st.markdown("---")
            st.markdown("##### 🎯 Resumen")
            mc1, mc2, mc3, mc4 = st.columns(4)
            last_y = result_fc.years[-1]
            with mc1:
                cagr_rev = (last_y.revenue / base_fc.revenue) ** (1/horizon) - 1 if base_fc.revenue > 0 else 0
                st.metric(f"Revenue CAGR {horizon}y", f"{cagr_rev*100:+.2f}%",
                          f"{base_fc.revenue:,.0f} → {last_y.revenue:,.0f}")
            with mc2:
                avg_ebit_m = sum(y.op_margin for y in result_fc.years) / horizon
                base_margin = base_fc.ebit / base_fc.revenue if base_fc.revenue > 0 else 0
                st.metric(f"Avg EBIT Margin", f"{avg_ebit_m*100:.1f}%",
                          f"vs base {base_margin*100:.1f}%")
            with mc3:
                total_fcff = sum(y.fcff for y in result_fc.years)
                st.metric(f"Sum FCFF {horizon}y", f"{total_fcff:,.0f} MDP")
            with mc4:
                last_fcff = result_fc.years[-1].fcff
                st.metric(f"FCFF Y{horizon}", f"{last_fcff:,.0f} MDP",
                          f"vs hoy {(base_fc.cfo - base_fc.capex):,.0f}")

            # 8) BACK-TEST
            st.markdown("---")
            st.markdown("##### 🧪 Back-test: ¿Cómo predeciría esta metodología si la hubiéramos aplicado en el pasado?")
            available_anchors = [s.year for s in hs_fc.annual[:-1]]   # excluyendo el último
            if len(available_anchors) >= 1:
                anchor_pick = st.selectbox(
                    "Año-ancla del back-test",
                    options=available_anchors,
                    index=len(available_anchors)-1,
                    help="Selecciona un año del pasado. El modelo proyecta usando solo info ≤ ese año, "
                         "y compara contra los valores reales observados después.",
                    key=f"fc_anchor_{issuer.ticker}",
                )
                bt = run_backtest(hs_fc, anchor_year=anchor_pick, fx_mult=fx_fc, smoothing=smoothing)
                if bt:
                    bm1, bm2, bm3, bm4 = st.columns(4)
                    with bm1:
                        st.metric("Revenue MAPE",
                                  f"{bt.mape_revenue*100:.1f}%",
                                  "✅ excelente" if bt.mape_revenue < 0.05 else "🟡 aceptable" if bt.mape_revenue < 0.15 else "🔴 alto")
                    with bm2:
                        st.metric("EBIT MAPE",
                                  f"{bt.mape_ebit*100:.1f}%",
                                  "✅" if bt.mape_ebit < 0.10 else "🟡" if bt.mape_ebit < 0.30 else "🔴")
                    with bm3:
                        st.metric("Net Income MAPE",
                                  f"{bt.mape_ni*100:.1f}%",
                                  "✅" if bt.mape_ni < 0.15 else "🟡" if bt.mape_ni < 0.40 else "🔴")
                    with bm4:
                        st.metric("Direction Accuracy",
                                  f"{bt.direction_accuracy_revenue*100:.0f}%",
                                  "✅ predice tendencia" if bt.direction_accuracy_revenue >= 0.7 else "🔴 random")

                    st.markdown("**Tabla detallada del back-test:**")
                    st.dataframe(bt.to_table(), hide_index=True, use_container_width=True)
                    st.caption(
                        f"📌 **Interpretación:** Si Revenue MAPE < 5% y Direction Accuracy = 100%, "
                        f"la metodología capta bien la tendencia para esta empresa. "
                        f"EBIT y NI tienen MAPE más alto porque dependen de items volátiles "
                        f"(FX, ventas extraordinarias, taxes). Es **normal y honesto**."
                    )
                else:
                    st.info("No hay suficientes años posteriores al ancla para back-testar.")
            else:
                st.info("Necesitas al menos 3 años de histórico para back-test (1 ancla + 1+ futuros).")

    except Exception as e_fc:
        st.error(f"Error en Forecast: {e_fc}")
        import traceback
        st.code(traceback.format_exc())

    tab_forecast.__exit__(None, None, None)
    tab_intel.__enter__()

    # ============================================================
    # 🎙️ INVESTOR INTEL — Timeline narrativo de management
    # ============================================================
    st.subheader(f"🎙️ Investor Intelligence — {issuer.ticker}")
    st.caption(
        "Timeline de lo que la administración ha dicho trimestre a trimestre: "
        "guías, drivers, eventos estratégicos, sentimiento. Captura inteligencia "
        "narrativa para complementar el análisis cuantitativo."
    )

    try:
        from src.dcf_mexico.investor_intel import (
            InvestorReport, get_cuervo_demo_reports,
            save_report, save_and_commit_to_github,
            load_all_reports_for_ticker, delete_report,
            extract_with_claude_api, extract_from_manual_json,
            sentiment_evolution, sentiment_to_table,
            detect_material_changes,
            extract_dcf_suggestions,
            generate_alerts,
            list_report_types, ReportType,
        )

        # Load existing reports
        existing_reports = load_all_reports_for_ticker(issuer.ticker)

        # ============================================================
        # SECCION 1: UPLOAD / EXTRACT NEW REPORT
        # ============================================================
        st.markdown("### ➕ Cargar nuevo reporte")
        intel_mode = st.radio(
            "Método de extracción:",
            options=[
                "🆓 Wizard Claude.ai (gratis, 3 pasos)",
                "💻 Slash command Claude Code",
                "🤖 Upload PDF + Claude API ($)",
                "📋 Paste JSON crudo",
                "📊 Cargar demo CUERVO",
            ],
            horizontal=False,
            key=f"intel_mode_{issuer.ticker}",
        )

        if intel_mode == "🆓 Wizard Claude.ai (gratis, 3 pasos)":
            st.success(
                "💡 **No necesitas API key.** Claude.ai web (Claude Pro $20/mes "
                "o trial gratis) te permite procesar PDFs ilimitados."
            )

            wizard_step = st.radio(
                "Step:",
                options=["1️⃣ Copiar prompt", "2️⃣ Procesar en Claude.ai", "3️⃣ Pegar JSON aquí"],
                horizontal=True,
                key=f"wizard_step_{issuer.ticker}",
            )

            if wizard_step == "1️⃣ Copiar prompt":
                st.markdown("**Paso 1:** Copia este prompt completo (será tu instrucción a Claude)")
                from src.dcf_mexico.investor_intel import EXTRACTION_PROMPT
                # Pre-fill con ticker conocido
                prompt_filled = EXTRACTION_PROMPT.format(
                    ticker=issuer.ticker, filename="(reemplazar con nombre del PDF)"
                )
                st.code(prompt_filled, language="text")
                st.caption(
                    "💡 En Streamlit puedes seleccionar el código y Ctrl+C. "
                    "El icono 📋 arriba a la derecha también lo copia entero."
                )

            elif wizard_step == "2️⃣ Procesar en Claude.ai":
                st.markdown("**Paso 2:** En Claude.ai web:")
                col_w1, col_w2 = st.columns([1, 2])
                with col_w1:
                    st.markdown("[🌐 Abrir Claude.ai](https://claude.ai/)")
                with col_w2:
                    st.markdown(
                        "1. New chat → modelo Claude Sonnet 4.5\n"
                        "2. Sube tu PDF (📎 paperclip icon)\n"
                        "3. Pega el prompt del paso 1\n"
                        "4. Espera ~10-30 segundos\n"
                        "5. Copia el JSON de la respuesta"
                    )
                st.info(
                    "📌 **Tip:** Claude responderá con JSON puro. "
                    "Si lo envuelve en ```json ... ``` (markdown), "
                    "no te preocupes, el sistema lo limpia automáticamente."
                )

            else:  # paso 3
                st.markdown("**Paso 3:** Pega el JSON aquí")
                json_text = st.text_area(
                    "JSON desde Claude.ai",
                    height=400,
                    placeholder='{\n  "ticker": "CUERVO",\n  "report_date": "2026-02-27",\n  ...\n}',
                    key=f"wizard_json_{issuer.ticker}",
                )

                colf1, colf2 = st.columns(2)
                with colf1:
                    fname = st.text_input(
                        "Nombre del PDF original",
                        value="report.pdf",
                        key=f"wizard_fname_{issuer.ticker}",
                    )
                with colf2:
                    do_commit = st.checkbox(
                        "💾 Auto-commit a GitHub",
                        value=True,
                        key=f"wizard_commit_{issuer.ticker}",
                    )

                # Optional: subir el PDF original también (para viewer inline)
                wizard_pdf = st.file_uploader(
                    "📄 (Opcional) Sube el PDF original también — para verlo inline después",
                    type=["pdf"],
                    key=f"wizard_pdf_{issuer.ticker}",
                    help="Si subes el PDF aquí, se guardará junto con el JSON y "
                         "podrás verlo inline en el timeline.",
                )

                # Live JSON validator
                if json_text:
                    # Strip markdown fences si existen
                    clean = json_text.strip()
                    if clean.startswith("```"):
                        lines = clean.split("\n")
                        if lines[-1].strip().startswith("```"):
                            clean = "\n".join(lines[1:-1])
                        else:
                            clean = "\n".join(lines[1:])
                    try:
                        import json as _json
                        parsed = _json.loads(clean.strip())
                        st.success(f"✅ JSON válido | Campos detectados: "
                                    f"guidance={len(parsed.get('guidance', []))}, "
                                    f"drivers={len(parsed.get('drivers', []))}, "
                                    f"events={len(parsed.get('events', []))}")
                    except Exception as e:
                        st.error(f"❌ JSON inválido: {e}")

                if json_text and st.button("📥 Guardar reporte",
                                            key=f"wizard_save_{issuer.ticker}",
                                            type="primary"):
                    # Strip markdown si existe
                    clean = json_text.strip()
                    if clean.startswith("```"):
                        lines = clean.split("\n")
                        if lines[-1].strip().startswith("```"):
                            clean = "\n".join(lines[1:-1])
                        else:
                            clean = "\n".join(lines[1:])
                    # Si el usuario subió el PDF, usar su nombre real
                    if wizard_pdf:
                        fname = wizard_pdf.name
                    report, err = extract_from_manual_json(
                        clean.strip(), ticker=issuer.ticker, filename=fname,
                    )
                    if err:
                        st.error(f"❌ {err}")
                    elif report:
                        # Guardar PDF original si se subio
                        if wizard_pdf:
                            from src.dcf_mexico.investor_intel import save_pdf_alongside_report
                            pdf_path = save_pdf_alongside_report(
                                wizard_pdf.getvalue(),
                                ticker=issuer.ticker,
                                pdf_filename=wizard_pdf.name,
                            )
                            # Set relative path en el report
                            report.pdf_local_path = (
                                f"data/investor_reports/{issuer.ticker.upper()}/"
                                f"pdfs/{wizard_pdf.name}"
                            )
                            st.success(f"📄 PDF guardado: {pdf_path.name}")

                        if do_commit:
                            fpath, gh_result = save_and_commit_to_github(report)
                            st.success(f"✅ JSON guardado: {fpath.name}")
                            if gh_result and gh_result.ok:
                                st.success(f"📤 GitHub: {gh_result.commit_url}")
                            elif gh_result:
                                st.warning(f"⚠️ Commit GitHub falló: {gh_result.message}")
                        else:
                            fpath = save_report(report)
                            st.success(f"✅ JSON guardado local: {fpath.name}")
                        st.rerun()

        elif intel_mode == "💻 Slash command Claude Code":
            st.success(
                "💡 **Si usas Claude Code**, hay un slash command listo. "
                "No necesitas API key, no copy-paste, todo automático."
            )
            st.markdown("**Cómo usar:**")
            st.code(
                f"/extract-investor-report {issuer.ticker} ruta/al/archivo.pdf",
                language="text",
            )
            st.markdown(
                "Esto le dice a Claude Code que:\n"
                "1. Lee el PDF\n"
                "2. Extrae con el prompt estructurado\n"
                "3. Genera el JSON\n"
                f"4. Lo guarda en `data/investor_reports/{issuer.ticker}/`\n"
                "5. (Opcional) Hace commit + push al repo automático\n\n"
                "Ver `.claude/commands/extract-investor-report.md` para el prompt completo."
            )

        elif intel_mode == "🤖 Upload PDF + Claude API ($)":
            uploaded_pdf = st.file_uploader(
                "Sube el PDF de IR",
                type=["pdf"],
                key=f"intel_pdf_upload_{issuer.ticker}",
            )

            # Check if Anthropic API key configured
            anthropic_ok = False
            try:
                if "anthropic" in st.secrets and "api_key" in st.secrets["anthropic"]:
                    anthropic_ok = True
            except Exception:
                pass
            import os
            if not anthropic_ok and os.environ.get("ANTHROPIC_API_KEY"):
                anthropic_ok = True

            if not anthropic_ok:
                st.warning(
                    "⚠️ Claude API key NO configurada. Configura en "
                    "Streamlit secrets:\n```toml\n[anthropic]\napi_key = \"sk-ant-...\"\n```"
                )

            if uploaded_pdf and anthropic_ok:
                if st.button(f"🤖 Extraer con Claude API", key=f"extract_btn_{issuer.ticker}"):
                    with st.spinner("Procesando con Claude API..."):
                        report, err = extract_with_claude_api(
                            uploaded_pdf.getvalue(),
                            ticker=issuer.ticker,
                            filename=uploaded_pdf.name,
                        )
                        if err:
                            st.error(f"❌ Error: {err}")
                        elif report:
                            # Guardar PDF original tambien
                            from src.dcf_mexico.investor_intel import save_pdf_alongside_report
                            save_pdf_alongside_report(
                                uploaded_pdf.getvalue(),
                                ticker=issuer.ticker,
                                pdf_filename=uploaded_pdf.name,
                            )
                            report.pdf_local_path = (
                                f"data/investor_reports/{issuer.ticker.upper()}/"
                                f"pdfs/{uploaded_pdf.name}"
                            )
                            fpath, gh_result = save_and_commit_to_github(report)
                            st.success(f"✅ Procesado: {fpath.name} + PDF guardado")
                            if gh_result and gh_result.ok:
                                st.success(f"📤 Commit a GitHub: {gh_result.commit_url}")
                            st.rerun()

        elif intel_mode == "📋 Paste JSON crudo":
            with st.expander("ℹ️ Cómo usar el modo manual"):
                st.markdown(
                    "1. Abre [Claude.ai web](https://claude.ai/) (gratuito)\n"
                    "2. Sube el PDF\n"
                    "3. Pega este prompt:\n"
                )
                from src.dcf_mexico.investor_intel import EXTRACTION_PROMPT
                st.code(EXTRACTION_PROMPT[:1500] + "\n[...truncado, copia completo del modulo extractor.py]")
                st.markdown("4. Copia el JSON resultante y pégalo abajo")

            json_text = st.text_area(
                "JSON extraído (con la estructura de InvestorReport)",
                height=300,
                key=f"intel_json_{issuer.ticker}",
            )
            fname = st.text_input(
                "Nombre del PDF original (para registro)",
                value="report.pdf",
                key=f"intel_fname_{issuer.ticker}",
            )
            if json_text and st.button("📥 Guardar JSON", key=f"save_json_{issuer.ticker}"):
                report, err = extract_from_manual_json(
                    json_text, ticker=issuer.ticker, filename=fname,
                )
                if err:
                    st.error(f"❌ {err}")
                elif report:
                    fpath, gh_result = save_and_commit_to_github(report)
                    st.success(f"✅ Guardado: {fpath.name}")
                    if gh_result and gh_result.ok:
                        st.success(f"📤 GitHub: {gh_result.commit_url}")
                    st.rerun()

        else:  # demo
            st.info(
                "💡 Carga 4 reports DEMO de CUERVO basados en los PDFs reales "
                "(Guía 2026, IR Presentation Marzo 2026, 1T26 Earnings, Conf Call). "
                "Los IDs cualitativos están reales, datos numéricos son placeholders "
                "donde el PDF no fue procesado."
            )
            if st.button("📊 Cargar demo CUERVO", key=f"load_demo_{issuer.ticker}"):
                if issuer.ticker.upper() == "CUERVO":
                    demo_reports = get_cuervo_demo_reports()
                    for r in demo_reports:
                        save_report(r)
                    st.success(f"✅ {len(demo_reports)} demo reports cargados")
                    st.rerun()
                else:
                    st.warning("Demo solo disponible para CUERVO actualmente")

        # ============================================================
        # SECCION 2: TIMELINE VISUAL
        # ============================================================
        if existing_reports:
            st.markdown("---")
            st.markdown(f"### 📅 Timeline ({len(existing_reports)} reports)")

            # Altair timeline chart
            sent = sentiment_evolution(existing_reports)
            if sent:
                timeline_data = []
                for s in sent:
                    timeline_data.append({
                        "Fecha": s.report_date,
                        "Tipo": s.report_type,
                        "Tono": s.tone,
                        "Score": s.score,
                        "Periodo": s.period,
                        "Title": s.title,
                    })
                tl_df = pd.DataFrame(timeline_data)
                # Convert to date type
                tl_df["Fecha"] = pd.to_datetime(tl_df["Fecha"])

                # Color por sentiment score
                color_scale = alt.Scale(
                    domain=[-1.0, 0.0, 1.0],
                    range=["#DA3633", "#999999", "#2EA043"],
                )

                timeline = (
                    alt.Chart(tl_df)
                    .mark_circle(size=200)
                    .encode(
                        x=alt.X("Fecha:T", title="Fecha", axis=alt.Axis(labelColor='black')),
                        y=alt.Y("Tipo:N", title="Tipo de Report",
                                axis=alt.Axis(labelColor='black')),
                        color=alt.Color("Score:Q", scale=color_scale,
                                         legend=alt.Legend(title="Sentiment Score",
                                                            orient="bottom")),
                        size=alt.Size("Score:Q", legend=None,
                                       scale=alt.Scale(domain=[-1, 1], range=[100, 400])),
                        tooltip=[
                            alt.Tooltip("Fecha:T"),
                            alt.Tooltip("Periodo:N"),
                            alt.Tooltip("Tipo:N"),
                            alt.Tooltip("Tono:N"),
                            alt.Tooltip("Score:Q", format=".2f"),
                            alt.Tooltip("Title:N"),
                        ],
                    )
                    .properties(height=250)
                )
                st.altair_chart(timeline, use_container_width=True)

            # ============================================================
            # SECCION 3: REPORT CARDS (uno por uno con details)
            # ============================================================
            st.markdown("---")
            st.markdown("### 📋 Reports detallados")

            for r in existing_reports:
                tone_emoji = (r.sentiment.tone[0] if r.sentiment else "⚪")
                with st.expander(
                    f"{tone_emoji} **{r.report_date}** | {r.report_type} | "
                    f"{r.title[:60]} ({r.period_covered})",
                    expanded=False,
                ):
                    col1, col2 = st.columns([2, 1])

                    with col1:
                        # PDF original (download + viewer embebido)
                        from src.dcf_mexico.investor_intel import load_pdf_for_report
                        pdf_bytes = load_pdf_for_report(r)

                        if pdf_bytes:
                            pdf_c1, pdf_c2 = st.columns([1, 2])
                            with pdf_c1:
                                st.download_button(
                                    label="📄 Descargar PDF",
                                    data=pdf_bytes,
                                    file_name=r.pdf_filename or "report.pdf",
                                    mime="application/pdf",
                                    key=f"dl_pdf_{r.report_id}",
                                    use_container_width=True,
                                )
                            with pdf_c2:
                                show_viewer = st.toggle(
                                    "👁️ Ver PDF inline",
                                    value=False,
                                    key=f"toggle_pdf_{r.report_id}",
                                )
                            if show_viewer:
                                # Embed PDF as base64 iframe
                                import base64 as _b64
                                pdf_b64 = _b64.b64encode(pdf_bytes).decode("utf-8")
                                pdf_display = (
                                    f'<iframe src="data:application/pdf;base64,{pdf_b64}" '
                                    f'width="100%" height="800px" type="application/pdf" '
                                    f'style="border: 1px solid #ddd; border-radius: 4px;">'
                                    f'</iframe>'
                                )
                                st.markdown(pdf_display, unsafe_allow_html=True)
                                st.caption(
                                    f"PDF: `{r.pdf_filename}` "
                                    f"({len(pdf_bytes)/1024:.0f} KB)"
                                )
                        else:
                            st.caption(
                                f"📄 PDF: `{r.pdf_filename}` (no guardado en repo — "
                                "solo JSON disponible)"
                            )

                        if r.summary_es:
                            st.info(f"📝 **Resumen:** {r.summary_es}")

                        if r.guidance:
                            st.markdown("##### 🎯 Guidance")
                            g_rows = []
                            for g in r.guidance:
                                g_rows.append({
                                    "Métrica": g.metric,
                                    "Periodo": g.period,
                                    "Range": g.range_str(),
                                    "Direction": g.direction,
                                    "Confianza": g.confidence,
                                    "Texto": g.qualitative_text[:80],
                                })
                            st.dataframe(pd.DataFrame(g_rows), hide_index=True,
                                          use_container_width=True)

                        if r.drivers:
                            st.markdown("##### 🚀 Drivers")
                            d_rows = []
                            for d in r.drivers:
                                d_rows.append({
                                    "Categoría": d.category,
                                    "Descripción": d.description,
                                    "Impact": d.impact,
                                    "Materialidad": d.materiality,
                                })
                            st.dataframe(pd.DataFrame(d_rows), hide_index=True,
                                          use_container_width=True)

                        if r.events:
                            st.markdown("##### 📢 Eventos Materiales")
                            for e in r.events:
                                st.warning(
                                    f"**{e.event_type}** | {e.title}\n\n"
                                    f"{e.description}\n\n"
                                    f"*Impact:* {e.financial_impact} • Materialidad: {e.materiality}"
                                )

                    with col2:
                        if r.sentiment:
                            st.metric("Sentiment Tone", r.sentiment.tone,
                                       f"Score: {r.sentiment.score:+.2f}")
                            st.caption(f"💡 {r.sentiment.rationale}")

                        if r.key_topics:
                            st.markdown("**🔑 Key Topics:**")
                            for t in r.key_topics:
                                st.caption(f"• {t}")

                        st.caption(f"Extraído: {r.extraction_method} • {r.extraction_date[:10]}")

                        # Delete button
                        if st.button(f"🗑️ Eliminar", key=f"del_{r.report_id}"):
                            delete_report(r.report_id, r.ticker)
                            st.success(f"Eliminado: {r.report_id}")
                            st.rerun()

            # ============================================================
            # SECCION 4: ALERTS (cambios entre reports)
            # ============================================================
            if len(existing_reports) >= 2:
                st.markdown("---")
                st.markdown("### 🚨 Cambios materiales entre reports recientes")
                # Compara los 2 más recientes
                curr = existing_reports[0]
                prior = existing_reports[1]
                alerts_list = generate_alerts(curr, prior)
                if alerts_list:
                    st.caption(f"Comparando `{curr.report_date}` vs `{prior.report_date}`")
                    for alert in alerts_list:
                        sev_func = {"high": st.error, "medium": st.warning,
                                     "low": st.info}.get(alert.severity, st.info)
                        sev_func(
                            f"**{alert.title}** ({alert.category})\n\n"
                            f"{alert.description}\n\n"
                            f"💡 **Acción:** {alert.action_recommended}"
                        )
                else:
                    st.success("✅ Sin cambios materiales detectados.")

            # ============================================================
            # SECCION 5: DCF DRIVER SUGGESTIONS
            # ============================================================
            st.markdown("---")
            st.markdown("### 🔄 Sugerencias para DCF (auto-fill desde guidance)")
            try:
                # Use revenue del DCF actual como base para CapEx %
                rev_for_capex = base.revenue if base else None
                dcf_sugs = extract_dcf_suggestions(
                    existing_reports,
                    revenue_for_capex_pct=rev_for_capex,
                )
                if dcf_sugs:
                    st.caption(
                        "Estos drivers vienen DIRECTO de la guidance más reciente "
                        "de management. Puedes copiarlos al tab Valuation Output."
                    )
                    for sug in dcf_sugs:
                        st.info(
                            f"**{sug.driver_name}** = `{sug.suggested_value:.4f}` "
                            f"({sug.confidence} confidence)\n\n"
                            f"📌 *{sug.note}*\n\n"
                            f"📅 Source: {sug.source_metric} ({sug.source_period}) "
                            f"emitida {sug.source_date}"
                        )
                else:
                    st.info("No hay guidance numérica reciente para sugerir drivers.")
            except Exception as e_dcf:
                st.caption(f"DCF integration: {e_dcf}")

        else:
            st.info(
                "📭 Sin reports cargados todavía. Usa el panel arriba para "
                "subir PDFs (con Claude API) o cargar demo CUERVO."
            )

    except Exception as e_intel:
        st.error(f"Error en Investor Intel: {e_intel}")
        import traceback
        st.code(traceback.format_exc())

    tab_intel.__exit__(None, None, None)
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
                    axis=alt.Axis(
                        labelAngle=-90,          # etiquetas verticales
                        labelColor='black',       # texto negro
                        labelFontSize=12,
                        labelLimit=200,
                    )),
            y=alt.Y("start:Q", title="MDP",
                    axis=alt.Axis(labelColor='black', titleColor='black',
                                   labelFontSize=11, titleFontSize=12)),
            y2="end:Q",
            color=alt.Color("kind:N", scale=color_scale, legend=None),
            tooltip=[
                alt.Tooltip("step:N"),
                alt.Tooltip("delta:Q", title="Δ MDP", format=",.0f"),
                alt.Tooltip("end:Q",   title="Cumulative MDP", format=",.0f"),
            ],
        )
        .properties(height=450)
    )
    label_chart = (
        alt.Chart(wf_df)
        .mark_text(dy=-8, fontSize=11, color='black', fontWeight=600)
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

    # ----- TAB 4 close, SUPPORTING WORKSHEETS open -----
    tab_sens.__exit__(None, None, None)

    # ============================================================
    # SUB-TAB 8: 🔧 SUPPORTING WORKSHEETS (R&D, Op Lease, NOL, Failure)
    # Réplica de las hojas auxiliares del fcffsimpleginzu.xlsx
    # ============================================================
    tab_worksheets.__enter__()
    st.subheader(f"🔧 Supporting Worksheets — {issuer.ticker}")
    st.caption(
        "Hojas auxiliares del modelo Damodaran. Cada worksheet hace una "
        "transformación específica antes de alimentar al Input Sheet."
    )

    # ---- A. R&D Capitalization Worksheet ----
    with st.expander(
        "**🧪 A · R&D Capitalization Worksheet**",
        expanded=False,
    ):
        st.markdown(
            """
            **Lógica Damodaran:** convertir R&D de gasto operativo a activo
            capitalizado. Esto sube el EBIT (porque ya no se gasta R&D
            corriente) y crea un **Research Asset** en el balance.

            **Pasos:**
            1. Ingresa R&D de los últimos 3-5 años
            2. Define vida útil (3-10 años para tech, default 5)
            3. Cómputo: Research Asset = Σ R&D no amortizado
            4. Adjusted EBIT = EBIT + R&D corriente − Amortización R&D
            5. Adjusted Equity = Equity + Research Asset
            6. Adjusted CapEx = CapEx + R&D corriente

            **CUERVO / Beverages → R&D ≈ 0 → este worksheet no aplica.**
            Para emisoras tech (ej. SOFTTEK si entrara al IPC), sí aplica.
            """
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            rd_active = st.checkbox("Activar R&D capitalization",
                                     value=False,
                                     key=f"dam_in_rd_active_{issuer.ticker}")
        with c2:
            rd_life = st.number_input("Vida útil R&D (años)",
                                       value=5, min_value=2, max_value=15,
                                       step=1,
                                       disabled=not rd_active,
                                       key=f"dam_in_rd_life_{issuer.ticker}")
        with c3:
            rd_current = st.number_input("R&D corriente (MDP)",
                                          value=0.0, step=10.0, format="%.1f",
                                          disabled=not rd_active,
                                          key=f"dam_in_rd_curr_{issuer.ticker}")
        if rd_active and rd_current > 0:
            import pandas as _pd
            rd_table = _pd.DataFrame({
                "Year": [f"-{i}" for i in range(int(rd_life), 0, -1)] + ["Current"],
                "R&D ($)": [rd_current * (0.9 ** i) for i in range(int(rd_life), 0, -1)] + [rd_current],
                "Amort. lineal": [rd_current * (0.9 ** i) / rd_life for i in range(int(rd_life), 0, -1)] + [rd_current / rd_life],
                "Unamortized portion": [rd_current * (0.9 ** i) * (i / rd_life) for i in range(int(rd_life), 0, -1)] + [rd_current],
            })
            st.dataframe(rd_table.style.format({
                "R&D ($)": "{:,.1f}",
                "Amort. lineal": "{:,.1f}",
                "Unamortized portion": "{:,.1f}",
            }), hide_index=True, use_container_width=True)
            res_asset = rd_table["Unamortized portion"].sum()
            st.success(
                f"📦 **Research Asset implícito:** {res_asset:,.1f} MDP "
                f"(suma de la columna *Unamortized portion*)"
            )
        elif rd_active:
            st.info("Ingresa R&D corriente > 0 para ver la tabla.")

    # ---- B. Operating Lease Converter ----
    with st.expander(
        "**🏢 B · Operating Lease Converter**",
        expanded=False,
    ):
        try:
            ol_st = res.dcf.lease_debt or 0.0
        except Exception:
            ol_st = 0.0
        ol_total = base.financial_debt - (base.financial_debt - ol_st) if ol_st else 0.0
        st.markdown(
            f"""
            **Lógica Damodaran:** convertir compromisos de leasing operativo
            (off-balance) en deuda + activo de derecho de uso. Capitaliza al
            **pre-tax cost of debt** ({out.wacc_result.pretax_cost_debt:.4%}).

            **México post-IFRS 16 (2019+):**
            Los leases ya están en el balance como `right_of_use_assets`
            (activo) y `short_term_lease + long_term_lease` (deuda). El
            modelo ya los incluye automáticamente en `total_debt_with_leases`.

            | Concepto | Valor (MDP) |
            |---|---:|
            | Lease debt (ya capitalizado IFRS 16) | **{ol_st:,.1f}** |
            | Financial debt (préstamos puros) | {base.financial_debt - ol_st:,.1f} |
            | **Total debt with leases (usado en DCF)** | **{base.financial_debt:,.1f}** |
            | Pre-tax Kd usado para capitalizar | {out.wacc_result.pretax_cost_debt:.4%} |

            ✅ **No requiere conversión adicional** — IFRS 16 ya hace el trabajo.
            Si reportas en US-GAAP (ej. KOF.A en SEC), entonces sí requeriría
            convertir las commitments del 10-K.
            """
        )

    # ---- C. NOL Worksheet (Tax shield year-by-year) ----
    with st.expander(
        "**💸 C · NOL Worksheet (Tax shield año a año)**",
        expanded=False,
    ):
        st.markdown(
            """
            **Lógica Damodaran:** los NOL (Net Operating Losses) actúan
            como escudo fiscal en los años futuros. Cada año, parte del
            EBIT se exenta de impuestos hasta agotar el NOL.

            **Tracking del modelo:**
            """
        )
        if out.nol_remaining and out.nol_used and out.tax_shield:
            import pandas as _pd
            nol_df = _pd.DataFrame({
                "Year":              out.years,
                "EBIT (MDP)":        [round(x, 1) for x in out.ebit],
                "NOL used (MDP)":    [round(x, 1) for x in out.nol_used],
                "NOL remaining (MDP)": [round(x, 1) for x in out.nol_remaining],
                "Tax shield (MDP)":  [round(x, 1) for x in out.tax_shield],
            })
            st.dataframe(nol_df.style.format({
                "EBIT (MDP)": "{:,.1f}",
                "NOL used (MDP)": "{:,.1f}",
                "NOL remaining (MDP)": "{:,.1f}",
                "Tax shield (MDP)": "{:,.1f}",
            }), hide_index=True, use_container_width=True,
            height=min(600, 50 + 32 * len(out.years)))

            total_shield = sum(out.tax_shield)
            if total_shield > 0:
                st.success(
                    f"📊 **Tax shield acumulado por NOL:** "
                    f"{total_shield:,.1f} MDP a lo largo del forecast. "
                    f"Esto reduce el tax expense efectivo y eleva el FCFF."
                )
            else:
                st.info(
                    "🟢 NOL = 0 (CUERVO no tiene pérdidas acumuladas). "
                    "Para activar: Input Sheet → sec G → 'Override NOL' = Yes."
                )
        else:
            st.warning("Sin data de NOL en el output del modelo.")

    # ---- D. Failure Rate / Distress Worksheet ----
    with st.expander(
        "**⚠️ D · Failure Rate & Distress Worksheet**",
        expanded=False,
    ):
        st.markdown(
            f"""
            **Lógica Damodaran:** ajusta el equity value por la probabilidad
            de fracaso de la empresa. Si la empresa quiebra, los proceeds
            distress se basan en book value o fair value.

            **Tabla de orientación (Damodaran):**

            | Etapa | Probabilidad de failure típica |
            |---|---|
            | Idea / Pre-revenue | 60-80% |
            | Early stage | 30-50% |
            | Growth (rentable) | 10-20% |
            | Mature / Established | 0-5% |
            | Blue chip / IG rating | 0-1% |

            **Configuración actual del modelo:**

            | Concepto | Valor |
            |---|---:|
            | Probability of failure | **{a.probability_of_failure:.2%}** |
            | Failure proceeds basis | **{a.failure_proceeds_basis}** ({"Fair value" if a.failure_proceeds_basis == "V" else "Book value"}) |
            | Recovery % | **{a.failure_proceeds_pct:.0%}** |
            | Distress proceeds (MDP) | **{out.distress_proceeds:,.1f}** |
            | Operating value DCF (pre-failure) | **{out.operating_value_dcf:,.1f}** |
            | Equity value (post-failure adj) | **{out.equity_value:,.1f}** |

            Para CUERVO (mature, IG rating) → P(failure) ≈ 0% es razonable.
            Para emisoras small-cap o cíclicas distress, considera 5-15%.

            **Para editar:** Input Sheet → sec G → "Override probability of failure?"
            """
        )

    st.info(
        "📚 **Referencia Damodaran:** estos worksheets son las hojas "
        "auxiliares del modelo `fcffsimpleginzu.xlsx`. Su rol es transformar "
        "data raw del 10-K (R&D, lease commitments, NOL, prob failure) "
        "en inputs limpios que alimentan al Input Sheet principal."
    )

    tab_worksheets.__exit__(None, None, None)

    # ----- DuPont open -----
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

    # ----- TAB 5 close, TAB Ratios open -----
    tab_dupont.__exit__(None, None, None)
    tab_ratios.__enter__()

    # ============================================================
    # TAB Ratios & Metrics: ~80 ratios financieros con explicaciones
    # ============================================================
    st.subheader(f"Ratios & Metrics — {issuer.ticker}")
    st.caption(
        "Analisis financiero comprehensivo: 70+ ratios organizados en 10 categorias "
        "(margenes, returns, DuPont, liquidez, apalancamiento, eficiencia, calidad de "
        "flujo, per-share, multiplos, growth). Cada ratio incluye formula, descripcion "
        "y guia de interpretacion."
    )

    try:
        from src.dcf_mexico.analysis import compute_all_ratios, RATIO_CATEGORIES

        # Selector de periodo
        col_p1, col_p2, col_p3 = st.columns([2, 1, 1])
        with col_p1:
            snap_labels = [s.label for s in hs.snapshots]
            sel_idx = st.selectbox(
                "Periodo a analizar:",
                options=range(len(snap_labels)),
                index=len(snap_labels) - 1,
                format_func=lambda i: snap_labels[i],
                key="ratios_period_sel",
            )
        with col_p2:
            mp_input = st.number_input(
                "Market Price (pesos/accion):",
                min_value=0.0, value=0.0, step=0.5,
                help="Si > 0, calcula multiplos de valuacion (P/E, P/B, EV/EBITDA, etc.)",
                key="ratios_market_price",
            )
        with col_p3:
            cat_filter = st.multiselect(
                "Filtrar categorias:",
                options=RATIO_CATEGORIES,
                default=RATIO_CATEGORIES,
                key="ratios_cat_filter",
            )

        sel_snap = hs.snapshots[sel_idx]
        prev_snap = hs.snapshots[sel_idx - 1] if sel_idx >= 1 else None
        # Mismo Q año anterior para Growth YoY
        by_yq = {(s.year, s.quarter): s for s in hs.snapshots}
        prev_year_snap = by_yq.get((sel_snap.year - 1, sel_snap.quarter))

        all_ratios = compute_all_ratios(
            sel_snap,
            prev_snap=prev_snap,
            prev_year_snap=prev_year_snap,
            market_price=mp_input if mp_input > 0 else None,
        )

        # Group by category
        from collections import defaultdict
        by_cat = defaultdict(list)
        for r in all_ratios:
            by_cat[r.category].append(r)

        # Display
        st.markdown(f"**{len(all_ratios)} ratios** computados para "
                    f"`{sel_snap.label}` " +
                    (f"• Market Price: ${mp_input:.2f}/accion" if mp_input > 0 else
                     "• (sin precio: multiplos de valuacion no disponibles)"))
        st.divider()

        # Format unit-aware value display (2 decimales standard)
        def _fmt_val(r):
            if r.value is None:
                return "—"
            v = r.value
            u = r.unit
            if u == "%":
                return f"{v:>9,.2f}%"
            elif u == "x":
                return f"{v:>9,.2f}x"
            elif u == "days":
                return f"{v:>9,.2f} days"
            elif u == "MDP":
                return f"{v:>11,.2f} MDP"
            elif u == "pesos":
                return f"$ {v:>9,.2f}"
            else:
                return f"{v:>9,.2f}"

        for cat in RATIO_CATEGORIES:
            if cat not in cat_filter:
                continue
            items = by_cat.get(cat, [])
            if not items:
                continue

            # Icono por categoria
            icons = {
                "Profitability Margins": "💰",
                "Returns": "📈",
                "DuPont Decomposition": "🔗",
                "Liquidity": "💧",
                "Leverage": "⚖️",
                "Efficiency": "⚡",
                "Cash Flow Quality": "💵",
                "Per-Share": "📊",
                "Valuation Multiples": "🏷️",
                "Growth (YoY)": "🚀",
            }
            icon = icons.get(cat, "📐")

            with st.expander(f"{icon} **{cat}** ({len(items)} ratios)", expanded=True):
                import pandas as _pd
                rows = []
                for r in items:
                    # Format inputs_used dict to readable string
                    if r.inputs_used:
                        inputs_str = " · ".join(
                            [f"{k}: {v}" for k, v in r.inputs_used.items()]
                        )
                    else:
                        inputs_str = "—"
                    rows.append({
                        "Ratio": r.name,
                        "Valor": _fmt_val(r),
                        "Interpretacion": r.interpretation,
                        "Formula": r.formula,
                        "Descripcion": r.description,
                        "Datos usados": inputs_str,
                        "Rating": r.rating or "⚪ N/A",
                    })
                df_cat = _pd.DataFrame(rows)
                st.dataframe(
                    df_cat,
                    hide_index=True,
                    use_container_width=True,
                    height=min(700, 50 + 80 * len(items)),
                    column_config={
                        "Ratio": st.column_config.TextColumn(width=210),
                        "Valor": st.column_config.TextColumn(width=110),
                        "Interpretacion": st.column_config.TextColumn(width=340),
                        "Formula": st.column_config.TextColumn(width=200),
                        "Descripcion": st.column_config.TextColumn(width=320),
                        "Datos usados": st.column_config.TextColumn(width=280),
                        "Rating": st.column_config.TextColumn(width=120),
                    },
                )

    except Exception as e:
        st.error(f"Error calculando ratios: {e}")
        import traceback
        st.code(traceback.format_exc())

    # ----- TAB Ratios close, TAB Diagnostics open -----
    tab_ratios.__exit__(None, None, None)
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

    # ----- GITHUB AUTO-COMMIT (persistencia permanente) -----
    from dcf_mexico.github_storage import (
        GitHubConfig, commit_file_to_github, test_github_connection,
    )
    gh_cfg = GitHubConfig.from_streamlit_secrets()
    gh_available = gh_cfg is not None

    with st.expander(
        "🔐 **GitHub Auto-Commit** "
        + ("✅ CONFIGURADO (persistencia permanente)" if gh_available
           else "❌ NO configurado (solo persistencia en sesión)"),
        expanded=not gh_available,
    ):
        if gh_available:
            st.success(f"📦 Repo: `{gh_cfg.repo}` • Branch: `{gh_cfg.branch}`")
            colt1, colt2 = st.columns([1, 3])
            with colt1:
                if st.button("🧪 Test conexión", key="test_gh"):
                    ok, msg = test_github_connection(gh_cfg)
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)
            with colt2:
                st.caption(
                    "Cuando subas un XBRL, se hará **commit automático** al repo. "
                    "Sobrevivirá restarts de Streamlit Cloud y nuevos deploys."
                )
        else:
            st.warning(
                "⚠️ Auto-commit a GitHub NO configurado. Los XBRLs solo "
                "persistirán durante la sesión del navegador."
            )
            st.markdown("""
**Para activar persistencia permanente:**

1. **Crear GitHub Personal Access Token** (PAT):
   - Ir a https://github.com/settings/tokens
   - "Generate new token" → "Fine-grained tokens"
   - Resource owner: tu usuario
   - Repository access: Solo este repo (`dcf-universal-mx`)
   - Permissions: **Contents → Read and Write**
   - Copiar el token (`ghp_xxx...`)

2. **Configurar en Streamlit:**

   **Streamlit Cloud:** App settings → Secrets → pegar:
   ```toml
   [github]
   token  = "ghp_xxxxxxxxxxxx"
   repo   = "CompositeManTrader/dcf-universal-mx"
   branch = "main"
   ```

   **Local:** crear archivo `.streamlit/secrets.toml` (NO commitearlo):
   ```toml
   [github]
   token  = "ghp_xxxxxxxxxxxx"
   repo   = "CompositeManTrader/dcf-universal-mx"
   branch = "main"
   ```

3. **Recargar la app** — el auto-commit estará disponible.
            """)

    # ----- PERSISTENCIA SESSION_STATE (fallback / capa intermedia) -----
    if "uploaded_xbrls" not in st.session_state:
        st.session_state["uploaded_xbrls"] = {}   # filename -> bytes

    raw = ROOT / "data" / "raw_xbrl"
    raw.mkdir(parents=True, exist_ok=True)

    # Auto-restore: si hay archivos en session_state pero no en disco, escribirlos
    restored = []
    for fname, fbytes in st.session_state["uploaded_xbrls"].items():
        path = raw / fname
        if not path.exists():
            path.write_bytes(fbytes)
            restored.append(fname)
    if restored:
        st.success(
            f"♻️ Restaurados {len(restored)} archivos de session_state al disco "
            f"(persistencia entre reruns):\n" + "\n".join(f"  • {f}" for f in restored)
        )
        _list_local_xbrl_names.clear()

    # Mostrar archivos en session_state actuales
    if st.session_state["uploaded_xbrls"]:
        with st.expander(
            f"📦 {len(st.session_state['uploaded_xbrls'])} archivos persistidos en sesión "
            "(sobreviven reruns hasta cerrar el navegador)",
            expanded=False,
        ):
            persisted_df = pd.DataFrame([
                {"Archivo": fname, "Tamaño (KB)": f"{len(fb)/1024:.1f}"}
                for fname, fb in st.session_state["uploaded_xbrls"].items()
            ])
            st.dataframe(persisted_df, hide_index=True, use_container_width=True)
            colp1, colp2 = st.columns(2)
            with colp1:
                if st.button("🗑️ Limpiar archivos persistidos", key="clear_persisted"):
                    st.session_state["uploaded_xbrls"] = {}
                    st.success("Archivos persistidos borrados de session_state.")
                    st.rerun()
            with colp2:
                st.caption(
                    "💡 Para persistencia PERMANENTE, hacer commit de los archivos "
                    "a `data/raw_xbrl/` en el repo GitHub."
                )

    st.divider()

    uploaded = st.file_uploader(
        "Archivo(s) XBRL", type=["xls", "xlsx"], accept_multiple_files=True,
    )

    if not uploaded:
        if not st.session_state["uploaded_xbrls"]:
            st.info("Sube uno o mas archivos para procesar.")
        else:
            st.info(
                f"No hay archivos nuevos. {len(st.session_state['uploaded_xbrls'])} "
                "ya están persistidos en sesión (panel arriba)."
            )
        st.stop()

    # Toggle GitHub auto-commit (solo si configurado)
    do_github_commit = False
    if gh_available:
        do_github_commit = st.checkbox(
            "💾 **Auto-commit a GitHub** (persistencia PERMANENTE)",
            value=True,
            help="Hace commit + push automático del archivo al repo. "
                 "Sobrevive restarts de Streamlit Cloud y nuevos deploys.",
        )

    summaries = []
    github_results = []

    progress = st.progress(0, text="Procesando archivos...")

    for idx, u in enumerate(uploaded):
        # 1) Guardar bytes en session_state (persistencia entre reruns)
        st.session_state["uploaded_xbrls"][u.name] = u.getvalue()
        # 2) Escribir a disco para parser
        path = raw / u.name
        path.write_bytes(u.getvalue())
        # 3) Parsear
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

        # 4) GitHub auto-commit (si aplica)
        if do_github_commit and gh_cfg:
            progress.progress(
                (idx + 0.5) / len(uploaded),
                text=f"📤 Commiteando {u.name} a GitHub..."
            )
            commit_res = commit_file_to_github(u.name, u.getvalue(), gh_cfg)
            github_results.append({
                "Archivo": u.name,
                "Status": "✅ OK" if commit_res.ok else "❌ Error",
                "Mensaje": commit_res.message,
                "Commit URL": commit_res.commit_url or "-",
                "Error": commit_res.error_detail or "-",
            })

        progress.progress(
            (idx + 1) / len(uploaded),
            text=f"Procesados {idx+1}/{len(uploaded)}"
        )

    progress.empty()
    _list_local_xbrl_names.clear()
    _parse_cached.clear()

    st.success(
        f"✅ Procesados {len(summaries)} archivos. "
        f"Persistidos en session_state ({len(st.session_state['uploaded_xbrls'])} totales)."
    )
    st.dataframe(pd.DataFrame(summaries), hide_index=True, use_container_width=True)

    # Mostrar resultados GitHub si aplica
    if github_results:
        st.markdown("### 📦 GitHub Auto-Commit Results")
        gh_ok_count = sum(1 for r in github_results if "OK" in r["Status"])
        gh_err_count = len(github_results) - gh_ok_count
        if gh_err_count == 0:
            st.success(
                f"🎉 **{gh_ok_count}/{len(github_results)} archivos commiteados al repo.** "
                f"Persistencia permanente activa."
            )
        else:
            st.warning(
                f"⚠️ {gh_ok_count}/{len(github_results)} OK, "
                f"{gh_err_count} errores. Ver detalle abajo."
            )
        st.dataframe(
            pd.DataFrame(github_results),
            hide_index=True, use_container_width=True,
            column_config={
                "Commit URL": st.column_config.LinkColumn("Commit", display_text="🔗 Ver"),
            },
        )

    if not gh_available:
        st.info(
            "ℹ️ **Persistencia:** Los archivos sobrevivirán reruns de Streamlit "
            "**durante esta sesión del navegador**. Si cierras la pestaña, se pierden.\n\n"
            "**Para persistencia permanente:** Configura GitHub auto-commit (panel arriba)."
        )


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
