import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

APP_NAME = os.getenv("APP_NAME", "Stitch It")
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
if (
    len(SECRET_KEY) < 32
    or SECRET_KEY.lower().startswith(("replace-with-", "change-me", "your-"))
):
    raise RuntimeError(
        "Set SECRET_KEY to a unique random value of at least 32 characters."
    )

SESSION_HTTPS_ONLY = os.getenv("SESSION_HTTPS_ONLY", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'stitch_it.db'}")
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "8"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
