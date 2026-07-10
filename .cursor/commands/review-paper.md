# Review Paper

Use the **review-paper** skill to review a student manuscript with professor-assistance.

Steps:
1. Determine the **source document** — a `.docx` path. If I did not include one after this
   command, ask me for it and wait; do not guess a path.
2. Ask me (one line, with defaults) for the options, then proceed:
   - **backend**: `mock` (free) · `local` (free, private) · `gemini` (free cloud) · `api` (best quality)
   - **rebuild-corpus**: yes/no (default no)
   - **rebuild-style**: yes/no (default no)
3. Follow the review-paper skill workflow to run `profa review` on the source document.
4. Present the results from `output/<name>/suggestions.md`: totals by severity, the 2–3
   strongest before→after rewrites, and any `content` flags to verify. Link the
   `reviewed.docx`.
