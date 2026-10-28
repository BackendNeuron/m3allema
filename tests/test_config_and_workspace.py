from pathlib import Path

import pytest

from m3allema.config.loader import ConfigError, load_config, resolve_env_refs
from m3allema.workspace.prompt import PromptBuilder
from m3allema.workspace.workspace import Workspace, WorkspaceError

CONFIG = """
providers:
  claude: {type: anthropic, api_key: env:TEST_KEY}
models:
  main: claude/claude-opus-5-5
"""


def write_config(tmp_path: Path, text: str = CONFIG) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_env_refs_resolve_recursively() -> None:
    data = {"a": "env:X", "b": ["env:X", 1], "c": "plain"}
    assert resolve_env_refs(data, {"X": "secret"}) == {
        "a": "secret",
        "b": ["secret", 1],
        "c": "plain",
    }


def test_missing_env_var_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="TEST_KEY"):
        load_config(write_config(tmp_path), environ={})


def test_valid_config_loads(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path), environ={"TEST_KEY": "k"})
    assert config.providers["claude"].api_key == "k"
    assert config.builtin_tools == ["files", "excel", "docs", "web", "memory", "skills"]


@pytest.mark.parametrize(
    ("models", "message"),
    [("main: other/model", "unknown provider"), ("main: no-slash", "provider/model")],
)
def test_bad_model_refs_are_rejected(tmp_path: Path, models: str, message: str) -> None:
    text = CONFIG.replace("main: claude/claude-opus-5-5", models)
    with pytest.raises(ConfigError, match=message):
        load_config(write_config(tmp_path, text), environ={"TEST_KEY": "k"})


def test_unknown_keys_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="typo"):
        load_config(write_config(tmp_path, CONFIG + "typo: 1\n"), environ={"TEST_KEY": "k"})


def test_workspace_create_open_and_context(tmp_path: Path) -> None:
    created = Workspace.create(tmp_path / "shop")
    (created.root / "RULES.md").write_text("Always be kind.", encoding="utf-8")

    opened = Workspace.open(tmp_path / "shop")
    context = opened.read_context()
    assert list(context) == ["IDENTITY.md", "BUSINESS.md", "OWNER.md", "RULES.md", "MEMORY.md"]
    assert opened.files_dir.is_dir()

    prompt = PromptBuilder().build(context)
    assert '<workspace_file name="RULES.md">\nAlways be kind.' in prompt


def test_create_keeps_existing_edits(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)
    (workspace.root / "BUSINESS.md").write_text("Mine", encoding="utf-8")
    Workspace.create(tmp_path)
    assert (workspace.root / "BUSINESS.md").read_text(encoding="utf-8") == "Mine"


def test_open_rejects_non_workspace(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError):
        Workspace.open(tmp_path)
