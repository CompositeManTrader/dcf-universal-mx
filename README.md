# DCF Universal MX

Valuacion DCF de las **35 emisoras del IPC mexicano** a partir del XBRL oficial de la CNBV/BMV.

Pipeline end-to-end:

```
XBRL CNBV (.xls)  ->  Parser  ->  EEFF estructurados  ->  DCF FCFF Damodaran (adaptado MX)  ->  Streamlit UI
```

## Quickstart local

```bash
# 1) Crear ambiente
conda create -n dcfmx python=3.11 -y
conda activate dcfmx
pip install -r requirements.txt

# 2) Colocar XBRLs en data/raw_xbrl/  (descargados manualmente de la BMV)
#    Naming convention: ifrsxbrl_<TICKER>_<YYYY-Q>.xls

# 3) Correr tests
pytest tests -v

# 4) Valuar una emisora (CLI)
python scripts/run_parse_one.py
python scripts/value_cuervo_calibrated.py

# 5) Batch sobre todas las disponibles
python scripts/value_all.py

# 6) UI Streamlit
streamlit run app.py
```

## Streamlit Cloud

1. Push este repo a GitHub.
2. En [share.streamlit.io](https://share.streamlit.io) -> New app -> selecciona el repo, branch y `app.py`.
3. Asegurate que `requirements.txt` esta en raiz (Streamlit Cloud lo detecta automaticamente).
4. Los XBRLs deben estar commiteados en `data/raw_xbrl/` o subirse via UI (modo *Upload XBRL*).

## Estructura

```
.
├── app.py                              # Streamlit entry point
├── requirements.txt
├── config/
│   ├── sectors.yaml                    # 17 sectores con beta/S2C/margen
│   └── issuers.yaml                    # 35 tickers IPC + sector + precio
├── src/dcf_mexico/
│   ├── config.py                       # YAML loader
│   ├── parse/
│   │   ├── xbrl_reader.py              # Parser CNBV (match exacto, leases, etc.)
│   │   ├── schema.py                   # BalanceSheet, IncomeStatement, CashFlow, DCFInputs
│   │   └── validators.py               # A=L+E checks
│   ├── valuation/
│   │   ├── wacc.py                     # CAPM bottom-up + CRP MX + synthetic rating
│   │   ├── dcf_fcff.py                 # FCFF 10y + terminal Gordon
│   │   ├── sensitivity.py              # Tornado + matrix
│   │   └── runner.py                   # value_one(ticker)
│   └── ui/                             # (libre para extender)
├── scripts/
│   ├── run_parse_one.py
│   ├── value_cuervo.py
│   ├── value_cuervo_calibrated.py      # Replica al WIP del analista
│   ├── value_all.py                    # Batch sobre los 35
│   └── compare_parser_vs_wip.py
├── data/
│   ├── raw_xbrl/                       # Inputs XBRL CNBV
│   ├── parsed/                         # EEFF parseados (Excel/parquet)
│   └── valuations/                     # Outputs DCF
└── tests/
    ├── fixtures/ifrsxbrl_CUERVO_2025-4.xls
    └── test_parser.py
```

## Metodologia DCF

- **Modelo**: FCFF estilo Damodaran "Ginzu simplificado" (10 anios + terminal Gordon).
- **WACC**: CAPM bottom-up con beta de industria re-apalancada (D/E company-specific).
- **Cost of debt**: Synthetic rating Damodaran sobre interest coverage + Mexico CRP.
- **Reinversion**: `(Revenue_t - Revenue_{t-1}) / Sales_to_Capital`.
- **Convergencia**: Margin, tax rate y WACC convergen linealmente al estado estable Y10.
- **Calibrado** contra modelo de equity research (CUERVO) -> 21.74 vs target 21 MXN (3.5% diff).

## Naming convention de XBRL

```
data/raw_xbrl/ifrsxbrl_<TICKER>_<YYYY>-<Q>.xls
```

Ejemplo: `ifrsxbrl_CUERVO_2025-4.xls` (Q4 2025 de CUERVO).

## Excluidas del DCF FCFF (8 emisoras)

Bancos, aseguradoras y financieras requieren Dividend Discount Model (DDM) o Excess Returns Model:

- BBAJIO, BOLSA, ELEKTRA, GENTERA, GFINBUR, GFNORTE, Q, RA

## Tests

7 tests con CUERVO Q4 2025 como fixture:

```bash
pytest tests -v
```

## Roadmap

- [ ] Descargador automatico de XBRL desde la BMV
- [ ] Historico 5y por emisora (no solo ultimo trimestre)
- [ ] DDM/Excess Returns para financieras
- [ ] Comps EV/EBITDA, P/E como sanity check
- [ ] Monte Carlo sobre los drivers
