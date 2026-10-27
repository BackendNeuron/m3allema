"""Small text helpers shared by tools and integrations."""

from __future__ import annotations

from bs4 import BeautifulSoup

_NOISE_TAGS = ["script", "style", "noscript", "svg", "nav", "footer"]


def html_to_text(html: str) -> str:
    """Strip scripts, styles and markup, keeping readable text one line per block."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_NOISE_TAGS):
        tag.decompose()
    lines = (line.strip() for line in soup.get_text("\n").splitlines())
    return "\n".join(line for line in lines if line)
