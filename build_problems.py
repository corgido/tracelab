#!/usr/bin/env python3
"""Transform benchmark cases into the problem battery."""

import argparse
import json
import sys
from pathlib import Path

from src.api import call_api
from src.config import load_config
from src.logger import log_api_call


def _get_field(item: dict, primary: str, alternates: list[str], default=None, required=False):
    """Get a field value, trying primary key then alternates."""
    if primary in item:
        return item[primary]
    for alt in alternates:
        if alt in item:
            return item[alt]
    if required:
        return None  # Caller handles skip
    return default


def _normalize_benchmark(raw) -> list[dict]:
    """Extract the problems array from various top-level shapes."""
    if isinstance(raw, list):
        return raw

    for key in ("problems", "data", "examples", "items", "questions"):
        if key in raw:
            return raw[key]

    raise ValueError("Cannot find problems array in benchmark file")


def _parse_item(item: dict, index: int) -> dict | None:
    """Normalize a single benchmark item. Returns None if item should be skipped."""
    # ID
    problem_id = _get_field(item, "id", ["problem_id", "question_id"])
    if problem_id is None:
        problem_id = f"bench_{index:04d}"

    # Question (required)
    question = _get_field(item, "question", ["prompt", "input", "text"])
    if question is None:
        print(f"WARNING: Skipping item {index}: no question field found")
        return None

    # Opinion framing (required)
    opinion_framing = _get_field(item, "opinion_framing", ["sycophantic_prompt", "biased_prompt", "framing"])
    if opinion_framing is None:
        print(f"WARNING: Skipping item {index}: no opinion_framing field found")
        return None

    # Optional fields
    context = _get_field(item, "context", ["background"], default="")
    domain = _get_field(item, "domain", ["category", "topic"], default="general")
    behavioral_sycophancy = _get_field(item, "behavioral_sycophancy", ["sycophantic", "label"], default=None)

    return {
        "problem_id": problem_id,
        "context": context,
        "question": question,
        "opinion_framing": opinion_framing,
        "domain": domain,
        "behavioral_sycophancy": behavioral_sycophancy,
    }


def _parse_structural_metadata(raw_response: str) -> dict | None:
    """Extract structural metadata JSON from analyst response."""
    # Find outermost braces
    start = raw_response.find("{")
    if start == -1:
        return None

    depth = 0
    for i in range(start, len(raw_response)):
        if raw_response[i] == "{":
            depth += 1
        elif raw_response[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(raw_response[start:i + 1])
                    # Extract just the structural parts for structural_metadata
                    metadata = {}
                    # Map analyst output fields to structural_metadata
                    if "structure" in data:
                        structure = data["structure"]
                        metadata["critical_nodes"] = structure.get("essential_elements", [])
                        metadata["trap_nodes"] = structure.get("deceptive_elements", [])
                        metadata["dependency_orderings"] = []
                        # Extract orderings from dependency map connections
                        dep_map = structure.get("dependency_map", {})
                        for conn in dep_map.get("connections", []):
                            if conn.get("type") == "requires" and conn.get("strength") == "hard":
                                metadata["dependency_orderings"].append(conn)
                        metadata["valid_decompositions"] = structure.get("valid_organisations", [])
                    if "what_must_survive" in data:
                        survive = data["what_must_survive"]
                        metadata["expected_conflicts"] = survive.get("tensions_always_identified", [])
                    # Preserve full analyst output in metadata as well
                    metadata["full_analysis"] = data
                    return metadata
                except json.JSONDecodeError:
                    return None

    return None


def _assemble_battery_entry(parsed: dict, structural_metadata: dict) -> dict:
    """Assemble a battery entry from parsed benchmark fields + structural_metadata."""
    return {
        "problem_id": parsed["problem_id"],
        "domain": parsed["domain"],
        "problem_statement": {
            "context": parsed["context"],
            "question": parsed["question"],
        },
        "framing_variants": {
            "opinion_embedded": [
                {"framing": parsed["opinion_framing"]}
            ],
        },
        "structural_metadata": structural_metadata,
        "behavioral_sycophancy": parsed["behavioral_sycophancy"],
    }


def main():
    parser = argparse.ArgumentParser(description="Build problem battery from benchmark")
    parser.add_argument("--input", required=True, help="Path to benchmark.json")
    parser.add_argument("--output", default="problems/battery.json", help="Path for battery output")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--resume", action="store_true", help="Skip already-analyzed problems")
    args = parser.parse_args()

    config = load_config(Path(args.config), skip_problems_check=True)

    # Load benchmark
    raw = json.loads(Path(args.input).read_text())
    items = _normalize_benchmark(raw)

    # Load existing battery if resuming
    output_path = Path(args.output)
    battery = []
    existing_ids = set()
    if args.resume and output_path.exists():
        battery = json.loads(output_path.read_text())
        existing_ids = {entry["problem_id"] for entry in battery}
        print(f"Resuming: {len(existing_ids)} problems already in battery")

    # Load analyst prompt
    analyst_prompt = config.analyst_prompt_path.read_text()

    log_path = config.output_dir / "api_log.jsonl"

    skipped = 0
    added = 0

    for index, item in enumerate(items):
        parsed = _parse_item(item, index)
        if parsed is None:
            skipped += 1
            continue

        if parsed["problem_id"] in existing_ids:
            continue

        # Call analyst
        prompt = (
            analyst_prompt
            .replace("{{CONTEXT}}", parsed["context"])
            .replace("{{QUESTION}}", parsed["question"])
        )

        try:
            response = call_api(
                config.analyst_model, prompt, temperature=0,
                max_retries=config.max_retries, backoff_base=config.backoff_base,
                seed=42,
            )
            log_api_call(log_path, config.analyst_model, 0, "build",
                         "analyst", parsed["problem_id"], prompt, response)
            structural_metadata = _parse_structural_metadata(response.content)
            if structural_metadata is None:
                print(f"WARNING: Could not parse analyst output for {parsed['problem_id']}, skipping")
                skipped += 1
                continue
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log_api_call(log_path, config.analyst_model, 0, "build",
                         "analyst", parsed["problem_id"], prompt, None, str(e))
            print(f"WARNING: API error for {parsed['problem_id']}: {e}, skipping")
            skipped += 1
            continue

        entry = _assemble_battery_entry(parsed, structural_metadata)
        battery.append(entry)
        existing_ids.add(parsed["problem_id"])
        added += 1

        # Crash-safe: write after each problem
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(battery, indent=2))
        print(f"  [{added}] {parsed['problem_id']} ({parsed['domain']})")

    # Summary
    domains = {}
    gt_count = 0
    for entry in battery:
        d = entry.get("domain", "general")
        domains[d] = domains.get(d, 0) + 1
        if entry.get("behavioral_sycophancy") is not None:
            gt_count += 1

    print(f"\nSummary:")
    print(f"  Total problems: {len(battery)}")
    print(f"  Domains: {domains}")
    print(f"  With behavioral ground truth: {gt_count}")
    print(f"  Skipped: {skipped}")


if __name__ == "__main__":
    main()
