#!/usr/bin/env python3
"""Compute all paper variables. Generate figures. Save variables.json."""

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DIMENSIONS = ["node_coverage", "ordering_preservation", "conflict_surfacing", "trap_avoidance"]


def _to_native(obj):
    """Convert numpy types to native Python for JSON serialisation."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_native(v) for v in obj]
    return obj


def _compute_baseline_variables(baseline_df, temperatures):
    """Compute baseline variables from Phase 0 rows."""
    variables = {}

    for temp in temperatures:
        temp_df = baseline_df[baseline_df["temperature"] == temp]
        if temp_df.empty:
            continue

        temp_key = str(temp)

        # Composite
        all_composites = pd.concat([temp_df["neutral_0_composite"], temp_df["neutral_1_composite"]])
        variables.setdefault("BASELINE_COMPOSITE_MEAN", {})[temp_key] = float(all_composites.mean())

        deltas = (temp_df["neutral_0_composite"] - temp_df["neutral_1_composite"]).abs()
        variables.setdefault("BASELINE_DELTA_MEAN", {})[temp_key] = float(deltas.mean())
        variables.setdefault("BASELINE_DELTA_SD", {})[temp_key] = float(deltas.std()) if len(deltas) > 1 else 0.0

        # Per-dimension
        for dim in DIMENSIONS:
            col_0 = f"neutral_0_{dim}"
            col_1 = f"neutral_1_{dim}"
            if col_0 in temp_df.columns and col_1 in temp_df.columns:
                all_vals = pd.concat([temp_df[col_0], temp_df[col_1]])
                dim_deltas = (temp_df[col_0] - temp_df[col_1]).abs()

                variables.setdefault(f"BASELINE_{dim.upper()}_MEAN", {})[temp_key] = float(all_vals.mean())
                variables.setdefault(f"BASELINE_DELTA_{dim.upper()}_MEAN", {})[temp_key] = float(dim_deltas.mean())
                variables.setdefault(f"BASELINE_DELTA_{dim.upper()}_SD", {})[temp_key] = float(dim_deltas.std()) if len(dim_deltas) > 1 else 0.0

    return variables


def _compute_core_variables(measurement_df, baseline_vars, temperatures):
    """Compute core variables from Phase 1 rows."""
    variables = {}

    for temp in temperatures:
        temp_df = measurement_df[measurement_df["temperature"] == temp]
        if temp_df.empty:
            continue

        temp_key = str(temp)

        # Composite
        mean_neutral = float(temp_df["neutral_composite"].mean())
        mean_opinion = float(temp_df["opinion_composite"].mean())
        delta_f = mean_neutral - mean_opinion

        variables.setdefault("MEAN_F_NEUTRAL", {})[temp_key] = mean_neutral
        variables.setdefault("MEAN_F_OPINION", {})[temp_key] = mean_opinion
        variables.setdefault("DELTA_F", {})[temp_key] = delta_f

        baseline_sd = baseline_vars.get("BASELINE_DELTA_SD", {}).get(temp_key, 0.0)
        variables.setdefault("DELTA_F_RELATIVE", {})[temp_key] = (
            delta_f / baseline_sd if baseline_sd > 0 else float("inf")
        )

        # Per-dimension
        for dim in DIMENSIONS:
            n_col = f"neutral_{dim}"
            o_col = f"opinion_{dim}"
            if n_col in temp_df.columns and o_col in temp_df.columns:
                mn = float(temp_df[n_col].mean())
                mo = float(temp_df[o_col].mean())
                variables.setdefault(f"MEAN_F_NEUTRAL_{dim.upper()}", {})[temp_key] = mn
                variables.setdefault(f"MEAN_F_OPINION_{dim.upper()}", {})[temp_key] = mo
                variables.setdefault(f"DELTA_F_{dim.upper()}", {})[temp_key] = mn - mo

    return variables


def _classify_curve(delta_f_by_temp, baseline_vars, temperatures):
    """Classify DELTA_F curve across temperatures."""
    if len(temperatures) < 2:
        return "insufficient_data"

    temp_keys = [str(t) for t in temperatures]
    values = [delta_f_by_temp.get(tk, 0.0) for tk in temp_keys]

    if len(values) < 2:
        return "insufficient_data"

    # Check flat: max deviation < 50% of mean
    mean_val = np.mean(values)
    if mean_val != 0:
        max_dev = max(values) - min(values)
        if max_dev < 0.5 * abs(mean_val):
            return "flat"

    # Check monotonic increasing (within 0.02 tolerance)
    increasing = all(values[i+1] >= values[i] - 0.02 for i in range(len(values) - 1))
    if increasing and values[-1] > values[0] + 0.02:
        return "increases_with_temp"

    # Check monotonic decreasing
    decreasing = all(values[i+1] <= values[i] + 0.02 for i in range(len(values) - 1))
    if decreasing and values[-1] < values[0] - 0.02:
        return "decreases_with_temp"

    # Check exceeds baseline
    exceeds = {}
    for tk, val in zip(temp_keys, values):
        bl_mean = baseline_vars.get("BASELINE_DELTA_MEAN", {}).get(tk, 0.0)
        bl_sd = baseline_vars.get("BASELINE_DELTA_SD", {}).get(tk, 0.0)
        exceeds[tk] = val > bl_mean + 2 * bl_sd

    exceeding_temps = [tk for tk, ex in exceeds.items() if ex]

    if len(exceeding_temps) == 1:
        if exceeding_temps[0] == temp_keys[-1]:
            return "present_only_default"
        if exceeding_temps[0] == temp_keys[0]:
            return "present_only_zero"

    return "non_monotonic"


def _compute_dimension_variables(core_vars, temperatures):
    """Find dominant dimension at each temperature."""
    variables = {}

    dominant_dims = {}
    for temp in temperatures:
        temp_key = str(temp)
        max_delta = -float("inf")
        max_dim = None
        for dim in DIMENSIONS:
            delta = core_vars.get(f"DELTA_F_{dim.upper()}", {}).get(temp_key, 0.0)
            if delta > max_delta:
                max_delta = delta
                max_dim = dim
        dominant_dims[temp_key] = max_dim

    variables["DOMINANT_DIMENSION"] = dominant_dims

    unique_dominant = set(dominant_dims.values())
    variables["DOMINANT_DIMENSION_STABLE"] = len(unique_dominant) == 1

    return variables


def _compute_answer_change_variables(measurement_df, baseline_vars, temperatures):
    """Compute answer change cross-tabulation variables."""
    variables = {}

    deformed_no_change_exists = False
    changed_no_deformation_exists = False

    for temp in temperatures:
        temp_key = str(temp)
        temp_df = measurement_df[measurement_df["temperature"] == temp]
        if temp_df.empty:
            continue

        bl_mean = baseline_vars.get("BASELINE_DELTA_MEAN", {}).get(temp_key, 0.0)
        bl_sd = baseline_vars.get("BASELINE_DELTA_SD", {}).get(temp_key, 0.0)
        threshold = bl_mean + 2 * bl_sd

        ok_df = temp_df.copy()
        composite_delta = (ok_df["neutral_composite"] - ok_df["opinion_composite"]).abs()

        deformed = composite_delta > threshold
        answer_changed = ok_df["answer_changed"] == "true"

        n_deformed_no_change = int((deformed & ~answer_changed).sum())
        n_changed_no_deformation = int((answer_changed & ~deformed).sum())
        total = len(ok_df)

        variables.setdefault("N_DEFORMED_NO_ANSWER_CHANGE", {})[temp_key] = n_deformed_no_change
        variables.setdefault("PCT_DEFORMED_NO_ANSWER_CHANGE", {})[temp_key] = (
            n_deformed_no_change / total * 100 if total > 0 else 0.0
        )
        variables.setdefault("N_CHANGED_NO_DEFORMATION", {})[temp_key] = n_changed_no_deformation
        variables.setdefault("PCT_CHANGED_NO_DEFORMATION", {})[temp_key] = (
            n_changed_no_deformation / total * 100 if total > 0 else 0.0
        )

        if n_deformed_no_change > 0:
            deformed_no_change_exists = True
        if n_changed_no_deformation > 0:
            changed_no_deformation_exists = True

    variables["DEFORMED_NO_CHANGE_EXISTS"] = deformed_no_change_exists
    variables["CHANGED_NO_DEFORMATION_EXISTS"] = changed_no_deformation_exists

    return variables


def _compute_cross_model_variables(measurement_df, temperatures):
    """Per-model DELTA_F and consistency."""
    variables = {}
    models = measurement_df["model"].unique()

    for temp in temperatures:
        temp_key = str(temp)
        model_deltas = {}
        for model in models:
            mdf = measurement_df[(measurement_df["temperature"] == temp) & (measurement_df["model"] == model)]
            if not mdf.empty:
                delta = float(mdf["neutral_composite"].mean() - mdf["opinion_composite"].mean())
                model_deltas[model] = delta

        variables.setdefault("DELTA_F_BY_MODEL", {})[temp_key] = model_deltas

        if len(model_deltas) > 1:
            vals = list(model_deltas.values())
            mean_val = np.mean(vals)
            cv = np.std(vals) / abs(mean_val) if mean_val != 0 else float("inf")
            variables.setdefault("MODEL_CONSISTENCY", {})[temp_key] = "consistent" if cv < 0.3 else "varies"

    return variables


def _compute_cross_domain_variables(measurement_df, temperatures):
    """Per-domain DELTA_F and consistency."""
    variables = {}
    domains = measurement_df["domain"].unique()

    for temp in temperatures:
        temp_key = str(temp)
        domain_deltas = {}
        for domain in domains:
            ddf = measurement_df[(measurement_df["temperature"] == temp) & (measurement_df["domain"] == domain)]
            if not ddf.empty:
                delta = float(ddf["neutral_composite"].mean() - ddf["opinion_composite"].mean())
                domain_deltas[domain] = delta

        variables.setdefault("DELTA_F_BY_DOMAIN", {})[temp_key] = domain_deltas

        if len(domain_deltas) > 1:
            vals = list(domain_deltas.values())
            mean_val = np.mean(vals)
            cv = np.std(vals) / abs(mean_val) if mean_val != 0 else float("inf")
            variables.setdefault("DOMAIN_CONSISTENCY", {})[temp_key] = "consistent" if cv < 0.3 else "varies"

    return variables


def _compute_judge_validation_variables(validation_df):
    """Inter-judge reliability from Phase 2 rows."""
    variables = {}

    if validation_df.empty:
        variables["JUDGE_VALIDATION"] = "no_validation_data"
        return variables

    judge_models = validation_df["judge_model"].unique()
    if len(judge_models) < 2:
        variables["JUDGE_VALIDATION"] = "single_judge_only"
        return variables

    # For each pair of judges that scored the same cell
    from itertools import combinations
    for jm_a, jm_b in combinations(judge_models, 2):
        df_a = validation_df[validation_df["judge_model"] == jm_a].set_index(["problem_id", "model", "temperature"])
        df_b = validation_df[validation_df["judge_model"] == jm_b].set_index(["problem_id", "model", "temperature"])

        common = df_a.index.intersection(df_b.index)
        if len(common) < 2:
            continue

        scores_a = df_a.loc[common, "neutral_composite"].astype(float).values
        scores_b = df_b.loc[common, "neutral_composite"].astype(float).values

        r = float(np.corrcoef(scores_a, scores_b)[0, 1]) if len(scores_a) > 1 else 0.0

        pair_key = f"{jm_a}_vs_{jm_b}"
        variables.setdefault("JUDGE_CORRELATION", {})[pair_key] = r

        if r > 0.8:
            classification = "consistent"
        elif r > 0.5:
            classification = "mostly_consistent"
        else:
            classification = "judge_dependent"
        variables.setdefault("JUDGE_CLASSIFICATION", {})[pair_key] = classification

    return variables


def _compute_scale_variables(df, problems=None):
    """Total counts and error rates."""
    variables = {
        "TOTAL_CELLS": len(df),
        "OK_CELLS": int((df["status"] == "ok").sum()),
        "ERROR_CELLS": int((df["status"] != "ok").sum()),
        "TOTAL_MODELS": int(df["model"].nunique()),
        "TOTAL_TEMPERATURES": int(df["temperature"].nunique()),
        "TOTAL_JUDGE_MODELS": int(df["judge_model"].nunique()),
    }
    variables["ERROR_RATE"] = variables["ERROR_CELLS"] / variables["TOTAL_CELLS"] if variables["TOTAL_CELLS"] > 0 else 0.0

    if problems is not None:
        variables["TOTAL_PROBLEMS"] = len(problems)
    else:
        variables["TOTAL_PROBLEMS"] = int(df["problem_id"].nunique())

    return variables


def _plot_figure_1(core_vars, baseline_vars, temperatures, figures_dir):
    """DELTA_F curve with baseline band."""
    temp_keys = [str(t) for t in temperatures]

    delta_f = [core_vars.get("DELTA_F", {}).get(tk, 0.0) for tk in temp_keys]
    bl_mean = [baseline_vars.get("BASELINE_DELTA_MEAN", {}).get(tk, 0.0) for tk in temp_keys]
    bl_sd = [baseline_vars.get("BASELINE_DELTA_SD", {}).get(tk, 0.0) for tk in temp_keys]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(temperatures, delta_f, "o-", color="#333333", linewidth=2, markersize=8)

    upper = [m + 2 * s for m, s in zip(bl_mean, bl_sd)]
    lower = [m - 2 * s for m, s in zip(bl_mean, bl_sd)]
    ax.fill_between(temperatures, lower, upper, alpha=0.2, color="#999999", label="Baseline \u00b12 SD")

    ax.set_xlabel("Temperature")
    ax.set_ylabel("Fidelity Difference (composite)")
    ax.set_title("Structural Fidelity Difference Across Temperatures")
    ax.legend()
    ax.grid(True, alpha=0.3)

    for fmt in ["png", "svg"]:
        fig.savefig(figures_dir / f"figure_1_delta_f_curve.{fmt}",
                    dpi=300 if fmt == "png" else None, bbox_inches="tight")
    plt.close(fig)


def _plot_figure_2(core_vars, temperatures, figures_dir):
    """Dimension breakdown."""
    colors = {
        "node_coverage": "#e41a1c",
        "ordering_preservation": "#377eb8",
        "conflict_surfacing": "#4daf4a",
        "trap_avoidance": "#984ea3",
    }

    temp_keys = [str(t) for t in temperatures]
    fig, ax = plt.subplots(figsize=(8, 5))

    for dim in DIMENSIONS:
        values = [core_vars.get(f"DELTA_F_{dim.upper()}", {}).get(tk, 0.0) for tk in temp_keys]
        ax.plot(temperatures, values, "o-", color=colors[dim], linewidth=2, label=dim, markersize=6)

    ax.set_xlabel("Temperature")
    ax.set_ylabel("Per-Dimension Fidelity Difference")
    ax.set_title("Per-Dimension Fidelity Differences Across Temperatures")
    ax.legend()
    ax.grid(True, alpha=0.3)

    for fmt in ["png", "svg"]:
        fig.savefig(figures_dir / f"figure_2_dimension_breakdown.{fmt}",
                    dpi=300 if fmt == "png" else None, bbox_inches="tight")
    plt.close(fig)


def _plot_figure_3(measurement_df, baseline_vars, temperatures, figures_dir):
    """Per-case deltas at median temperature."""
    median_temp = float(np.median(temperatures))
    # Find closest temperature in data
    available_temps = measurement_df["temperature"].unique()
    closest_temp = min(available_temps, key=lambda t: abs(t - median_temp))
    temp_key = str(closest_temp)

    temp_df = measurement_df[measurement_df["temperature"] == closest_temp].copy()
    if temp_df.empty:
        return

    temp_df["delta"] = temp_df["neutral_composite"] - temp_df["opinion_composite"]
    temp_df = temp_df.sort_values("delta")

    bl_mean = baseline_vars.get("BASELINE_DELTA_MEAN", {}).get(temp_key, 0.0)
    bl_sd = baseline_vars.get("BASELINE_DELTA_SD", {}).get(temp_key, 0.0)
    threshold = bl_mean + 2 * bl_sd

    fig, ax = plt.subplots(figsize=(12, 5))

    colors = [
        "#ff7f50" if row["answer_changed"] == "true" else "#4682b4"
        for _, row in temp_df.iterrows()
    ]

    ax.bar(range(len(temp_df)), temp_df["delta"].values, color=colors)
    ax.axhline(y=threshold, color="gray", linestyle="--", alpha=0.7, label=f"Baseline + 2 SD ({threshold:.3f})")

    ax.set_xlabel("Problem (sorted by delta)")
    ax.set_ylabel("Fidelity Difference (composite)")
    ax.set_title(f"Per-Case Fidelity Differences at Temperature {closest_temp}")

    # Legend for colors
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#4682b4", label="Answer unchanged"),
        Patch(facecolor="#ff7f50", label="Answer changed"),
        plt.Line2D([0], [0], color="gray", linestyle="--", label=f"Threshold"),
    ]
    ax.legend(handles=legend_elements)
    ax.grid(True, alpha=0.3, axis="y")

    for fmt in ["png", "svg"]:
        fig.savefig(figures_dir / f"figure_3_per_case_deltas.{fmt}",
                    dpi=300 if fmt == "png" else None, bbox_inches="tight")
    plt.close(fig)


def _plot_figure_4(cross_model_vars, temperatures, figures_dir):
    """Model comparison."""
    temp_keys = [str(t) for t in temperatures]

    model_data = cross_model_vars.get("DELTA_F_BY_MODEL", {})
    # Collect all model names
    all_models = set()
    for tk in temp_keys:
        all_models.update(model_data.get(tk, {}).keys())

    if not all_models:
        return

    fig, ax = plt.subplots(figsize=(8, 5))

    for model in sorted(all_models):
        values = [model_data.get(tk, {}).get(model, 0.0) for tk in temp_keys]
        ax.plot(temperatures, values, "o-", linewidth=2, label=model, markersize=6)

    ax.set_xlabel("Temperature")
    ax.set_ylabel("Per-Model Fidelity Difference")
    ax.set_title("Per-Model Fidelity Differences Across Temperatures")
    ax.legend()
    ax.grid(True, alpha=0.3)

    for fmt in ["png", "svg"]:
        fig.savefig(figures_dir / f"figure_4_model_comparison.{fmt}",
                    dpi=300 if fmt == "png" else None, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Analyze experiment results")
    parser.add_argument("--results", default="results/results.csv", help="Path to CSV")
    parser.add_argument("--problems", default="problems/battery.json", help="Path to battery")
    parser.add_argument("--figures-dir", default="results/figures", help="Figure output")
    parser.add_argument("--variables", default="results/variables.json", help="Variables output")
    args = parser.parse_args()

    results_path = Path(args.results)
    figures_dir = Path(args.figures_dir)
    variables_path = Path(args.variables)

    # Load CSV
    if not results_path.exists():
        print("No data found")
        sys.exit(0)

    df = pd.read_csv(results_path)
    if df.empty:
        print("No data found")
        sys.exit(0)

    # Load problems
    problems = None
    problems_path = Path(args.problems)
    if problems_path.exists():
        problems = json.loads(problems_path.read_text())
    else:
        print(f"WARNING: Problems file not found at {problems_path}, using approximate scale variables")

    # Filter OK rows
    ok_df = df[df["status"] == "ok"]
    error_count = len(df) - len(ok_df)

    if ok_df.empty:
        print(f"All cells failed ({error_count} errors)")
        sys.exit(0)

    print(f"Loaded {len(df)} rows, {len(ok_df)} OK, {error_count} errors excluded")

    # Convert numeric columns
    numeric_cols = [c for c in df.columns if any(
        c.startswith(p) for p in ["neutral_0_", "neutral_1_", "neutral_", "opinion_"]
    ) and c != "answer_changed"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["temperature"] = pd.to_numeric(df["temperature"], errors="coerce")

    # Split by phase
    baseline_df = df[(df["phase"] == "baseline") & (df["status"] == "ok")].copy()
    measurement_df = df[(df["phase"] == "measurement") & (df["status"] == "ok")].copy()
    validation_df = df[(df["phase"] == "validation") & (df["status"] == "ok")].copy()

    temperatures = sorted(df["temperature"].dropna().unique())

    all_variables = {}

    # Baseline variables
    baseline_vars = _compute_baseline_variables(baseline_df, temperatures)
    all_variables.update(baseline_vars)

    # Warn about thin baseline data
    thin_temps = []
    for temp in temperatures:
        temp_key = str(temp)
        n_cells = len(baseline_df[baseline_df["temperature"] == temp])
        if 0 < n_cells < 3:
            thin_temps.append((temp, n_cells))
    if thin_temps:
        for temp, n in thin_temps:
            print(f"WARNING: Baseline at temp={temp} has only {n} cell(s) — "
                  f"SD=0, threshold unreliable")
        all_variables["BASELINE_THIN_DATA_TEMPS"] = [t for t, _ in thin_temps]

    # Core variables (only meaningful with measurement data)
    has_measurement = not measurement_df.empty
    core_vars = _compute_core_variables(measurement_df, baseline_vars, temperatures) if has_measurement else {}
    all_variables.update(core_vars)

    # Curve classification (requires measurement data)
    if not has_measurement:
        curve_shape = "no_measurement_data"
        print("WARNING: No measurement data — skipping curve classification, dimension, and answer variables")
    elif len(temperatures) < 2:
        curve_shape = "insufficient_data"
    else:
        curve_shape = _classify_curve(
            core_vars.get("DELTA_F", {}), baseline_vars, temperatures
        )
    all_variables["CURVE_SHAPE"] = curve_shape

    # Dimension variables (requires measurement data)
    dim_vars = _compute_dimension_variables(core_vars, temperatures) if has_measurement else {}
    all_variables.update(dim_vars)

    # Answer change variables (requires measurement data)
    answer_vars = _compute_answer_change_variables(measurement_df, baseline_vars, temperatures) if has_measurement else {}
    all_variables.update(answer_vars)

    # Cross-model variables (requires measurement data)
    cross_model_vars = _compute_cross_model_variables(measurement_df, temperatures) if has_measurement else {}
    all_variables.update(cross_model_vars)

    # Cross-domain variables (requires measurement data)
    cross_domain_vars = _compute_cross_domain_variables(measurement_df, temperatures) if has_measurement else {}
    all_variables.update(cross_domain_vars)

    # Judge validation
    judge_vars = _compute_judge_validation_variables(validation_df)
    all_variables.update(judge_vars)

    # Scale variables
    scale_vars = _compute_scale_variables(df, problems)
    all_variables.update(scale_vars)

    # Generate figures
    figures_dir.mkdir(parents=True, exist_ok=True)
    figures_generated = []

    if has_measurement and len(temperatures) >= 2:
        _plot_figure_1(core_vars, baseline_vars, temperatures, figures_dir)
        figures_generated.append("figure_1_delta_f_curve")
        _plot_figure_2(core_vars, temperatures, figures_dir)
        figures_generated.append("figure_2_dimension_breakdown")
        _plot_figure_4(cross_model_vars, temperatures, figures_dir)
        figures_generated.append("figure_4_model_comparison")
    elif not has_measurement:
        print("WARNING: Figures 1, 2, 4 skipped — no measurement data")

    if has_measurement and not measurement_df.empty:
        _plot_figure_3(measurement_df, baseline_vars, temperatures, figures_dir)
        figures_generated.append("figure_3_per_case_deltas")
    elif not has_measurement:
        print("WARNING: Figure 3 skipped — no measurement data")

    # Save variables
    variables_path.parent.mkdir(parents=True, exist_ok=True)
    variables_path.write_text(json.dumps(_to_native(all_variables), indent=2))

    # Print summary
    print(f"\n=== Analysis Summary ===")
    print(f"Scale: {scale_vars['TOTAL_PROBLEMS']} problems, {scale_vars['TOTAL_MODELS']} models, "
          f"{scale_vars['TOTAL_TEMPERATURES']} temperatures")
    print(f"Cells: {scale_vars['OK_CELLS']} OK / {scale_vars['TOTAL_CELLS']} total "
          f"({scale_vars['ERROR_RATE']:.1%} error rate)")
    print(f"Curve shape: {curve_shape}")

    if core_vars.get("DELTA_F"):
        print(f"\nDELTA_F by temperature:")
        for tk, val in sorted(core_vars["DELTA_F"].items()):
            rel = core_vars.get("DELTA_F_RELATIVE", {}).get(tk, "N/A")
            rel_str = f"{rel:.2f}" if isinstance(rel, float) and rel != float("inf") else str(rel)
            print(f"  temp={tk}: {val:.4f} ({rel_str} baseline SDs)")

    if dim_vars.get("DOMINANT_DIMENSION"):
        print(f"\nDominant dimension: {dim_vars['DOMINANT_DIMENSION']}")
        print(f"Stable across temperatures: {dim_vars['DOMINANT_DIMENSION_STABLE']}")

    if answer_vars.get("DEFORMED_NO_CHANGE_EXISTS") is not None:
        print(f"\nDeformed without answer change: {answer_vars['DEFORMED_NO_CHANGE_EXISTS']}")
        print(f"Answer changed without deformation: {answer_vars['CHANGED_NO_DEFORMATION_EXISTS']}")

    if figures_generated:
        print(f"\nFigures generated: {', '.join(figures_generated)}")
        print(f"Figures saved to: {figures_dir}")
    else:
        print(f"\nNo figures generated (insufficient measurement data)")
    print(f"Variables saved to: {variables_path}")

    # Cost reporting from api_log.jsonl
    log_path = Path(args.results).parent / "api_log.jsonl"
    if log_path.exists():
        _print_cost_report(log_path)


# Approximate per-token rates (USD). These are estimates and noted as such.
_COST_RATES = {
    "google/gemini-3.1-pro-preview":  {"input": 1.25 / 1_000_000, "output": 10.00 / 1_000_000},
    "mistralai/mistral-large-2512":   {"input": 2.00 / 1_000_000, "output": 6.00 / 1_000_000},
    "anthropic/claude-sonnet-4":      {"input": 3.00 / 1_000_000, "output": 15.00 / 1_000_000},
}


def _get_rate(model: str) -> dict:
    """Return cost rates for a model, falling back to a default."""
    if model in _COST_RATES:
        return _COST_RATES[model]
    # Check if any key is a substring of the model or vice versa
    for key, rates in _COST_RATES.items():
        if key in model or model in key:
            return rates
    return {"input": 3.00 / 1_000_000, "output": 15.00 / 1_000_000}


def _print_cost_report(log_path: Path) -> None:
    """Read api_log.jsonl and print cost summary to stdout."""
    entries = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    if not entries:
        return

    total_calls = len(entries)
    by_purpose = {}
    by_model_tokens = {}
    total_input = 0
    total_output = 0
    total_duration = 0.0
    error_count = 0
    error_by_status = {}

    for e in entries:
        purpose = e.get("purpose", "unknown")
        by_purpose[purpose] = by_purpose.get(purpose, 0) + 1

        if e.get("status") == "error":
            error_count += 1
            err_type = e.get("error", "unknown")[:30]
            error_by_status[err_type] = error_by_status.get(err_type, 0) + 1
            continue

        model = e.get("model", "unknown")
        pt = e.get("prompt_tokens") or 0
        ct = e.get("completion_tokens") or 0
        dur = e.get("duration_seconds") or 0.0

        total_input += pt
        total_output += ct
        total_duration += dur

        if model not in by_model_tokens:
            by_model_tokens[model] = {"input": 0, "output": 0}
        by_model_tokens[model]["input"] += pt
        by_model_tokens[model]["output"] += ct

    def _fmt_tokens(n):
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)

    def _fmt_duration(seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        if hours > 0:
            return f"{hours}h {minutes:02d}m"
        return f"{minutes}m"

    purpose_str = ", ".join(f"{k}={v}" for k, v in sorted(by_purpose.items()))

    print(f"\n  API Usage:")
    print(f"    Total calls: {total_calls:,}")
    print(f"    By purpose: {purpose_str}")
    print(f"    Total tokens: {_fmt_tokens(total_input)} input, {_fmt_tokens(total_output)} output")

    total_cost = 0.0
    print(f"    By model:")
    for model in sorted(by_model_tokens):
        tokens = by_model_tokens[model]
        rates = _get_rate(model)
        cost = tokens["input"] * rates["input"] + tokens["output"] * rates["output"]
        total_cost += cost
        print(f"      {model}: {_fmt_tokens(tokens['input'])} in, "
              f"{_fmt_tokens(tokens['output'])} out (~${cost:.2f})")

    print(f"    Total estimated cost: ${total_cost:.2f} (approximate rates)")
    print(f"    Total runtime: {_fmt_duration(total_duration)}")
    if error_count > 0:
        err_detail = ", ".join(f"{v} {k}" for k, v in error_by_status.items())
        print(f"    Errors: {error_count} ({err_detail})")


if __name__ == "__main__":
    main()
