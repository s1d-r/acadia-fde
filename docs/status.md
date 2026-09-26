# Status

This file has two parts. The first is the audit of the repo against the brief,
written before any of the remaining work was done. The second is the completion
summary, written at the end.

## Part 1. Audit, taken before this session's work

The build was stopped after slice 4 of the eleven slices in CLAUDE.md. The
engine works end to end from the command line. There is no HTTP service, no UI
and no job layer yet.

### What exists and works

| Area | State | Evidence |
| --- | --- | --- |
| CSV ingestion into DuckDB | Done | `src/insights/ingest/` |
| Schema profiling | Done | 78 MB, 511,395 rows, 25 columns profiled in about 2.9 seconds |
| Schema context builder with inferred roles | Done | `src/insights/context/` |
| Question planner, model to SQL | Done | `src/insights/planner/` |
| Refusal as a first class outcome | Done | `PlanOutcome.REFUSAL` |
| SQL validator | Done | `src/insights/validator.py`, 34 tests |
| Executor with row limit and timeout | Done | `src/insights/executor.py` |
| LLM provider seam | Done | `src/insights/llm/base.py` |
| Command line interface | Done | `insights ingest`, `list`, `show`, `context`, `ask` |
| Tests | 166 passing, 3 integration tests behind a marker | `pytest` |
| CI workflow | Present but never run, since there are no commits | `.github/workflows/ci.yml` |
| Decisions log | Done for slices 1 to 4 | `docs/decisions.md` |

### What is missing

| Brief requirement | State before this session |
| --- | --- |
| Async job handling, submit and poll | Missing |
| HTTP API with validation and status codes | Missing |
| Working UI | Missing |
| Evaluation harness with expected answers | Missing |
| One command setup | Missing |
| README | Missing |
| System design document | Missing |
| Architecture image | Missing |
| GIFs of the app working | Missing |
| Cut list | Missing |
| Any git commit at all | Missing |

### Environment facts that shaped the remaining work

These were checked, not assumed.

* Docker is not installed on this machine. Neither is `make`.
* Node and npx are not installed, so a JavaScript build step is not available.
* ffmpeg is not installed.
* The GitHub CLI is installed but not logged in, and no token is present in the
  environment.
* Ollama is installed with `qwen2.5-coder:7b` pulled.

Each of these changed a decision. They are recorded with the decision they
affected in `docs/assumptions.md`.

## Part 2. Completion summary

See the end of this file. It is written once the remaining work is finished.
