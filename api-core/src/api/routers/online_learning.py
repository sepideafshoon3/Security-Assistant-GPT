from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from time import time
from typing import Any, Dict, Iterable, List

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from src.api.schemas.schemas_learning import (
    OnlineLearningBulkRequest,
    OnlineLearningBulkResponse,
    OnlineLearningEventRequest,
    OnlineLearningEventResponse,
)
from src.api.state import DATASETS_DIR, EVENTS_LOG_DIR, online_learning_client
from src.db.models import User
from src.learning.schemas_online_learning import (
    IncomingOnlineLearningEvent,
    IncomingOnlineLearningResponse,
)
from src.security.audit import audit_log
from src.security.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["online-learning"])


# ============================================================
# Helpers: dataset builder (from logged JSONL)
# ============================================================

def _iter_event_files(dir_path: Path) -> Iterable[Path]:
    for p in sorted(dir_path.glob("*.jsonl")):
        if p.is_file():
            yield p


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "[dataset] skip bad jsonl line | file=%s line=%d error=%r",
                    path.name,
                    line_no,
                    e,
                )


def build_online_learning_dataset_csv(
    *,
    events_dir: Path,
    output_path: Path,
    dedupe_by_event_id: bool = False,
) -> Path:
    """
    Build a simple CSV dataset from logged online-learning events.

    Output columns:
      - event_type
      - ts
      - received_ts
      - risk_score
      - payload_json
      - meta_json
      - source_file
    """
    rows: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()

    for file_path in _iter_event_files(events_dir):
        event_type_from_file = file_path.stem

        for obj in _read_jsonl(file_path):
            # event id heuristic
            evt_id = str(obj.get("id") or obj.get("event_id") or "")
            if dedupe_by_event_id and evt_id:
                if evt_id in seen_ids:
                    continue
                seen_ids.add(evt_id)

            rows.append(
                {
                    "event_type": obj.get("event_type") or event_type_from_file,
                    "ts": obj.get("ts"),
                    "received_ts": obj.get("received_ts"),
                    "risk_score": obj.get("risk_score"),
                    "payload_json": json.dumps(obj.get("payload") or {}, ensure_ascii=False),
                    "meta_json": json.dumps(obj.get("meta") or {}, ensure_ascii=False),
                    "source_file": file_path.name,
                }
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "event_type",
        "ts",
        "received_ts",
        "risk_score",
        "payload_json",
        "meta_json",
        "source_file",
    ]

    with output_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    logger.info(
        "[dataset] csv built | path=%s rows=%d",
        output_path,
        len(rows),
    )
    return output_path


# ============================================================
# Online Learning Proxy Endpoints
# ============================================================

@router.post(
    "/online-learning/events",
    response_model=OnlineLearningEventResponse,
    status_code=status.HTTP_200_OK,
)
async def send_online_learning_event(
    body: OnlineLearningEventRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> OnlineLearningEventResponse:
    if online_learning_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Online learning client is not configured.",
        )

    base_meta: Dict[str, Any] = {
        "remote_addr": request.client.host if request.client else None,
        "user_agent": request.headers.get("User-Agent"),
        "path": str(request.url.path),
    }

    merged_meta: Dict[str, Any] = dict(base_meta)
    if body.metadata:
        merged_meta.update(body.metadata)

    ok = online_learning_client.send_event(
        event_type=body.event_type,
        payload=body.payload,
        risk_score=body.risk_score,
        metadata=merged_meta,
    )

    audit_log(
        "online_learning_event",
        {
            "event_type": body.event_type,
            "risk_score": body.risk_score,
            "success": ok,
        },
    )

    if ok:
        return OnlineLearningEventResponse(
            success=True,
            status_code=status.HTTP_200_OK,
            message="Event delivered to online learning backend.",
        )

    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Failed to deliver event to online learning backend.",
    )


@router.post(
    "/online-learning/bulk",
    response_model=OnlineLearningBulkResponse,
    status_code=status.HTTP_200_OK,
)
async def send_online_learning_bulk(
    body: OnlineLearningBulkRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> OnlineLearningBulkResponse:
    if online_learning_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Online learning client is not configured.",
        )

    sent = 0
    failed = 0

    for evt in body.events:
        base_meta: Dict[str, Any] = {
            "remote_addr": request.client.host if request.client else None,
            "user_agent": request.headers.get("User-Agent"),
            "path": str(request.url.path),
        }
        merged_meta: Dict[str, Any] = dict(base_meta)
        if evt.metadata:
            merged_meta.update(evt.metadata)

        ok = online_learning_client.send_event(
            event_type=evt.event_type,
            payload=evt.payload,
            risk_score=evt.risk_score,
            metadata=merged_meta,
        )
        if ok:
            sent += 1
        else:
            failed += 1

    audit_log(
        "online_learning_bulk",
        {
            "total": len(body.events),
            "sent": sent,
            "failed": failed,
        },
    )

    return OnlineLearningBulkResponse(
        success=failed == 0,
        sent=sent,
        failed=failed,
        message=f"Bulk send finished: sent={sent}, failed={failed}",
    )


# ============================================================
# Collector endpoint for OnlineLearningClient (darkworker side)
# ============================================================

@router.post(
    "/events",
    response_model=IncomingOnlineLearningResponse,
    status_code=status.HTTP_200_OK,
)
async def receive_online_learning_event(
    body: IncomingOnlineLearningEvent,
    request: Request,
) -> IncomingOnlineLearningResponse:
    remote_addr = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    event_dict: Dict[str, Any] = body.model_dump()
    event_dict.setdefault("meta", {})
    event_dict["meta"]["remote_addr"] = remote_addr
    event_dict["meta"]["user_agent"] = user_agent
    event_dict["received_ts"] = time()

    event_type = body.event_type
    log_path = EVENTS_LOG_DIR / f"{event_type}.jsonl"

    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event_dict, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.exception("[events] persist failed | type=%s error=%r", event_type, e)
        return IncomingOnlineLearningResponse(
            success=False,
            message=f"Failed to persist event: {e}",
        )

    logger.info(
        "[events] received",
        extra={"event_type": event_type, "remote_addr": remote_addr},
    )

    return IncomingOnlineLearningResponse(
        success=True,
        message="Event received and stored.",
    )


# ============================================================
# Build dataset from logged events
# ============================================================

@router.post("/online-learning/build-dataset")
async def build_online_learning_dataset(
    request: Request,
    body: Dict[str, Any] = Body(default={}),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Build a CSV from JSONL logs under data/online-learning-events/.

    Body options:
      - output_filename: str (default: online_learning_dataset.csv)
      - dedupe_by_event_id: bool (default: False)
    """
    output_filename = str(body.get("output_filename") or "online_learning_dataset.csv")
    dedupe_by_event_id = bool(body.get("dedupe_by_event_id") or False)

    output_path = DATASETS_DIR / output_filename

    try:
        csv_path = build_online_learning_dataset_csv(
            events_dir=EVENTS_LOG_DIR,
            output_path=output_path,
            dedupe_by_event_id=dedupe_by_event_id,
        )
    except Exception as e:
        logger.exception("[dataset] build failed | error=%r", e)
        raise HTTPException(status_code=500, detail=f"Dataset build failed: {e}")

    audit_log(
        "online_learning_build_dataset",
        {
            "output": str(csv_path),
            "dedupe_by_event_id": dedupe_by_event_id,
        },
    )

    return {
        "success": True,
        "output_path": str(csv_path),
        "events_dir": str(EVENTS_LOG_DIR),
    }