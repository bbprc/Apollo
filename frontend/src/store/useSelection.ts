/** Which player the drawer is showing. */

import { useCallback, useState } from "react";
import type { PlayerScore } from "../api/types";

export function useSelection() {
  // The drawer opens from the PlayerScore the list already holds, so its first
  // paint costs nothing — the slower per-player calls fill in behind it.
  const [selected, setSelected] = useState<PlayerScore | null>(null);
  return {
    selected,
    select: useCallback((score: PlayerScore) => setSelected(score), []),
    close: useCallback(() => setSelected(null), []),
  };
}
