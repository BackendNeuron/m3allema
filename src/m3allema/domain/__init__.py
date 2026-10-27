"""Provider-neutral domain model.

Everything in this package is plain data with no dependency on any LLM SDK,
MCP library or database. The agent loop, the providers and the storage layer
all speak this language, which keeps them independent of each other.
"""

from m3allema.domain.events import (
    AgentEvent,
    RunFinished,
    RunStarted,
    StreamEvent,
    TextDelta,
    ToolCallFinished,
    ToolCallStarted,
    TurnCompleted,
)
from m3allema.domain.messages import (
    AssistantMessage,
    ContentBlock,
    Message,
    Role,
    StopReason,
    TextBlock,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from m3allema.domain.tools import Risk, ToolSpec

__all__ = [
    "AgentEvent",
    "AssistantMessage",
    "ContentBlock",
    "Message",
    "Risk",
    "Role",
    "RunFinished",
    "RunStarted",
    "StopReason",
    "StreamEvent",
    "TextBlock",
    "TextDelta",
    "ToolCall",
    "ToolCallFinished",
    "ToolCallStarted",
    "ToolResult",
    "ToolResultMessage",
    "ToolSpec",
    "TurnCompleted",
    "Usage",
    "UserMessage",
]
