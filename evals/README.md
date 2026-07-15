# Eval harness

Tiny fixed-draft checks so prompt/style changes can be re-run without eyeballing every suggestion.

## Quick start (mock / CI-like)

```bash
# from repo root, with the package installed (`pip install -e .`)
python evals/run_eval.py
# equivalent: python evals/run_eval.py --backend mock
```

Defaults to `--backend mock` (ignores `.env` for this process) so CI stays fast and
deterministic.

## Demo-quality backend (recommended: Gemini)

```bash
python evals/run_eval.py --backend gemini
# optional: fail if RAG returned nothing (requires `profa ingest` first)
python evals/run_eval.py --backend gemini --require-retrieval
```

Requires `GEMINI_API_KEY` in `.env`. **Ollama** remains a documented offline alternative:

```bash
python evals/run_eval.py --backend local
```

## Style card hook (Horizon 1 ready)

Pass an explicit style card without waiting for example-trained cards to land:

```bash
python evals/run_eval.py --style-card config/style_card.md
```

Or set `"style_card": "config/style_card.md"` in `cases.json`. When Horizon 1 ships example-trained cards, point this path at that artifact.

## What is scored

| Signal | Meaning |
|---|---|
| Theme hit | Golden phrases (e.g. “in order to”, “significant”) appear in suggestions |
| Severity mix | Mix of language/clarity vs content; not empty / not all-content runaway |
| No invented facts | `content` stays flag-only; rewrites don’t introduce new numbers |
| Retrieval hit | Optional (`--require-retrieval` or per-case `expect_retrieval_hit`) |

## Layout

```
evals/
  cases.json          # fixed cases + golden themes
  build_fixtures.py   # regenerates fixtures/*.docx
  fixtures/           # generated drafts (gitignored or rebuilt on demand)
  run_eval.py         # scorer CLI
  README.md
```

## Machine-readable output

```bash
python evals/run_eval.py --json
```

Exit code `0` = all cases pass, `1` = at least one failure.
