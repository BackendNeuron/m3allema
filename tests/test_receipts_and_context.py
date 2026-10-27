from pathlib import Path

from m3allema.agent.context import OutputArchive
from m3allema.agent.sinks import FanOutSink, ReceiptWriter
from m3allema.domain.events import AgentEvent, RunFinished, RunStarted, ToolCallFinished
from m3allema.domain.messages import ToolCall, ToolResult, Usage


def test_receipt_lists_actions_cost_and_what_needs_the_owner(tmp_path: Path) -> None:
    written: list[Path] = []
    writer = ReceiptWriter(tmp_path / "receipts", written.append)
    read = ToolCall("c1", "files__read_file", {"path": "invoices.csv"})
    send = ToolCall("c2", "gmail__send", {"to": "client@example.com"})
    writer.record("run12345", RunStarted("run12345", "Chase invoices", "claude/opus"))
    writer.record("run12345", ToolCallFinished(read, ToolResult("c1", "rows"), 12, "read"))
    writer.record(
        "run12345",
        ToolCallFinished(
            send, ToolResult("c2", "Not run: declined by the owner.", True), 3, "external"
        ),
    )
    writer.record(
        "run12345",
        RunFinished("run12345", "completed", "Drafted 6 reminders.", Usage(1200, 300), 3, 0.0123),
    )

    assert len(written) == 1
    text = written[0].read_text(encoding="utf-8")
    assert "**Task:** Chase invoices" in text
    assert "$0.0123" in text
    assert "| 1 | `files__read_file` | read | done (12 ms) |" in text
    assert "| 2 | `gmail__send` | external | not run |" in text
    assert "## Needs you" in text


def test_fan_out_forwards_to_every_sink() -> None:
    seen: list[str] = []

    class Sink:
        def __init__(self, name: str) -> None:
            self.name = name

        def record(self, run_id: str, event: AgentEvent) -> None:
            seen.append(self.name)

    FanOutSink([Sink("a"), Sink("b")]).record("r", RunStarted("r", "t", "m"))
    assert seen == ["a", "b"]


def test_archive_keeps_small_output_and_saves_large_output(tmp_path: Path) -> None:
    archive = OutputArchive(tmp_path / "_tool_outputs", tmp_path, inline_chars=10)
    assert archive.fit("c1", "web__fetch_url", "short") == "short"

    preview = archive.fit("c/2", "web__fetch_url", "x" * 50)
    assert preview.startswith("x" * 10)
    assert "_tool_outputs/web__fetch_url-c_2.txt" in preview
    saved = tmp_path / "_tool_outputs" / "web__fetch_url-c_2.txt"
    assert saved.read_text(encoding="utf-8") == "x" * 50
