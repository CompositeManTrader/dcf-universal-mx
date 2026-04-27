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

    # Matriz heatmap growth × margin
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
