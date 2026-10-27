"""Locate, create and read a workspace folder.

A workspace is the single source of truth the owner can read and edit::

    my-business/
      IDENTITY.md   who M3allema is: tone, languages
      BUSINESS.md   facts about the business
      OWNER.md      the owner's preferences
      RULES.md      soft guidance for the model
      config.yaml   providers, models, tools (secrets as env:NAME)
      .env          secrets, never committed
      files/        documents M3allema may read and write
      .m3allema/    internal state (database, caches)

Markdown files shape what M3allema knows and says. What she is *allowed to
do* is enforced in code, never by these files.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

CONTEXT_FILES: tuple[str, ...] = ("IDENTITY.md", "BUSINESS.md", "OWNER.md", "RULES.md")
"""Markdown files loaded into the system prompt, in this order."""

_TEMPLATE_FILES: tuple[str, ...] = (
    *CONTEXT_FILES,
    "config.yaml",
    "policy.yaml",
    ".env.example",
)


class WorkspaceError(Exception):
    """The folder is not a usable workspace."""


@dataclass(frozen=True, slots=True)
class Workspace:
    """A business workspace on disk.

    Use :meth:`open` for an existing folder and :meth:`create` for a new one.
    """

    root: Path

    @property
    def config_path(self) -> Path:
        """``config.yaml`` inside the workspace."""
        return self.root / "config.yaml"

    @property
    def env_path(self) -> Path:
        """``.env``: secrets for this workspace, never committed."""
        return self.root / ".env"

    @property
    def policy_path(self) -> Path:
        """``policy.yaml``: enforced permissions and budgets."""
        return self.root / "policy.yaml"

    @property
    def receipts_dir(self) -> Path:
        """One markdown receipt per run."""
        return self.root / "receipts"

    @property
    def files_dir(self) -> Path:
        """The only folder the built-in file tools may touch."""
        return self.root / "files"

    @property
    def state_dir(self) -> Path:
        """Internal state such as the SQLite database."""
        return self.root / ".m3allema"

    @property
    def default_database_url(self) -> str:
        """SQLite URL used when ``storage.url`` is not configured."""
        return f"sqlite:///{(self.state_dir / 'm3allema.db').as_posix()}"

    @classmethod
    def open(cls, root: Path) -> Workspace:
        """Open an existing workspace.

        Raises:
            WorkspaceError: ``root`` has no ``config.yaml``.

        """
        workspace = cls(root.resolve())
        if not workspace.config_path.is_file():
            raise WorkspaceError(
                f"{workspace.root} is not a M3allema workspace (no config.yaml). "
                "Run 'm3allema init' to create one."
            )
        workspace.files_dir.mkdir(exist_ok=True)
        workspace.state_dir.mkdir(exist_ok=True)
        return workspace

    @classmethod
    def create(cls, root: Path, *, overwrite: bool = False) -> Workspace:
        """Create a workspace from the bundled templates.

        Existing files are kept unless ``overwrite`` is true, so running
        ``init`` twice never destroys the owner's edits.
        """
        workspace = cls(root.resolve())
        workspace.root.mkdir(parents=True, exist_ok=True)
        templates = resources.files("m3allema.workspace") / "templates"
        for name in _TEMPLATE_FILES:
            target = workspace.root / name
            if target.exists() and not overwrite:
                continue
            target.write_text((templates / name).read_text(encoding="utf-8"), encoding="utf-8")
        workspace.files_dir.mkdir(exist_ok=True)
        workspace.state_dir.mkdir(exist_ok=True)
        return workspace

    def read_context(self) -> dict[str, str]:
        """Return the non-empty context files, keyed by file name."""
        context: dict[str, str] = {}
        for name in CONTEXT_FILES:
            path = self.root / name
            if path.is_file():
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    context[name] = text
        return context
