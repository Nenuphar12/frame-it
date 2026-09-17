"""ASGI entry point for `uvicorn the_frame_v2.asgi:app` (settings from env / config.toml)."""

from the_frame_v2.app import create_app
from the_frame_v2.config import load_settings

app = create_app(load_settings())
