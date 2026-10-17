# Person 4 — durable sessions and narration integration

## Durable world service (P3 calls, P4 owns)

```python
from backend.world import WorldService
from backend.world.session_store import SessionError

world = WorldService.open_session(
    "/path/outside/repository/floodshift-session.sqlite3",
    "scenarios/nepal_rasuwa_hot_v1",
)
```

The parent directory must exist. Use a configured server-side path, never a path
supplied by a narrator or HTTP action. The file stores JSON checkpoints in SQLite,
using Python's standard library. Existing `WorldService()` / `from_bundle()` stay
in-memory for fixtures and tests. The public snapshot/action shape is unchanged.

- Every accepted mutation is committed before `apply()` acknowledges success.
  A failed write returns `accepted=False, reason="persistence_unavailable"`, with
  the old version, inventory and world intact. The gateway must not broadcast it
  as an accepted placement.
- A second writer with a stale checkpoint returns `session_conflict`. Reopen the
  session to recover the latest committed state; do not auto-overwrite it.
- On restart, the service verifies the JSON checksum and exact bundle fingerprint,
  replays the event log, and compares regenerated events and final snapshot to
  stored data. Branch history, baseline snapshots and accepted action IDs recover.
- Corrupt, incompatible or divergent sessions raise `SessionError`. Surface this
  to the operator; do not silently create a fresh game. To deliberately begin a
  separate session, choose a new filename. A normal `reset` remains a logged action
  with a monotonically increasing world version.
- This is a single-local-session implementation. It rewrites the session's small
  JSON checkpoint each commit; it is not a high-volume or multi-server event store.
  No runtime database, credentials or transient recordings belong in Git.

Proof from two separate processes:

```sh
python -m backend.world.session_demo --session /tmp/floodshift-demo.sqlite3
python -m backend.world.session_demo --session /tmp/floodshift-demo.sqlite3
```

First run performs the six-token HOT demo. Second run reports `recovered: true`
at the same world version and metrics without placing another token.

## Gemini adapter (optional; P3 owns the HTTP endpoint)

```sh
python -m pip install -r backend/narration/requirements.txt
```

Configure `GEMINI_API_KEY` **locally** in the server environment. Do not paste keys
into chat, commit them, or put them into frontend code. `GOOGLE_API_KEY` is an
alternative; if both exist, this adapter explicitly prefers `GEMINI_API_KEY`.
`GEMINI_MODEL` is optional; default `gemini-flash-latest` follows Google's SDK
example. Set a pinned model ID after verifying account availability for the demo.

```python
from backend.narration.gemini_adapter import GeminiNarrator

narrator = GeminiNarrator()
result = narrator.answer(world, "Where should we put the bridge?")
# In an async FastAPI route, avoid blocking the event loop:
# result = await asyncio.to_thread(narrator.answer, world, question)
```

Result fields: `mode` (`LIVE` or `TEXT`), `text`, `reason`, `world_version`,
`branch_id`, `model_only`, `facts` (authoritative metrics) and `tools_used`.
Use the returned mode for the GEMINI badge. Never label TEXT fallback as live.

The adapter seeds current facts and manually dispatches only the seven existing
read-only `WorldTools` methods. The model has no mutation tool. Each answer reads
one detached world version; if the actual world advances during generation, the
adapter discards that answer and returns a fresh state-derived TEXT summary.
P2 should still ignore a narration response older than its currently displayed
world version, because a new action can arrive after any response is returned.

Defaults: at most three model requests, eight tool calls, 10-second HTTP timeout
per request and one HTTP attempt per request. SDK errors, missing keys/dependencies,
empty/overlong responses and tool-budget exhaustion use the offline fallback.
Errors returned to clients contain stable reason codes, not SDK exception text.
Each generation allows at most 2,048 output tokens (including model reasoning);
the displayed answer remains capped at 90 words. Non-STOP completion reasons
fall back to TEXT, so a token-limited fragment is never accepted as a live answer.
The adapter sends the typed question and compact model facts to Gemini; it does
not upload camera frames, raw GIS downloads, event logs or credentials as prompts.

Generated text is prompted to stay grounded, but it is not a formal proof of factual
correctness. Authoritative metrics remain in `facts`; test the real account/model
against the demo questions before presenting LIVE narration. No live Gemini call
has been claimed by the mock/transport tests.

## Validation and remaining work

See [Gemini setup and live acceptance check](../narration/GEMINI_SETUP.md) for
the ignored local key file and bounded three-question smoke runner. The live
runner requires a successful read-only tool call for each answer and fails if
any answer falls back to TEXT. Authentication, quota, model and timeout failures
have separate sanitized reason codes; no API exception text is returned.

```sh
python -m pytest tests/test_world_*.py
```

With the optional SDK installed, the suite also runs an actual SDK serialization
test using an HTTP mock transport; no Gemini request or billing occurs. Without
the SDK, only that test skips. Session tests cover both schematic/HOT bundles,
branches, reset, duplicate events, disk-write failure, transaction rollback,
competing writers, corrupted checkpoints and recovery in a separate process.
Narration tests cover tool allowlists, bad arguments, timeout fallback, stale
world answers and bounded request loops.

The API endpoint/schema handshake remains P3's work; P2/P1 still own the matching
projection/print SVGs and hardware registration. Person 4 can fix simulation or
tolerance issues revealed by their integration. Tiger Data remains optional and
unimplemented. Live Gemini calls and read-only tools have been verified; the latest full smoke
run was quota-limited. See [LIVE_VERIFICATION.md](../narration/LIVE_VERIFICATION.md)
for reviewed results and the remaining account-quota check.

Implementation references checked against the official
[Google Gen AI Python SDK documentation](https://googleapis.github.io/python-genai/)
and [Gemini function-calling guide](https://ai.google.dev/gemini-api/docs/function-calling).
