"""The agent loop and the interfaces it depends on."""

from m3allema.agent.context import OutputArchive
from m3allema.agent.interfaces import EventSink, MessageLog, ToolExecutor, ToolOutput
from m3allema.agent.loop import Agent
from m3allema.agent.permissions import Approver, Decision, PermissionGate, PolicyGate
from m3allema.agent.sinks import FanOutSink, ReceiptWriter

__all__ = [
    "Agent",
    "Approver",
    "Decision",
    "EventSink",
    "FanOutSink",
    "MessageLog",
    "OutputArchive",
    "PermissionGate",
    "PolicyGate",
    "ReceiptWriter",
    "ToolExecutor",
    "ToolOutput",
]
