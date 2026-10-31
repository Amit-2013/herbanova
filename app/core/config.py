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

    # Scheduled email reports. Two independent switches: nothing leaves the
    # server unless EMAIL_MODE=live *and* EMAIL_SEND_ENABLED=true. The default is
    # test mode, which redirects every message to one Administrator address.
    # SMTP secrets come from the environment only and are never logged.
    email_mode: str = "test"              # test | live
    email_send_enabled: bool = False
    email_test_recipient: str = ""
    email_max_bytes: int = 9_500_000
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    smtp_from: str = ""
    smtp_reply_to: str = ""
    email_worker_interval: int = 60       # seconds between worker ticks
    app_base_url: str = "http://127.0.0.1:8000"

settings = Settings()