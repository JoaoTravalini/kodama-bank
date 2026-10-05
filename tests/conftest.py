from pathlib import Path
from os import path, environ

root = Path(__file__).resolve().parents[1]

if not environ.get("APP_ENV") or environ.get("APP_ENV") == "local":
    from dotenv import load_dotenv

    load_dotenv(path.join(str(root), ".env"))

    if not environ.get("JWT_SECRET"):
        environ["JWT_SECRET"] = "kodama-local-demo-key-change-outside-local"

    if environ.get("SERVER_LOCALHOST") is None:
        environ["SERVER_LOCALHOST"] = "0.0.0.0"
