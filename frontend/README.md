# FLOODSHIFT frontend (Person 2 — UI/UX & Projection)

Operator HUD + projector view. Renders `WorldSnapshot`s from the real FastAPI `WorldService` only; never computes routes, access, rejections or scores. There is no mock/offline mode: if the backend is down the UI says so.

```bash
# terminal 1 — repo root
uvicorn backend.main:app --port 8000          # FLOODSHIFT_SCENARIO=nepal_rasuwa_hot_v1 by default

# terminal 2
cd frontend
npm install
npm run dev                                   # VITE_API_URL defaults to http://localhost:8000
npm test                                      # vitest: reaction engine + route layers
npm run build                                 # typecheck + production build
```

- Operator: http://localhost:5173/
- Projector: http://localhost:5173/projector (second window/screen; `?mode=overlay` for the printed map)

If port 8000 is unavailable, run uvicorn on another port and start Vite with `VITE_API_URL=http://localhost:<port>`.

Keys, contracts, flood art, reactions and the game layer are documented in the master spec, §16 "As built — frontend".

| Path | What |
|---|---|
| `src/types/contracts.ts` | Mirror of `backend/contracts.py` (schema v2, incl. `game`, `service_routes[].board_uv`) |
| `src/types/scenario.ts` | Static scenario geometry from `GET /scenario` (roads, sites, hazard zones, flood corridors) |
| `src/hooks/useWorldSocket.ts` | Snapshot stream, actions (place/move/remove/advance/reset), log, feedback, reactions |
| `src/lib/liveTransport.ts` | FastAPI HTTP + WebSocket client with reconnect; no fallback data |
| `src/lib/worldReactions.ts` | Snapshot-diff → environmental reactions, headline, score delta |
| `src/lib/routeLayers.ts` | Per-edge grouping of backend service routes; route polylines |
| `src/components/FloodLayer.tsx` | Woodblock-style SVG flood, masked to backend hazard geometry |
| `src/components/MapProjection.tsx` | The SVG board (shared by projector and operator mini-map) |
| `src/components/ProjectionView.tsx` | Fullscreen projector + calibration |
| `src/components/OperatorPanel.tsx` | Operator HUD, controls, hardware-free test sequence |
| `src/components/GamePanels.tsx` | Game HUD, objectives, score breakdown, results modal |
