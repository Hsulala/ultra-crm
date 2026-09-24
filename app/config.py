from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./ultra_crm.db"
    session_secret_key: str = "dev-secret-change-me"
    base_url: str = "http://localhost:8080"
    internal_cron_secret: str = "dev-secret-change-me"

    # LINE Developers Console：Messaging API channel + LIFF 共用的 LINE Login channel
    line_channel_id: str = ""
    line_channel_secret: str = ""
    line_channel_access_token: str = ""

    # 只給本機開發用：開啟後 LIFF API 可以用 X-Dev-Line-User-Id header 取代真的
    # LINE ID Token，繞過需要真實 LINE channel 才能測試的限制。正式環境（Railway）
    # 不會設這個環境變數，所以正式環境不受影響——跟 sales-crm 的 DEV_LOGIN_EMAIL 同樣做法。
    dev_mode: bool = False


settings = Settings()
