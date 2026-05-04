"""Investor Intel: timeline narrativo de management."""
from .schema import (
    ReportType, GuidanceDirection, GuidanceConfidence,
    SentimentTone, DriverImpact, EventType,
    GuidanceItem, Driver, StrategicEvent, SentimentScore,
    InvestorReport,
    list_report_types, list_guidance_directions, list_sentiment_tones,
    list_event_types, list_driver_impacts,
)
from .storage import (
    save_report, load_report, load_all_reports_for_ticker,
    load_all_reports, delete_report, list_report_files,
    save_and_commit_to_github,
    get_storage_root, get_ticker_dir,
)
from .extractor import (
    extract_with_claude_api, extract_from_manual_json,
    get_cuervo_demo_reports, EXTRACTION_PROMPT,
)
from .analyzer import (
    GuidanceVsActual, CredibilityScore, SentimentTimepoint, MaterialChange,
    compare_guidance_vs_actuals, compare_to_table,
    compute_credibility,
    sentiment_evolution, sentiment_to_table,
    detect_material_changes,
    guidance_evolution, guidance_evolution_table,
)
from .alerts import Alert, generate_alerts, generate_alerts_from_change
from .dcf_integration import (
    DCFDriverSuggestion, TrackRecordAdjustment,
    extract_dcf_suggestions, apply_track_record_haircut,
)
from .scraper import (
    IRSiteConfig, IR_SITES, ScrapedFile,
    list_ir_sites, get_ir_config,
    scrape_ir_site, scrape_all_enabled,
)

__all__ = [
    # Schema
    "ReportType", "GuidanceDirection", "GuidanceConfidence",
    "SentimentTone", "DriverImpact", "EventType",
    "GuidanceItem", "Driver", "StrategicEvent", "SentimentScore",
    "InvestorReport",
    "list_report_types", "list_guidance_directions", "list_sentiment_tones",
    "list_event_types", "list_driver_impacts",
    # Storage
    "save_report", "load_report", "load_all_reports_for_ticker",
    "load_all_reports", "delete_report", "list_report_files",
    "save_and_commit_to_github",
    "get_storage_root", "get_ticker_dir",
    # Extractor
    "extract_with_claude_api", "extract_from_manual_json",
    "get_cuervo_demo_reports", "EXTRACTION_PROMPT",
    # Analyzer
    "GuidanceVsActual", "CredibilityScore", "SentimentTimepoint", "MaterialChange",
    "compare_guidance_vs_actuals", "compare_to_table",
    "compute_credibility",
    "sentiment_evolution", "sentiment_to_table",
    "detect_material_changes",
    "guidance_evolution", "guidance_evolution_table",
    # Alerts
    "Alert", "generate_alerts", "generate_alerts_from_change",
    # DCF Integration
    "DCFDriverSuggestion", "TrackRecordAdjustment",
    "extract_dcf_suggestions", "apply_track_record_haircut",
    # Scraper
    "IRSiteConfig", "IR_SITES", "ScrapedFile",
    "list_ir_sites", "get_ir_config",
    "scrape_ir_site", "scrape_all_enabled",
]
