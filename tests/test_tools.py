from pathlib import Path

import pytest

from m3allema.domain.tools import Risk
from m3allema.tools.hub import ToolHub
from m3allema.tools.servers import ToolContext
from m3allema.tools.servers.files import PathOutsideRootError, resolve_inside
from m3allema.tools.servers.web import ensure_public_url, html_to_text


async def test_files_tools_round_trip_and_risk_levels(tmp_path: Path) -> None:
    async with ToolHub.from_config(["files"], {}, ToolContext(tmp_path)) as hub:
        risks = {spec.name: spec.risk for spec in hub.specs()}
        assert risks["files__read_file"] is Risk.READ
        assert risks["files__write_file"] is Risk.WRITE

        written = await hub.call("files__write_file", {"path": "notes/a.txt", "content": "hello"})
        assert not written.is_error
        read = await hub.call("files__read_file", {"path": "notes/a.txt"})
        assert read.content == "hello"
        listing = await hub.call("files__list_files", {})
        assert "notes/a.txt" in listing.content
        found = await hub.call("files__search_files", {"query": "HELLO"})
        assert "notes/a.txt:1" in found.content


async def test_write_refuses_to_overwrite_by_default(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("old", encoding="utf-8")
    async with ToolHub.from_config(["files"], {}, ToolContext(tmp_path)) as hub:
        result = await hub.call("files__write_file", {"path": "a.txt", "content": "new"})
    assert result.is_error
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "old"


async def test_path_traversal_is_blocked(tmp_path: Path) -> None:
    async with ToolHub.from_config(["files"], {}, ToolContext(tmp_path / "files")) as hub:
        result = await hub.call("files__read_file", {"path": "../secret.txt"})
    assert result.is_error


@pytest.mark.parametrize("path", ["../x", "/etc/passwd", "a/../../x"])
def test_resolve_inside_rejects_escapes(tmp_path: Path, path: str) -> None:
    with pytest.raises(PathOutsideRootError):
        resolve_inside(tmp_path, path)


def test_unknown_builtin_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="nope"):
        ToolHub.from_config(["nope"], {}, ToolContext(tmp_path))


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "http://127.0.0.1/admin", "http://localhost:8080", "ftp://x.com"]
)
def test_web_rejects_local_and_non_http_urls(url: str) -> None:
    with pytest.raises(ValueError):
        ensure_public_url(url)


def test_html_to_text_drops_scripts() -> None:
    html = "<html><script>evil()</script><h1>Title</h1><p>Body</p></html>"
    assert html_to_text(html) == "Title\nBody"
