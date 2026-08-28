import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Sleeper-ish dark cockpit. ink is the page, panel the cards,
        // line the hairlines between them.
        ink: "#0b0e14",
        panel: "#141922",
        raised: "#1c2230",
        line: "#252c3a",
        muted: "#7b8798",
        // Position accents, reused on board cells, list rows and the drawer.
        qb: "#ff4c6d",
        rb: "#12d6ba",
        wr: "#58a7ff",
        te: "#ffae58",
        k: "#c084fc",
        dst: "#94a3b8",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      keyframes: {
        clock: {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(88,167,255,0.55)" },
          "50%": { boxShadow: "0 0 0 4px rgba(88,167,255,0)" },
        },
      },
      animation: { clock: "clock 1.8s ease-out infinite" },
    },
  },
  plugins: [],
} satisfies Config;
