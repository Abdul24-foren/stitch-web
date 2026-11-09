import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
APP_NAME = os.getenv("APP_NAME", "Stitch It")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-this-secret-key")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'stitch_it.db'}")
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "8"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
