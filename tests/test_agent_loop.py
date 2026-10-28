import pytest

from fakes import READ_TOOL, SEND_TOOL, FakeTools, ScriptedProvider, turn
from m3allema.agent import loop as loop_module
from m3allema.agent.loop import Agent
from m3allema.agent.permissions import PolicyGate
from m3allema.config.models import AgentSettings
from m3allema.domain.events import AgentEvent, RunFinished, ToolCallFinished
from m3allema.domain.messages import StopReason, ToolCall, ToolResultMessage, UserMessage
from m3allema.domain.tools import ToolSpec
from m3allema.providers.base import INVALID_ARGUMENTS_KEY, InvalidToolCallError, ProviderError
from m3allema.providers.factory import ResolvedModel


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, AgentEvent]] = []

    def record(self, run_id: str, event: AgentEvent) -> None:
        self.events.append((run_id, event))


def make_agent(
    provider: ScriptedProvider,
    tools: FakeTools,
    *,
    gate: PolicyGate | None = None,
    fallback: ScriptedProvider | None = None,
    max_steps: int = 10,
    sink: RecordingSink | None = None,
) -> Agent:
    return Agent(
        model=ResolvedModel("fake/main", provider, "main"),
        fallback=ResolvedModel("fake/backup", fallback, "backup") if fallback else None,
        tools=tools,
        gate=gate or PolicyGate(),
        system_prompt="system",
        settings=AgentSettings(max_steps=max_steps),
        sink=sink,
        new_id=lambda: "run-1",
    )


async def collect(agent: Agent, task: str) -> list[AgentEvent]:
    return [event async for event in agent.run(task)]


def finished(events: list[AgentEvent]) -> RunFinished:
    last = events[-1]
    assert isinstance(last, RunFinished)
    return last


async def test_plain_answer_completes_in_one_step() -> None:
    agent = make_agent(ScriptedProvider(turn("Hello!")), FakeTools([]))
    result = finished(await collect(agent, "hi"))
    assert (result.status, result.answer, result.steps) == ("completed", "Hello!", 1)


async def test_an_empty_reply_is_nudged_once_and_not_kept() -> None:
    provider = ScriptedProvider(turn(""), turn("13,000 EGP"))
    agent = make_agent(provider, FakeTools([]))
    result = finished(await collect(agent, "total?"))
    assert (result.status, result.answer, result.steps) == ("completed", "13,000 EGP", 2)
    second = provider.requests[1].messages
    nudge = second[-1]
    assert isinstance(nudge, UserMessage)
    assert "empty" in nudge.text, "the model is asked to continue"
    assert all(getattr(m, "blocks", True) for m in second), "no empty assistant turn is kept"


async def test_a_second_empty_reply_ends_the_run() -> None:
    agent = make_agent(ScriptedProvider(turn(""), turn("")), FakeTools([]))
    result = finished(await collect(agent, "total?"))
    assert (result.status, result.answer, result.steps) == ("completed", "", 2)


async def test_tool_call_runs_and_result_goes_back_to_model() -> None:
    call = ToolCall("c1", "files__read_file", {"path": "a.txt"})
    provider = ScriptedProvider(turn("", call), turn("The file says ok."))
    tools = FakeTools([READ_TOOL], {"files__read_file": "contents"})
    events = await collect(make_agent(provider, tools), "read a.txt")

    assert tools.calls == [("files__read_file", {"path": "a.txt"})]
    second_request = provider.requests[1]
    results = second_request.messages[-1]
    assert isinstance(results, ToolResultMessage)
    assert results.results[0].content == "contents"
    assert finished(events).usage.input_tokens == 20


async def test_risky_call_is_declined_without_approver_and_model_is_told() -> None:
    call = ToolCall("c1", "gmail__send", {"to": "x@example.com"})
    provider = ScriptedProvider(turn("", call), turn("I did not send it."))
    tools = FakeTools([SEND_TOOL])
    events = await collect(make_agent(provider, tools), "email them")

    assert tools.calls == []
    result = next(e for e in events if isinstance(e, ToolCallFinished)).result
    assert result.is_error
    assert result.content.startswith("Not run: needs approval")


