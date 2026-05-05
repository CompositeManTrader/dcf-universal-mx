"""
Tabla de BENCHMARKS SECTORIALES estilo Damodaran (Industry Averages).

Fuentes:
- Damodaran 2024 industry data (US + Global Markets)
  http://pages.stern.nyu.edu/~adamodar/New_Home_Page/dataarchived.html
- Spectrum aggregate data 2024
- Industry-specific reports (IWSR, McKinsey, etc.)

Cubre las 20 industrias mas relevantes para emisoras IPC mexicanas.

Ratios incluidos por industria:
- beta_unlevered:   Beta del activo (sin apalancamiento)
- op_margin_avg:    EBIT/Revenue mediana
- op_margin_p25:    Percentil 25 (bear case)
- op_margin_p75:    Percentil 75 (bull case)
- s2c_avg:          Sales-to-Capital
- s2c_p25 / p75:    Rangos
- de_ratio:         Debt/Equity tipico
- effective_tax:    Tasa efectiva sectorial
- revenue_growth:   Growth secular industria
- roic_typical:     ROIC tipico industria
- payout_ratio:     Dividend payout tipico
- description:      Texto descriptivo
"""
from dataclasses import dataclass
from typing import Dict, Optional, List


@dataclass
class SectorBenchmark:
    """Benchmark sectorial Damodaran-style."""
    sector_id: str
    sector_name: str
    sector_name_es: str

    # Beta (CAPM)
    beta_unlevered: float
    beta_unlevered_p25: float
    beta_unlevered_p75: float

    # Profitability
    op_margin_avg: float        # EBIT margin mediana sector
    op_margin_p25: float        # bear case
    op_margin_p75: float        # bull case
    gross_margin_avg: float

    # Capital efficiency
    s2c_avg: float              # Sales-to-Capital mediana
    s2c_p25: float              # bear (capital intensive)
    s2c_p75: float              # bull (capital light)

    # Capital structure
    de_ratio_avg: float         # Debt/Equity tipico
    effective_tax_avg: float

    # Growth
    revenue_growth_secular: float   # CAGR esperado largo plazo industria
    revenue_growth_high_period: float   # CAGR esperado proximos 5 años

    # Returns
    roic_typical: float
    payout_ratio: float

    # Capital intensity
    capex_pct_revenue: float
    da_pct_revenue: float

    description: str


# ============================================================================
# Tabla de benchmarks (20 industrias IPC MX)
# ============================================================================

