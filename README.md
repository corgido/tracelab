# tracelab

An experiment measuring whether user opinions deform how LLMs
organise their reasoning, not just whether they change their answer.

This is a research artifact release, not a library. It contains the
experimental harness, the 15-problem benchmark, the 984-line build
specification the harness was implemented from, 539 raw model traces,
and the outputs of one incomplete run. The traces are the primary
artifact. The automated scoring layer runs, but its numbers are not
meaningful, for reasons documented below.

## The question

Sycophancy in LLMs is usually measured as answer change: did the model
agree with the user? But a model can deform *how* it reasons without
changing *what* it concludes. When a user says "I think they should
close School C," the model might still recommend closing School C, but
it restructures its response to engage the user's position first,
validate their reasoning, then proceed to the analysis it would have
given anyway. The conclusion is the same. The reasoning path is
different.

This experiment tried to measure that structural deformation. Each
benchmark problem is a multi-stakeholder policy dilemma with a neutral
framing and an opinion-embedded framing. Subject models answer both.
A blind judge describes how the two responses differ in structure; a
second instrument, the cartographer, scores each response's fidelity
to a pre-computed structural skeleton of the problem; a baseline phase
measures how much two neutral responses differ from each other, so
that the opinion effect can be compared against natural variation.
The design is described in [Design](#design) and specified in full in
[`CLAUDE.md`](CLAUDE.md).

## What worked

The experimental design and the harness. Blinding is deterministic
per cell (the judge sees "Response A" and "Response B", assigned by a
seed derived from the cell coordinates, so a validation pass recovers
the same assignment without re-randomising). The baseline phase gives
a within-condition noise floor. The validation phase re-scores a
stratified sample with a second judge model. Every trace, judge
output, and cartographer output is written atomically to a file named
by its experimental coordinates, and the runner resumes from those
files. Every API call is logged with a prompt hash, token counts, and
status; errors become CSV rows with a descriptive status rather than
crashes. The run hash covers the config and all three instrument
prompts.

The 15 benchmark problems (`benchmark.json`) are rich civic-policy
dilemmas where reasoning structure matters: school closures, lead
pipe replacement, reservoir flood management, prison budgets,
autonomous-vehicle regulation. Each has a hidden structural analysis
(critical nodes, trap nodes, dependency orderings, expected conflicts)
produced once by an analyst model and stored in
`problems/battery.json`.

The traces show the phenomenon. Across problems and both subject
models (Gemini 3.1 Pro Preview and GPT-4.1 via OpenRouter) at
temperature 0, the opinion-framed responses consistently open with an
acknowledgment-and-reframe preamble that the neutral responses lack:
"Your reasoning is understandable, but..." / "While your instinct is
ecologically sound...". The neutral versions go straight to analysis.
Both typically reach the same substantive recommendation. This is
visible to a human reader in the paired files under `traces/`. It is
not a scored result; it is what the data looks like.

## What didn't work

The LLM-as-judge scoring layer. Two problems, both fundamental, plus
one practical one.

**Circularity.** The judge and the cartographer are Claude Haiku 4.5,
an LLM evaluating whether other LLMs' reasoning structure changed in
response to a user opinion. But the judge has its own structural
preferences and its own sycophantic tendencies. When one response
starts with "your reasoning is sound but..." and the other starts with
analytical framing, the judge's own biases influence how it reads that
difference. The instrument is contaminated by the phenomenon it is
supposed to measure. Nothing in the design removes this; the
validation phase (a second judge model) could only have shown whether
two contaminated instruments agree with each other.

**Numeric assignment.** The cartographer prompt asks an LLM to emit
floats between 0 and 1 for "node coverage", "ordering preservation",
"conflict surfacing", and "trap avoidance", defined as ratios of
counted items. LLMs do not do this reliably, and the partial results
show it. Across the 2,080 dimension scores in `results-partial/results.csv`,
only 39 distinct values occur and 45% are exactly 1.0; the rest cluster
on small-integer ratios (0.75, 0.5, 0.67, 0.8, 0.83). These are
subjective judgments in decimal-point clothing. More telling is what
the pipeline's own baseline says about its resolution: two *neutral*
responses to the same problem differ in composite score by 0.08 to
0.17 on average (SD 0.11 to 0.14, depending on temperature), while the
measured neutral-versus-opinion difference is between -0.027 and
+0.025, changes sign across temperatures, and never exceeds 0.2
baseline standard deviations. The dimension that "dominates" the
effect changes from temperature to temperature. The instrument's
test-retest noise is an order of magnitude larger than the effect it
is being asked to detect. Separately, the answer-comparison instrument
(an LLM asked whether two one-sentence summaries "express the same
recommendation") reported a changed answer in 98 of 101 scored
measurement cells, which is implausible on reading the traces and
suggests it is over-sensitive to wording.

**Credits.** The run exhausted its OpenRouter balance during the
measurement phase. 250 of the 261 logged API errors are credit
refusals; the entire validation phase (202 attempted cells) failed for
that reason, so the cross-judge correlation was never computed. The
cartographer itself failed to produce parseable output in only 3 of
267 calls; the high error rate in the CSV (50.4% of 524 rows) is
almost entirely the credit exhaustion, not parser failures.

The experiment demonstrates the limits of using LLMs as measurement
instruments for structural properties of LLM output. The phenomenon
is real and human-visible. Automating its measurement remains an open
problem. The code is released as the implementation of a methodology
that did not work at the measurement layer; it is not broken, and it
has not been "fixed", because the problem is not in the code.

## The traces

The 539 trace files under `traces/` are the primary data release.
Each is a JSON object with the model's full response (`content`) and
its coordinates: `problem_id`, `condition` (`neutral` or `opinion`),
`model`, `temperature`, `phase` (`baseline` or `measurement`),
`run_index`, `tokens_input`, `tokens_output`, and the `filepath` the
runner wrote it to. Filenames encode every coordinate:

```
{phase}__{problem_id}__{model}__{temperature}__{condition}__{run_index}.json
```

with `/` in the model id replaced by `--` and `.` in the temperature
replaced by `_`, for example
`measurement__school_closure_001__openai--gpt-4.1__0_3__opinion__0.json`.
515 files with unique coordinates sit directly in `traces/`; 24 more,
duplicate generations of twelve baseline cells from the first minutes
of the run, sit in `traces/first-pass/`. See
[`traces/README.md`](traces/README.md) for the counts, coverage, and
the reason for the split.

## How to run it

```
pip install -e .
export OPENROUTER_API_KEY=...

# Build the problem battery (one analyst call per problem):
python build_problems.py --input benchmark.json --config config.yaml

# Run all three phases (add --resume to continue an interrupted run,
# --workers N for parallel cells):
python run_experiment.py --config config.yaml

# Analyse (defaults read results/results.csv and write results/figures
# and results/variables.json):
python analyze_results.py
```

To re-run the analysis on the shipped partial results without any API
access:

```
python analyze_results.py --results results-partial/results.csv \
    --figures-dir /tmp/figures --variables /tmp/variables.json
```

This reproduces `results-partial/variables.json` exactly.

**Cost.** The partial run made 1,653 API calls in 2 hours 22 minutes
on 2026-04-04. Token totals from `results-partial/api_log.jsonl`:

| Model | Role | Input tokens | Output tokens |
|---|---|---|---|
| `anthropic/claude-haiku-4.5` | judge, cartographer, answer extraction, analyst | 5,266,699 | 2,145,344 |
| `google/gemini-3.1-pro-preview` | subject | 95,679 | 892,835 |
| `openai/gpt-4.1` | subject | 83,614 | 284,529 |

At OpenRouter list prices as of 2026-09-03 (Haiku 4.5 $1/$5,
Gemini 3.1 Pro Preview $2/$12, GPT-4.1 $2/$8 per million input/output
tokens) that is roughly $29: $16 for the instruments, $11 for Gemini,
$2.50 for GPT-4.1. The cartographer alone is about 40% of the total,
because it receives both traces, the judge output, and the structural
metadata on every call. A complete run at the configured scale
(15 problems × 2 models × 5 temperatures, 600 subject traces, about
360 judge and cartographer calls including validation) extrapolates to
roughly $40 at the same prices. `analyze_results.py` prints its own
cost report using hard-coded approximate rates, which will differ.
Running with fewer problems, models, or temperatures is a matter of
editing `config.yaml`.

## How to use your own problems

`benchmark.json` is an object with a single key, `problems`, holding a
list of entries:

```json
{
  "id": "school_closure_001",
  "domain": "education_policy",
  "context": "...the situation, stakeholders, constraints...",
  "question": "...what should be decided...",
  "opinion_framing": "...the same question, with the user's opinion embedded...",
  "behavioral_sycophancy": null
}
```

`build_problems.py` accepts a few aliases (`problem_id`, `prompt`,
`sycophantic_prompt`, `category`, and so on; see `_parse_item`) and
runs the analyst prompt over each entry to produce
`problems/battery.json`, which is what `run_experiment.py` reads.
Any set of (context, question, opinion_framing) triples works. The
scoring pipeline will run over them and produce a CSV, figures, and
variables; treat those outputs as exploratory, not as measurements,
for the reasons above. The traces are the part worth reading.

## Design

The full specification is [`CLAUDE.md`](CLAUDE.md). In brief:

**Three phases.** Phase 0 (baseline) generates two independent neutral
responses per (problem, model, temperature) cell, judges the pair, and
scores both with the cartographer; this measures natural variation.
Phase 1 (measurement) generates one neutral and one opinion-framed
response per cell and runs the same instruments, plus answer
extraction and comparison. Phase 2 (validation) re-judges a stratified
20% sample of successful Phase 1 cells with every configured judge
model. All three run in sequence from one invocation; `--resume` skips
cells that already have a CSV row.

**Blinding.** The judge receives "Response A" and "Response B" and
nothing about which condition either came from. The assignment is
decided by `random.Random(seed)` where the seed is the first 16 hex
digits of `sha256("{problem_id}|{model}|{temperature}")`, so it is
fixed per cell and Phase 2 recovers Phase 1's assignment by calling the
same function with the same arguments (`src/blinding.py`). Scores are
unblinded before the CSV row is written; the analysis never sees A/B.

**Instrument temperature.** Only the subject models use the
experiment's temperature range. The judge, cartographer, answer
extractor, answer comparator, and analyst are all called with
`temperature=0` and `seed=42` as literals at the call site, not as
config values.

**Provenance.** The run hash is a SHA-256 over `config.yaml` and the
three prompt files. Each API call is logged to `api_log.jsonl` with a
prompt hash, model, purpose, phase, token counts, duration, and status.
Trace, judge, and cartographer files are named by their coordinates
and written atomically. Every error produces a CSV row with one of
`api_error`, `cartographer_parse_error`, or `upstream_parse_error`;
the analysis excludes non-`ok` rows and reports how many.

## The build specification

The `CLAUDE.md` file is the 984-line specification this codebase was
built from. It defines every module, every schema, every invariant,
and the verification checklist. It is included as part of the release.

## Repository layout

```
README.md, LICENSE, CLAUDE.md, pyproject.toml
config.yaml              experiment configuration as run
benchmark.json           the 15 problems
build_problems.py        battery builder (analyst pass)
run_experiment.py        three-phase runner
analyze_results.py       analysis and figures
src/                     harness library
prompts/                 frozen instrument prompts (analyst, judge, cartographer)
problems/                generated battery and its generation log
traces/                  539 model responses (primary data)
results-partial/         CSV, API log, judge/cartographer/answer outputs,
                         figures, and variables from the incomplete run
```

## License

Apache-2.0. Copyright 2026 corgido.
