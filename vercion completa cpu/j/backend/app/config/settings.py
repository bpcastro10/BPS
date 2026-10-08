"""Configuración central de la aplicación (se puede sobreescribir con variables de entorno o backend/.env)."""
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "si", "sí")


@dataclass(frozen=True)
class Settings:
    input_dir: Path
    data_dir: Path
    frontend_dir: Path
    host: str
    port: int
    poll_seconds: float
    max_image_width: int
    min_image_width: int
    low_confidence: float
    handwriting_enabled: bool
    handwriting_model: str
    ollama_url: str
    ollama_model: str
    vlm_mode: str
    cors_origins: list[str] = field(default_factory=list)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cheques.db"

    @property
    def previews_dir(self) -> Path:
        return self.data_dir / "previews"


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".pdf"}


@lru_cache
def get_settings() -> Settings:
    _load_dotenv(BACKEND_DIR / ".env")
    settings = Settings(
        input_dir=Path(os.getenv("CHEQUES_INPUT_DIR", PROJECT_DIR / "cheques_entrada")).resolve(),
        data_dir=Path(os.getenv("CHEQUES_DATA_DIR", BACKEND_DIR / "data")).resolve(),
        frontend_dir=Path(os.getenv("CHEQUES_FRONTEND_DIR", PROJECT_DIR / "frontend")).resolve(),
        host=os.getenv("APP_HOST", "127.0.0.1"),
        port=int(os.getenv("APP_PORT", "8000")),
        poll_seconds=float(os.getenv("POLL_SECONDS", "2")),
        max_image_width=int(os.getenv("MAX_IMAGE_WIDTH", "2000")),
        min_image_width=int(os.getenv("MIN_IMAGE_WIDTH", "1400")),
        low_confidence=float(os.getenv("LOW_CONFIDENCE", "0.80")),
        handwriting_enabled=_env_bool("HANDWRITING_ENABLED", True),
        handwriting_model=os.getenv("HANDWRITING_MODEL", "microsoft/trocr-base-handwritten"),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", ""),
        vlm_mode=os.getenv("VLM_MODE", "fallback").lower(),
        cors_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()],
    )
    settings.input_dir.mkdir(parents=True, exist_ok=True)
    settings.previews_dir.mkdir(parents=True, exist_ok=True)
    return settings
