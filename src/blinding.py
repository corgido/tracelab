"""Randomise trace pair assignment for Judge blinding. Deterministic per cell."""

import hashlib
import random
from dataclasses import dataclass


@dataclass
class BlindedPair:
    response_a_content: str
    response_b_content: str
    a_original_role: str
    b_original_role: str


def blind_pair(
    content_first: str,
    content_second: str,
    role_first: str,
    role_second: str,
    problem_id: str,
    model: str,
    temperature: float,
) -> BlindedPair:
    key = f"{problem_id}|{model}|{temperature}"
    seed = int(hashlib.sha256(key.encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)

    if rng.random() < 0.5:
        # Keep order
        return BlindedPair(
            response_a_content=content_first,
            response_b_content=content_second,
            a_original_role=role_first,
            b_original_role=role_second,
        )
    else:
        # Swap
        return BlindedPair(
            response_a_content=content_second,
            response_b_content=content_first,
            a_original_role=role_second,
            b_original_role=role_first,
        )


def unblind_scores(
    trace_a_scores: dict,
    trace_b_scores: dict,
    a_original_role: str,
    b_original_role: str,
) -> dict:
    return {
        a_original_role: trace_a_scores,
        b_original_role: trace_b_scores,
    }
