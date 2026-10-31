from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "local"
    database_url: str
    app_secret: str
    cors_origins: str = "http://localhost:5173"
    demo_mode: bool = False
    log_level: str = "INFO"
    # Telegram notifications. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env only;
    # never put real values here (empty = disabled).
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_notify_login: bool = False   # logins are noisy; off by default

settings = Settings()