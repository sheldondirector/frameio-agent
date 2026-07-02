"""Tests for the shared media layer (thumbnail extraction, visual filter)."""
from __future__ import annotations

import pytest

from frameio_agent import media


class TestExtractThumbnailUrl:
    def test_media_links_nested_dict_download_url(self) -> None:
        meta = {"media_links": {"thumbnail": {"download_url": "https://x/y.jpg"}}}
        assert media.extract_thumbnail_url(meta) == "https://x/y.jpg"

    def test_media_links_nested_dict_url(self) -> None:
        meta = {"media_links": {"poster": {"url": "https://x/p.jpg"}}}
        assert media.extract_thumbnail_url(meta) == "https://x/p.jpg"

    def test_media_links_href(self) -> None:
        meta = {"media_links": {"thumb": {"href": "https://x/h.jpg"}}}
        assert media.extract_thumbnail_url(meta) == "https://x/h.jpg"

    def test_media_links_bare_string(self) -> None:
        meta = {"media_links": {"thumb": "https://x/t.jpg"}}
        assert media.extract_thumbnail_url(meta) == "https://x/t.jpg"

    def test_top_level_flat_field(self) -> None:
        meta = {"thumbnail": "https://x/t.jpg"}
        assert media.extract_thumbnail_url(meta) == "https://x/t.jpg"

    def test_field_priority_order(self) -> None:
        # 'thumb' comes before 'poster' in THUMBNAIL_FIELDS
        meta = {"media_links": {
            "poster": {"url": "https://x/poster.jpg"},
            "thumb": {"url": "https://x/thumb.jpg"},
        }}
        assert media.extract_thumbnail_url(meta) == "https://x/thumb.jpg"

    def test_empty_string_skipped(self) -> None:
        meta = {"media_links": {"thumb": ""}, "thumbnail": "https://x/fallback.jpg"}
        assert media.extract_thumbnail_url(meta) == "https://x/fallback.jpg"

    def test_missing_returns_none(self) -> None:
        assert media.extract_thumbnail_url({"id": "f1"}) is None

    def test_empty_media_links_returns_none(self) -> None:
        assert media.extract_thumbnail_url({"media_links": {}}) is None


class TestIsVisual:
    @pytest.mark.parametrize("mt,expected", [
        ("video/mp4", True),
        ("video/quicktime", True),
        ("image/png", True),
        ("image/jpeg", True),
        ("audio/wav", False),
        ("application/pdf", False),
        ("", True),      # unknown at list level — permissive
        (None, True),
    ])
    def test_media_types(self, mt, expected) -> None:
        child = {"media_type": mt}
        assert media._is_visual(child, visual_only=True) is expected

    def test_visual_only_false_accepts_everything(self) -> None:
        assert media._is_visual({"media_type": "application/pdf"}, visual_only=False) is True
