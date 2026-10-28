"""The eval suite: case files, checks, and the runner with a scripted session."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from m3allema.domain.events import RunFinished, ToolCallFinished
from m3allema.domain.messages import ToolCall, ToolResult, Usage
from m3allema.domain.tools import Risk, ToolSpec
from m3allema.evals import load_cases, run_suite
from m3allema.evals.cases import EvalCase, Outcome, evaluate
from m3allema.workspace.workspace import Workspace

WRITE = ToolSpec("files__write_file", "Write", risk=Risk.WRITE)


def test_builtin_suite_loads_and_covers_every_category() -> None:
    cases = load_cases()
    assert len(cases) >= 12
    assert {c.category for c in cases} >= {"safety", "permissions", "language", "documents"}
    assert len({c.id for c in cases}) == len(cases)
    assert load_cases(only="safety")
    assert all(c.category == "safety" for c in load_cases(only="safety"))


def test_typography_does_not_fail_a_correct_answer(tmp_path: Path) -> None:
    outcome = Outcome(
        files_root=tmp_path,
        status="completed",
        answer=(
            f"I couldn{chr(0x2019)}t find INV{chr(0x2011)}900. "
            f"Top client: Cairo{chr(0x202F)}Hotel, 13{chr(0xA0)}000 EGP"
        ),
    )
    checks = EvalCase.model_validate(
        {
            "id": "t",
            "category": "c",
            "task": "t",
            "checks": [
                {"type": "answer_matches", "pattern": "(?i)couldn't find"},
                {"type": "answer_contains", "values": ["INV-900", "Cairo Hotel"]},
                {"type": "answer_matches", "pattern": "13[,. ]?000"},
            ],
        }
    ).checks
    assert [evaluate(check, outcome) for check in checks] == [None, None, None]


def test_checks(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("Total 7,750 EGP", encoding="utf-8")
    outcome = Outcome(
        files_root=tmp_path,
        status="completed",
        answer="المجموع 4 فواتير",
        tools_run=["files__read_file"],
        approvals=["memory__remember"],
    )
    case = EvalCase.model_validate(
        {
            "id": "x",
            "category": "c",
            "task": "t",
            "checks": [
                {"type": "file_contains", "path": "a.txt", "values": ["7,750"]},
                {"type": "file_absent", "path": "b.txt"},
                {"type": "tool_called", "tool": "files__*"},
                {"type": "tool_not_called", "tool": "gmail__*"},
                {"type": "approval_asked", "tool": "memory__remember"},
                {"type": "answer_matches", "pattern": "[؀-ۿ]"},
                {"type": "status", "status": "completed"},
            ],
        }
    )
    assert [evaluate(check, outcome) for check in case.checks] == [None] * 7
    # An approval request counts as an attempt even when it was declined.
    refused = EvalCase.model_validate(
        {
            "id": "y",
            "category": "c",
            "task": "t",
            "checks": [{"type": "tool_not_called", "tool": "memory__*"}],
        }
    )
    assert evaluate(refused.checks[0], outcome) == "memory__* was attempted"


def scripted_factory(declined: bool) -> Any:
    """A session whose agent asks to write a file, then reports what happened."""

    @asynccontextmanager
    async def factory(root: Path, *, approver: Any) -> AsyncIterator[Any]:
        files = Workspace.open(root).files_dir

        async def run(task: str) -> AsyncIterator[Any]:
            call = ToolCall("c1", WRITE.name, {"path": "out.txt"})
            if await approver(call, WRITE):
                (files / "out.txt").write_text("done", encoding="utf-8")
                result = ToolResult("c1", "written")
            else:
                result = ToolResult("c1", "Not run: declined by the owner.", is_error=True)
            yield ToolCallFinished(call, result, 5)
            yield RunFinished("r", "completed", "All done.", Usage(), 2, 0.01)

        yield SimpleNamespace(agent=SimpleNamespace(run=run))

    return factory


async def test_runner_scores_cases(tmp_path: Path) -> None:
    base = Workspace.create(tmp_path / "base")
    approve = EvalCase.model_validate(
        {
            "id": "writes",
            "category": "permissions",
            "task": "write",
            "files": {"in/a.txt": "hello"},
            "sheets": {"s.xlsx": [["Client", "Amount"], ["Nour", 5]]},
            "checks": [
                {"type": "file_exists", "path": "out.txt"},
                {"type": "file_contains", "path": "s.xlsx", "values": ["Nour"]},
                {"type": "tool_called", "tool": "files__write_file"},
            ],
        }
    )
    decline = approve.model_copy(update={"id": "declined", "approvals": "decline"})
    report = await run_suite(
        [approve], base, "fake/model", session_factory=scripted_factory(declined=False)
    )
    assert report.passed == 1
    assert report.results[0].approvals == ["files__write_file"]

    declined_report = await run_suite(
        [decline], base, "fake/model", session_factory=scripted_factory(declined=True)
    )
    result = declined_report.results[0]
    assert not result.passed
    assert result.tools_run == [], "a declined call does not count as run"
    assert any("out.txt missing" in f for f in result.failures)
    summary = declined_report.to_dict()
    assert summary["pass_rate"] == 0
    assert summary["categories"] == {"permissions": {"passed": 0, "total": 1}}
    assert "Failed" in declined_report.to_markdown()


async def test_a_crash_fails_one_case_not_the_suite(tmp_path: Path) -> None:
    @asynccontextmanager
    async def broken(root: Path, *, approver: Any) -> AsyncIterator[Any]:
        raise RuntimeError("provider down")
        yield  # pragma: no cover

    case = EvalCase.model_validate(
        {"id": "c", "category": "x", "task": "t", "checks": [{"type": "status"}]}
    )
    report = await run_suite([case, case], Workspace.create(tmp_path), "m", session_factory=broken)
    assert len(report.results) == 2
    assert report.results[0].status == "crashed"
    assert "provider down" in report.results[0].failures[0]
