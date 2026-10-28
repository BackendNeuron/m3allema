"""What the owner sees before approving a tool call.

Every interface (terminal, Telegram, dashboard) shows the same view:

* a short title and the key fields of the action (To, Subject, file path...),
* **mentions**: email addresses, links, phone and account numbers found
  anywhere in the arguments, always listed in full, so an instruction hidden
  deep inside a long skill or email body cannot slip past unseen,
* the full text, with a preview and an honest "showing X of Y characters"
  when it is long.

All of this is plain code over the call's arguments: no model is involved, so
it costs nothing and cannot be talked out of listing what it finds.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from m3allema.domain.messages import ToolCall
from m3allema.domain.tools import ToolSpec

PREVIEW_CHARS = 600
"""Text shown before "view full text"; the full text is always available."""

_MENTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("link", re.compile(r"(?:https?://|www\.)[^\s\"'<>)\]]+", re.IGNORECASE)),
    # IBAN-style accounts (any country): two letters, two check digits, then groups of up
    # to four letters or digits; the last group may be a single character.
    ("account", re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{1,4}){3,8}\b")),
    # Long digit runs (phone, card or account numbers), allowing spaces and dashes.
    ("number", re.compile(r"(?<![\w.,])\+?\d(?:[ -]?\d){7,}(?!\w|[.,]\d)")),
)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# Per tool: (title, [(label, argument name)]). Unknown tools get a generic view.
_LAYOUTS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "gmail__send_email": ("Send an email", [("To", "to"), ("Subject", "subject")]),
    "gmail__create_draft": ("Save an email draft", [("To", "to"), ("Subject", "subject")]),
    "calendar__create_event": (
        "Create a calendar event",
        [("Title", "summary"), ("Start", "start"), ("Attendees", "attendees")],
    ),
    "memory__remember": ("Remember for future conversations", [("Fact", "fact")]),
    "memory__forget": ("Forget facts", [("Containing", "text")]),
    "skills__save_skill": (
        "Save a new skill",
        [("Name", "name"), ("When to use", "description")],
    ),
    "files__write_file": ("Write a file", [("Path", "path")]),
    "excel__write_sheet": ("Write an Excel sheet", [("Path", "path"), ("Sheet", "sheet")]),
    "excel__append_rows": ("Add rows to an Excel sheet", [("Path", "path"), ("Sheet", "sheet")]),
    "docs__write_docx": ("Write a Word document", [("Path", "path"), ("Title", "title")]),
    "sheets__update_range": ("Overwrite Google Sheet cells", [("Range", "range")]),
    "sheets__append_rows": ("Add rows to a Google Sheet", [("Range", "range")]),
}


@dataclass(frozen=True, slots=True)
class ApprovalView:
    """A tool call, laid out for a person to judge."""

    title: str
    tool: str
    risk: str
    fields: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    full_text: str = ""

    @property
    def is_long(self) -> bool:
        """Whether the full text is longer than the preview."""
        return len(self.full_text) > PREVIEW_CHARS

    @property
    def preview(self) -> str:
        """The start of the full text, with an honest note when it is cut."""
        if not self.is_long:
            return self.full_text
        return (
            f"{self.full_text[:PREVIEW_CHARS]}...\n"
            f"[showing {PREVIEW_CHARS:,} of {len(self.full_text):,} characters]"
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON form for the dashboard."""
        return {
            "title": self.title,
            "fields": [list(item) for item in self.fields],
            "warnings": self.warnings,
            "mentions": self.mentions,
        }


def find_mentions(text: str) -> list[str]:
    """Email addresses, links, accounts and long numbers in ``text``, each once, in order.

    When two patterns match overlapping text (the digits inside an IBAN, say),
    only the longest match is kept.
    """
    spans: list[tuple[int, int, str]] = []
    for _, pattern in _MENTION_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group().rstrip(".,;:")
            if not _DATE.fullmatch(value):
                spans.append((match.start(), match.start() + len(value), value))
    kept: list[tuple[int, int, str]] = []
    for start, end, value in sorted(spans, key=lambda s: s[0] - s[1]):  # longest first
        if all(end <= k_start or start >= k_end for k_start, k_end, _ in kept):
            kept.append((start, end, value))
    ordered: list[str] = []
    for _, _, value in sorted(kept):
        if value not in ordered:
            ordered.append(value)
    return ordered


def describe_call(call: ToolCall, spec: ToolSpec) -> ApprovalView:
    """Lay out ``call`` for the owner."""
    title, layout = _LAYOUTS.get(call.name, (spec.description or call.name, []))
    fields = [
        (label, _as_text(call.arguments[key]))
        for label, key in layout
        if call.arguments.get(key) not in (None, "", [])
    ]
    warnings = []
    if call.arguments.get("overwrite") is True:
        warnings.append("Replaces an existing file.")
    full_text = _full_text(call.arguments)
    return ApprovalView(
        title=title,
        tool=call.name,
        risk=spec.risk.value,
        fields=fields,
        warnings=warnings,
        mentions=find_mentions(full_text),
        full_text=full_text,
    )


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ", ".join(_as_text(item) for item in value)
    return json.dumps(value, ensure_ascii=False)


def _full_text(arguments: dict[str, Any]) -> str:
    """Every argument, readable: plain strings as-is, everything else as JSON."""
    parts = []
    for key, value in arguments.items():
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=1)
        parts.append(f"{key}:\n{text}" if "\n" in text or len(text) > 80 else f"{key}: {text}")
    return "\n".join(parts)
