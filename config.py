from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    flink_base_url: str = "https://api.goflink.com"
    flink_token: str = ""
    flink_hub_id: str = ""
    flink_hub_slug: str = ""
    flink_country_code: str = "+49"
    flink_datadome_cookie: str = ""
    flink_firebase_refresh_token: str = ""


settings = Settings()
