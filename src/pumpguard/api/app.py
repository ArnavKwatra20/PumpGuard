"""FastAPI app factory."""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pumpguard.api.routes.health import router as health_router
from pumpguard.api.routes.pumps import router as pumps_router
from pumpguard.api.routes.diagnostics import router as diagnostics_router
from pumpguard.api.routes.diagnostic_chat import router as diagnostic_chat_router
from pumpguard.api.routes.relationships import router as relationships_router
from pumpguard.api.routes.analysis import router as analysis_router
from pumpguard.api.routes.ai_features import router as ai_features_router
from pumpguard.api.routes.ml import router as ml_router
from pumpguard.config import get_settings
from pumpguard.services.telemetry_service import TelemetryService
from pumpguard.simulator.live import LiveSimulationService
from pumpguard.services.diagnostics.providers import AmdProvider, DiagnosticProvider
from pumpguard.services.diagnostics.service import DiagnosticService
from pumpguard.services.diagnostics.chat import DiagnosticChatService
from pumpguard.services.ml_inference import MLInferenceService
from pumpguard.relationships.service import RelationshipService
from pumpguard.analysis.telemetry import TelemetryAnalysisService
from pumpguard.api.rate_limit import DemoRateLimitMiddleware
def create_app(service: TelemetryService | None = None, *, diagnostic_provider: DiagnosticProvider | None = None) -> FastAPI:
    """Build app and attach a bounded, process-local telemetry service."""
    settings=get_settings()
    app=FastAPI(title="PumpGuard API",version="0.1.0",description="Synthetic telemetry and explainable rule-based pump monitoring. Not a trained failure predictor.")
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
        allow_credentials=False, allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"])
    app.add_middleware(DemoRateLimitMiddleware, window_seconds=settings.rate_limit_window_seconds,
        simulation=settings.rate_limit_simulation, analysis=settings.rate_limit_analysis,
        ml=settings.rate_limit_ml)
    app.state.telemetry=service or TelemetryService(settings.history_limit)
    app.state.live_simulation=LiveSimulationService()
    app.state.ml_inference=MLInferenceService()
    app.state.relationships=RelationshipService()
    app.state.telemetry_analysis=TelemetryAnalysisService()
    provider=diagnostic_provider or AmdProvider(
        settings.radeon_base_url, settings.radeon_model, settings.radeon_api_key,
        connect_timeout_seconds=settings.diagnostic_connect_timeout_seconds,
        response_timeout_seconds=max(
            0.01,
            settings.diagnostic_timeout_seconds
            - min(5.0, settings.diagnostic_timeout_seconds * 0.2),
        ),
        max_output_tokens=settings.diagnostic_max_output_tokens,
    )
    app.state.diagnostic_service=DiagnosticService(provider,settings.diagnostic_timeout_seconds)
    app.state.diagnostic_chat_service=DiagnosticChatService(provider,settings.diagnostic_timeout_seconds)
    logging.basicConfig(level=settings.log_level)
    app.include_router(health_router)
    app.include_router(pumps_router,prefix="/api/v1")
    app.include_router(diagnostics_router,prefix="/api/v1")
    app.include_router(diagnostic_chat_router,prefix="/api/v1")
    app.include_router(relationships_router,prefix="/api/v1")
    app.include_router(analysis_router,prefix="/api/v1")
    app.include_router(ai_features_router,prefix="/api/v1")
    app.include_router(ml_router)
    return app
