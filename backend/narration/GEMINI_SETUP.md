# Gemini: what the operator needs to supply

Only a working **Gemini API key** is needed to test this module independently.
The real Nepal scenario, sample questions, tool declarations and offline fallback
are already included. No additional map downloads are required.

1. Open [Google AI Studio API keys](https://aistudio.google.com/apikey), sign in,
   and create or select a key in your project. Complete any Google account/project
   setup yourself. See the [official key guide](https://ai.google.dev/gemini-api/docs/api-key).
2. Copy `backend/narration/gemini.env.example` to `backend/narration/gemini.env`.
   Enter the key after `GEMINI_API_KEY=` **locally**. Do not send it in chat.
   `gemini.env` is ignored by this directory's `.gitignore`.
3. Leave `GEMINI_MODEL=gemini-flash-latest` initially, or use a specific model your
   account supports. This alias comes from the official Python SDK examples;
   the live test verifies account/model availability rather than assuming it.

The env file is a small configuration file, not a shell script. Only
`GEMINI_API_KEY` and `GEMINI_MODEL` assignments are accepted. Quotes are optional;
shell substitutions are never executed. The CLI does not print file contents.
If you prefer environment variables, omit `--env-file`.

## Install and test

From the repository root in your Python environment:

```sh
python -m pip install -r backend/world/requirements.txt -r backend/narration/requirements.txt

# Offline rehearsal; no cloud calls, always honestly marked TEXT.
python -m backend.narration.smoke

# Real Gemini calls; requires your local key and uses account quota.
python -m backend.narration.smoke --live \
  --env-file backend/narration/gemini.env \
  --report backend/narration/live_smoke_report.json
```

The report is Git-ignored. There are three questions: blocked access/bridge advice,
before/after branch comparison, and rejecting an unsupported real-rescue claim.
Each question uses at most three model requests and eight read-only tool calls.
Live questions are spaced 60 seconds apart by default to accommodate low free-tier
request quotas (`--interval-seconds` adjusts this). Missing local credentials do
not trigger the pause. The smoke test allows a 10-second per-request timeout; the normal adapter defaults
to the same 10 seconds after live latency checks. There is no unbounded retry loop.

Exit `0` in live mode means all three questions returned LIVE answers with actual
tool calls and no world mutation. A TEXT fallback returns exit `1`, so it cannot
masquerade as a successful API test. Exit `2` indicates local configuration/setup
failure. `narration_text_review_required=true` reminds us to review generated
answers against the attached authoritative metrics; a working API is not proof
that every sentence is correct.

## Failure reasons

| Reason | Next action |
| --- | --- |
| `missing_api_key` | Save the local key or export the server environment variable |
| `sdk_unavailable` | Install `backend/narration/requirements.txt` |
| `api_authentication_failed` | Check that the configured key is valid |
| `api_permission_denied` | Check project/API access and key restrictions in Google |
| `api_bad_request` | Verify key and model configuration; request format also needs checking |
| `api_model_not_found` | Set `GEMINI_MODEL` to an available model in your account |
| `api_quota_exceeded` | Check project quota in AI Studio; any billing decision is yours |
| `api_timeout` / `api_unavailable` | Retry a bounded smoke test when connectivity/service recovers |
| `incomplete_response` | Model stopped before completion; deterministic TEXT fallback is used |
| `tool_call_missing` / `round_limit` | Tool calling did not complete; inspect adapter/model compatibility |

Do not share SDK traceback dumps or screenshots containing a key. The adapter
returns sanitized reason codes instead of raw SDK error messages.

## P3 connection

`GeminiNarrator().answer(world, question)` is ready for P3's `/narrate` endpoint;
run it via `asyncio.to_thread` in an async server. P3 should load credentials into
the **backend process environment**; the CLI env-file loader is not automatically
used by the server. P2 reads `mode`, `text` and `world_version`, and should discard
responses older than the displayed world. Neither P2 nor the browser receives the
API key. Voice controls remain P2's responsibility.

## Live verification record

See [LIVE_VERIFICATION.md](LIVE_VERIFICATION.md): all three question behaviors
have returned reviewed LIVE results across runs. The latest full run was limited
by account quota and correctly failed overall; do not present it as all-green.
