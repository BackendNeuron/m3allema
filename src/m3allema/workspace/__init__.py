"""The workspace: one business's folder of editable markdown and config files."""

from m3allema.workspace.prompt import PromptBuilder
from m3allema.workspace.workspace import Workspace, WorkspaceError

__all__ = ["PromptBuilder", "Workspace", "WorkspaceError"]
