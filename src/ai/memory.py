"""Conversation and research memory store for AI Copilot sessions."""

from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from src.ai.schemas import ResearchReport


class SessionMessage(BaseModel):
    role: str  # 'user', 'assistant', 'system'
    content: str
    timestamp: str = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat())


class ResearchSession(BaseModel):
    session_id: str
    messages: List[SessionMessage] = Field(default_factory=list)
    reports: List[ResearchReport] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat())


class MemoryManager:
    """In-memory session cache with thread-safe session tracking."""

    def __init__(self) -> None:
        self._sessions: Dict[str, ResearchSession] = {}

    def get_or_create_session(self, session_id: str) -> ResearchSession:
        if session_id not in self._sessions:
            self._sessions[session_id] = ResearchSession(session_id=session_id)
        return self._sessions[session_id]

    def add_user_message(self, session_id: str, message: str) -> None:
        session = self.get_or_create_session(session_id)
        session.messages.append(SessionMessage(role="user", content=message))

    def add_assistant_report(self, session_id: str, report: ResearchReport) -> None:
        session = self.get_or_create_session(session_id)
        session.messages.append(SessionMessage(role="assistant", content=report.summary))
        session.reports.append(report)

    def get_session_history(self, session_id: str) -> List[SessionMessage]:
        session = self.get_or_create_session(session_id)
        return session.messages


memory_manager = MemoryManager()
