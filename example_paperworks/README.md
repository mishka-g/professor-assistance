# Example paperworks

Two matched sample documents (same topic — graphene biosensors) for trying the web UI.

```
professor_paper/professor_paper.docx   → upload under "Add my paper"       (updates the RAG)
student_paper/student_draft.docx       → upload under "Improve a student draft" (get reviewed)
```

Suggested flow:

1. Start the app: `uvicorn professor_assistant.api:app --port 8000`
2. In **Add my paper**, upload `professor_paper.docx` — the corpus/chunk count rises.
3. In **Improve a student draft**, upload `student_draft.docx` — the review now borrows the
   professor's terminology and phrasing, then Accept/Skip and export a clean `.docx`.

Regenerate these from the scripts if needed:
`python scripts/make_sample_paper.py` and `python scripts/make_sample_draft.py`.