SECTOR_DATA: Dict[str, SectorBenchmark] = {

    # ========================================================================
    # BEBIDAS / CONSUMO
    # ========================================================================
    "beverage_alcoholic": SectorBenchmark(
        sector_id="beverage_alcoholic",
        sector_name="Beverage (Alcoholic)",
        sector_name_es="Bebidas Alcoholicas",
        # CUERVO esta aqui. Mediana global Damodaran 2024:
        beta_unlevered=0.75, beta_unlevered_p25=0.62, beta_unlevered_p75=0.92,
        op_margin_avg=0.21, op_margin_p25=0.16, op_margin_p75=0.28,
        gross_margin_avg=0.55,
        # Tequila/whisky aged: ciclo capital largo => S2C bajo
        s2c_avg=1.10, s2c_p25=0.80, s2c_p75=1.50,
        de_ratio_avg=0.45, effective_tax_avg=0.255,
        revenue_growth_secular=0.045, revenue_growth_high_period=0.055,
        roic_typical=0.13, payout_ratio=0.55,
        capex_pct_revenue=0.045, da_pct_revenue=0.035,
        description="Diageo, Brown-Forman, Pernod, CUERVO. Tequila premium en boom 2017-2022, "
                    "post-COVID destocking 2023-2025, recovery esperado 2026+.",
    ),

    "beverage_soft": SectorBenchmark(
        sector_id="beverage_soft",
        sector_name="Beverage (Soft)",
        sector_name_es="Bebidas no Alcoholicas",
        # KOF, Coca-Cola FEMSA, Arca Continental
        beta_unlevered=0.55, beta_unlevered_p25=0.45, beta_unlevered_p75=0.70,
        op_margin_avg=0.20, op_margin_p25=0.14, op_margin_p75=0.27,
        gross_margin_avg=0.48,
        s2c_avg=1.80, s2c_p25=1.40, s2c_p75=2.20,
        de_ratio_avg=0.50, effective_tax_avg=0.27,
        revenue_growth_secular=0.04, revenue_growth_high_period=0.05,
        roic_typical=0.16, payout_ratio=0.65,
        capex_pct_revenue=0.06, da_pct_revenue=0.05,
        description="KOF, Arca Continental (Coca-Cola embotelladoras MX). Defensive, low growth, "
                    "estable. Margen presionado por sugar tax y inflacion materias primas.",
    ),

    # ========================================================================
    # RETAIL
    # ========================================================================
    "retail_general": SectorBenchmark(
        sector_id="retail_general",
        sector_name="Retail (General)",
        sector_name_es="Retail General",
        # WALMEX, Liverpool, ELEKTRA, CHEDRAUI
        beta_unlevered=0.85, beta_unlevered_p25=0.70, beta_unlevered_p75=1.05,
        op_margin_avg=0.07, op_margin_p25=0.04, op_margin_p75=0.10,
        gross_margin_avg=0.25,
        s2c_avg=2.50, s2c_p25=1.80, s2c_p75=3.50,
        de_ratio_avg=0.60, effective_tax_avg=0.28,
        revenue_growth_secular=0.05, revenue_growth_high_period=0.07,
        roic_typical=0.12, payout_ratio=0.40,
        capex_pct_revenue=0.025, da_pct_revenue=0.025,
        description="WALMEX, Chedraui, Liverpool. High turnover, low margin. Working Capital negativo "
                    "tipico (proveedores financian). Crece con inflacion + share gains.",
    ),

    # ========================================================================
    # TELECOM
    # ========================================================================
    "telecom_wireless": SectorBenchmark(
        sector_id="telecom_wireless",
        sector_name="Telecom (Wireless)",
        sector_name_es="Telecom Inalambrico",
        # AMX, MEGACABLE
        beta_unlevered=0.65, beta_unlevered_p25=0.55, beta_unlevered_p75=0.80,
        op_margin_avg=0.18, op_margin_p25=0.13, op_margin_p75=0.24,
        gross_margin_avg=0.55,
        s2c_avg=0.75, s2c_p25=0.55, s2c_p75=1.00,
        de_ratio_avg=1.20, effective_tax_avg=0.27,
        revenue_growth_secular=0.025, revenue_growth_high_period=0.03,
        roic_typical=0.10, payout_ratio=0.70,
        capex_pct_revenue=0.18, da_pct_revenue=0.18,
        description="AMX (America Movil). Mature, high CapEx (5G rollout), regulated. "
                    "Margenes presionados por OTT competition.",
    ),

    # ========================================================================
    # CEMENT / CONSTRUCTION
    # ========================================================================
    "cement": SectorBenchmark(
        sector_id="cement",
        sector_name="Cement / Construction",
        sector_name_es="Cemento / Construccion",
        # CEMEX, Cementos Pacasa, GCC
        beta_unlevered=0.95, beta_unlevered_p25=0.80, beta_unlevered_p75=1.15,
        op_margin_avg=0.12, op_margin_p25=0.07, op_margin_p75=0.18,
        gross_margin_avg=0.32,
        s2c_avg=0.85, s2c_p25=0.65, s2c_p75=1.10,
        de_ratio_avg=0.85, effective_tax_avg=0.27,
        revenue_growth_secular=0.03, revenue_growth_high_period=0.05,
        roic_typical=0.09, payout_ratio=0.30,
        capex_pct_revenue=0.10, da_pct_revenue=0.09,
        description="CEMEX, GCC. Cyclical (construccion), capital intensive (plantas), "
                    "carbon transition cost rising. EM exposure.",
    ),

    # ========================================================================
    # BANKS / FINANCIAL SERVICES (special - DCF FCFE no FCFF)
    # ========================================================================
    "banks": SectorBenchmark(
        sector_id="banks",
        sector_name="Banks (Money Center)",
        sector_name_es="Bancos",
        # GFNORTE, BBAJIO, REGIONAL, BSMX
        beta_unlevered=0.80, beta_unlevered_p25=0.65, beta_unlevered_p75=0.95,
        op_margin_avg=0.40, op_margin_p25=0.30, op_margin_p75=0.50,
        gross_margin_avg=0.65,
        s2c_avg=0.10, s2c_p25=0.07, s2c_p75=0.15,    # NA realmente
        de_ratio_avg=8.0, effective_tax_avg=0.28,    # bancos super apalancados
        revenue_growth_secular=0.07, revenue_growth_high_period=0.09,
        roic_typical=0.18, payout_ratio=0.45,        # ROE > 15% tipico
        capex_pct_revenue=0.04, da_pct_revenue=0.03,
        description="GFNORTE, BBAJIO. Para bancos usar FCFE no FCFF. ROE 15-20%, NIM 5-7%, "
                    "TIE-1 ratio 14-18%. Sensible a tasas Banxico.",
    ),

    # ========================================================================
    # MINING
    # ========================================================================
    "mining_precious": SectorBenchmark(
        sector_id="mining_precious",
        sector_name="Mining (Precious Metals)",
        sector_name_es="Mineria Metales Preciosos",
        # PE&OLES, GMEXICO (cobre + plata + oro)
        beta_unlevered=1.20, beta_unlevered_p25=0.95, beta_unlevered_p75=1.55,
        op_margin_avg=0.25, op_margin_p25=0.10, op_margin_p75=0.40,
        gross_margin_avg=0.45,
        s2c_avg=0.65, s2c_p25=0.45, s2c_p75=0.95,
        de_ratio_avg=0.40, effective_tax_avg=0.30,
        revenue_growth_secular=0.025, revenue_growth_high_period=0.04,
        roic_typical=0.12, payout_ratio=0.35,
        capex_pct_revenue=0.12, da_pct_revenue=0.10,
        description="PE&OLES, GMEXICO. Highly cyclical (commodity prices), capital intensive. "
                    "ESG/ambiental risks. Sensible a USD prices.",
    ),

    # ========================================================================
    # FOOD PROCESSING
    # ========================================================================
    "food_processing": SectorBenchmark(
        sector_id="food_processing",
        sector_name="Food Processing",
        sector_name_es="Procesamiento Alimentos",
        # BIMBO, GRUMA, LALA
        beta_unlevered=0.55, beta_unlevered_p25=0.45, beta_unlevered_p75=0.70,
        op_margin_avg=0.10, op_margin_p25=0.06, op_margin_p75=0.14,
        gross_margin_avg=0.32,
        s2c_avg=2.20, s2c_p25=1.70, s2c_p75=2.80,
        de_ratio_avg=0.55, effective_tax_avg=0.28,
        revenue_growth_secular=0.04, revenue_growth_high_period=0.05,
        roic_typical=0.13, payout_ratio=0.45,
        capex_pct_revenue=0.04, da_pct_revenue=0.04,
        description="BIMBO, GRUMA. Defensive, low growth, mature distribution. Margenes "
                    "expuestos a inflacion materias primas (trigo, maiz).",
    ),

    # ========================================================================
    # INDUSTRIALS / MANUFACTURING
    # ========================================================================
    "industrial_manufacturing": SectorBenchmark(
        sector_id="industrial_manufacturing",
        sector_name="Industrial Manufacturing",
        sector_name_es="Manufactura Industrial",
        # ALPEK, NEMAK, KIMBER, SIMEC
        beta_unlevered=1.00, beta_unlevered_p25=0.80, beta_unlevered_p75=1.25,
        op_margin_avg=0.10, op_margin_p25=0.05, op_margin_p75=0.16,
        gross_margin_avg=0.22,
        s2c_avg=1.50, s2c_p25=1.10, s2c_p75=2.00,
        de_ratio_avg=0.60, effective_tax_avg=0.28,
        revenue_growth_secular=0.04, revenue_growth_high_period=0.06,
        roic_typical=0.10, payout_ratio=0.35,
        capex_pct_revenue=0.06, da_pct_revenue=0.05,
        description="ALPEK, NEMAK. Cyclical, exposed to nearshoring tailwind, automotive cycle.",
    ),

    # ========================================================================
    # REAL ESTATE / FIBRAS
    # ========================================================================
    "real_estate_diversified": SectorBenchmark(
        sector_id="real_estate_diversified",
        sector_name="Real Estate (Diversified)",
        sector_name_es="Bienes Raices",
        # FUNO, FIBRA Mty, FIBRA Prologis, FIHO, etc.
        beta_unlevered=0.65, beta_unlevered_p25=0.50, beta_unlevered_p75=0.85,
        op_margin_avg=0.55, op_margin_p25=0.45, op_margin_p75=0.65,
        gross_margin_avg=0.75,
        s2c_avg=0.30, s2c_p25=0.20, s2c_p75=0.45,
        de_ratio_avg=0.95, effective_tax_avg=0.0,       # FIBRAs casi exentas
        revenue_growth_secular=0.06, revenue_growth_high_period=0.08,
        roic_typical=0.07, payout_ratio=0.95,           # FIBRAs payout 95%+
        capex_pct_revenue=0.10, da_pct_revenue=0.20,
        description="FIBRAs (FUNO, FIBRA Prologis, FIBRA Mty). Payout casi 100% de FFO. "
                    "Tax-exempt. Sensibles a tasas. Industrial fibras beneficiados nearshoring.",
    ),

    # ========================================================================
    # CHEMICALS
    # ========================================================================
    "chemicals": SectorBenchmark(
        sector_id="chemicals",
        sector_name="Chemicals (Diversified)",
        sector_name_es="Quimicos",
        # ORBIA (Mexichem)
        beta_unlevered=0.95, beta_unlevered_p25=0.75, beta_unlevered_p75=1.20,
        op_margin_avg=0.13, op_margin_p25=0.08, op_margin_p75=0.20,
        gross_margin_avg=0.28,
        s2c_avg=1.20, s2c_p25=0.90, s2c_p75=1.60,
        de_ratio_avg=0.65, effective_tax_avg=0.27,
        revenue_growth_secular=0.04, revenue_growth_high_period=0.05,
        roic_typical=0.11, payout_ratio=0.40,
        capex_pct_revenue=0.06, da_pct_revenue=0.05,
        description="ORBIA. Cyclical, energy cost exposure, diversified portfolio.",
    ),

    # ========================================================================
    # HEALTHCARE
    # ========================================================================
    "healthcare": SectorBenchmark(
        sector_id="healthcare",
        sector_name="Healthcare",
        sector_name_es="Salud",
        # GENOMMA, SANB
        beta_unlevered=0.70, beta_unlevered_p25=0.55, beta_unlevered_p75=0.90,
        op_margin_avg=0.18, op_margin_p25=0.12, op_margin_p75=0.25,
        gross_margin_avg=0.55,
        s2c_avg=1.50, s2c_p25=1.10, s2c_p75=2.00,
        de_ratio_avg=0.40, effective_tax_avg=0.27,
        revenue_growth_secular=0.06, revenue_growth_high_period=0.08,
        roic_typical=0.15, payout_ratio=0.40,
        capex_pct_revenue=0.04, da_pct_revenue=0.04,
        description="GENOMMA. Defensive, brand-driven, OTC growing.",
    ),

    # ========================================================================
    # AIRPORTS / INFRASTRUCTURE (special)
    # ========================================================================
    "airports": SectorBenchmark(
        sector_id="airports",
        sector_name="Airports / Infrastructure",
        sector_name_es="Aeropuertos / Infraestructura",
        # ASUR, GAP, OMA
        beta_unlevered=0.80, beta_unlevered_p25=0.65, beta_unlevered_p75=1.00,
        op_margin_avg=0.45, op_margin_p25=0.35, op_margin_p75=0.55,
        gross_margin_avg=0.65,
        s2c_avg=0.40, s2c_p25=0.30, s2c_p75=0.55,
        de_ratio_avg=0.65, effective_tax_avg=0.30,
        revenue_growth_secular=0.06, revenue_growth_high_period=0.10,
        roic_typical=0.13, payout_ratio=0.65,
        capex_pct_revenue=0.18, da_pct_revenue=0.10,
        description="ASUR, GAP, OMA. Concession-based (fija duracion). Volume + tariff growth. "
                    "Capital intensive (terminal expansions). Defensive con upside cyclical.",
    ),

    # ========================================================================
    # MEDIA / CONSUMER
    # ========================================================================
    "consumer_durables": SectorBenchmark(
        sector_id="consumer_durables",
        sector_name="Consumer Durables",
        sector_name_es="Bienes Durables",
        # ELEKTRA, KIMBER, GENTERA
        beta_unlevered=0.85, beta_unlevered_p25=0.70, beta_unlevered_p75=1.05,
        op_margin_avg=0.12, op_margin_p25=0.08, op_margin_p75=0.18,
        gross_margin_avg=0.35,
        s2c_avg=2.00, s2c_p25=1.50, s2c_p75=2.60,
        de_ratio_avg=0.55, effective_tax_avg=0.27,
        revenue_growth_secular=0.05, revenue_growth_high_period=0.07,
        roic_typical=0.13, payout_ratio=0.40,
        capex_pct_revenue=0.04, da_pct_revenue=0.04,
        description="ELEKTRA, KIMBER. Sensible a credit cycle MX, consumer spending.",
    ),
}


