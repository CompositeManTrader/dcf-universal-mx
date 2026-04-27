"""Side-by-side: parser XBRL vs modelo WIP del analista (FY2025).

Produce data/parsed/CUERVO_compare.xlsx con tabla de validacion."""
import sys, warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")

import pandas as pd
from dcf_mexico.parse import parse_xbrl

XBRL = ROOT / "data" / "raw_xbrl" / "ifrsxbrl_CUERVO_2025-4.xls"
WIP = ROOT / "data" / "raw_xbrl" / "CUERVO_WIP.xlsx"

# Parser
res = parse_xbrl(XBRL)
M = 1_000_000

# WIP - extraer FY2025 = suma 1Q25..4Q25 (cols 51..54) o 4Q25 EoP (col 54)
wip = pd.read_excel(WIP, sheet_name="Cuervo DCF", header=None, engine="openpyxl")

def wip_sum_2025(row_idx):
    """Suma 1Q25+2Q25+3Q25+4Q25 (cols 51-54)."""
    return sum(float(wip.iloc[row_idx, c]) for c in range(51, 55) if pd.notna(wip.iloc[row_idx, c]))

def wip_eop_4q25(row_idx):
    """Toma valor 4Q25 (col 54)."""
    v = wip.iloc[row_idx, 54]
    return float(v) if pd.notna(v) else 0.0

# Filas clave del WIP (de la inspeccion)
rows = [
    # (Concepto,           Parser value MDP,                                                 WIP value MDP,                            Tipo)
    ("Revenue (FY)",       res.income.revenue / M,                                            wip_sum_2025(21),                          "flow"),
    ("COGS (FY)",          res.income.cost_of_sales / M,                                       -wip_sum_2025(227),                        "flow"),
    ("EBIT (FY)",          res.income.ebit / M,                                                wip_sum_2025(234),                         "flow"),
    ("Income tax (FY)",    res.income.tax_expense / M,                                         -wip_sum_2025(245),                        "flow"),
    ("Net Income (FY)",    res.income.net_income / M,                                          wip_sum_2025(246),                         "flow"),
    ("D&A (FY)",           res.informative.da_12m / M,                                         wip_sum_2025(251),                         "flow"),
    ("EBITDA (FY)",        (res.income.ebit + res.informative.da_12m) / M,                     wip_sum_2025(252),                         "flow"),
    ("CapEx PPE (FY)",     res.cashflow.capex_ppe / M,                                         wip_sum_2025(254),                         "flow"),
    ("CapEx total (FY)",   res.cashflow.capex_gross / M,                                       wip_sum_2025(254),                         "flow"),  # WIP solo PPE
    ("CFO (FY)",           res.cashflow.cfo / M,                                               wip_eop_4q25(588),                         "flow"),
    ("Pretax Income (FY)", res.income.pretax_income / M,                                       wip_eop_4q25(561),                         "flow"),
    ("Effective tax rate", res.income.effective_tax_rate * 100,                                wip_eop_4q25(342) * 100,                   "ratio"),
    # Balance sheet
    ("Total Assets",       res.balance.total_assets / M,                                       wip_eop_4q25(374),                         "stock"),
    ("Cash + Restricted",  res.balance.cash / M,                                               wip_eop_4q25(349) + wip_eop_4q25(350),     "stock"),
    ("Total Debt",         res.balance.total_financial_debt / M,                               wip_eop_4q25(450),                         "stock"),
    ("Net Debt (debt+lease - cash)", res.balance.net_debt / M,                                 wip_eop_4q25(452),                         "stock"),
    ("Common Equity",      res.balance.equity_controlling / M,                                 wip_eop_4q25(398),                         "stock"),
    ("Total Equity",       res.balance.total_equity / M,                                       wip_eop_4q25(400),                         "stock"),
    ("Shares (mn)",        res.informative.shares_outstanding / M,                             wip_eop_4q25(258),                         "count"),
]

table = []
for name, p, w, kind in rows:
    diff = p - w
    pct = (diff / w * 100) if w not in (0, None) and abs(w) > 0.01 else 0.0
    flag = ""
    if abs(pct) < 0.5:
        flag = "OK"
    elif abs(pct) < 2:
        flag = "ok-rounding"
    elif abs(pct) < 10:
        flag = "DIFF (review)"
    else:
        flag = "MAJOR DIFF"
    table.append({
        "Concepto": name,
        "Tipo": kind,
        "Parser (MDP)": round(p, 2),
        "WIP (MDP)":    round(w, 2),
        "Diff abs":     round(diff, 2),
        "Diff %":       round(pct, 2),
        "Status":       flag,
    })

df = pd.DataFrame(table)
print(df.to_string(index=False))

out = ROOT / "data" / "parsed" / "CUERVO_compare.xlsx"
df.to_excel(out, index=False)
print(f"\nGuardado: {out}")
