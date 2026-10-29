"""All settings come from environment variables (or a local .env file)."""
import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv is optional
    pass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    site_url: str = _env("SITE_URL", "https://labeffects.com").rstrip("/")
    database_url: str = _env("DATABASE_URL") or "sqlite:///seo.db"
    gsc_service_account_json: str = _env("GSC_SERVICE_ACCOUNT_JSON")
    gsc_property: str = _env("GSC_PROPERTY", "sc-domain:labeffects.com")
    slack_webhook_url: str = _env("SLACK_WEBHOOK_URL")
    slack_bot_token: str = _env("SLACK_BOT_TOKEN")
    slack_channel_id: str = _env("SLACK_CHANNEL_ID", "C0B1ZM4TASY")
    report_dir: str = _env("REPORT_DIR", "reports")
    keyword_provider: str = _env("KEYWORD_PROVIDER", "none").lower()
    dataforseo_login: str = _env("DATAFORSEO_LOGIN")
    dataforseo_password: str = _env("DATAFORSEO_PASSWORD")
    crawl_max_pages: int = int(_env("CRAWL_MAX_PAGES", "3000") or 3000)
    crawl_delay_seconds: float = float(_env("CRAWL_DELAY_SECONDS", "0.5") or 0.5)

    @property
    def host(self) -> str:
        return self.site_url.split("//", 1)[-1].split("/", 1)[0].lower()


settings = Settings()
