"""Memory (MEMORY.md) and skills (skills/*.md): files, tools, prompt and policy."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from m3allema.config.policy import Mode, load_policy
from m3allema.domain.tools import Risk, ToolSpec
from m3allema.tools.hub import ToolHub
from m3allema.tools.servers import ToolContext
from m3allema.workspace.memory import MemoryBook, MemoryBookError
from m3allema.workspace.prompt import PromptBuilder
from m3allema.workspace.skills import Skill, SkillError, SkillLibrary, parse_skill
from m3allema.workspace.workspace import Workspace


def test_memory_appends_dated_facts_and_keeps_other_lines(tmp_path: Path) -> None:
    (tmp_path / "MEMORY.md").write_text("# Memory\n\nOwner note: keep this.\n", encoding="utf-8")
    book = MemoryBook(tmp_path)
    book.remember("Cairo Hotel pays  net 30", today=date(2026, 10, 28))
    book.remember("cairo hotel pays net 30")  # duplicate, ignored
    book.remember("Prices include VAT")
    assert [f.text for f in book.facts()] == ["Cairo Hotel pays net 30", "Prices include VAT"]
    text = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "- (2026-10-28) Cairo Hotel pays net 30" in text

    assert [f.text for f in book.forget("VAT")] == ["Prices include VAT"]
    assert "Owner note: keep this." in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")


def test_memory_refuses_empty_long_and_unknown(tmp_path: Path) -> None:
    book = MemoryBook(tmp_path)
    with pytest.raises(MemoryBookError):
        book.remember("   ")
    with pytest.raises(MemoryBookError):
        book.remember("x" * 301)
    with pytest.raises(MemoryBookError):
        book.forget("nothing")


def test_skill_files_parse_and_save(tmp_path: Path) -> None:
    library = SkillLibrary(tmp_path)
    library.save(Skill("monthly-report", "Monthly sales report.", "1. Read sales.xlsx"))
    skill = library.get("monthly-report")
    assert skill.description == "Monthly sales report."
    assert skill.steps == "1. Read sales.xlsx"
    assert library.index() == "- monthly-report: Monthly sales report."
    with pytest.raises(SkillError):
        library.save(Skill("monthly-report", "again", "steps"))


def test_skill_without_front_matter_uses_first_line() -> None:
    skill = parse_skill("quick", "# Do the quick thing\n1. Step")
    assert skill.description == "Do the quick thing"


@pytest.mark.parametrize("name", ["../evil", "Bad Name", "a", "x/y", "-lead"])
def test_skill_names_cannot_escape_the_folder(tmp_path: Path, name: str) -> None:
    with pytest.raises(SkillError):
        SkillLibrary(tmp_path).save(Skill(name, "d", "s"))


def test_new_workspace_has_starter_skills_and_safe_policy(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)
    names = {s.name for s in SkillLibrary(workspace.root).list()}
    assert {"invoice-summary", "inbox-triage", "client-follow-up"} <= names
    assert all(s.description for s in SkillLibrary(workspace.root).list())
    assert "MEMORY.md" in workspace.read_context()
    policy = load_policy(workspace.policy_path)
    assert policy.mode_for(ToolSpec("memory__remember", "", risk=Risk.WRITE)) is Mode.ASK
    assert policy.mode_for(ToolSpec("skills__save_skill", "", risk=Risk.WRITE)) is Mode.ASK


def test_prompt_lists_skills() -> None:
    prompt = PromptBuilder().build({}, "- invoice-summary: Summarise invoices.")
    assert "- invoice-summary: Summarise invoices.\n</skills>" in prompt
    assert "skills__read_skill" in prompt.split("<skills>")[1]
    assert "Skills first" in prompt, "the rule is stated up front"
    assert "</skills>" not in PromptBuilder().build({}, ""), "no empty skills block"


async def test_memory_and_skills_tools(tmp_path: Path) -> None:
    context = ToolContext(tmp_path / "files", workspace_root=tmp_path)
    async with ToolHub.from_config(["memory", "skills"], {}, context) as hub:
        risks = {spec.name: spec.risk for spec in hub.specs()}
        assert risks["memory__remember"] is Risk.WRITE
        assert risks["memory__forget"] is Risk.EXTERNAL
        assert risks["skills__read_skill"] is Risk.READ
        assert risks["skills__save_skill"] is Risk.WRITE

        saved = await hub.call("memory__remember", {"fact": "Owner prefers Arabic"})
        assert not saved.is_error
        assert MemoryBook(tmp_path).facts()[0].text == "Owner prefers Arabic"

        args = {"name": "weekly-check", "description": "Weekly check.", "steps": "1. Look"}
        assert not (await hub.call("skills__save_skill", args)).is_error
        read = await hub.call("skills__read_skill", {"name": "weekly-check"})
        assert "1. Look" in read.content
        missing = await hub.call("skills__read_skill", {"name": "nope-skill"})
        assert missing.is_error
