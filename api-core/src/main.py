from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

# CORS is configured once, in src/api/http.py (CORS_ORIGINS env var) -
# it used to be duplicated here with a different hardcoded origin list,
# which meant the allowed origins silently depended on whether you ran
# `uvicorn src.main:app` or `uvicorn src.api.http:app`, and running this
# entrypoint stacked two CORS middlewares, which browsers reject on
# credentialed requests (two Access-Control-Allow-Origin headers).
from src.api.http import app  # noqa: E402

# Entry-point helper for uvicorn
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
