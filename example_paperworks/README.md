# Example paperworks — golden-path demo pack

Matched sample documents on the same topic (graphene biosensors) for a cold-clone demo:

```
professor_paper/professor_paper.docx   → upload under "Add my paper"        (updates the RAG)
student_paper/student_draft.docx       → upload under "Improve a student draft" (get reviewed)
```

The professor paper uses precise GFET / Dirac-point / label-free terminology. The student
draft is deliberately weak (informal wording, vague intensifiers, unsupported “significant”
claims) so a quality backend can ground rewrites in the professor corpus.

## Cold-clone demo path (≈5 minutes)

**Quality demos need a real backend.** Default `mock` is heuristic-only and will not sound
like corpus-grounded professor voice. For demos, use **Gemini** (recommended):

```bash
git clone <repo-url> professor-assistance
cd professor-assistance
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env
# edit .env:
#   MODEL_BACKEND=gemini
#   GEMINI_API_KEY=...   # https://aistudio.google.com/apikey

uvicorn professor_assistant.api:app --port 8000
# open http://127.0.0.1:8000
```

Then in the web UI:

1. Confirm the status bar shows `backend: gemini` (not `mock`).
2. **Add my paper** → upload `professor_paper/professor_paper.docx` (corpus/chunk count rises).
3. **Improve a draft** → upload `student_paper/student_draft.docx`.
4. Accept / Skip suggestions, then export the clean `.docx`.

### CLI equivalent

```bash
# optional: also fold the sample into data/corpus/ for CLI ingest demos
cp example_paperworks/professor_paper/professor_paper.docx data/corpus/
profa ingest
MODEL_BACKEND=gemini profa style   # optional style card refresh
MODEL_BACKEND=gemini profa review example_paperworks/student_paper/student_draft.docx
# → output/student_draft/reviewed.docx + suggestions.md
```

Or in Cursor: `/review-paper` with the student draft and **backend = gemini**.

## Expected suggestion themes

A quality (`gemini` / `local` / `api`) review of the student draft should surface themes like:

| Theme | What to look for |
|---|---|
| Terminology | Prefer professor phrasing: GFET / graphene field-effect, Dirac point shift, label-free, limit of detection, capture antibodies |
| Language | Drop vague intensifiers (`very`, `really`, `a lot of`, `obviously`, `clearly`) |
| Clarity | Replace generic openers (`In recent years`, `It is well known that`) with a concrete problem statement |
| Structure / wording | Tighten Methods (“CVD growth / transfer / functionalize / measure”) vs. run-on informal narration |
| Content (flag only) | Unsupported “significant” / “we believe” / “proves” claims — flag, do not invent science |

`mock` may catch some heuristics (wordiness, intensifiers) but will **not** reliably produce
corpus-grounded terminology guidance.

## Regenerate samples

```bash
python scripts/make_sample_paper.py   # → example_paperworks/professor_paper/professor_paper.docx
python scripts/make_sample_draft.py   # → example_paperworks/student_paper/student_draft.docx
                                      #    and data/drafts/sample_draft.docx
```
