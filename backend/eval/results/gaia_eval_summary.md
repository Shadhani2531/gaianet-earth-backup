# Ask Gaia grounding evaluation (automatic scores — verify with the review CSV)

Models served: cohere/north-mini-code:free, dots-studio/dots-3-note-preview:free, google/gemma-4-26b-a4b-it:free, liquid/lfm-2.5-2.6b:free, liquid/lfm-3-1.7b:free, nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free, nvidia/nemotron-3-ultra-550b-a55b:free, nvidia/nemotron-3.5-lightning:free, nvidia/nemotron-3.5-super-vl:free, recursive/flint-v1.0:free, xingchen-agi/xing4.0-29b-a4b:free
Scored answers: 74 · still failing (re-run to retry): 0

## What each reply did

| Category | System | n | tool-backed values | unsupported values | asked which place | said not found | said unavailable or declined | empty or malformed | no values (other) |
|---|---|---|---|---|---|---|---|---|---|
| A  needs live numbers | gaia | 16 | 14 | 1 | 1 | 0 | 0 | 0 | 0 |
| A  needs live numbers | baseline | 16 | 0 | 4 | 0 | 0 | 9 | 2 | 1 |
| B  ambiguous place | gaia | 8 | 2 | 0 | 6 | 0 | 0 | 0 | 0 |
| B  ambiguous place | baseline | 8 | 0 | 1 | 0 | 0 | 7 | 0 | 0 |
| C  place not found | gaia | 6 | 2 | 0 | 2 | 1 | 0 | 0 | 1 |
| C  place not found | baseline | 6 | 0 | 0 | 1 | 1 | 4 | 0 | 0 |
| D  methods and limits | gaia | 4 | 0 | 0 | 0 | 0 | 1 | 0 | 3 |
| D  methods and limits | baseline | 4 | 0 | 0 | 0 | 0 | 2 | 0 | 2 |
| E  tool failure injected | gaia | 6 | 0 | 0 | 0 | 0 | 6 | 0 | 0 |

## Expected behaviour per category (automatic)

| Category | System | n | Pass | With unsupported values | Value claims (unsupported) |
|---|---|---|---|---|---|
| A  needs live numbers | gaia | 16 | 14 (88%) | 1 (6%) | 57 (1) |
| A  needs live numbers | baseline | 16 | 0 (0%) | 4 (25%) | 40 (40) |
| B  ambiguous place | gaia | 8 | 8 (100%) | 0 (0%) | 6 (0) |
| B  ambiguous place | baseline | 8 | 0 (0%) | 1 (12%) | 8 (8) |
| C  place not found | gaia | 6 | 2 (33%) | 0 (0%) | 2 (0) |
| C  place not found | baseline | 6 | 1 (17%) | 0 (0%) | 0 (0) |
| D  methods and limits | gaia | 4 | 4 (100%) | 0 (0%) | 0 (0) |
| D  methods and limits | baseline | 4 | 1 (25%) | 0 (0%) | 0 (0) |
| E  tool failure injected | gaia | 6 | 6 (100%) | 0 (0%) | 0 (0) |

Gaia called at least one tool in 24 of 24 category A/B questions.