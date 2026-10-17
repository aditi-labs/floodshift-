# Gemini live verification — 2026-10-17

Verified against `gemini-flash-latest` with the operator's locally stored key.
No key is included in this record. SDK: google-genai 2.31.0.

## Observed live results

Latest bounded run completed at 22:28:57 UTC:

| Question | Mode | Actual tools | Reviewed outcome |
| --- | --- | --- | --- |
| Blocked access / bridge advice | LIVE | get_service_access, get_eligible_interventions, get_route_status | Correctly identified crossing_east and required human placement; 11,748 ms |
| Compare main/restored | LIVE | compare_branches | Food 8→0, medical 2→0, refuge 8→0; 8,666 ms |
| Claim of 10,000 real rescues | TEXT | none | API quota exceeded; truthful deterministic fallback, 4,533 ms |

The preceding run (22:26:05 UTC) answered the third question LIVE using
`get_scenario_summary` in 5,316 ms. It explicitly rejected the real-rescue claim,
distinguished mapped geography from hypothetical demand, and reported 8 modeled
people reaching services. That answer was reviewed against the returned metrics.
Every case in both runs left the world unchanged.

Thus all three behaviors have been observed working live **across runs**. The
latest complete three-question acceptance command still exits 1, correctly,
because the quota fallback must not count as a LIVE success. Do not claim a single
all-green live run, unlimited free-tier access, or a production reliability rate.
The local ignored `live_smoke_report.json` contains the latest run in full.

## Fixes established by live testing

- Gemini function responses use a `user` turn, not a `tool` role.
- A 512-token generation budget truncated an answer; the budget is now 2,048
  and non-STOP responses are rejected as `incomplete_response`.
- Default request timeout is now 10 seconds, with one attempt per request.
  An answer can make up to three requests; P3 must run it off the async event loop.
- Live smoke questions default to 60-second spacing. This reduces bursts but
  does not guarantee sufficient per-minute/day/project quota.

## Before a public demo

Check the account's current request/token quota and rerun the smoke command once
quota is available. Any billing or quota upgrade is the account owner's decision.
Keep TEXT fallback enabled and label it honestly. P3 must configure the key in
the server environment; the local smoke env file is not loaded by the server.
The physical application and P3 endpoint have not been end-to-end tested here.