# ============================================================================
# Mapeo Ticker IPC -> Industria
# ============================================================================

TICKER_TO_SECTOR: Dict[str, str] = {
    # Bebidas
    "CUERVO":   "beverage_alcoholic",
    "KOF":      "beverage_soft",
    "AC":       "beverage_soft",        # Arca Continental
    # Retail
    "WALMEX":   "retail_general",
    "CHEDRAUI": "retail_general",
    "LIVEPOL":  "retail_general",
    "ELEKTRA":  "retail_general",
    # Telecom
    "AMX":      "telecom_wireless",
    "MEGA":     "telecom_wireless",     # Megacable
    # Cement / Construction
    "CEMEX":    "cement",
    "GCC":      "cement",
    # Banks
    "GFNORTE":  "banks",
    "BBAJIO":   "banks",
    "REGIONAL": "banks",
    "BSMX":     "banks",                # Santander Mexico
    # Mining
    "PE&OLES":  "mining_precious",
    "PENOLES":  "mining_precious",
    "GMEXICO":  "mining_precious",
    # Food
    "BIMBO":    "food_processing",
    "GRUMA":    "food_processing",
    "LALA":     "food_processing",
    "HERDEZ":   "food_processing",
    # Industrials
    "ALPEK":    "industrial_manufacturing",
    "NEMAK":    "industrial_manufacturing",
    "KIMBER":   "consumer_durables",
    "SIMEC":    "industrial_manufacturing",
    # Real Estate (FIBRAs)
    "FUNO":     "real_estate_diversified",
    "FIBRAMQ":  "real_estate_diversified",
    "FIBRAPL":  "real_estate_diversified",
    "FIHO":     "real_estate_diversified",
    # Chemicals
    "ORBIA":    "chemicals",
    "MEXCHEM":  "chemicals",
    # Healthcare
    "GENOMMA":  "healthcare",
    # Airports
    "ASUR":     "airports",
    "GAP":      "airports",
    "OMA":      "airports",
    # Conglomerates
    "GFAMSA":   "consumer_durables",
    "FEMSA":    "beverage_soft",        # Holding embotelladoras + OXXO
    "GENTERA":  "banks",
}


def get_sector(ticker: str) -> Optional[SectorBenchmark]:
    """Devuelve el SectorBenchmark para un ticker IPC. None si no esta mapeado."""
    sector_id = TICKER_TO_SECTOR.get(ticker.upper())
    if sector_id is None:
        return None
    return SECTOR_DATA.get(sector_id)


def list_sectors() -> List[SectorBenchmark]:
    """Lista de todas las industrias disponibles."""
    return list(SECTOR_DATA.values())


def get_sector_by_id(sector_id: str) -> Optional[SectorBenchmark]:
    return SECTOR_DATA.get(sector_id)
