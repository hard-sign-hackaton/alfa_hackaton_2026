"""Compatibility entry point. Prefer python -m app.modules.news."""
from app.modules.news.cli import entrypoint

if __name__ == '__main__':
    entrypoint()
