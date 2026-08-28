import { POSITIONS, positionStyle } from "../lib/positions";

interface Props {
  active: string[];
  onChange: (next: string[]) => void;
  counts: Record<string, number>;
}

export default function PositionFilter({ active, onChange, counts }: Props) {
  const toggle = (position: string) =>
    onChange(
      active.includes(position) ? active.filter((p) => p !== position) : [...active, position],
    );

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => onChange([])}
        className={`chip border ${
          active.length === 0
            ? "border-slate-400/40 bg-slate-500/20 text-slate-200"
            : "border-line text-muted hover:text-slate-300"
        }`}
      >
        All
      </button>
      {POSITIONS.map((position) => {
        const style = positionStyle(position);
        const on = active.includes(position);
        return (
          <button
            key={position}
            type="button"
            onClick={() => toggle(position)}
            className={`chip border transition ${
              on ? `${style.chip} border-current` : "border-line text-muted hover:text-slate-300"
            }`}
            title={`${counts[position] ?? 0} available`}
          >
            {position}
          </button>
        );
      })}
    </div>
  );
}
