"use client";

import { useEffect } from "react";
import { CONSENT_COOKIE, POSTHOG_HOST, POSTHOG_KEY } from "@/lib/config";

/**
 * Product analytics (PostHog EU). Disabled unless NEXT_PUBLIC_POSTHOG_KEY is set.
 *
 * Mounted only in the signed-in areas. Privacy defaults:
 *  - no autocapture, no session recording, no surveys, no feature-flag calls;
 *  - all text and element attributes masked (exceptions and pageviews still arrive);
 *  - without a consent decision nothing is stored on the device (memory persistence);
 *    with consent ("analytics" or "all" in the consent cookie) a first-party cookie keeps
 *    the anonymous id; a declined consent turns analytics off entirely.
 *  - the person is identified by the opaque user id only, never by email or name.
 */
export function Analytics({ userId, role }: { userId: string; role: string }) {
  useEffect(() => {
    if (!POSTHOG_KEY) return;
    const consent = readCookie(CONSENT_COOKIE);
    if (consent !== null && !/\b(analytics|all)\b/.test(consent)) return;
    let cancelled = false;
    void import("posthog-js").then(({ default: posthog }) => {
      if (cancelled) return;
      if (!posthog.__loaded) {
        posthog.init(POSTHOG_KEY, {
          api_host: POSTHOG_HOST,
          persistence: consent === null ? "memory" : "localStorage+cookie",
          autocapture: false,
          capture_pageview: "history_change",
          capture_pageleave: false,
          capture_exceptions: true,
          disable_session_recording: true,
          disable_surveys: true,
          advanced_disable_flags: true,
          mask_all_text: true,
          mask_all_element_attributes: true,
          person_profiles: "identified_only",
        });
      }
      posthog.identify(userId, { role });
    });
    return () => {
      cancelled = true;
    };
  }, [userId, role]);
  return null;
}

function readCookie(name: string): string | null {
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}
