from pathlib import Path

from m3allema.domain.events import RunFinished, RunStarted, TextDelta, ToolCallStarted
from m3allema.domain.messages import ToolCall, Usage
from m3allema.storage.database import Database
from m3allema.storage.event_store import EventStore


def test_runs_and_events_are_recorded_in_order(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    store = EventStore(database)
    store.record("r1", RunStarted("r1", "chase invoices", "claude/opus"))
    store.record("r1", TextDelta("streaming text is not stored"))
    store.record("r1", ToolCallStarted(ToolCall("c1", "files__read_file", {"path": "a"})))
    store.record("r1", RunFinished("r1", "completed", "Done.", Usage(100, 20), steps=2))

    run = store.get_run("r1")
    assert run is not None
    assert (run.status, run.input_tokens, run.steps) == ("completed", 100, 2)

    events = store.list_events("r1")
    assert [e.kind for e in events] == ["run_started", "tool_call_started", "run_finished"]
    assert [e.seq for e in events] == [1, 2, 3]
    assert events[1].payload["call"]["arguments"] == {"path": "a"}
    assert store.list_runs()[0].id == "r1"
    database.close()
