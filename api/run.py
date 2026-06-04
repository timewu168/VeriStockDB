from __future__ import annotations

import config


def main() -> int:
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            "ERROR FastAPI runtime is not installed. Run: pip install -r requirements.txt"
        ) from exc

    uvicorn.run("api.app:app", host=config.API_HOST, port=config.API_PORT)
    return 0
