type Tone = "ok" | "warn" | "bad" | "neutral" | "info";

export function StateBadge({ label, value, tone = "neutral", title }: { label: string; value: string; tone?: Tone; title?: string }) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      <span className="badge-label">{label}</span>
      <span className="badge-value">{value}</span>
    </span>
  );
}
