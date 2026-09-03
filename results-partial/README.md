# Partial results

Outputs from an incomplete experimental run on 2026-04-04 (18:07 to
20:29 UTC). The run covered 15 problems × 2 subject models (Gemini 3.1
Pro Preview, GPT-4.1) × 5 temperatures and exhausted its OpenRouter
credits during the measurement phase: 250 of the 261 logged API errors
are "This request requires more credits" refusals (the balance fell
below the amount reserved for the 64k-token output cap). 539 subject
traces were collected before the run stopped; they are in `../traces/`.

These outputs are included for transparency and to demonstrate the
pipeline's output format. They should not be treated as experimental
findings. See the main README for why the scores are not meaningful
even where they exist.

## Files

- `results.csv`: 524 rows, one per attempted (phase, problem, model,
  temperature, judge) cell. Status counts: `ok` 260, `api_error` 261,
  `cartographer_parse_error` 2, `upstream_parse_error` 1 (50.4% of
  rows are errors). By phase: baseline 172 rows (159 ok), measurement
  150 (101 ok), validation 202 (0 ok; every validation call failed on
  credits, so no cross-judge data exists). Known quirks: 10 rows are
  for `mistralai/mistral-large-2512`, a subject model tried before the
  run and removed from `config.yaml`, all `api_error` ("no endpoints
  available"); 101 rows carry the second judge `openai/gpt-5.4-mini`,
  all `api_error`; the temperature column contains both `0` and `0.0`;
  12 rows repeat a resume key already present (cells re-run after the
  path fix described in `../traces/README.md`).
- `results-run-1.csv`: a snapshot of `results.csv` taken at 20:03 UTC
  during the run (151 baseline rows, all contained in `results.csv`).
  Kept as found.
- `variables.json`: output of `analyze_results.py` over `results.csv`
  (53 keys). Headline values: `DELTA_F` per temperature is 0.005,
  0.025, -0.021, -0.027, 0.018 against a baseline neutral-vs-neutral
  delta of 0.08 to 0.17 (SD 0.11 to 0.14); `CURVE_SHAPE` is
  `non_monotonic`; `JUDGE_VALIDATION` is `no_validation_data`.
- `figures/`: the four figures `analyze_results.py` draws (PNG and
  SVG), generated 2026-04-12 from `results.csv`. Not regenerated for
  this release; re-running the script reproduces `variables.json`
  exactly.
- `api_log.jsonl`: 1,653 API calls (1,392 ok) with model, purpose,
  phase, problem, prompt hash, token counts, duration, and error text.
  Contains no prompt or response text.
- `judge_outputs/`: 269 judge results (268 parsed), one per judged
  pair, with the parsed convergence/divergence structure and the raw
  XML.
- `cartographer_outputs/`: 267 cartographer results (264 parsed) with
  the extracted per-trace scores and the raw JSON response.
- `answer_extractions/`: 202 one-sentence recommendation summaries
  extracted from measurement traces for the answer-change comparison.

`judge_outputs/` and `cartographer_outputs/` each contain three
subdirectories named `baseline__{problem}__google/`. These hold the
first-pass outputs written before the model id's `/` was sanitised
(see `../traces/README.md`). They are left exactly as the run wrote
them.
