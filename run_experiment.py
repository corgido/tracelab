#!/usr/bin/env python3
"""Run all three phases. Produce results.csv and artifacts."""

import argparse
import json
import math
import random
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from src.answers import answers_match, extract_answer
from src.blinding import blind_pair, unblind_scores
from src.cartographer import load_cartographer_output, run_cartographer, save_cartographer_output
from src.config import load_config
from src.csv_store import append_row, init_csv, load_completed_cells
from src.judge import load_judge_output, run_judge, save_judge_output
from src.traces import generate_trace

_csv_lock = threading.Lock()


def _encode_temp(temperature: float) -> str:
    return str(temperature).replace(".", "_")


def _safe_model(model: str) -> str:
    return model.replace("/", "--")


def _save_answer(content: str, filepath: Path) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(json.dumps({"answer": content}, indent=2))


def _locked_append_row(csv_path: Path, row: dict) -> None:
    with _csv_lock:
        append_row(csv_path, row)


def _run_baseline_cell(config, problem, model, temp, judge_model, output_dir,
                       csv_path, log_path, label):
    """Run a single baseline cell. Returns None on success, raises on KeyboardInterrupt."""
    pid = problem["problem_id"]
    domain = problem.get("domain", "general")

    try:
        trace_0 = generate_trace(
            problem, "neutral", model, temp, "baseline", 0,
            output_dir, config.max_retries, config.backoff_base, log_path,
        )
        trace_1 = generate_trace(
            problem, "neutral", model, temp, "baseline", 1,
            output_dir, config.max_retries, config.backoff_base, log_path,
        )

        blinded = blind_pair(
            trace_0.content, trace_1.content,
            "neutral_0", "neutral_1", pid, model, temp,
        )

        temp_str = _encode_temp(temp)
        judge_filepath = (
            output_dir / "judge_outputs"
            / f"baseline__{pid}__{_safe_model(model)}__{temp_str}__neutral_neutral__{_safe_model(judge_model)}.json"
        )
        if judge_filepath.exists():
            judge_output = load_judge_output(judge_filepath)
        else:
            judge_output = run_judge(
                blinded.response_a_content, blinded.response_b_content,
                config.judge_prompt_path, judge_model,
                config.max_retries, config.backoff_base,
                log_path, "baseline", pid,
            )
            save_judge_output(judge_output, judge_filepath)

        carto_filepath = (
            output_dir / "cartographer_outputs"
            / f"baseline__{pid}__{_safe_model(model)}__{temp_str}__neutral_neutral__{_safe_model(judge_model)}.json"
        )
        if carto_filepath.exists():
            carto_output = load_cartographer_output(carto_filepath)
        else:
            carto_output = run_cartographer(
                judge_output, problem,
                blinded.response_a_content, blinded.response_b_content,
                config.cartographer_prompt_path, config.cartographer_model,
                config.max_retries, config.backoff_base,
                log_path, "baseline", pid,
            )
            save_cartographer_output(carto_output, carto_filepath)

        if not carto_output.parse_success:
            status = "upstream_parse_error" if carto_output.parse_error == "upstream judge parse failure" else "cartographer_parse_error"
            row = {
                "phase": "baseline", "problem_id": pid, "domain": domain,
                "condition_pair": "neutral_neutral", "model": model,
                "temperature": temp, "judge_model": judge_model,
                "status": status,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            _locked_append_row(csv_path, row)
            print(f"{label}\n  ERROR ({status}): {carto_output.parse_error}")
            return

        unblinded = unblind_scores(
            asdict(carto_output.trace_a_scores),
            asdict(carto_output.trace_b_scores),
            blinded.a_original_role, blinded.b_original_role,
        )

        row = {
            "phase": "baseline", "problem_id": pid, "domain": domain,
            "condition_pair": "neutral_neutral", "model": model,
            "temperature": temp, "judge_model": judge_model,
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        row.update({f"neutral_0_{k}": v for k, v in unblinded["neutral_0"].items()})
        row.update({f"neutral_1_{k}": v for k, v in unblinded["neutral_1"].items()})
        _locked_append_row(csv_path, row)

        n0c = unblinded["neutral_0"]["composite"]
        n1c = unblinded["neutral_1"]["composite"]
        divs = len(judge_output.divergences)
        print(f"{label}\n  Judge: {divs} divergences | Carto: n0={n0c:.2f} n1={n1c:.2f}")

    except KeyboardInterrupt:
        raise
    except Exception as e:
        row = {
            "phase": "baseline", "problem_id": pid, "domain": domain,
            "condition_pair": "neutral_neutral", "model": model,
            "temperature": temp, "judge_model": judge_model,
            "status": "api_error",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        _locked_append_row(csv_path, row)
        print(f"{label}\n  ERROR (api_error): {e}")


def _run_measurement_cell(config, problem, model, temp, judge_model, output_dir,
                          csv_path, log_path, label):
    """Run a single measurement cell."""
    pid = problem["problem_id"]
    domain = problem.get("domain", "general")

    try:
        trace_neutral = generate_trace(
            problem, "neutral", model, temp, "measurement", 0,
            output_dir, config.max_retries, config.backoff_base, log_path,
        )
        trace_opinion = generate_trace(
            problem, "opinion", model, temp, "measurement", 0,
            output_dir, config.max_retries, config.backoff_base, log_path,
        )

        blinded = blind_pair(
            trace_neutral.content, trace_opinion.content,
            "neutral", "opinion", pid, model, temp,
        )

        temp_str = _encode_temp(temp)
        judge_filepath = (
            output_dir / "judge_outputs"
            / f"measurement__{pid}__{_safe_model(model)}__{temp_str}__neutral_opinion__{_safe_model(judge_model)}.json"
        )
        if judge_filepath.exists():
            judge_output = load_judge_output(judge_filepath)
        else:
            judge_output = run_judge(
                blinded.response_a_content, blinded.response_b_content,
                config.judge_prompt_path, judge_model,
                config.max_retries, config.backoff_base,
                log_path, "measurement", pid,
            )
            save_judge_output(judge_output, judge_filepath)

        carto_filepath = (
            output_dir / "cartographer_outputs"
            / f"measurement__{pid}__{_safe_model(model)}__{temp_str}__neutral_opinion__{_safe_model(judge_model)}.json"
        )
        if carto_filepath.exists():
            carto_output = load_cartographer_output(carto_filepath)
        else:
            carto_output = run_cartographer(
                judge_output, problem,
                blinded.response_a_content, blinded.response_b_content,
                config.cartographer_prompt_path, config.cartographer_model,
                config.max_retries, config.backoff_base,
                log_path, "measurement", pid,
            )
            save_cartographer_output(carto_output, carto_filepath)

        if not carto_output.parse_success:
            status = "upstream_parse_error" if carto_output.parse_error == "upstream judge parse failure" else "cartographer_parse_error"
            row = {
                "phase": "measurement", "problem_id": pid, "domain": domain,
                "condition_pair": "neutral_opinion", "model": model,
                "temperature": temp, "judge_model": judge_model,
                "status": status,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            _locked_append_row(csv_path, row)
            print(f"{label}\n  ERROR ({status}): {carto_output.parse_error}")
            return

        answer_neutral = extract_answer(
            trace_neutral.content, config.answer_extraction_model,
            config.max_retries, config.backoff_base,
            log_path, "measurement", pid,
        )
        answer_opinion = extract_answer(
            trace_opinion.content, config.answer_extraction_model,
            config.max_retries, config.backoff_base,
            log_path, "measurement", pid,
        )

        ans_dir = output_dir / "answer_extractions"
        _save_answer(answer_neutral,
            ans_dir / f"measurement__{pid}__{_safe_model(model)}__{temp_str}__neutral__0.json")
        _save_answer(answer_opinion,
            ans_dir / f"measurement__{pid}__{_safe_model(model)}__{temp_str}__opinion__0.json")

        answer_changed = not answers_match(
            answer_neutral, answer_opinion,
            config.answer_extraction_model,
            config.max_retries, config.backoff_base,
            log_path, "measurement", pid,
        )

        unblinded = unblind_scores(
            asdict(carto_output.trace_a_scores),
            asdict(carto_output.trace_b_scores),
            blinded.a_original_role, blinded.b_original_role,
        )

        row = {
            "phase": "measurement", "problem_id": pid, "domain": domain,
            "condition_pair": "neutral_opinion", "model": model,
            "temperature": temp, "judge_model": judge_model,
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "answer_changed": "true" if answer_changed else "false",
        }
        row.update({f"neutral_{k}": v for k, v in unblinded["neutral"].items()})
        row.update({f"opinion_{k}": v for k, v in unblinded["opinion"].items()})
        _locked_append_row(csv_path, row)

        nc = unblinded["neutral"]["composite"]
        oc = unblinded["opinion"]["composite"]
        divs = len(judge_output.divergences)
        ac = "yes" if answer_changed else "no"
        print(f"{label}\n  Judge: {divs} divergences | Carto: neutral={nc:.2f} opinion={oc:.2f} | Answer changed: {ac}")

    except KeyboardInterrupt:
        raise
    except Exception as e:
        row = {
            "phase": "measurement", "problem_id": pid, "domain": domain,
            "condition_pair": "neutral_opinion", "model": model,
            "temperature": temp, "judge_model": judge_model,
            "status": "api_error",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        _locked_append_row(csv_path, row)
        print(f"{label}\n  ERROR (api_error): {e}")


def _run_validation_cell(config, problem, model, temp, domain, judge_model,
                         phase1_row, output_dir, csv_path, log_path, label):
    """Run a single validation cell."""
    pid = problem["problem_id"]

    try:
        trace_neutral = generate_trace(
            problem, "neutral", model, temp, "measurement", 0,
            output_dir, config.max_retries, config.backoff_base, log_path,
        )
        trace_opinion = generate_trace(
            problem, "opinion", model, temp, "measurement", 0,
            output_dir, config.max_retries, config.backoff_base, log_path,
        )

        blinded = blind_pair(
            trace_neutral.content, trace_opinion.content,
            "neutral", "opinion", pid, model, temp,
        )

        temp_str = _encode_temp(temp)
        judge_filepath = (
            output_dir / "judge_outputs"
            / f"validation__{pid}__{_safe_model(model)}__{temp_str}__neutral_opinion__{_safe_model(judge_model)}.json"
        )
        if judge_filepath.exists():
            judge_output = load_judge_output(judge_filepath)
        else:
            judge_output = run_judge(
                blinded.response_a_content, blinded.response_b_content,
                config.judge_prompt_path, judge_model,
                config.max_retries, config.backoff_base,
                log_path, "validation", pid,
            )
            save_judge_output(judge_output, judge_filepath)

        carto_filepath = (
            output_dir / "cartographer_outputs"
            / f"validation__{pid}__{_safe_model(model)}__{temp_str}__neutral_opinion__{_safe_model(judge_model)}.json"
        )
        if carto_filepath.exists():
            carto_output = load_cartographer_output(carto_filepath)
        else:
            carto_output = run_cartographer(
                judge_output, problem,
                blinded.response_a_content, blinded.response_b_content,
                config.cartographer_prompt_path, config.cartographer_model,
                config.max_retries, config.backoff_base,
                log_path, "validation", pid,
            )
            save_cartographer_output(carto_output, carto_filepath)

        if not carto_output.parse_success:
            status = "upstream_parse_error" if carto_output.parse_error == "upstream judge parse failure" else "cartographer_parse_error"
            csv_row = {
                "phase": "validation", "problem_id": pid, "domain": domain,
                "condition_pair": "neutral_opinion", "model": model,
                "temperature": temp, "judge_model": judge_model,
                "status": status,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            _locked_append_row(csv_path, csv_row)
            print(f"{label}\n  ERROR ({status}): {carto_output.parse_error}")
            return

        unblinded = unblind_scores(
            asdict(carto_output.trace_a_scores),
            asdict(carto_output.trace_b_scores),
            blinded.a_original_role, blinded.b_original_role,
        )

        answer_changed_str = phase1_row.get("answer_changed", "")

        csv_row = {
            "phase": "validation", "problem_id": pid, "domain": domain,
            "condition_pair": "neutral_opinion", "model": model,
            "temperature": temp, "judge_model": judge_model,
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "answer_changed": answer_changed_str,
        }
        csv_row.update({f"neutral_{k}": v for k, v in unblinded["neutral"].items()})
        csv_row.update({f"opinion_{k}": v for k, v in unblinded["opinion"].items()})
        _locked_append_row(csv_path, csv_row)

        nc = unblinded["neutral"]["composite"]
        oc = unblinded["opinion"]["composite"]
        divs = len(judge_output.divergences)
        print(f"{label}\n  Judge: {divs} divergences | Carto: neutral={nc:.2f} opinion={oc:.2f}")

    except KeyboardInterrupt:
        raise
    except Exception as e:
        csv_row = {
            "phase": "validation", "problem_id": pid, "domain": domain,
            "condition_pair": "neutral_opinion", "model": model,
            "temperature": temp, "judge_model": judge_model,
            "status": "api_error",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        _locked_append_row(csv_path, csv_row)
        print(f"{label}\n  ERROR (api_error): {e}")


def _run_phase(phase_name, cells, cell_fn, workers):
    """Run cells sequentially or with thread pool. Handle KeyboardInterrupt."""
    total = len(cells)
    completed = 0

    if workers <= 1:
        for cell_args in cells:
            try:
                cell_fn(*cell_args)
                completed += 1
            except KeyboardInterrupt:
                print(f"\n{phase_name}: {completed}/{total} cells complete.")
                print("Resume with --resume to continue.")
                sys.exit(0)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(cell_fn, *args) for args in cells]
            try:
                for future in futures:
                    future.result()
                    completed += 1
            except KeyboardInterrupt:
                executor.shutdown(wait=False, cancel_futures=True)
                print(f"\n{phase_name}: {completed}/{total} cells complete.")
                print("Resume with --resume to continue.")
                sys.exit(0)


def _build_baseline_cells(config, problems, completed_cells, output_dir, csv_path, log_path):
    """Build list of (args_tuple) for baseline cells."""
    judge_model = config.judge_models[0]
    total = len(problems) * len(config.models) * len(config.temperatures)
    cells = []
    count = 0

    for problem in problems:
        pid = problem["problem_id"]
        for model in config.models:
            for temp in config.temperatures:
                count += 1
                cell_key = ("baseline", pid, model, str(temp), judge_model)
                if cell_key in completed_cells:
                    continue
                label = f"[{count}/{total}] baseline: {pid} / {model} / temp={temp}"
                cells.append((config, problem, model, temp, judge_model,
                              output_dir, csv_path, log_path, label))
    return cells, total


def _build_measurement_cells(config, problems, completed_cells, output_dir, csv_path, log_path):
    """Build list of (args_tuple) for measurement cells."""
    judge_model = config.judge_models[0]
    total = len(problems) * len(config.models) * len(config.temperatures)
    cells = []
    count = 0

    for problem in problems:
        pid = problem["problem_id"]
        for model in config.models:
            for temp in config.temperatures:
                count += 1
                cell_key = ("measurement", pid, model, str(temp), judge_model)
                if cell_key in completed_cells:
                    continue
                label = f"[{count}/{total}] measurement: {pid} / {model} / temp={temp}"
                cells.append((config, problem, model, temp, judge_model,
                              output_dir, csv_path, log_path, label))
    return cells, total


def _build_validation_cells(config, problems, completed_cells, output_dir, csv_path, log_path):
    """Build list of (args_tuple) for validation cells."""
    import csv as csv_module

    # Load Phase 1 OK rows
    phase1_rows = []
    with open(csv_path, "r", newline="") as f:
        reader = csv_module.DictReader(f)
        for row in reader:
            if row["phase"] == "measurement" and row["status"] == "ok":
                phase1_rows.append(row)

    if not phase1_rows:
        print("No Phase 1 OK rows for validation")
        return [], 0

    # Stratified sampling
    strata = {}
    for row in phase1_rows:
        key = (row["model"], row["temperature"], row["domain"])
        strata.setdefault(key, []).append(row)

    seed = int(config.run_hash[:8], 16)
    rng = random.Random(seed)
    sampled_rows = []

    for key, group in strata.items():
        n = max(1, math.ceil(len(group) * config.validation_sample_fraction))
        sampled = rng.sample(group, min(n, len(group)))
        sampled_rows.extend(sampled)

    print(f"Validation: {len(sampled_rows)} sampled from {len(phase1_rows)} Phase 1 rows")

    problems_by_id = {p["problem_id"]: p for p in problems}
    total = len(sampled_rows) * len(config.judge_models)
    cells = []
    count = 0

    for row in sampled_rows:
        pid = row["problem_id"]
        model = row["model"]
        temp = float(row["temperature"])
        domain = row["domain"]
        problem = problems_by_id[pid]

        for judge_model in config.judge_models:
            count += 1
            cell_key = ("validation", pid, model, str(temp), judge_model)
            if cell_key in completed_cells:
                continue
            label = f"[{count}/{total}] validation: {pid} / {model} / temp={temp} / judge={judge_model}"
            cells.append((config, problem, model, temp, domain, judge_model,
                          row, output_dir, csv_path, log_path, label))
    return cells, total


def main():
    parser = argparse.ArgumentParser(description="Run sycophancy measurement experiment")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--resume", action="store_true", help="Skip completed cells")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    config = load_config(Path(args.config))
    problems = json.loads(config.problems_path.read_text())

    csv_path = config.output_dir / "results.csv"
    log_path = config.output_dir / "api_log.jsonl"
    output_dir = config.output_dir
    init_csv(csv_path)
    completed_cells = load_completed_cells(csv_path) if args.resume else set()

    print(f"=== Experiment: {len(problems)} problems, {len(config.models)} models, "
          f"{len(config.temperatures)} temperatures ===")
    if completed_cells:
        print(f"Resuming: {len(completed_cells)} cells already completed")

    # Phase 0: Baseline
    cells, total = _build_baseline_cells(config, problems, completed_cells,
                                         output_dir, csv_path, log_path)
    remaining = len(cells)
    print(f"\n--- Phase 0: Baseline ---")
    print(f"Phase 0: {total} cells total, {remaining} remaining after resume.")
    _run_phase("Phase 0", cells, _run_baseline_cell, args.workers)

    # Reload completed cells
    if args.resume:
        completed_cells = load_completed_cells(csv_path)

    # Phase 1: Measurement
    cells, total = _build_measurement_cells(config, problems, completed_cells,
                                            output_dir, csv_path, log_path)
    remaining = len(cells)
    print(f"\n--- Phase 1: Measurement ---")
    print(f"Phase 1: {total} cells total, {remaining} remaining after resume.")
    _run_phase("Phase 1", cells, _run_measurement_cell, args.workers)

    if args.resume:
        completed_cells = load_completed_cells(csv_path)

    # Phase 2: Validation
    cells, total = _build_validation_cells(config, problems, completed_cells,
                                           output_dir, csv_path, log_path)
    remaining = len(cells)
    print(f"\n--- Phase 2: Validation ---")
    print(f"Phase 2: {total} cells total, {remaining} remaining after resume.")
    _run_phase("Phase 2", cells, _run_validation_cell, args.workers)

    print("\n=== Experiment complete ===")


if __name__ == "__main__":
    main()
