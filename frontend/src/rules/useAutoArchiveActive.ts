import { useCallback, useEffect, useState } from "react";
import { getAutoArchiveActiveCodes } from "../api";

export function useAutoArchiveActive() {
  const [active, setActive] = useState<Set<string>>(new Set());

  const refresh = useCallback(() => {
    getAutoArchiveActiveCodes()
      .then((codes) => setActive(new Set(codes)))
      .catch(() => {});
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  return { active, refresh };
}