async def test_approver_can_allow_a_risky_call() -> None:
    async def approve(call: ToolCall, spec: ToolSpec) -> bool:
        return True

    call = ToolCall("c1", "gmail__send", {})
    provider = ScriptedProvider(turn("", call), turn("Sent."))
    tools = FakeTools([SEND_TOOL])
    gate = PolicyGate(approver=approve)
    await collect(make_agent(provider, tools, gate=gate), "send")
    assert tools.calls == [("gmail__send", {})]


async def test_unknown_tool_and_invalid_arguments_become_errors() -> None:
    calls = (
        ToolCall("c1", "nope__tool", {}),
        ToolCall("c2", "files__read_file", {INVALID_ARGUMENTS_KEY: "{bad"}),
    )
    provider = ScriptedProvider(turn("", *calls), turn("Sorry."))
    tools = FakeTools([READ_TOOL])
    events = await collect(make_agent(provider, tools), "go")

    errors = [e.result for e in events if isinstance(e, ToolCallFinished)]
    assert all(r.is_error for r in errors)
    assert tools.calls == []


async def test_stops_at_max_steps() -> None:
    call = ToolCall("c", "files__read_file", {})
    provider = ScriptedProvider(*(turn("", call) for _ in range(3)))
    result = finished(
        await collect(make_agent(provider, FakeTools([READ_TOOL]), max_steps=3), "loop")
    )
    assert (result.status, result.steps) == ("max_steps", 3)


async def test_truncated_tool_call_is_not_run_and_history_stays_valid() -> None:
    call = ToolCall("c1", "files__read_file", {"path": "a"})
    provider = ScriptedProvider(turn("", call, stop=StopReason.MAX_TOKENS))
    tools = FakeTools([READ_TOOL])
    agent = make_agent(provider, tools)
    result = finished(await collect(agent, "go"))

    assert result.status == "truncated"
    assert tools.calls == []
    assert isinstance(agent.history[-1], ToolResultMessage)


async def test_falls_back_on_retryable_error() -> None:
    main = ScriptedProvider(ProviderError("overloaded", retryable=True))
    backup = ScriptedProvider(turn("From backup."))
    result = finished(await collect(make_agent(main, FakeTools([]), fallback=backup), "hi"))
    assert result.answer == "From backup."


async def test_non_retryable_error_fails_the_run_cleanly() -> None:
    main = ScriptedProvider(ProviderError("bad request", retryable=False))
    backup = ScriptedProvider(turn("unused"))
    result = finished(await collect(make_agent(main, FakeTools([]), fallback=backup), "hi"))
    assert result.status == "failed"
    assert backup.requests == []


async def test_without_fallback_a_transient_error_is_retried_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(loop_module, "RETRY_DELAY_S", 0)
    main = ScriptedProvider(ProviderError("timed out", retryable=True), turn("Recovered."))
    result = finished(await collect(make_agent(main, FakeTools([])), "hi"))
    assert (result.status, result.answer) == ("completed", "Recovered.")

    twice = ScriptedProvider(
        ProviderError("timed out", retryable=True), ProviderError("timed out", retryable=True)
    )
    failed = finished(await collect(make_agent(twice, FakeTools([])), "hi"))
    assert failed.status == "failed"
    assert "timed out" in failed.answer


async def test_a_rejected_tool_call_is_explained_and_retried() -> None:
    provider = ScriptedProvider(
        InvalidToolCallError("attempted to call tool 'files__write_docx'"), turn("Done.")
    )
    result = finished(await collect(make_agent(provider, FakeTools([])), "write it"))
    assert (result.status, result.answer) == ("completed", "Done.")
    feedback = provider.requests[1].messages[-1]
    assert isinstance(feedback, UserMessage)
    assert "files__write_docx" in feedback.text


async def test_repeated_rejected_tool_calls_end_the_run_cleanly() -> None:
    errors = [InvalidToolCallError("bad JSON") for _ in range(3)]
    result = finished(await collect(make_agent(ScriptedProvider(*errors), FakeTools([])), "x"))
    assert result.status == "failed"


async def test_every_event_reaches_the_sink_and_history_persists() -> None:
    sink = RecordingSink()
    provider = ScriptedProvider(turn("One."), turn("Two."))
    agent = make_agent(provider, FakeTools([]), sink=sink)
    await collect(agent, "first")
    await collect(agent, "second")

    assert {run_id for run_id, _ in sink.events} == {"run-1"}
    assert len(provider.requests[1].messages) == 3  # user, assistant, user
