from pathlib import Path

import pytest

from fakes import READ_TOOL, SEND_TOOL, FakeTools, ScriptedProvider, turn
from m3allema.agent.loop import Agent
from m3allema.agent.permissions import PolicyGate
from m3allema.config.loader import ConfigError
from m3allema.config.models import AgentSettings
from m3allema.config.policy import Budget, Mode, Policy, load_policy
from m3allema.domain.events import RunFinished
from m3allema.domain.messages import ToolCall, Usage
from m3allema.domain.tools import Risk, ToolSpec
from m3allema.providers.factory import ResolvedModel
from m3allema.providers.pricing import PriceBook

WRITE_TOOL = ToolSpec("files__write_file", "Write", risk=Risk.WRITE)


@pytest.mark.parametrize(
    ("spec", "expected"),
    [(READ_TOOL, Mode.AUTO), (WRITE_TOOL, Mode.ASK), (SEND_TOOL, Mode.ASK)],
)
def test_default_policy_only_reads_run_alone(spec: ToolSpec, expected: Mode) -> None:
    assert Policy().mode_for(spec) is expected


def test_tool_patterns_override_risk_defaults_first_match_wins() -> None:
    policy = Policy(tools={"files__*": Mode.AUTO, "files__write_file": Mode.DENY})
    assert policy.mode_for(WRITE_TOOL) is Mode.AUTO


async def test_deny_never_asks_the_approver() -> None:
    asked: list[str] = []

    async def approver(call: ToolCall, spec: ToolSpec) -> bool:
        asked.append(call.name)
        return True

    gate = PolicyGate(Policy(tools={"gmail__*": Mode.DENY}), approver)
    decision = await gate.check(ToolCall("c", "gmail__send", {}), SEND_TOOL)
    assert not decision.allowed
    assert asked == []


def test_missing_policy_file_means_safe_defaults(tmp_path: Path) -> None:
    assert load_policy(tmp_path / "policy.yaml") == Policy()


def test_invalid_policy_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text("defaults: {read: maybe}\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_policy(path)


def test_price_book_uses_cache_rates_and_overrides() -> None:
    book = PriceBook()
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000, cache_read_tokens=1_000_000)
    assert book.cost("claude-opus-5-5", usage) == pytest.approx(4.0 + 20.0 + 0.20)
    assert book.cost("unknown-model", usage) is None


def priced_agent(provider: ScriptedProvider, budget: Budget, spent: float = 0.0) -> Agent:
    return Agent(
        model=ResolvedModel("claude/claude-opus-5-5", provider, "claude-opus-5-5"),
        tools=FakeTools([READ_TOOL]),
        gate=PolicyGate(),
        system_prompt="s",
        settings=AgentSettings(),
        budget=budget,
        spent_today=lambda: spent,
    )


async def test_run_stops_when_its_budget_is_reached() -> None:
    call = ToolCall("c", "files__read_file", {})
    # Each fake turn costs 10 in + 5 out tokens on Opus 5.5 = $0.00014.
    provider = ScriptedProvider(*(turn("", call) for _ in range(5)))
    agent = priced_agent(provider, Budget(per_run_usd=0.0002))
    events = [e async for e in agent.run("loop")]
    finished = events[-1]
    assert isinstance(finished, RunFinished)
    assert finished.status == "budget"
    assert finished.steps == 2
    assert finished.cost_usd == pytest.approx(0.00028)


async def test_daily_budget_blocks_before_any_model_call() -> None:
    provider = ScriptedProvider(turn("unused"))
    agent = priced_agent(provider, Budget(per_day_usd=5.0), spent=5.0)
    events = [e async for e in agent.run("hi")]
    assert isinstance(events[-1], RunFinished)
    assert events[-1].status == "budget"
    assert provider.requests == []
