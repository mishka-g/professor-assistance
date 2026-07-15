# professor-assistant

A grounded scientific-writing reviewer for a professor, built on his **own published
corpus** (retrieval-augmented generation). It reviews student `.docx` drafts and returns:

- `reviewed.docx` — the draft with inline review notes (reason → suggestion),
- `suggestions.md` — a section-by-section redline.

It is designed to **improve wording, clarity, structure and terminology** while
**never inventing scientific content** (unsupported claims are flagged, not changed).

## Why RAG, not fine-tuning

The professor's papers are used as *retrieved context* so terminology and phrasing come
from real source material — no expensive fine-tuning, no hallucinated results, fully editable.

## Privacy & cost — pluggable backend

Embeddings and the vector store **always run locally** (private, free). Only the final
text generation has a choice of backend (set `MODEL_BACKEND` in `.env`):

| Backend | Quality | Cost | Privacy | Use for |
|---|---|---|---|---|
| `gemini`| good | free tier | draft sent to Google | **quality demos (recommended)** |
| `local` | good | free | fully local (Ollama) | private iteration / offline |
| `api`   | best | paid | sent to provider | the real drafts |
| `mock`  | heuristic only | free | fully local | pipeline smoke tests only |

`.env.example` ships with `MODEL_BACKEND=mock` so a cold install still runs without API
keys — but **demos that should look like professor voice need `gemini`** (or `local` /
`api`). Mock never produces reliable corpus-grounded terminology.

## Setup (M1/M2 Mac, Python 3.11+)

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env            # edit if using local/gemini/api backend
```

### Recommended for demos: Gemini (free tier)

Embeddings and RAG still run locally; only the final text generation uses Google's API.
Get a free API key at [Google AI Studio](https://aistudio.google.com/apikey), then set in `.env`:

```
MODEL_BACKEND=gemini
GEMINI_API_KEY=your-key-here
# GEMINI_MODEL=gemini-2.0-flash   # optional, this is the default
```

### Optional: local LLM (free, private — Ollama)

```bash
brew install ollama
ollama serve &
ollama pull qwen2.5:14b-instruct
# then set MODEL_BACKEND=local in .env
```

### Optional: API (best quality, for the real drafts)

Set in `.env`:

```
MODEL_BACKEND=api
API_PROVIDER=openai
API_MODEL=gpt-4o
OPENAI_API_KEY=sk-...
```

## Usage

```bash
# 1. Add the professor's published papers (PDF/DOCX/TXT) to data/corpus/
profa ingest            # parse + chunk + embed into local Chroma

# 2. (optional, high value) learn from his before/after edited drafts in data/examples/
python scripts/make_sample_examples.py   # no real pairs yet? generate a testable demo set
profa examples           # diff pairs -> phrase swaps / hedging habits + retrieval index

# 3. build the style card (folds in corpus + examples automatically)
profa style              # writes config/style_card.md

# 4. (for a quick test) generate a throwaway student draft
python scripts/make_sample_draft.py   # -> data/drafts/sample_draft.docx (+ demo pack)

# 5. Review a student draft (use gemini for quality; mock is heuristics only)
MODEL_BACKEND=gemini profa review data/drafts/sample_draft.docx
#    -> output/sample_draft/reviewed.docx
#    -> output/sample_draft/suggestions.md (shows "grounded in: ..." per suggestion)

