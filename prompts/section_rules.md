# Section-specific expectations

Use these conventions when reviewing each section type.

## Content vs. language calibration (applies to every section)

Ask "does this change what is being claimed?" before choosing `content` severity:

- Missing a parameter/value, a number, a citation, or a claim of novelty/significance ->
  `content` (flag only — do not invent the missing value, do not silently add a citation,
  do not soften "significant" into a hedge yourself).
- Wordiness, repetition, informal tone, awkward grammar, generic openers, run-on
  sentences -> `language` / `clarity` / `structure` (rewrite freely).
- Non-standard terminology vs. the group's usual terms -> `terminology` (rewrite to the
  preferred term from RETRIEVED CONTEXT / PROFESSOR'S PAST EDITS).

Do not default to `content` "to be safe" — over-flagging ordinary wording as `content`
is itself a false positive that erodes trust and buries the real flags. Reserve `content`
for cases where the wording change would actually alter a scientific claim, number,
citation, or degree of certainty; everything else gets a rewrite under the appropriate
non-`content` severity.

## Abstract
- One paragraph. Motivation → gap → what was done → key result (qualitative) → significance.
- No citations, no undefined acronyms, no figures/tables references.
- Avoid vague openers ("In recent years...") — rewrite as `clarity`, not `content`.
- Unsupported superlatives about the result's importance ("this is the best...") -> `content`.

## Introduction
- Funnel: broad field → specific problem → prior work + gap → this work's contribution.
- Last paragraph should clearly state the contribution/novelty.
- Claims of novelty must be hedged appropriately ("to the best of our knowledge") — an
  unhedged novelty claim is `content` (flag); a merely awkward hedge is `language` (rewrite).

## Methods / Experimental
- Reproducible, past tense, passive acceptable here.
- Instruments/materials with parameters; do not invent missing parameters — flag as
  `content`. Awkward phrasing of a parameter that IS present is `language`, not `content`.

## Results
- Report observations objectively; interpretation belongs in Discussion.
- Each figure/table must be referenced and described.
- Numbers/units consistent; do NOT alter any numeric value — flag inconsistencies as
  `content`. Restating a number in clearer prose (without changing the number) is `clarity`.

## Discussion
- Interpret results, compare with prior work, state limitations.
- Distinguish speculation from supported conclusions — unsupported causal claims ("this
  proves...") are `content`; a wordy but already-hedged interpretation is `clarity`.

## Conclusion
- Concise summary of findings + outlook. No new results — a new claim introduced here
  that doesn't appear earlier in the draft is `content`.
