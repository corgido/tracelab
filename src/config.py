"""Load, validate, and hash the experiment configuration."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Config:
    problems_path: Path
    judge_prompt_path: Path
    cartographer_prompt_path: Path
    analyst_prompt_path: Path
    models: list[str]
    judge_models: list[str]
    cartographer_model: str
    answer_extraction_model: str
    analyst_model: str
    temperatures: list[float]
    validation_sample_fraction: float
    max_retries: int
    backoff_base: float
    output_dir: Path
    run_hash: str


def load_config(path: Path, skip_problems_check: bool = False) -> Config:
    path = Path(path)
    raw = yaml.safe_load(path.read_text())

    judge_prompt_path = Path(raw["prompts"]["judge"])
    cartographer_prompt_path = Path(raw["prompts"]["cartographer"])
    analyst_prompt_path = Path(raw["prompts"]["analyst"])
    problems_path = Path(raw["problems_path"])

    # Validate prompt files exist
    for p, name in [
        (judge_prompt_path, "judge prompt"),
        (cartographer_prompt_path, "cartographer prompt"),
        (analyst_prompt_path, "analyst prompt"),
    ]:
        if not p.is_file():
            raise ValueError(f"{name} file not found: {p}")

    # Validate problems path (can skip for build_problems.py before battery exists)
    if not skip_problems_check and not problems_path.is_file():
        raise ValueError(f"problems file not found: {problems_path}")

    temperatures = sorted(raw["temperatures"])
    if 0 not in [int(t) if t == int(t) else t for t in temperatures]:
        # Check if 0 or 0.0 is present
        if not any(t == 0 for t in temperatures):
            raise ValueError("temperatures must contain 0")
    if not any(t > 0 for t in temperatures):
        raise ValueError("temperatures must contain at least one value > 0")

    models = raw["models"]
    if not models:
        raise ValueError("models must be non-empty")

    judge_models = raw["judge_models"]
    if not judge_models:
        raise ValueError("judge_models must be non-empty")

    cartographer_model = raw["cartographer_model"]
    if not cartographer_model:
        raise ValueError("cartographer_model must be a non-empty string")

    answer_extraction_model = raw["answer_extraction_model"]
    if not answer_extraction_model:
        raise ValueError("answer_extraction_model must be a non-empty string")

    analyst_model = raw["analyst_model"]
    if not analyst_model:
        raise ValueError("analyst_model must be a non-empty string")

    validation_sample_fraction = float(raw["validation_sample_fraction"])
    if not (0 < validation_sample_fraction <= 1):
        raise ValueError("validation_sample_fraction must be in (0, 1]")

    api = raw.get("api", {})
    max_retries = int(api.get("max_retries", 3))
    if max_retries < 0:
        raise ValueError("max_retries must be >= 0")

    backoff_base = float(api.get("backoff_base", 2.0))
    if backoff_base <= 0:
        raise ValueError("backoff_base must be > 0")

    output_dir = Path(raw["output_dir"])

    # Run hash: SHA-256 of config file + judge prompt + cartographer prompt + analyst prompt
    hasher = hashlib.sha256()
    hasher.update(path.read_bytes())
    hasher.update(judge_prompt_path.read_bytes())
    hasher.update(cartographer_prompt_path.read_bytes())
    hasher.update(analyst_prompt_path.read_bytes())
    run_hash = hasher.hexdigest()[:12]

    return Config(
        problems_path=problems_path,
        judge_prompt_path=judge_prompt_path,
        cartographer_prompt_path=cartographer_prompt_path,
        analyst_prompt_path=analyst_prompt_path,
        models=models,
        judge_models=judge_models,
        cartographer_model=cartographer_model,
        answer_extraction_model=answer_extraction_model,
        analyst_model=analyst_model,
        temperatures=temperatures,
        validation_sample_fraction=validation_sample_fraction,
        max_retries=max_retries,
        backoff_base=backoff_base,
        output_dir=output_dir,
        run_hash=run_hash,
    )
