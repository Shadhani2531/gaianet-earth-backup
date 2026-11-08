# Evaluations

Two scripts that measure GaiaNet Earth's main claims on real data. Both run
from `backend/` with the virtual environment active, reuse GaiaNet's own code
(nothing is re-implemented or changed), and save everything they download, so
a stopped run can simply be started again.

```powershell
cd backend
venv\Scripts\activate
```

## 1. Hazard reconciliation over 12 months — `eval_hazards.py`

```powershell
python eval\eval_hazards.py
```

Downloads the last 12 full months of GDACS and USGS records (about 1,000
requests; roughly 10–20 minutes, mostly polite pauses) and measures:

| | What it measures |
|---|---|
| E1 | Earthquake duplicate matching: precision/recall against the USGS event GDACS names in each quake's detail record (a fixed random sample of 400 plus all Orange/Red quakes; `--eq-sample N`), a threshold grid, and how many quakes would be listed twice without matching |
| E2 | "Active now": GaiaNet's rule vs "started in the last 7 days" and "GDACS flag only", at the moment of the run |
| E3 | How far GDACS's single flood/drought point can be from its own affected area; flood–landslide links |
| E4 | Impact rows: naive summing vs the old latest-row-per-country rule vs the current per-place range |
| E5 | "Magnitude 0" severities on floods and droughts |

Results: `eval/results/hazards_<start>_<end>.json` and `..._summary.md`.
Re-analyse without downloading: `python eval\eval_hazards.py --offline`.
Each run also appends its E2 snapshot to `eval/results/hazard_snapshots.jsonl`;
running it on a few different days gives a stronger E2 result.

## 2. Ask Gaia grounding — `eval_gaia.py`

Needs `GAIA_LLM_API_KEY` in `backend/.env`. For a reproducible run, set
`GAIA_LLM_MODEL` to one specific model that supports tool calling instead of
a router that switches models; the summary lists the models actually used.

```powershell
python eval\eval_gaia.py
```

Asks the 40 questions in `gaia_questions.json` to Ask Gaia and, as a
baseline, to the same model without tools (about 130–150 model calls, 4 s
apart). Each question goes to Gaia and then to the baseline, so a partial
run still gives matched pairs.

Daily limits: OpenRouter's free models allow 50 requests a day unless at
least $10 of credit has ever been bought (then 1,000). The script reads how
many you have left, stops cleanly when they run out or the provider reports
its daily limit, and says when it resets. Run the same command the next day;
saved answers are skipped. `--budget N` caps the calls for one run.

Results: `eval/results/gaia_eval_summary.md` and `gaia_eval_review.csv`.
Scores are automatic; open the CSV, check each reply and fill in
`manual_pass` (Y/N). Report the checked figures.
Rebuild the summary without new calls: `python eval\eval_gaia.py --report`.
After changing Ask Gaia's code, `python eval\eval_gaia.py --reset gaia` sets its saved
answers aside (a full copy is kept) so they are asked again; the baseline's answers,
which do not depend on GaiaNet's code, are kept. Use it once, not on every run.

To check fixes without disturbing the results, `python eval\eval_gaia.py --retest A07,C02`
asks Gaia just those questions again, saves the answers to `gaia_eval_retest.jsonl`
and writes a before/after table to `gaia_eval_retest_summary.md`. Add `--report` to rebuild
that table from the saved answers without asking again (after a change to the scoring code, say).
