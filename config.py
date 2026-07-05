import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

IMAGE_ROOT = Path(os.getenv("IMAGE_ROOT", "./downloads")).resolve()
ROOT = IMAGE_ROOT
DB_PATH = Path(os.getenv("DB_PATH", "./data/peakpics.db")).resolve()
SCAN_INTERVAL_SEC = int(os.getenv("SCAN_INTERVAL_SEC", "300"))
SUPPORTED_SOURCES = os.getenv("SUPPORTED_SOURCES", "a1111,comfyui,novelai,fooocus").split(",")
PORT = int(os.getenv("PORT", "8000"))
API_KEY = os.getenv("API_KEY", "")

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".svg"}
PARSEABLE_EXTS = {".png"}  # v1: PNG only for metadata extraction