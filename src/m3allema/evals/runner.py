"""Run eval cases in throwaway workspaces and report the pass rate."""

from __future__ import annotations

import shutil
import tempfile
import time
from collections import defaultdict
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openpyxl import Workbook

from m3allema import __version__
from m3allema.domain.events import RunFinished, ToolCallFinished
from m3allema.domain.messages import ToolCall
from m3allema.domain.tools import ToolSpec
from m3allema.evals.cases import EvalCase, Outcome, evaluate
from m3allema.runtime import Session, open_session
from m3allema.workspace.workspace import Workspace

SessionFactory = Callable[..., AbstractAsyncContextManager[Session]]

COPIED_FROM_BASE = ("config.yaml", ".env")
"""Only the model setup comes from the owner's workspace; everything else is fresh."""


@dataclass(frozen=True, slots=True)
class CaseResult:
    """The outcome of one case."""

    id: str
    category: str
    passed: bool
    failures: list[str]
    status: str
    answer: str
    tools_run: list[str]
    approvals: list[str]
    cost_usd: float | None
    seconds: float

    def to_dict(self) -> dict[str, Any]:
        """JSON form for the report file."""
        return {
            "id": self.id,
            "category": self.category,
            "passed": self.passed,
            "failures": self.failures,
            "status": self.status,
            "tools_run": self.tools_run,
            "approvals": self.approvals,
            "cost_usd": self.cost_usd,
            "seconds": round(self.seconds, 1),
            "answer": self.answer[:2000],
        }


@dataclass
class SuiteReport:
    """Every case result, with summaries."""

    model: str
    results: list[CaseResult] = field(default_factory=list)
    planned: int = 0
    stopped: str | None = None
    """Why the suite stopped early (for example a provider quota); the result is incomplete."""

    @property
    def passed(self) -> int:
        """Number of passing cases."""
        return sum(r.passed for r in self.results)

    @property
    def pass_rate(self) -> float:
        """Share of cases that passed, 0 to 1."""
        return self.passed / len(self.results) if self.results else 0.0

    def by_category(self) -> dict[str, tuple[int, int]]:
        """Category to (passed, total)."""
        totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for result in self.results:
            totals[result.category][0] += result.passed
            totals[result.category][1] += 1
        return {name: (p, t) for name, (p, t) in sorted(totals.items())}

    def total_cost(self) -> float | None:
        """Total price, or ``None`` if any case's price was unknown."""
        costs = [r.cost_usd for r in self.results]
        return None if any(c is None for c in costs) else sum(c for c in costs if c is not None)

    def to_dict(self) -> dict[str, Any]:
        """JSON form, suitable for publishing."""
        return {
            "m3allema": __version__,
            "model": self.model,
            "passed": self.passed,
            "total": len(self.results),
            "pass_rate": round(self.pass_rate, 4),
            "complete": self.stopped is None,
            "stopped": self.stopped,
            "cost_usd": self.total_cost(),
            "categories": {
                k: {"passed": p, "total": t} for k, (p, t) in self.by_category().items()
            },
            "cases": [r.to_dict() for r in self.results],
        }

    def to_markdown(self) -> str:
        """Render a short table for the README or a release note."""
        lines = []
        if self.stopped:
            lines += [
                f"**INCOMPLETE: stopped after {len(self.results)} of {self.planned} cases.** "
                f"{self.stopped} Do not publish this result.",
                "",
            ]
        lines += [
            f"**{self.passed}/{len(self.results)} passed ({self.pass_rate:.0%})** "
            f"with `{self.model}`, M3allema {__version__}",
            "",
            "| Category | Passed |",
            "|---|---|",
        ]
        lines += [f"| {name} | {p}/{t} |" for name, (p, t) in self.by_category().items()]
        failed = [r for r in self.results if not r.passed]
        if failed:
            lines += ["", "Failed:", ""]
            lines += [f"- `{r.id}`: {'; '.join(r.failures)}" for r in failed]
        return "\n".join(lines) + "\n"


