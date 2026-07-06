---
name: review-paper
description: Review a student's scientific manuscript grounded in the professor's own published corpus (RAG) and produce reviewed.docx + suggestions.md. Use when the user asks to review, edit, critique, or polish a student draft/paper with professor-assistance, or runs the /review-paper command.
disable-model-invocation: true
---

# Review Paper (professor-assistance)

Reviews a source document against the professor's published corpus and writes:
- `output/<name>/reviewed.docx` — original text with inline `[SEVERITY] reason → suggestion` notes
- `output/<name>/suggestions.md` — a section-by-section redline

This wraps the `profa` CLI in this repo. It never invents scientific content; unsupported
claims are flagged (`content`), not rewritten.

## Required input

- **Source document** (REQUIRED): path to a `.docx` student draft.
  If the user did not provide one, ask for it and STOP until they do. Do not invent a path.

## Options

Confirm these quickly, then use defaults for anything unspecified.

| Option | Values | Default | Effect |
|---|---|---|---|
| `backend` | `mock` \| `local` \| `api` | value in `.env` (currently `local`) | Reviewer engine: `mock`=free heuristics, `local`=Ollama (free, private), `api`=paid (best) |
| `rebuild-corpus` | yes \| no | no | Re-run `profa ingest` first (only after adding/removing papers in `data/corpus/`) |
| `rebuild-style` | yes \| no | no | Re-run `profa style` first to refresh `config/style_card.md` |

## Workflow

Run everything from the repo root with the venv active. Prepend the Ollama path so the
`local` backend can reach the server.

```bash
cd /Users/mishka/Github/professor-assistance
source .venv/bin/activate
export PATH="/opt/homebrew/bin:$PATH"
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

- `local`/`api` runs call an LLM and can take ~1–2 min per 5 sections on the local 14B model.
- If `backend=local` fails to reach Ollama, tell the user to run `ollama serve` and
  `ollama pull qwen2.5:14b-instruct`, or fall back to `backend=mock`.

4. **Present the result.** Read `output/<name>/suggestions.md` and summarize:
   - total suggestions + counts per severity,
   - 2–3 strongest before→after rewrites,
   - any `content` flags (things the professor must verify).
   Then point to `output/<name>/reviewed.docx` for the annotated Word file.

## Notes

- `content` severity = flagged for human review; nothing was changed.
- For unpublished drafts prefer `local` (fully private) or `mock`; use `api` for best quality.
- See the repo `README.md` for setup and backend configuration.
