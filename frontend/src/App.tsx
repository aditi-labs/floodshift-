import { useWorldSocket } from "./hooks/useWorldSocket";
import { OperatorPanel } from "./components/OperatorPanel";
import { ProjectionView } from "./components/ProjectionView";

// Two screens, one source of truth: both subscribe to the same WorldSnapshot stream.
//   /           operator laptop HUD
//   /projector  fullscreen projector output (?mode=overlay over the printed map)
export function App() {
  const world = useWorldSocket();
  const isProjector = window.location.pathname.replace(/\/$/, "").endsWith("/projector");
  return isProjector ? <ProjectionView world={world} /> : <OperatorPanel world={world} />;
}
