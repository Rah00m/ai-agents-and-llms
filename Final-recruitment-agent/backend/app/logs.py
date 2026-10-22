"""Logging for the timing of each stage. Logs carry durations, sizes and counts only, never CV text or names."""
import logging

_ROOT = "recruitment"


def get_logger(name: str) -> logging.Logger:
    root = logging.getLogger(_ROOT)
    if not root.handlers and not logging.getLogger().handlers:     # uvicorn does not set up the root logger
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
        root.setLevel(logging.INFO)
    return logging.getLogger(f"{_ROOT}.{name}")
