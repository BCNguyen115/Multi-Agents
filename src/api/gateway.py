"""FastAPI Gateway entrypoint alias module.

Re-exports the `app` instance from `src.gateway.main` so that both:
  - uvicorn src.api.gateway:app --host 0.0.0.0 --port 8000
  - uvicorn src.gateway.main:app --host 0.0.0.0 --port 8000
work seamlessly.
"""

from src.gateway.main import app

__all__ = ["app"]
