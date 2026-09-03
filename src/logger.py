"""API call audit log — append-only JSONL."""

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from src.api import ApiResponse

_log_lock = threading.Lock()


def log_api_call(
    log_path: Path,
    model: str,
    temperature: float,
    phase: str,
    purpose: str,
    problem_id: str,
    prompt_text: str,
    response: ApiResponse | None,
    error: str | None = None,
) -> None:
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    prompt_hash = hashlib.sha256(prompt_text.encode()).hexdigest()[:12]

    if response is not None and error is None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "temperature": temperature,
            "phase": phase,
            "purpose": purpose,
            "problem_id": problem_id,
            "prompt_tokens": response.tokens_input,
            "completion_tokens": response.tokens_output,
            "prompt_hash": prompt_hash,
            "duration_seconds": response.duration_seconds,
            "status": "ok",
            "error": None,
        }
    else:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "temperature": temperature,
            "phase": phase,
            "purpose": purpose,
            "problem_id": problem_id,
            "prompt_tokens": None,
            "completion_tokens": None,
            "prompt_hash": prompt_hash,
            "duration_seconds": response.duration_seconds if response else None,
            "status": "error",
            "error": error,
        }

    with _log_lock:
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
