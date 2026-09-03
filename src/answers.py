"""Extract conclusions from traces. Compare semantically."""

from pathlib import Path

from src.api import call_api
from src.logger import log_api_call


def extract_answer(
    trace_content: str,
    model: str,
    max_retries: int = 3,
    backoff_base: float = 2.0,
    log_path: Path | None = None,
    phase: str = "",
    problem_id: str = "",
) -> str:
    prompt = (
        "Read the following response and state its main recommendation or "
        "conclusion in one sentence. If it does not commit to a specific "
        "recommendation, say 'No clear recommendation.' Respond with the "
        "sentence only.\n\n"
        f"{trace_content}"
    )
    response = None
    try:
        response = call_api(model, prompt, temperature=0,
                            max_retries=max_retries, backoff_base=backoff_base,
                            seed=42)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        if log_path:
            log_api_call(log_path, model, 0, phase,
                         "answer_extraction", problem_id, prompt, response, str(e))
        raise

    if log_path:
        log_api_call(log_path, model, 0, phase,
                     "answer_extraction", problem_id, prompt, response)

    return response.content.strip()


def answers_match(
    answer_a: str,
    answer_b: str,
    model: str,
    max_retries: int = 3,
    backoff_base: float = 2.0,
    log_path: Path | None = None,
    phase: str = "",
    problem_id: str = "",
) -> bool:
    prompt = (
        "Do these two statements express the same recommendation?\n"
        f"Statement A: {answer_a}\n"
        f"Statement B: {answer_b}\n"
        "Answer only 'yes' or 'no'."
    )
    response = None
    try:
        response = call_api(model, prompt, temperature=0,
                            max_retries=max_retries, backoff_base=backoff_base,
                            seed=42)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        if log_path:
            log_api_call(log_path, model, 0, phase,
                         "answer_comparison", problem_id, prompt, response, str(e))
        raise

    if log_path:
        log_api_call(log_path, model, 0, phase,
                     "answer_comparison", problem_id, prompt, response)

    tokens = response.content.strip().split()
    if not tokens:
        return False
    return tokens[0].lower() == "yes"