profa info              # show config + corpus + examples status
```

Student drafts and before/after examples under `data/drafts/` and `data/examples/` stay
git-ignored. The corpus ships with public arXiv preprints so you can run `profa ingest`
right away; add more of the professor's published work as needed.

### Before/after learning (`data/examples/`)

Drop matched `<name>.before.docx` / `<name>.after.docx` pairs into `data/examples/` (see
[`data/examples/README.md`](data/examples/README.md)) — these are drafts the professor has
actually edited. `profa examples`:

1. diffs each pair section-by-section to extract phrase swaps, hedging/claim calibration,
   and trimmed filler (`src/professor_assistant/examples.py`),
2. indexes them into a local retrieval collection separate from the paper corpus, so
   `profa review` can pull the most relevant real edits as few-shot grounding, and
3. is folded into `profa style`'s output as a "## Edit habits" section (skip with
   `profa style --no-examples` to compare corpus-only vs. corpus+examples).

No real pairs yet? `python scripts/make_sample_examples.py` generates a small, realistic
synthetic set so the whole pipeline is testable end-to-end.

For the matched professor + student demo pack, see [`example_paperworks/`](example_paperworks/).

## Project layout

```
config/style_card.md          # extracted "how he writes" guide (generated)
data/corpus/                  # published papers (public arXiv preprints included)
data/drafts/                  # student drafts to review (private)
data/examples/                # before/after edited pairs (optional, high value)
evals/                        # tiny review-quality harness (see evals/README.md)
prompts/                      # reviewer + section + style prompts
src/professor_assistant/      # ingest, retrieve, review, llm, docx_io, cli, ...
storage/chroma/               # local vector DB (generated)
storage/reviews/              # persisted web reviews (survives API restart)
storage/feedback/             # Accept/Skip preference log (JSONL)
output/<draft>/               # review artifacts (generated)
```

## Eval harness

After prompt or style-card changes, re-score the fixed draft set without manual eyeballing:

```bash
python evals/run_eval.py                              # mock CI check (default)
python evals/run_eval.py --backend gemini --require-retrieval
```

Details: [`evals/README.md`](evals/README.md).

## Web UI (recommended for the professor)

A modern web app wraps the same pipeline so no terminal is needed. It has two jobs:

- **Add my paper** — upload one of the professor's papers; it is folded into the RAG corpus.
- **Improve a student draft** — upload a student `.docx`, Accept/Skip each suggestion in the
  browser, and download a clean Word file containing only the accepted edits.

### Running it from a fresh clone

You need **Python 3.11+** and an internet connection (the frontend loads React + Tailwind from
a CDN at runtime). **Node/npm is NOT required** — the UI is a single `web/index.html` served by
FastAPI, with no build step.

```bash
git clone <repo-url> professor-assistance
cd professor-assistance

python3 -m venv .venv           # or: uv venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e .                # installs everything, incl. the web-server packages below

# For a quality demo (recommended), set Gemini before starting the server:
#   MODEL_BACKEND=gemini
#   GEMINI_API_KEY=...   # https://aistudio.google.com/apikey

uvicorn professor_assistant.api:app --port 8000
# then open http://127.0.0.1:8000
```

That's it — `pip install -e .` pulls all dependencies from `pyproject.toml`. The web server
specifically needs **`fastapi`**, **`uvicorn[standard]`**, and **`python-multipart`** (for file
uploads); these are already declared, so no extra install step is needed.

### Golden-path demo (cold clone → export)

1. Set `MODEL_BACKEND=gemini` + `GEMINI_API_KEY` in `.env` and start the server.
2. Confirm the status bar shows `backend: gemini` (not `mock`).
3. **Add my paper** → `example_paperworks/professor_paper/professor_paper.docx`.
4. **Improve a draft** → `example_paperworks/student_paper/student_draft.docx`.
5. Accept / Skip suggestions → export the clean `.docx`.

Full notes and expected suggestion themes: [`example_paperworks/README.md`](example_paperworks/README.md).

### Review quality

`mock` uses regex heuristics only — fine for plumbing checks, **not** for quality demos.
For corpus-grounded terminology, set **`MODEL_BACKEND=gemini`** (recommended), or `local` /
`api` — see [Privacy & cost](#privacy--cost--pluggable-backend). The active backend is shown
in the app's status bar; the UI warns when `mock` is active.

### Troubleshooting

- **Blank page** → almost always no internet reaching the CDN (React/Tailwind fail to load), or
  a browser blocking third-party scripts. Confirm you can reach `https://unpkg.com`.
- **Port already in use** → change `--port 8000` to another port.
- **`ModuleNotFoundError`** → the virtualenv isn't active, or `pip install -e .` wasn't run.

## Present it in Cursor (skill + command)

This repo ships a Cursor **skill** and **command** that wrap the CLI for easy demos:

- Command: type `/review-paper` in Cursor, give it a `.docx` source document (or the
  demo pack student draft), pick a backend (**`gemini` default for quality demos**;
  `local` / `api` / `mock`), and it runs the review and summarizes the results.
- Skill: `.cursor/skills/review-paper/` — requires a source document and exposes the
  `backend`, `rebuild-corpus`, and `rebuild-style` options.

## Roadmap

Full product roadmap for contributors: **[docs/roadmap.md](docs/roadmap.md)**.

Summary:

- **v1 (this):** inline review notes + redline, mock/local/gemini/api backends, web UI.
- **Next (quality):** demo polish, before/after learning, style grounding, content guards.
- **Later (parked):** Word tracked-changes / comments, Google Docs, optional hosted vector store,
  multi-user / SaaS — only after review quality is credible.
