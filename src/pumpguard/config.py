"""Central app configuration."""
from dataclasses import dataclass, field
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Load the one documented project-level environment file, independent of cwd.
load_dotenv(PROJECT_ROOT / ".env")
@dataclass(frozen=True)
class Settings:
    """Runtime settings."""
    history_limit:int=1000
    log_level:str="INFO"
    diagnostic_provider:str="amd"
    diagnostic_timeout_seconds:float=250.0
    diagnostic_connect_timeout_seconds:float=3.0
    diagnostic_catalog_timeout_seconds:float=5.0
    diagnostic_completion_timeout_seconds:float=240.0
    radeon_base_url:str="https://developer.amd.com.cn/radeon/api/v1"
    radeon_model:str="DeepSeek-V4-Flash"
    radeon_api_key:str|None=field(default=None,repr=False)
    diagnostic_max_output_tokens:int=1800
    cors_origins:tuple[str,...]=("http://localhost:5173","http://127.0.0.1:5173")
    rate_limit_window_seconds:int=60
    rate_limit_simulation:int=120
    rate_limit_analysis:int=60
    rate_limit_ml:int=30
def get_settings() -> Settings:
    """Read environment settings."""
    n=int(os.getenv("PUMPGUARD_HISTORY_LIMIT","1000"))
    if n<1: raise ValueError("PUMPGUARD_HISTORY_LIMIT must be positive")
    provider=os.getenv("PUMPGUARD_DIAGNOSTIC_PROVIDER","amd").lower()
    if provider != "amd": raise ValueError("PUMPGUARD_DIAGNOSTIC_PROVIDER must be amd; mock providers are test-only")
    timeout=float(os.getenv("PUMPGUARD_DIAGNOSTIC_TIMEOUT_SECONDS","250"))
    if not .05<=timeout<=295: raise ValueError("PUMPGUARD_DIAGNOSTIC_TIMEOUT_SECONDS must be between 0.05 and 295")
    connect_timeout=float(os.getenv("PUMPGUARD_DIAGNOSTIC_CONNECT_TIMEOUT_SECONDS","3"))
    if not .05<=connect_timeout<=30: raise ValueError("PUMPGUARD_DIAGNOSTIC_CONNECT_TIMEOUT_SECONDS must be between 0.05 and 30")
    catalog_timeout=float(os.getenv("PUMPGUARD_DIAGNOSTIC_CATALOG_TIMEOUT_SECONDS","5"))
    if not .05<=catalog_timeout<=30: raise ValueError("PUMPGUARD_DIAGNOSTIC_CATALOG_TIMEOUT_SECONDS must be between 0.05 and 30")
    completion_timeout=float(os.getenv("PUMPGUARD_DIAGNOSTIC_COMPLETION_TIMEOUT_SECONDS","240"))
    if not .05<=completion_timeout<=280: raise ValueError("PUMPGUARD_DIAGNOSTIC_COMPLETION_TIMEOUT_SECONDS must be between 0.05 and 280")
    if timeout <= catalog_timeout + completion_timeout:
        raise ValueError("PUMPGUARD_DIAGNOSTIC_TIMEOUT_SECONDS must exceed catalog plus completion timeouts")
    base_url=os.getenv("RADEON_BASE_URL","https://developer.amd.com.cn/radeon/api/v1").rstrip("/")
    if not base_url.startswith("https://"):
        raise ValueError("RADEON_BASE_URL must use HTTPS")
    model=os.getenv("RADEON_MODEL","DeepSeek-V4-Flash").strip()
    if not model or len(model)>128:
        raise ValueError("RADEON_MODEL must contain 1 to 128 characters")
    max_tokens=int(os.getenv("PUMPGUARD_DIAGNOSTIC_MAX_OUTPUT_TOKENS","1800"))
    if not 64<=max_tokens<=4096:
        raise ValueError("PUMPGUARD_DIAGNOSTIC_MAX_OUTPUT_TOKENS must be between 64 and 4096")
    key=os.getenv("RADEON_API_KEY")
    if key and key.strip()=="PASTE_YOUR_AMD_API_KEY_HERE":
        key=None
    elif key:
        key=key.strip() or None
    origins=tuple(item.strip().rstrip("/") for item in os.getenv(
        "PUMPGUARD_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",") if item.strip())
    if not origins or "*" in origins:
        raise ValueError("PUMPGUARD_CORS_ORIGINS must contain explicit origins")
    window=int(os.getenv("PUMPGUARD_RATE_LIMIT_WINDOW_SECONDS","60"))
    if not 1<=window<=3600: raise ValueError("PUMPGUARD_RATE_LIMIT_WINDOW_SECONDS must be between 1 and 3600")
    limits={name: int(os.getenv(env, str(default))) for name, env, default in (
        ("simulation", "PUMPGUARD_RATE_LIMIT_SIMULATION", 120),
        ("analysis", "PUMPGUARD_RATE_LIMIT_ANALYSIS", 60),
        ("ml", "PUMPGUARD_RATE_LIMIT_ML", 30),
    )}
    if any(value<1 for value in limits.values()):
        raise ValueError("PUMPGUARD_RATE_LIMIT_* values must be positive")
    return Settings(history_limit=n, log_level=os.getenv("PUMPGUARD_LOG_LEVEL","INFO").upper(),
        diagnostic_provider=provider, diagnostic_timeout_seconds=timeout,
        diagnostic_connect_timeout_seconds=connect_timeout,
        diagnostic_catalog_timeout_seconds=catalog_timeout,
        diagnostic_completion_timeout_seconds=completion_timeout,
        radeon_base_url=base_url, radeon_model=model, radeon_api_key=key,
        diagnostic_max_output_tokens=max_tokens, cors_origins=origins,
        rate_limit_window_seconds=window,
        rate_limit_simulation=limits["simulation"], rate_limit_analysis=limits["analysis"],
        rate_limit_ml=limits["ml"])
