export function formatMoney(value: number | null | undefined, currency = "EUR", sign = false): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency,
    signDisplay: sign ? "exceptZero" : "auto",
    maximumFractionDigits: 2
  }).format(value);
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${new Intl.NumberFormat("fr-FR", { maximumFractionDigits: digits }).format(value)} %`;
}

export function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("fr-FR", { maximumFractionDigits: digits }).format(value);
}

export function formatDate(value: string | null | undefined, withTime = false): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "medium",
    ...(withTime ? { timeStyle: "short" } : {})
  }).format(date);
}

export function formatDuration(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || Number.isNaN(minutes)) return "—";
  if (minutes < 60) return `${Math.round(minutes)} min`;
  const hours = Math.floor(minutes / 60);
  const rest = Math.round(minutes % 60);
  return `${hours} h ${rest.toString().padStart(2, "0")}`;
}

export function cardLabel(card: string): { rank: string; suit: string; red: boolean } {
  const normalized = card.trim().replace("10", "T");
  const rank = normalized.charAt(0).toUpperCase() || "?";
  const suitCode = normalized.charAt(1)?.toLowerCase();
  const suits: Record<string, string> = { h: "♥", d: "♦", c: "♣", s: "♠" };
  return { rank, suit: suits[suitCode] ?? suitCode?.toUpperCase() ?? "", red: suitCode === "h" || suitCode === "d" };
}

export function joinCards(cards?: string[]): string {
  return cards?.length ? cards.join(" ") : "—";
}

export function severityLabel(severity: string): string {
  return (
    {
      info: "Information",
      low: "Faible",
      medium: "Modérée",
      high: "Élevée",
      critical: "Critique"
    }[severity.toLowerCase()] ?? severity
  );
}
