from __future__ import annotations

import json
import time
import logging
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


class OnlineLearningClient:
    """
    Simple HTTP-based online learning client.
    Sends JSON events to a remote collector endpoint (darkworker).
    """

    def __init__(
        self,
        endpoint_url: str,
        api_key: Optional[str] = None,
        timeout: float = 5.0,
        verify_ssl: bool = True,
        max_retries: int = 2,
        backoff_base: float = 0.5,
    ) -> None:
        """
        endpoint_url: base URL of the learning backend, e.g. http://127.0.0.1:2121
        timeout: per-request timeout in seconds
        max_retries: number of retries on network errors / timeouts
        backoff_base: base seconds for exponential backoff between retries
        """
        self.endpoint_url = (endpoint_url or "").rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.max_retries = max_retries
        self.backoff_base = backoff_base

    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "ApiCore-OnlineLearning/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
    
    def send_event_with_response(
        self,
        event_type: str,
        payload: Dict[str, Any],
        risk_score: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        event: Dict[str, Any] = {
            "ts": time.time(),
            "event_type": event_type,
            "payload": payload,
        }
        if risk_score is not None:
            event["risk_score"] = risk_score
        if metadata:
            event["meta"] = metadata

        try:
            resp = requests.post(
                f"{self.endpoint_url}/events",
                headers=self._build_headers(),
                data=json.dumps(event),
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            if resp.status_code // 100 == 2:
                try:
                    return True, resp.json()
                except Exception:
                    return True, {"success": True, "message": "ok", "feedback": None}

            return False, {"success": False, "status_code": resp.status_code, "body": resp.text[:512]}
        except Exception as exc:
            logger.error(
                "OnlineLearningClient: failed to send event",
                exc_info=exc,
                extra={"event_type": event_type},
            )
            return False, None
        
    def send_event(self, event_type: str, payload: Dict[str, Any],
                   risk_score: Optional[float] = None,
                   metadata: Optional[Dict[str, Any]] = None) -> bool:
        ok, _ = self.send_event_with_response(
            event_type=event_type,
            payload=payload,
            risk_score=risk_score,
            metadata=metadata,
        )
        return ok