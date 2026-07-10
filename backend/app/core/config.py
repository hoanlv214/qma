"""Configuration anchors for the staged backend refactor."""

from dataclasses import dataclass
from pathlib import Path
import os


ROOT_DIR = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    root_dir: Path = ROOT_DIR
    public_dir: Path = ROOT_DIR / "public"
    payment_ledger_path: Path = ROOT_DIR / "payment_ledger.json"
    paid_reports_path: Path = ROOT_DIR / "paid_reports.json"
    invoices_path: Path = ROOT_DIR / "invoices.json"
    creator_applications_path: Path = ROOT_DIR / "creator_applications.json"
    provider_controls_path: Path = ROOT_DIR / "provider_controls.json"
    creator_claims_path: Path = ROOT_DIR / "creator_claims.json"
    api_title: str = "Quant Memory Agent (QMA) Server"
    api_version: str = "1.0.0"

    @property
    def access_token_secret(self) -> str:
        return os.getenv("QMA_ACCESS_TOKEN_SECRET") or os.getenv("QMA_SESSION_SECRET") or "qma-local-demo-secret-change-me"

    @property
    def arc_gateway_base_url(self) -> str:
        return os.getenv("QMA_ARC_GATEWAY_URL", "http://127.0.0.1:3000")


settings = Settings()


def load_local_env(env_path: Path | None = None) -> None:
    """Load root .env values without overriding real environment variables."""
    target = env_path or settings.root_dir / ".env"
    if not target.exists():
        return
    with target.open("r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
