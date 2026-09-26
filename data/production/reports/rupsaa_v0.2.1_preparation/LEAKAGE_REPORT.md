# V0.2.1 leakage report

**Result: PASS — no leakage found**

Held-out corrective cases: 21 (c021-003, c021-020, c021-021, c021-023, c021-036, c021-040, c021-050, c021-064, c021-065, c021-078, c021-080, c021-087, c021-096, c021-103, c021-106, c021-113, c021-121, c021-138, c021-143, c021-156, c021-161); corrective train: 141.

Checked, on user and assistant turns (normalised case/punctuation):
1. held-out vs corrective train — exact, near-duplicate (≥0.8), same terminology entry, same definition concept
2. held-out vs the frozen V0.2 train/validation/test — exact, near-duplicate, concept keyword
3. every corrective record vs 100 benchmark prompts (owner's 11-turn live sequence, 10 live checks, 29 supplementary checks, 24 unseen-terminology cases) at ≥0.9 or exact, vs the 24 unseen terms + Strip/Foreplay, and vs all 412 frozen validation/test turns (which contain the clean V0.1-vs-V0.2 subsets) at ≥0.9
Strings under 12 characters are compared exactly only ("ok" vs "okay" similarity is meaningless).

## Blocking findings

none

## Warnings (short strings identical to frozen data)

none