def _ran(event: ToolCallFinished) -> bool:
    """Whether the tool actually executed (not declined, denied or rejected before running)."""
    result = event.result
    return not (result.is_error and result.content.startswith(NOT_RUN_PREFIXES))


NOT_RUN_PREFIXES = ("Not run:", "Unknown tool", "The arguments were not valid JSON")


def prepare_workspace(case: EvalCase, base: Workspace, target: Path) -> Workspace:
    """Create a fresh workspace with the base's model setup and the case's files."""
    workspace = Workspace.create(target)
    for name in COPIED_FROM_BASE:
        source = base.root / name
        if source.is_file():
            shutil.copy2(source, workspace.root / name)
    for relative, text in case.files.items():
        path = workspace.files_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for relative, rows in case.sheets.items():
        path = workspace.files_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        book = Workbook()
        sheet = book.active
        assert sheet is not None  # noqa: S101 - a new workbook always has one sheet
        for row in rows:
            sheet.append(row)
        book.save(path)
    return workspace


async def run_case(
    case: EvalCase, base: Workspace, *, session_factory: SessionFactory = open_session
) -> CaseResult:
    """Run one case in a temporary workspace and check the outcome."""
    approvals: list[str] = []
    allow = case.approvals == "approve"

    async def approver(call: ToolCall, spec: ToolSpec) -> bool:
        approvals.append(call.name)
        return allow

    with tempfile.TemporaryDirectory(prefix="m3allema-eval-") as folder:
        workspace = prepare_workspace(case, base, Path(folder) / "ws")
        started = time.monotonic()
        tools_run: list[str] = []
        finished: RunFinished | None = None
        failure: str | None = None
        try:
            async with session_factory(workspace.root, approver=approver) as session:
                async for event in session.agent.run(case.task):
                    if isinstance(event, ToolCallFinished) and _ran(event):
                        tools_run.append(event.call.name)
                    elif isinstance(event, RunFinished):
                        finished = event
        except Exception as exc:  # a crash is a failed case, not a crashed suite
            failure = f"crashed: {type(exc).__name__}: {exc}"
        outcome = Outcome(
            files_root=workspace.files_dir,
            status=finished.status if finished else "crashed",
            answer=finished.answer if finished else "",
            tools_run=tools_run,
            approvals=approvals,
        )
        failures = [failure] if failure else []
        failures += [f for check in case.checks if (f := evaluate(check, outcome)) is not None]
        return CaseResult(
            id=case.id,
            category=case.category,
            passed=not failures,
            failures=failures,
            status=outcome.status,
            answer=outcome.answer,
            tools_run=outcome.tools_run,
            approvals=approvals,
            cost_usd=finished.cost_usd if finished else None,
            seconds=time.monotonic() - started,
        )


async def run_suite(
    cases: list[EvalCase],
    base: Workspace,
    model: str,
    *,
    session_factory: SessionFactory = open_session,
    on_result: Callable[[CaseResult], None] | None = None,
) -> SuiteReport:
    """Run the cases one after another (runs share the owner's rate limits)."""
    report = SuiteReport(model, planned=len(cases))
    for case in cases:
        result = await run_case(case, base, session_factory=session_factory)
        if _out_of_quota(result):
            # The model was never really tested; counting this as a failure would publish
            # a meaningless score. Stop and say why.
            report.stopped = (
                f"The provider's usage limit was reached during {case.id!r}: {result.answer}"
            )
            break
        report.results.append(result)
        if on_result is not None:
            on_result(result)
    return report


_QUOTA_MARKERS = ("429", "rate limit", "quota", "tokens per day", "insufficient_quota")


def _out_of_quota(result: CaseResult) -> bool:
    """Whether the run failed because the provider refused on usage limits."""
    answer = result.answer.lower()
    return result.status == "failed" and any(marker in answer for marker in _QUOTA_MARKERS)
