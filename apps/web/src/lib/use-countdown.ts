"use client";

import { useEffect, useState } from "react";

/** Milliseconds left until `deadline` (epoch ms), ticking every 250 ms. `null` deadline -> null. */
export function useCountdown(deadline: number | null): number | null {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    if (deadline === null) return;
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0);
    const timer = setInterval(tick, 250);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [deadline]);
  if (deadline === null || now === null) return null;
  return Math.max(0, deadline - now);
}

export function formatClock(ms: number): string {
  const s = Math.ceil(ms / 1000);
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}
