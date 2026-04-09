"""Tests for runtime BASE_URL HTML rewriting."""

from app.config import get_settings
from app.main import _render_spa_html


def test_render_spa_html_root_base_url() -> None:
    settings = get_settings()
    original = settings.base_url
    try:
        settings.base_url = "/"
        template = (
            "<!doctype html><html><head></head><body>"
            '<script src="/__INSYNC_BASE__/assets/app.js"></script>'
            "</body></html>"
        )
        html = _render_spa_html(template)
        assert 'src="/assets/app.js"' in html
        assert 'window.__BASE_URL__ = "/"' in html
    finally:
        settings.base_url = original


def test_render_spa_html_subpath_base_url() -> None:
    settings = get_settings()
    original = settings.base_url
    try:
        settings.base_url = "/insync"
        template = (
            "<!doctype html><html><head></head><body>"
            '<link rel="stylesheet" href="/__INSYNC_BASE__/assets/app.css">'
            "</body></html>"
        )
        html = _render_spa_html(template)
        assert 'href="/insync/assets/app.css"' in html
        assert 'window.__BASE_URL__ = "/insync"' in html
    finally:
        settings.base_url = original
