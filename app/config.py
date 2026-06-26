from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: str = "dev-secret"
    dev_login: bool = True

    database_url: str = "sqlite:///./data/expenses.db"

    receipts_dir: str = "./receipts"
    receipt_max_bytes: int = 10 * 1024 * 1024
    tesseract_cmd: str = ""

    aad_tenant_id: str = ""
    aad_client_id: str = ""
    aad_client_secret: str = ""
    aad_redirect_uri: str = "http://localhost:8000/auth/callback"

    app_base_url: str = "http://localhost:8000"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    backup_dir: str = "./backups"
    backup_retention_days: int = 14


settings = Settings()
