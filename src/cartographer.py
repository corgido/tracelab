"""Run the Cartographer instrument. Parse per-trace scores."""

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from src.api import call_api
from src.judge import JudgeOutput
from src.logger import log_api_call


@dataclass
class TraceScores:
    node_coverage: float
    ordering_preservation: float
    conflict_surfacing: float
    trap_avoidance: float
    composite: float


@dataclass
class CartographerOutput:
    trace_a_scores: TraceScores | None
    trace_b_scores: TraceScores | None
    parse_success: bool
    parse_error: str | None
    raw_response: str
    tokens_input: int
    tokens_output: int


def _extract_json(raw: str) -> dict:
    """Find outermost matching braces and parse JSON."""
    start = raw.find("{")
    if start == -1:
        raise ValueError("No JSON object found in response")

    depth = 0
    for i in range(start, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(raw[start:i + 1])

    raise ValueError("No matching closing brace found")


def _parse_scores(score_dict: dict) -> TraceScores:
    """Parse and validate a trace's scores."""
    dimensions = ["node_coverage", "ordering_preservation", "conflict_surfacing", "trap_avoidance"]

    for dim in dimensions:
        val = float(score_dict[dim])
        if not (0 <= val <= 1):
            raise ValueError(f"{dim} score {val} not in [0, 1]")

    dim_values = [float(score_dict[d]) for d in dimensions]
    composite = round(sum(dim_values) / 4, 4)

    return TraceScores(
        node_coverage=dim_values[0],
        ordering_preservation=dim_values[1],
        conflict_surfacing=dim_values[2],
        trap_avoidance=dim_values[3],
        composite=composite,
    )


def run_cartographer(
    judge_output: JudgeOutput,
    problem: dict,
    trace_a_content: str,
    trace_b_content: str,
    cartographer_prompt_path: Path,
    cartographer_model: str,
    max_retries: int = 3,
    backoff_base: float = 2.0,
    log_path: Path | None = None,
    phase: str = "",
    problem_id: str = "",
) -> CartographerOutput:
    # Short-circuit if judge parse failed
    if not judge_output.parse_success:
        return CartographerOutput(
            trace_a_scores=None,
            trace_b_scores=None,
            parse_success=False,
            parse_error="upstream judge parse failure",
            raw_response="",
            tokens_input=0,
            tokens_output=0,
        )

    template = Path(cartographer_prompt_path).read_text()

    # Build judge output text from the raw XML
    judge_text = judge_output.raw_xml

    generator_metadata = json.dumps(
        problem.get("structural_metadata", {}), indent=2
    )

    prompt = (
        template
        .replace("{{JUDGE_OUTPUT}}", judge_text)
        .replace("{{GENERATOR_METADATA}}", generator_metadata)
        .replace("{{TRACE_A}}", trace_a_content)
        .replace("{{TRACE_B}}", trace_b_content)
    )

    api_response = None
    try:
        api_response = call_api(
            cartographer_model, prompt, temperature=0,
            max_retries=max_retries, backoff_base=backoff_base,
            seed=42,
        )
    except KeyboardInterrupt:
        raise
    except Exception as e:
        if log_path:
            log_api_call(log_path, cartographer_model, 0, phase,
                         "cartographer", problem_id, prompt, api_response, str(e))
        raise

    if log_path:
        log_api_call(log_path, cartographer_model, 0, phase,
                     "cartographer", problem_id, prompt, api_response)

    raw = api_response.content
    try:
        data = _extract_json(raw)
        fidelity = data["fidelity_scores"]
        trace_a_scores = _parse_scores(fidelity["trace_a"])
        trace_b_scores = _parse_scores(fidelity["trace_b"])
        return CartographerOutput(
            trace_a_scores=trace_a_scores,
            trace_b_scores=trace_b_scores,
            parse_success=True,
            parse_error=None,
            raw_response=raw,
            tokens_input=api_response.tokens_input,
            tokens_output=api_response.tokens_output,
        )
    except Exception as e:
        return CartographerOutput(
            trace_a_scores=None,
            trace_b_scores=None,
            parse_success=False,
            parse_error=str(e),
            raw_response=raw,
            tokens_input=api_response.tokens_input,
            tokens_output=api_response.tokens_output,
        )


def save_cartographer_output(output: CartographerOutput, filepath: Path) -> None:
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(output)
    filepath.write_text(json.dumps(data, indent=2))


def load_cartographer_output(filepath: Path) -> CartographerOutput:
    data = json.loads(Path(filepath).read_text())
    trace_a = TraceScores(**data["trace_a_scores"]) if data["trace_a_scores"] else None
    trace_b = TraceScores(**data["trace_b_scores"]) if data["trace_b_scores"] else None
    return CartographerOutput(
        trace_a_scores=trace_a,
        trace_b_scores=trace_b,
        parse_success=data["parse_success"],
        parse_error=data["parse_error"],
        raw_response=data["raw_response"],
        tokens_input=data["tokens_input"],
        tokens_output=data["tokens_output"],
    )
