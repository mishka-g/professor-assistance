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
| `mock`  | heuristic only | free | fully local | testing the pipeline (default) |
| `local` | good | free | fully local (Ollama) | iterating |
| `api`   | best | paid | sent to provider | the real drafts |

## Setup (M1/M2 Mac, Python 3.11+)

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env            # edit if using local/api backend
```

### Optional: local LLM (free, private)

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

# 2. (optional but recommended) build the style card
profa style             # writes config/style_card.md

# 3. (for a quick test) generate a throwaway student draft
python scripts/make_sample_draft.py   # -> data/drafts/sample_draft.docx

# 4. Review a student draft
profa review data/drafts/sample_draft.docx
#    -> output/sample_draft/reviewed.docx
#    -> output/sample_draft/suggestions.md

profa info              # show config + corpus status
```

Nothing under `data/` is committed to the repo — it is git-ignored to keep research
private. To try it out, add papers to `data/corpus/` (for local testing we used real
open-access arXiv preprints of the professor's work) and generate a throwaway student
draft with `python scripts/make_sample_draft.py`. Swap in the professor's real papers
and student drafts when ready.

## Project layout

```
config/style_card.md          # extracted "how he writes" guide (generated)
data/corpus/                  # his published papers (private, git-ignored)
data/drafts/                  # student drafts to review (private)
data/examples/                # before/after edited pairs (optional, high value)
prompts/                      # reviewer + section + style prompts
src/professor_assistant/      # ingest, retrieve, review, llm, docx_io, cli, ...
storage/chroma/               # local vector DB (generated)
output/<draft>/               # review artifacts (generated)
```

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

uvicorn professor_assistant.api:app --port 8000
# then open http://127.0.0.1:8000
```

That's it — `pip install -e .` pulls all dependencies from `pyproject.toml`. The web server
specifically needs **`fastapi`**, **`uvicorn[standard]`**, and **`python-multipart`** (for file
uploads); these are already declared, so no extra install step is needed.

> Tip: try it with the ready-made samples in `example_paperworks/` — upload
> `professor_paper/professor_paper.docx` under *Add my paper*, then
> `student_paper/student_draft.docx` under *Improve a student draft*.

### Review quality

The default `mock` backend uses regex heuristics only (free, fully local). For real,
corpus-grounded suggestions, set `MODEL_BACKEND=local` (Ollama) or `api` in `.env` — see
[Privacy & cost](#privacy--cost--pluggable-backend) above. The active backend is shown in the
app's status bar.

### Troubleshooting

- **Blank page** → almost always no internet reaching the CDN (React/Tailwind fail to load), or
  a browser blocking third-party scripts. Confirm you can reach `https://unpkg.com`.
- **Port already in use** → change `--port 8000` to another port.
- **`ModuleNotFoundError`** → the virtualenv isn't active, or `pip install -e .` wasn't run.

## Present it in Cursor (skill + command)

This repo ships a Cursor **skill** and **command** that wrap the CLI for easy demos:

- Command: type `/review-paper` in Cursor, give it a `.docx` source document, pick a
  backend (`mock` / `local` / `api`), and it runs the review and summarizes the results.
- Skill: `.cursor/skills/review-paper/` — requires a source document and exposes the
  `backend`, `rebuild-corpus`, and `rebuild-style` options.

## Roadmap

- v1 (this): inline review notes + redline, mock/local/api backends, web UI.
- v2: native Word tracked-changes / margin comments; Google Docs API; before/after learning.
- v3: Optional hosted vector store: opt-in `.env` flag to swap the local Chroma store in
  `store.py` for a hosted vector DB (e.g. Chroma Cloud / Qdrant Cloud), keeping local as the
  private default. Trade-off: convenience vs. sending the corpus to a third party.
