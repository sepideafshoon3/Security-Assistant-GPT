from __future__ import annotations

from typing import Any, Dict, Optional, List
from dataclasses import dataclass

from .online_learning_client import OnlineLearningClient


# --------- Event Models ---------

@dataclass
class ChatTurnEvent:
    conversation_id: str
    user_message: str
    assistant_reply: str
    num_history_messages: int
    model_name: Optional[str] = None
    source: str = "teacher_api.chat"

    def to_payload(self) -> Dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "user_message": self.user_message,
            "assistant_reply": self.assistant_reply,
            "num_history_messages": self.num_history_messages,
            "model_name": self.model_name,
        }

    def to_meta(self) -> Dict[str, Any]:
        return {
            "source": self.source,
        }


@dataclass
class PipelineResultEvent:
    module_name: str
    advisory: Dict[str, Any]
    scenario: Optional[Dict[str, Any]]
    playbook: Optional[Dict[str, Any]]
    training_plan: Optional[Dict[str, Any]]
    exploit: Optional[Dict[str, Any]]
    risk_level: Optional[str] = None
    risk_score: Optional[float] = None
    source: str = "security_engine.pipeline"

    def to_payload(self) -> Dict[str, Any]:
        return {
            "module_name": self.module_name,
            "advisory": self.advisory,
            "scenario": self.scenario,
            "playbook": self.playbook,
            "training_plan": self.training_plan,
            "exploit": self.exploit,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
        }

    def to_meta(self) -> Dict[str, Any]:
        return {
            "source": self.source,
        }


@dataclass
class ReconScanEvent:
    domain: str
    subdomains_count: int
    vulns_count: int
    assets_count: int
    risk_score: Optional[float] = None
    source: str = "recon.pipeline"

    def to_payload(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "subdomains_count": self.subdomains_count,
            "vulns_count": self.vulns_count,
            "assets_count": self.assets_count,
            "risk_score": self.risk_score,
        }

    def to_meta(self) -> Dict[str, Any]:
        return {
            "source": self.source,
        }


# --------- Dispatcher Wrapper ---------

class OnlineLearningEventDispatcher:
    """
    Thin wrapper around OnlineLearningClient with typed helpers.
    """

    def __init__(self, client: Optional[OnlineLearningClient]) -> None:
        self.client = client

    def send_chat_turn(self, evt: ChatTurnEvent) -> bool:
        if self.client is None:
            return False
        return self.client.send_event(
            event_type="chat_turn",
            payload=evt.to_payload(),
            risk_score=None,
            metadata=evt.to_meta(),
        )

    def send_openai_chat_turn(self, evt: ChatTurnEvent) -> bool:
        if self.client is None:
            return False
        return self.client.send_event(
            event_type="openai_style_chat_turn",
            payload=evt.to_payload(),
            risk_score=None,
            metadata=evt.to_meta(),
        )

    def send_pipeline_result(self, evt: PipelineResultEvent) -> bool:
        if self.client is None:
            return False
        return self.client.send_event(
            event_type="pipeline_full_result",
            payload=evt.to_payload(),
            risk_score=evt.risk_score,
            metadata=evt.to_meta(),
        )

    def send_recon_scan(self, evt: ReconScanEvent) -> bool:
        if self.client is None:
            return False
        return self.client.send_event(
            event_type="recon_scan_summary",
            payload=evt.to_payload(),
            risk_score=evt.risk_score,
            metadata=evt.to_meta(),
        )