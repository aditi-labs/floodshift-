import type { TokenType } from "../types/contracts";

// Projected/HUD symbols. Each type pairs a distinct SHAPE with its colour so the
// UI never relies on colour alone (spec §16 accessibility). Palette follows the
// physical kit: blue medical, orange food, purple refuge, steel bridge, amber START.
export const TOKEN_COLORS: Record<TokenType, string> = {
  hospital: "var(--c-medical)",
  food_shelter: "var(--c-food)",
  shelter: "var(--c-refuge)",
  bridge: "var(--c-bridge)",
  disaster_start: "var(--c-start)",
  person: "var(--c-person)",
  truck: "var(--c-bridge)",
  helicopter: "var(--c-bridge)",
  time_dial: "var(--c-bridge)",
};

export function TokenGlyph({ type, size = 22 }: { type: TokenType; size?: number }) {
  const s = size / 2;
  const c = TOKEN_COLORS[type];
  const stroke = { stroke: c, strokeWidth: size * 0.09, fill: "none", strokeLinejoin: "round" as const, strokeLinecap: "round" as const };
  switch (type) {
    case "hospital":
      return (
        <g>
          <rect x={-s} y={-s} width={size} height={size} rx={size * 0.15} {...stroke} />
          <path d={`M0 ${-s * 0.6} V${s * 0.6} M${-s * 0.6} 0 H${s * 0.6}`} {...stroke} strokeWidth={size * 0.16} />
        </g>
      );
    case "shelter":
      return <path d={`M${-s} ${s * 0.8} L0 ${-s} L${s} ${s * 0.8} Z M${-s * 0.25} ${s * 0.8} L0 ${s * 0.2} L${s * 0.25} ${s * 0.8}`} {...stroke} />;
    case "food_shelter":
      return (
        <g>
          <path d={`M${-s} ${-s * 0.1} H${s} A${s} ${s * 0.9} 0 0 1 ${-s} ${-s * 0.1} Z`} {...stroke} />
          <path d={`M${-s * 0.4} ${-s * 0.4} V${-s} M${s * 0.1} ${-s * 0.4} V${-s} M${s * 0.6} ${-s * 0.4} V${-s * 0.9}`} {...stroke} />
        </g>
      );
    case "bridge":
      return (
        <g>
          <path d={`M${-s * 1.3} ${s * 0.4} H${s * 1.3}`} {...stroke} strokeWidth={size * 0.14} />
          <path d={`M${-s * 1.1} ${s * 0.4} Q0 ${-s * 1.1} ${s * 1.1} ${s * 0.4} M${-s * 0.5} ${-s * 0.1} V${s * 0.4} M0 ${-s * 0.35} V${s * 0.4} M${s * 0.5} ${-s * 0.1} V${s * 0.4}`} {...stroke} />
        </g>
      );
    case "disaster_start":
      return (
        <g>
          <path d={`M0 ${-s} L${s} ${s * 0.8} H${-s} Z`} {...stroke} />
          <path d={`M0 ${-s * 0.35} V${s * 0.2}`} {...stroke} />
          <circle cx={0} cy={s * 0.5} r={size * 0.04} fill={c} />
        </g>
      );
    case "person":
      return (
        <g>
          <circle cx={0} cy={-s * 0.5} r={s * 0.35} {...stroke} />
          <path d={`M${-s * 0.7} ${s} Q${-s * 0.7} ${-s * 0.05} 0 ${-s * 0.05} Q${s * 0.7} ${-s * 0.05} ${s * 0.7} ${s}`} {...stroke} />
        </g>
      );
    default:
      return <circle r={s} {...stroke} />;
  }
}

/** Standalone inline icon for HTML (operator panel buttons, legends). */
export function TokenIcon({ type, size = 18 }: { type: TokenType; size?: number }) {
  const pad = size * 0.4;
  const box = size + pad * 2;
  return (
    <svg width={box} height={box} viewBox={`${-box / 2} ${-box / 2} ${box} ${box}`} aria-hidden className="token-icon">
      <TokenGlyph type={type} size={size} />
    </svg>
  );
}
