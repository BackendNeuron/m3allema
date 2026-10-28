"""The onboarding interview: a few questions that set up a new workspace.

The questions live here, in one place, so every interface (the dashboard, the
CLI) asks the same thing. :func:`apply_answers` turns the answers into the
workspace files:

* ``IDENTITY.md``, ``BUSINESS.md``, ``OWNER.md`` and ``RULES.md`` are rewritten.
* ``config.yaml`` and ``policy.yaml`` are edited line by line, so the owner's
  comments and any settings the interview does not cover are kept.

Every file is copied to ``.m3allema/backups/`` before it changes, so nothing is
lost if the owner prefers what they had.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from m3allema.workspace.workspace import Workspace

PLACEHOLDER = "[YOUR BUSINESS NAME]"
"""Text in the template ``BUSINESS.md``; while it is there, onboarding has not run."""

TOOL_CHOICES: tuple[str, ...] = ("files", "excel", "docs", "web", "gmail", "calendar", "sheets")
LANGUAGE_CHOICES: tuple[str, ...] = (
    "English",
    "Arabic",
    "Egyptian dialect",
    "Gulf dialect",
    "Franco",
)


class Kind(StrEnum):
    """How a question is answered."""

    TEXT = "text"
    LONG_TEXT = "long_text"
    LIST = "list"
    CHOICE = "choice"
    MULTI = "multi"
    MONEY = "money"


@dataclass(frozen=True, slots=True)
class Question:
    """One interview question, described for any interface to render.

    Attributes:
        id: Key of the answer in :class:`Answers`.
        section: Group shown as the step title.
        prompt: The question itself.
        kind: How it is answered.
        help: One line of guidance under the question.
        options: Allowed values for ``choice`` and ``multi``.
        required: Whether an empty answer is refused.

    """

    id: str
    section: str
    prompt: str
    kind: Kind
    help: str = ""
    options: tuple[str, ...] = field(default=())
    required: bool = False

    def to_dict(self, default: Any) -> dict[str, Any]:
        """JSON form, including the default answer."""
        return {
            "id": self.id,
            "section": self.section,
            "prompt": self.prompt,
            "kind": self.kind.value,
            "help": self.help,
            "options": list(self.options),
            "required": self.required,
            "default": default,
        }


QUESTIONS: tuple[Question, ...] = (
    Question("business_name", "Business", "What is the business called?", Kind.TEXT, required=True),
    Question(
        "offering",
        "Business",
        "What do you sell?",
        Kind.LONG_TEXT,
        "Products or services, in a sentence or two.",
        required=True,
    ),
    Question(
        "hours",
        "Business",
        "When are you open?",
        Kind.TEXT,
        "e.g. Sunday to Thursday, 9:00 to 17:00",
    ),
    Question("currency", "Business", "Which currency do you work in?", Kind.TEXT, "e.g. EGP"),
    Question("key_clients", "Business", "Who are your key clients?", Kind.LIST, "One per line."),
    Question("owner_name", "You", "What should M3allema call you?", Kind.TEXT, required=True),
    Question(
        "sign_off", "You", "How do you sign your emails?", Kind.TEXT, "e.g. Best regards, Mona"
    ),
    Question(
        "reply_length",
        "You",
        "Do you prefer short or detailed replies?",
        Kind.CHOICE,
        options=("short", "detailed"),
    ),
    Question(
        "vip_contacts",
        "You",
        "Anyone she must always check with you before writing to?",
        Kind.LIST,
        "One name or email per line.",
    ),
    Question(
        "languages",
        "M3allema",
        "Which languages should she use?",
        Kind.MULTI,
        "She always replies in the language you write in.",
        options=LANGUAGE_CHOICES,
    ),
    Question(
        "tone",
        "M3allema",
        "Describe her tone in a few words.",
        Kind.TEXT,
        "e.g. confident, warm and brief",
    ),
    Question(
        "rules",
        "M3allema",
        "Any house rules?",
        Kind.LIST,
        "One per line, e.g. 'Always CC accounts on invoices'.",
    ),
    Question(
        "tools",
        "Tools and limits",
        "Which tools should she have?",
        Kind.MULTI,
        "Gmail, Calendar and Sheets need 'm3allema google connect' afterwards.",
        options=TOOL_CHOICES,
    ),
    Question(
        "write_mode",
        "Tools and limits",
        "When she creates or changes files:",
        Kind.CHOICE,
        "'ask' waits for your approval.",
        options=("ask", "auto"),
    ),
    Question(
        "external_mode",
        "Tools and limits",
        "When she sends, books or deletes anything outside:",
        Kind.CHOICE,
        "We strongly recommend 'ask'.",
        options=("ask", "deny", "auto"),
    ),
    Question("per_run_usd", "Tools and limits", "Spending limit per task (USD)", Kind.MONEY),
    Question("per_day_usd", "Tools and limits", "Spending limit per day (USD)", Kind.MONEY),
)


def _clean_line(value: str) -> str:
    """Collapse whitespace so an answer cannot add Markdown headings or YAML lines."""
    return " ".join(value.split())


class Answers(BaseModel):
    """Validated answers to :data:`QUESTIONS`."""

    business_name: str = Field(min_length=1, max_length=120)
    offering: str = Field(min_length=1, max_length=1000)
    hours: str = Field(default="", max_length=200)
    currency: str = Field(default="", max_length=20)
    key_clients: list[str] = Field(default_factory=list, max_length=30)
    owner_name: str = Field(min_length=1, max_length=80)
    sign_off: str = Field(default="", max_length=120)
    reply_length: Literal["short", "detailed"] = "short"
    vip_contacts: list[str] = Field(default_factory=list, max_length=30)
    languages: list[str] = Field(default_factory=lambda: list(LANGUAGE_CHOICES))
    tone: str = Field(default="confident, warm and brief", max_length=200)
    rules: list[str] = Field(default_factory=list, max_length=30)
    tools: list[str] = Field(default_factory=lambda: ["files", "excel", "docs", "web"])
    write_mode: Literal["ask", "auto"] = "ask"
    external_mode: Literal["ask", "deny", "auto"] = "ask"
    per_run_usd: float = Field(default=1.0, gt=0, le=1000)
    per_day_usd: float = Field(default=10.0, gt=0, le=10000)

    @field_validator(
        "business_name", "offering", "hours", "currency", "owner_name", "sign_off", "tone"
    )
    @classmethod
    def _one_line(cls, value: str) -> str:
        return _clean_line(value)

    @field_validator("key_clients", "vip_contacts", "rules")
    @classmethod
    def _items(cls, value: list[str]) -> list[str]:
        return [item for item in (_clean_line(v)[:300] for v in value) if item]

    @field_validator("languages")
    @classmethod
    def _languages(cls, value: list[str]) -> list[str]:
        return _only(value, LANGUAGE_CHOICES, "language")

    @field_validator("tools")
    @classmethod
    def _tools(cls, value: list[str]) -> list[str]:
        return _only(value, TOOL_CHOICES, "tool")


def _only(values: list[str], allowed: tuple[str, ...], what: str) -> list[str]:
    unknown = [v for v in values if v not in allowed]
    if unknown:
        raise ValueError(f"unknown {what}: {', '.join(unknown)}")
    return [v for v in allowed if v in values]


def questions_json() -> list[dict[str, Any]]:
    """Return the interview, with defaults, ready to send to an interface."""
    defaults = {
        name: info.get_default(call_default_factory=True)
        for name, info in Answers.model_fields.items()
        if not info.is_required()
    }
    return [q.to_dict(defaults.get(q.id, "")) for q in QUESTIONS]


def needs_onboarding(workspace: Workspace) -> bool:
    """Whether ``BUSINESS.md`` still holds the template placeholder."""
    path = workspace.root / "BUSINESS.md"
    return not path.is_file() or PLACEHOLDER in path.read_text(encoding="utf-8")


def render_markdown(answers: Answers) -> dict[str, str]:
    """Render the four context files, keyed by file name."""
    return {
        "IDENTITY.md": _doc(
            "Identity",
            "Your name is M3allema. You run the back office for this business.",
            [
                f"Tone: {answers.tone or 'confident, warm and brief'}. No filler.",
                f"Languages: {', '.join(answers.languages) or 'English'}. "
                "Always reply in the language the owner uses.",
                "Style: lead with the result, then the details. "
                "Use short lists for multiple items.",
            ],
        ),
        "BUSINESS.md": _doc(
            "Business",
            None,
            [
                f"Name: {answers.business_name}",
                f"What we sell: {answers.offering}",
                f"Working hours: {answers.hours or 'not set'}",
                f"Currency: {answers.currency or 'not set'}",
                f"Key clients: {', '.join(answers.key_clients) or 'none listed'}",
            ],
        ),
        "OWNER.md": _doc(
            "Owner",
            None,
            [
                f"Name: {answers.owner_name}",
                f"Email sign-off: {answers.sign_off or answers.owner_name}",
                f"Prefers replies that are: {answers.reply_length}",
                "VIP contacts (always ask before writing to them): "
                f"{', '.join(answers.vip_contacts) or 'none'}",
            ],
        ),
        "RULES.md": _doc(
            "Rules",
            "<!-- Soft guidance. Hard permissions are enforced in code "
            "(policy.yaml), not here. -->",
            [
                "Keep files you create inside the files/ folder, with clear names.",
                "When summarising documents, quote exact figures "
                "and say which file they came from.",
                *answers.rules,
            ],
        ),
    }


def _doc(title: str, intro: str | None, items: list[str]) -> str:
    parts = [f"# {title}", ""]
    if intro:
        parts += [intro, ""]
    parts += [f"- {item}" for item in items]
    return "\n".join(parts) + "\n"


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """What :func:`apply_answers` did.

    Attributes:
        changed: Files that were written.
        skipped: Settings that could not be placed because the owner changed
            the file's layout; they are listed so the owner can set them by hand.
        backup_dir: Where the previous versions were copied.

    """

    changed: tuple[str, ...]
    skipped: tuple[str, ...]
    backup_dir: Path


def apply_answers(workspace: Workspace, answers: Answers) -> ApplyResult:
    """Write the answers into the workspace, backing up every file first."""
    backup_dir = workspace.state_dir / "backups" / datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    updates = render_markdown(answers)
    skipped: list[str] = []

    config, missed = _set_lines(
        _read(workspace.config_path),
        {"builtin_tools:" + _VALUE: f"builtin_tools: [{', '.join(answers.tools)}]"},
    )
    updates[workspace.config_path.name] = config
    skipped += [f"config.yaml: {m}" for m in missed]

    policy, missed = _set_lines(
        _read(workspace.policy_path),
        {
            "  write:" + _VALUE: f"  write: {answers.write_mode}",
            "  external:" + _VALUE: f"  external: {answers.external_mode}",
            "  per_run_usd:" + _VALUE: f"  per_run_usd: {answers.per_run_usd:.2f}",
            "  per_day_usd:" + _VALUE: f"  per_day_usd: {answers.per_day_usd:.2f}",
        },
    )
    updates[workspace.policy_path.name] = policy
    skipped += [f"policy.yaml: {m}" for m in missed]

    changed: list[str] = []
    for name, text in updates.items():
        path = workspace.root / name
        if path.is_file():
            if path.read_text(encoding="utf-8") == text:
                continue
            shutil.copy2(path, backup_dir / name)
        path.write_text(text, encoding="utf-8")
        changed.append(name)
    return ApplyResult(tuple(changed), tuple(skipped), backup_dir)


_VALUE = r"[^#\n]*?"
"""Regex for a YAML value up to (not including) a trailing comment."""


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _set_lines(text: str, replacements: dict[str, str]) -> tuple[str, list[str]]:
    """Replace the first line matching each pattern, keeping trailing comments.

    Returns the new text and the replacement lines that found no match.
    """
    missed: list[str] = []
    for pattern, line in replacements.items():
        regex = re.compile(rf"^{pattern}(?P<comment>\s+#.*)?$", re.MULTILINE)
        match = regex.search(text)
        if match is None:
            missed.append(line.strip())
            continue
        comment = match.group("comment") or ""
        text = text[: match.start()] + line + comment + text[match.end() :]
    return text, missed
