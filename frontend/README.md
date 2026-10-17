# FLOODSHIFT frontend (Person 2 — UI/UX & Projection)

Operator HUD + projector view. Renders `WorldSnapshot`s only; never computes routes, access or rejections.

```bash
cd frontend
npm install
npm run dev            # mock mode (default): scripted playthrough, no backend needed
```

- Operator: http://localhost:5173/
- Projector: http://localhost:5173/projector (open in a second window; `?mode=overlay` for the printed map)

Live backend: copy `.env.example` to `.env`, set `VITE_USE_MOCKS=false` and `VITE_API_URL`.

Keys, contracts and proposed snapshot fields are documented in the master spec, §16 "As built — frontend".

| Path | What |
|---|---|
| `src/types/contracts.ts` | Mirror of `backend/contracts.py` (schema v2) |
| `src/types/scenario.ts` | Static scenario geometry from `GET /scenario` |
| `src/hooks/useWorldSocket.ts` | Snapshot stream, actions, log, transient feedback |
| `src/lib/liveTransport.ts` | FastAPI HTTP + WebSocket client with reconnect |
| `src/mocks/` | Schematic scenario + scripted fixture snapshots + mock socket |
| `src/components/MapProjection.tsx` | The SVG board (shared by projector and operator mini-map) |
| `src/components/ProjectionView.tsx` | Fullscreen projector + calibration |
| `src/components/OperatorPanel.tsx` | Operator HUD |
