"""Documents MCP server: read Word and PDF files, write Word files.

Run standalone::

    M3ALLEMA_FILES_ROOT=./files python -m m3allema.tools.servers.docs
"""

from __future__ import annotations

import os
from pathlib import Path

import docx
from mcp.server.mcpserver import MCPServer
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from m3allema.tools.servers._annotations import LOCAL_WRITE, READ_ONLY
from m3allema.tools.servers.files import resolve_inside

MAX_PDF_PAGES = 30


def read_docx_text(path: Path) -> str:
    """Paragraphs and table rows of a Word document as plain text."""
    document = docx.Document(str(path))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(parts)


def read_pdf_text(path: Path, first_page: int, max_pages: int) -> str:
    """Text of a range of PDF pages, each labelled with its page number."""
    try:
        reader = PdfReader(str(path))
    except PdfReadError as exc:
        raise ValueError(f"cannot read PDF: {exc}") from exc
    total = len(reader.pages)
    start = max(first_page, 1)
    end = min(total, start + max(1, min(max_pages, MAX_PDF_PAGES)) - 1)
    pages = [
        f"--- page {n} ---\n{reader.pages[n - 1].extract_text() or ''}"
        for n in range(start, end + 1)
    ]
    text = "\n\n".join(pages)
    if end < total:
        text += f"\n\n[pages {start}-{end} of {total}; continue with first_page={end + 1}]"
    if not text.strip():
        return "(no extractable text: the PDF may be a scan)"
    return text


def write_docx_file(path: Path, title: str, body: str) -> None:
    """Create a Word document from simple markdown.

    Supported: ``# `` and ``## `` headings, ``- `` bullets, blank-line separated paragraphs.
    """
    document = docx.Document()
    if title:
        document.add_heading(title, level=0)
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## "):
            document.add_heading(stripped[3:], level=2)
        elif stripped.startswith("# "):
            document.add_heading(stripped[2:], level=1)
        elif stripped.startswith(("- ", "* ")):
            document.add_paragraph(stripped[2:], style="List Bullet")
        else:
            document.add_paragraph(stripped)
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))


def create_docs_server(root: Path) -> MCPServer:
    """Build a documents server confined to ``root``."""
    root = root.resolve()
    server = MCPServer(
        "docs", instructions="Read Word (.docx) and PDF files; write Word documents."
    )

    @server.tool(annotations=READ_ONLY)
    def read_document(path: str, first_page: int = 1, max_pages: int = MAX_PDF_PAGES) -> str:
        """Extract the text of a .docx or .pdf file. PDFs are read a range of pages at a time."""
        target = resolve_inside(root, path)
        if not target.is_file():
            raise ValueError(f"{path!r} does not exist")
        suffix = target.suffix.lower()
        if suffix == ".docx":
            return read_docx_text(target) or "(empty document)"
        if suffix == ".pdf":
            return read_pdf_text(target, first_page, max_pages)
        raise ValueError("only .docx and .pdf files are supported")

    @server.tool(annotations=LOCAL_WRITE)
    def write_docx(path: str, title: str, body: str, overwrite: bool = False) -> str:
        """Create a Word document. The body supports '# ' headings, '- ' bullets and paragraphs.

        Set overwrite=true to replace an existing file.
        """
        target = resolve_inside(root, path)
        if target.suffix.lower() != ".docx":
            raise ValueError("the file name must end with .docx")
        if target.exists() and not overwrite:
            raise ValueError(f"{path!r} already exists; pass overwrite=true to replace it")
        write_docx_file(target, title, body)
        return f"Wrote {path}"

    return server


if __name__ == "__main__":
    create_docs_server(Path(os.environ.get("M3ALLEMA_FILES_ROOT", "."))).run("stdio")
