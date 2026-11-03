from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "local"
    database_url: str
    app_secret: str
    cors_origins: str = "http://localhost:5173"
    demo_mode: bool = False
    log_level: str = "INFO"
    # Connection pool. The API and the email worker share one PostgreSQL
    # server, so the pool must be bounded and its idle connections recycled
    # before the server or a firewall drops them.
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800
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

    # Guarded database reset. Off unless the deployment explicitly switches it
    # on; the production template leaves it false. The two backup directories
    # must live on different devices, and the encrypted dump is only readable
    # with the key held in the environment, never in the database.
    db_reset_enabled: bool = False
    db_reset_backup_dir: str = ""
    db_reset_backup_mirror_dir: str = ""
    db_reset_encryption_key: str = ""     # Fernet key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    db_reset_state_dir: str = "var/db-reset"
    db_reset_confirm_minutes: int = 10    # how long the verified run may wait for the reset key
    db_reset_token_minutes: int = 30      # lifetime of an intermediate step token
    db_reset_max_attempts: int = 3        # wrong secrets before the feature locks
    db_reset_lockout_minutes: int = 60
    db_reset_pg_bin: str = ""             # directory holding pg_dump/pg_restore; empty = PATH

settings = Settings()