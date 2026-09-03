# Traces

539 model response traces from the sycophancy experiment, generated on
2026-04-04 from the two subject models in `config.yaml`
(`google/gemini-3.1-pro-preview`, 283 files; `openai/gpt-4.1`,
256 files) through OpenRouter.

Each file is a JSON object:
- `content`: the model's full response text
- `problem_id`: which benchmark problem
- `condition`: `"neutral"` or `"opinion"`
- `model`: the responding model (OpenRouter id)
- `temperature`: generation temperature (0, 0.3, 0.5, 0.7, or 1.0)
- `phase`: `"baseline"` or `"measurement"`
- `run_index`: 0 or 1 (baseline generates two independent neutral traces per cell)
- `tokens_input` / `tokens_output`: token counts reported by the API
- `filepath`: the path the runner wrote the file to at the time
  (`results/traces/...`); the directory has since been renamed to
  `traces/`, and the field is left as written

Filename convention:
`{phase}__{problem_id}__{model}__{temp}__{condition}__{run_index}.json`,
with `/` in the model id replaced by `--` and `.` in the temperature
replaced by `_`.

## Counts

**`traces/` (515 files, one per unique coordinate):**

| Phase | Files | Coverage |
|---|---|---|
| baseline | 300 | all 15 problems × 2 models × 5 temperatures, 2 neutral runs each (150 complete cells) |
| measurement | 215 | 108 neutral + 107 opinion; 107 complete neutral/opinion pairs over 11 problems |

The run exhausted its API credits during the measurement phase, so
four problems (`department_closure_001`, `housing_zoning_001`,
`urban_corridor_001`, `wildfire_evacuation_001`) have baseline traces
only, `av_regulation_001` is partially covered, and one cell
(`av_regulation_001`, Gemini, temperature 1.0) has a neutral trace but
no opinion trace.

**`traces/first-pass/` (24 files):** additional baseline traces for
twelve Gemini cells (`school_closure_001`, `community_garden_001`, all
five temperatures; `ridgeland_lead_001`, temperatures 0 and 0.3). Early
in the run (before 19:11 UTC) the model id's `/` was not yet sanitised, so these were written under a subdirectory
(`baseline__school_closure_001__google/gemini-3.1-pro-preview__...`).
After the path fix, `--resume` did not find them and regenerated those
cells, producing the files now in `traces/`. Both generations are
genuine, independent responses; they are kept because the API log
counts all 539. They are stored here, with the standard flat filename,
so that every filename in `traces/` is unique. Their `filepath` field
still shows the original nested path.

Across all 539 files: 324 baseline, 215 measurement; mean response
length about 2,200 output tokens.

The traces are unmodified model output. They have not been sanitised
or edited.
