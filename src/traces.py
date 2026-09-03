"""Generate reasoning traces from target models."""

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from src.api import call_api
from src.logger import log_api_call


def _encode_temp(temperature: float) -> str:
    return str(temperature).replace(".", "_")


def _safe_model(model: str) -> str:
    return model.replace("/", "--")


@dataclass
class Trace:
    content: str
    problem_id: str
    condition: str
    model: str
    temperature: float
    phase: str
    run_index: int
    filepath: Path
    tokens_input: int
    tokens_output: int


def generate_trace(
    problem: dict,
    condition: str,
    model: str,
    temperature: float,
    phase: str,
    run_index: int,
    output_dir: Path,
    max_retries: int = 3,
    backoff_base: float = 2.0,
    log_path: Path | None = None,
) -> Trace:
    problem_id = problem["problem_id"]
    temp_str = _encode_temp(temperature)

    filepath = (
        Path(output_dir)
        / "traces"
        / f"{phase}__{problem_id}__{_safe_model(model)}__{temp_str}__{condition}__{run_index}.json"
    )

    # Resume: if file exists, load and return
    if filepath.exists():
        data = json.loads(filepath.read_text())
        return Trace(
            content=data["content"],
            problem_id=data["problem_id"],
            condition=data["condition"],
            model=data["model"],
            temperature=data["temperature"],
            phase=data["phase"],
            run_index=data["run_index"],
            filepath=filepath,
            tokens_input=data["tokens_input"],
            tokens_output=data["tokens_output"],
        )

    # Build prompt based on condition
    if condition == "neutral":
        context = problem["problem_statement"]["context"]
        question = problem["problem_statement"]["question"]
        prompt = context + "\n\n" + question
    elif condition == "opinion":
        prompt = problem["framing_variants"]["opinion_embedded"][0]["framing"]
    else:
        raise ValueError(f"Unknown condition: {condition}")

    # No seed — trace generation is stochastic by design
    response = None
    try:
        response = call_api(model, prompt, temperature, max_retries, backoff_base)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        if log_path:
            log_api_call(log_path, model, temperature, phase,
                         "trace_generation", problem_id, prompt, response, str(e))
        raise

    if log_path:
        log_api_call(log_path, model, temperature, phase,
                     "trace_generation", problem_id, prompt, response)

    trace = Trace(
        content=response.content,
        problem_id=problem_id,
        condition=condition,
        model=model,
        temperature=temperature,
        phase=phase,
        run_index=run_index,
        filepath=filepath,
        tokens_input=response.tokens_input,
        tokens_output=response.tokens_output,
    )

    # Save
    filepath.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(trace)
    data["filepath"] = str(trace.filepath)
    filepath.write_text(json.dumps(data, indent=2))

    return trace
