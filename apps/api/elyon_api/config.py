from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "ELYON_"}

    database_url: str = "postgresql://elyon:CHANGE_ME@localhost:5432/elyon"
    media_storage_root: Path = Path("/var/lib/elyon/media")
    heartbeat_interval_seconds: int = 30
    storage_backend: str = "fs"
    s3_bucket: str = ""
    s3_region: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_endpoint_url: str = ""
    session_secret: str = "CHANGE_ME"
    session_ttl_seconds: int = 604800
    session_cookie_name: str = "elyon_session"
    csrf_cookie_name: str = "elyon_csrf"
    cookie_secure: bool = False
    public_base_url: str = "http://localhost:8000"
    signing_key_file: Path = Path("/var/lib/elyon/signing_key.pem")
    auto_migrate: bool = True
    org_quota_bytes: int = 20 * 1024**3
    max_media_bytes: int = 500 * 1024**2
    enrollment_code_ttl_seconds: int = 600
    offline_grace_seconds: int = 90
    max_login_attempts_per_minute: int = 10