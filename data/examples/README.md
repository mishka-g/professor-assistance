# Examples — before/after edited drafts (optional, high value)

If the professor has drafts he already edited, drop **pairs** here:

```
<name>.before.docx   (student version)
<name>.after.docx    (his edited version)
```

These teach the reviewer his actual editing decisions — far more valuable than
published papers alone.

Run `profa examples` to diff the pairs into edit patterns (phrase swaps, hedging/claim
calibration, trimmed filler) and build a retrieval index for few-shot grounding at review
time. `profa style` automatically folds a summary of these patterns into the style card
(pass `--no-examples` to compare a corpus-only card against corpus+examples).

No real pairs yet? `python scripts/make_sample_examples.py` generates a small, realistic
synthetic set so the whole pipeline is testable end-to-end. It also drops a
`.synthetic_examples` marker file here; every downstream artifact (style card, reviewer
prompts) checks for it and labels anything it derives from these pairs as demo/synthetic —
never as the professor's real editing decisions. The committed `config/style_card.md` is
built with `--no-examples` for that reason: it has no "Edit habits" section until real pairs
exist. Once you add his real before/after drafts (removing the synthetic pairs and their
marker), `profa examples && profa style` will rebuild that section from genuine edits.

This folder is git-ignored.
