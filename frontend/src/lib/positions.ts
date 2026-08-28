/** Position accents, shared by the board cells, the pool list and the drawer. */

export const POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"] as const;
export type KnownPosition = (typeof POSITIONS)[number];

interface PositionStyle {
  /** Tailwind text color. */
  text: string;
  /** Tailwind background for the solid chip. */
  chip: string;
  /** Tailwind border color for the cell's left edge. */
  border: string;
  /** Raw hex, for inline styles where a token will not do. */
  hex: string;
}

const STYLES: Record<string, PositionStyle> = {
  QB: { text: "text-qb", chip: "bg-qb/20 text-qb", border: "border-l-qb", hex: "#ff4c6d" },
  RB: { text: "text-rb", chip: "bg-rb/20 text-rb", border: "border-l-rb", hex: "#12d6ba" },
  WR: { text: "text-wr", chip: "bg-wr/20 text-wr", border: "border-l-wr", hex: "#58a7ff" },
  TE: { text: "text-te", chip: "bg-te/20 text-te", border: "border-l-te", hex: "#ffae58" },
  K: { text: "text-k", chip: "bg-k/20 text-k", border: "border-l-k", hex: "#c084fc" },
  DST: { text: "text-dst", chip: "bg-dst/20 text-dst", border: "border-l-dst", hex: "#94a3b8" },
};

const FALLBACK: PositionStyle = {
  text: "text-muted",
  chip: "bg-line text-muted",
  border: "border-l-line",
  hex: "#7b8798",
};

export const positionStyle = (position: string | null | undefined): PositionStyle =>
  STYLES[(position ?? "").toUpperCase()] ?? FALLBACK;
