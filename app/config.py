"""
Configuration management for STBcheck app using Pydantic Settings.
All configuration values can be set via environment variables.
"""

from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =============================================================================
    # Timeouts (in seconds)
    # =============================================================================
    request_timeout: int = Field(
        default=10,
        description="Timeout for HTTP requests to portals",
        alias="REQUEST_TIMEOUT",
    )
    stream_timeout: int = Field(
        default=30,
        description="Timeout for streaming operations (proxy, concurrent checks)",
        alias="STREAM_TIMEOUT",
    )
    logo_fetch_timeout: int = Field(
        default=15,
        description="Timeout for fetching logo images",
        alias="LOGO_FETCH_TIMEOUT",
    )

    # =============================================================================
    # Concurrency Limits
    # =============================================================================
    max_concurrent_portal_checks: int = Field(
        default=15,
        description="Maximum number of concurrent portal checks (semaphore limit)",
        alias="MAX_CONCURRENT_PORTAL_CHECKS",
    )

    # =============================================================================
    # Logging Configuration
    # =============================================================================
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
        alias="LOG_LEVEL",
    )
    log_file_max_bytes: int = Field(
        default=5 * 1024 * 1024,  # 5 MB
        description="Maximum size of log file before rotation (bytes)",
        alias="LOG_FILE_MAX_BYTES",
    )
    log_backup_count: int = Field(
        default=2,
        description="Number of backup log files to keep",
        alias="LOG_BACKUP_COUNT",
    )

    # =============================================================================
    # CORS Configuration
    # =============================================================================
    cors_origins: str = Field(
        default="*",
        description="Comma-separated list of allowed CORS origins, or '*' for all",
        alias="CORS_ORIGINS",
    )

    def get_cors_origins_list(self) -> List[str]:
        if self.cors_origins == "*":
            return ["*"]
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    # =============================================================================
    # Server Configuration
    # =============================================================================
    server_host: str = Field(
        default="0.0.0.0",
        description="Host address to bind the server to",
        alias="SERVER_HOST",
    )
    server_port: int = Field(
        default=8000,
        description="Port number for the server",
        alias="SERVER_PORT",
    )

    # =============================================================================
    # Application Settings
    # =============================================================================
    app_version: str = Field(
        default="1.1.0 - Organization & Refactoring",
        description="Application version string",
        alias="APP_VERSION",
    )

    # =============================================================================
    # Stalker Portal Detection
    # =============================================================================
    stalker_check_timeout: int = Field(
        default=10,
        description="Timeout for Stalker portal checks (seconds)",
        alias="STALKER_CHECK_TIMEOUT",
    )
    stalker_cache_ttl: int = Field(
        default=300,
        description="Cache TTL for Stalker portal results (seconds)",
        alias="STALKER_CACHE_TTL",
    )
    stalker_detection_enabled: bool = Field(
        default=True,
        description="Enable Stalker portal detection and specialized handling",
        alias="STALKER_DETECTION_ENABLED",
    )

    # =============================================================================
    # Expiry Detection Configuration
    # =============================================================================
    expiry_field_priority: List[str] = Field(
        default=[
            "expire_billing_date",
            "expire_date",
            "exp_date",
            "max_view_date",
            "end_date",
            "end_date_time",
            "date_end",
            "valid_until",
            "access_end",
            "end",
            "to",
            "active_until",
            "subscription_end",
            "billing_end",
            "plan_expires",
            "expires",
            "expiry_date",
            "expired",
        ],
        description="Ordered list of field names to check for expiry dates",
        alias="EXPIRY_FIELD_PRIORITY",
    )
    date_parsing_timezone: str = Field(
        default="UTC",
        description="Default timezone for date parsing",
        alias="DATE_PARSING_TIMEZONE",
    )

    # =============================================================================
    # SSL Verification
    # =============================================================================
    verify_ssl: bool = Field(
        default=True,
        description="Verify SSL certificates when making HTTPS requests",
        alias="VERIFY_SSL",
    )

    # =============================================================================
    # Logo Cache Configuration
    # =============================================================================
    logo_cache_maxsize: int = Field(
        default=1000,
        description="Maximum number of logo entries in memory cache",
        alias="LOGO_CACHE_MAXSIZE",
    )
    logo_cache_ttl: int = Field(
        default=300,  # 5 minutes
        description="Time-to-live for cached logos (seconds)",
        alias="LOGO_CACHE_TTL",
    )
    logo_chunk_size: int = Field(
        default=8192,
        description="Chunk size for streaming logo downloads",
        alias="LOGO_CHUNK_SIZE",
    )

    # =============================================================================
    # Stream Proxy Configuration
    # =============================================================================
    stream_chunk_size: int = Field(
        default=65536,  # 64 KB
        description="Chunk size for streaming video content",
        alias="STREAM_CHUNK_SIZE",
    )
    max_redirects: int = Field(
        default=10,
        description="Maximum number of redirects to follow when proxying streams",
        alias="MAX_REDIRECTS",
    )
    stream_auth_cache_ttl: int = Field(
        default=180,  # 3 minutes
        description="TTL for cached stream authentication cookies (seconds)",
        alias="STREAM_AUTH_CACHE_TTL",
    )

    # =============================================================================
    # Circuit Breaker Configuration
    # =============================================================================
    circuit_breaker_threshold: int = Field(
        default=3,
        description="Number of consecutive failures before opening circuit",
        alias="CIRCUIT_BREAKER_THRESHOLD",
    )
    circuit_breaker_duration: int = Field(
        default=300,  # 5 minutes
        description="How long circuit stays open (seconds)",
        alias="CIRCUIT_BREAKER_DURATION",
    )

    # =============================================================================
    # Rate Limiting Configuration
    # =============================================================================
    rate_limit_proxy_logo: str = Field(
        default="60/minute",
        description="Rate limit for proxy_logo endpoint",
        alias="RATE_LIMIT_PROXY_LOGO",
    )
    rate_limit_stream_ops: str = Field(
        default="30/minute",
        description="Rate limit for stream operations (get_link, check_stream, proxy_stream)",
        alias="RATE_LIMIT_STREAM_OPS",
    )
    rate_limit_portal_check: str = Field(
        default="20/minute",
        description="Rate limit for portal check endpoint",
        alias="RATE_LIMIT_PORTAL_CHECK",
    )

    # =============================================================================
    # Redis Configuration (Optional)
    # =============================================================================
    redis_url: Optional[str] = Field(
        default=None,
        description="Redis URL for shared cache (e.g., redis://localhost:6379/0)",
        alias="REDIS_URL",
    )

    # =============================================================================
    # Vercel Compatibility
    # =============================================================================
    vercel_compatible_mode: bool = Field(
        default=False,
        description="Enable reduced timeouts for Vercel serverless environment",
        alias="VERCEL_COMPATIBLE_MODE",
    )

    # =============================================================================
    # Proxy Base URL (for M3U generation)
    # =============================================================================
    proxy_base_url: Optional[str] = Field(
        default=None,
        description="Base URL of the STBcheck proxy server (used in M3U generation)",
        alias="PROXY_BASE_URL",
    )

    # =============================================================================
    # Default Timezone (for STB emulation)
    # =============================================================================
    default_timezone: str = Field(
        default="Europe/London",
        description="Default timezone string for STB emulation",
        alias="DEFAULT_TIMEZONE",
    )


# Global settings instance
settings = Settings()
