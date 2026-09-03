"""Manage the results CSV."""

import csv
from pathlib import Path

ALL_FIELDS: list[str] = [
    # Common columns
    "phase",
    "problem_id",
    "domain",
    "condition_pair",
    "model",
    "temperature",
    "judge_model",
    "status",
    "timestamp",
    # Baseline score columns (Phase 0)
    "neutral_0_node_coverage",
    "neutral_0_ordering_preservation",
    "neutral_0_conflict_surfacing",
    "neutral_0_trap_avoidance",
    "neutral_0_composite",
    "neutral_1_node_coverage",
    "neutral_1_ordering_preservation",
    "neutral_1_conflict_surfacing",
    "neutral_1_trap_avoidance",
    "neutral_1_composite",
    # Measurement score columns (Phase 1 and Phase 2)
    "neutral_node_coverage",
    "neutral_ordering_preservation",
    "neutral_conflict_surfacing",
    "neutral_trap_avoidance",
    "neutral_composite",
    "opinion_node_coverage",
    "opinion_ordering_preservation",
    "opinion_conflict_surfacing",
    "opinion_trap_avoidance",
    "opinion_composite",
    "answer_changed",
]


def init_csv(path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=ALL_FIELDS)
            writer.writeheader()


def append_row(path: Path, row: dict) -> None:
    path = Path(path)
    # Fill missing keys with empty string
    complete_row = {field: row.get(field, "") for field in ALL_FIELDS}
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ALL_FIELDS)
        writer.writerow(complete_row)


def load_completed_cells(path: Path) -> set[tuple]:
    path = Path(path)
    if not path.exists():
        return set()

    cells = set()
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cells.add((
                row["phase"],
                row["problem_id"],
                row["model"],
                str(row["temperature"]),
                row["judge_model"],
            ))
    return cells
