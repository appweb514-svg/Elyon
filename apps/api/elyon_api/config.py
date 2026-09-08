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
    user_quota_bytes: int = 5 * 1024**3
    max_media_bytes: int = 500 * 1024**2
    enrollment_code_ttl_seconds: int = 600
    offline_grace_seconds: int = 90
    max_login_attempts_per_minute: int = 10
    lab_enroll_dir: Path = Path("/var/lib/elyon/lab-enroll")
    lab_player_serials: str = "emu-rpi-1,emu-rpi-2"
    lab_org_slug: str = "lab"
    lab_site_name: str = "Écrans lab"
    enqueue_media_processing: bool = True
    process_media_inline: bool = False
    # Alertes offline par e-mail (SMTP). Vide = désactivé.
    alert_smtp_host: str = ""
    alert_smtp_port: int = 587
    alert_smtp_user: str = ""
    alert_smtp_password: str = ""
    alert_smtp_from: str = ""
    alert_smtp_starttls: bool = True
    alert_smtp_to: str = ""  # destinataires séparés par des virgules
    # Webhook d'urgence (type « Afficher » depuis un système externe).
    # Clé secrète partagée — vide = désactivé.
    trigger_secret: str = ""