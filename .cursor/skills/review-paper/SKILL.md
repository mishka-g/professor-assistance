---
name: review-paper
description: Review a student's scientific manuscript grounded in the professor's own published corpus (RAG) and produce reviewed.docx + suggestions.md. Use when the user asks to review, edit, critique, or polish a student draft/paper with professor-assistance, or runs the /review-paper command.
disable-model-invocation: true
---

# Review Paper (professor-assistance)

Portfolio demo surface for grounded scientific-writing review. Reviews a source document
against the professor's published corpus and writes:

- `output/<name>/reviewed.docx` — original text with inline `[SEVERITY] reason → suggestion` notes
- `output/<name>/suggestions.md` — a section-by-section redline

This wraps the `profa` CLI in this repo. It never invents scientific content; unsupported
claims are flagged (`content`), not rewritten.

## Required input

- **Source document** (REQUIRED): path to a `.docx` student draft.
  If the user did not provide one, ask for it and STOP until they do. Do not invent a path.

  Demo pack default (if they want the golden path):
  `example_paperworks/student_paper/student_draft.docx`

## Options

Confirm these quickly, then use defaults for anything unspecified.

| Option | Values | Default | Effect |
|---|---|---|---|
| `backend` | `gemini` \| `local` \| `api` \| `mock` | **`gemini`** (recommended for demos) | Reviewer engine. `gemini`=Google AI free tier (quality demos). `local`=Ollama (private). `api`=paid (best). `mock`=heuristics only — pipeline smoke tests, **not** quality demos. |
| `rebuild-corpus` | yes \| no | no | Re-run `profa ingest` first (only after adding/removing papers in `data/corpus/`) |
| `rebuild-style` | yes \| no | no | Re-run `profa style` first to refresh `config/style_card.md` |

When presenting the backend choice, lead with **gemini**. Mention `mock` last and label it
as heuristic-only / not for portfolio demos.

## Golden-path demo (cold clone)

If the user wants a full demo and has no draft yet:

1. Ensure `.env` has `MODEL_BACKEND=gemini` and `GEMINI_API_KEY=...`.
2. Optionally upload / copy `example_paperworks/professor_paper/professor_paper.docx` into the
   corpus (`data/corpus/` then `profa ingest`, or use the web UI *Add my paper*).
3. Review `example_paperworks/student_paper/student_draft.docx` with `backend=gemini`.
4. Summarize corpus-grounded terminology themes (GFET, Dirac point, label-free, etc.) — not
   mock fluff. See `example_paperworks/README.md` for expected suggestion themes.

## Workflow

Run everything from the **repo root** with the venv active.

```bash
cd <repo-root>
source .venv/bin/activate
```

1. **(optional) Rebuild corpus** — only if `rebuild-corpus=yes`:

```bash
profa ingest
```

2. **(optional) Rebuild style card** — only if `rebuild-style=yes` (respects chosen backend):

```bash
MODEL_BACKEND=<backend> profa style
```

3. **Review the source document** (required step). Override the backend for this run via env var:

```bash
MODEL_BACKEND=<backend> profa review "<source-document.docx>"
```

- Prefer `backend=gemini` for demos. Needs `GEMINI_API_KEY` (free:
  https://aistudio.google.com/apikey).
- `local`/`gemini`/`api` runs call an LLM and can take ~1–2 min per few sections.
- If `backend=gemini` fails, check the API key and free-tier quota; fall back to `local`
  (Ollama) or, for pipeline smoke only, `mock`.
- If `backend=local` fails to reach Ollama, tell the user to run `ollama serve` and
  `ollama pull qwen2.5:14b-instruct`, or switch to `gemini`.
- If `backend=mock`, warn clearly: results are heuristic-only and will not demonstrate
  corpus-grounded professor voice.

4. **Present the result.** Read `output/<name>/suggestions.md` and summarize:
   - total suggestions + counts per severity,
   - 2–3 strongest before→after rewrites (prefer terminology / clarity grounded in corpus),
   - any `content` flags (things the professor must verify),
   - which backend was used.
   Then point to `output/<name>/reviewed.docx` for the annotated Word file.

## Notes

- `content` severity = flagged for human review; nothing was changed.
- For unpublished drafts prefer `local` (fully private) or `gemini` with awareness that the
  draft is sent to Google; use `api` for best quality; use `mock` only to test plumbing.
- See the repo `README.md` and `example_paperworks/README.md` for setup and the cold-clone path.
