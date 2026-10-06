"""ASGI entry point for `uvicorn frame_it.asgi:app` (settings from env / config.toml)."""

from frame_it.app import create_app
from frame_it.config import load_settings

app = create_app(load_settings())
