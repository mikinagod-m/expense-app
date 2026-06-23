from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: str = "dev-secret"
    dev_login: bool = True

    database_url: str = "sqlite:///./data/expenses.db"

    receipts_dir: str = "./receipts"
    tesseract_cmd: str = ""

    aad_tenant_id: str = ""
    aad_client_id: str = ""
    aad_client_secret: str = ""
    aad_redirect_uri: str = "http://localhost:8000/auth/callback"


settings = Settings()
