import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement>;
const base = { viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", strokeWidth: 1.5, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true } as const;

export const Icons = {
  folder: (p: P) => (
    <svg {...base} {...p}><path d="M2 4.5A1.5 1.5 0 0 1 3.5 3h2.6l1.5 1.5h4.9A1.5 1.5 0 0 1 14 6v5.5a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 11.5v-7z" /></svg>
  ),
  plus: (p: P) => (
    <svg {...base} {...p}><path d="M8 3v10M3 8h10" /></svg>
  ),
  book: (p: P) => (
    <svg {...base} {...p}><path d="M3 3.5A1.5 1.5 0 0 1 4.5 2H13v10H4.5A1.5 1.5 0 0 0 3 13.5v-10z" /><path d="M3 13.5A1.5 1.5 0 0 0 4.5 15H13v-3" /></svg>
  ),
  db: (p: P) => (
    <svg {...base} {...p}><ellipse cx="8" cy="4" rx="5" ry="2" /><path d="M3 4v8c0 1.1 2.2 2 5 2s5-.9 5-2V4M3 8c0 1.1 2.2 2 5 2s5-.9 5-2" /></svg>
  ),
  question: (p: P) => (
    <svg {...base} {...p}><circle cx="8" cy="8" r="6" /><path d="M6.3 6.2a1.8 1.8 0 0 1 3.5.6c0 1.2-1.8 1.5-1.8 2.6M8 11.5h.01" /></svg>
  ),
  alert: (p: P) => (
    <svg {...base} {...p}><path d="M8 2.5l6 10.5H2L8 2.5z" /><path d="M8 6.5v3M8 11.5h.01" /></svg>
  ),
  chart: (p: P) => (
    <svg {...base} {...p}><path d="M2.5 13.5h11M4.5 11V8M8 11V4.5M11.5 11V6.5" /></svg>
  ),
  gear: (p: P) => (
    <svg {...base} {...p}><circle cx="8" cy="8" r="2" /><path d="M8 1.8v1.6M8 12.6v1.6M3.6 3.6l1.1 1.1M11.3 11.3l1.1 1.1M1.8 8h1.6M12.6 8h1.6M3.6 12.4l1.1-1.1M11.3 4.7l1.1-1.1" /></svg>
  ),
  home: (p: P) => (
    <svg {...base} {...p}><path d="M2.5 7L8 2.5 13.5 7v6a.5.5 0 0 1-.5.5H10V10H6v3.5H3a.5.5 0 0 1-.5-.5V7z" /></svg>
  ),
  check: (p: P) => (
    <svg {...base} {...p}><path d="M3 8.5l3 3 7-7" /></svg>
  ),
  target: (p: P) => (
    <svg {...base} {...p}><circle cx="8" cy="8" r="6" /><circle cx="8" cy="8" r="3" /><path d="M8 8h.01" /></svg>
  ),
  wallet: (p: P) => (
    <svg {...base} {...p}><rect x="2" y="4" width="12" height="9" rx="1.5" /><path d="M2 6.5h12M10.5 9.5h1" /></svg>
  ),
  flag: (p: P) => (
    <svg {...base} {...p}><path d="M3.5 14V2.5M3.5 3h8l-1.5 3 1.5 3h-8" /></svg>
  ),
  users: (p: P) => (
    <svg {...base} {...p}><circle cx="6" cy="5.5" r="2.5" /><path d="M1.5 13.5c.5-2.3 2.3-3.5 4.5-3.5s4 1.2 4.5 3.5M11 3.2a2.3 2.3 0 0 1 0 4.6M12.2 10.2c1.2.5 2 1.6 2.3 3.3" /></svg>
  ),
  scale: (p: P) => (
    <svg {...base} {...p}><path d="M8 2v12M4.5 14h7M3 4.5h10M3 4.5L1.5 9a1.8 1.8 0 0 0 3 0L3 4.5zM13 4.5L11.5 9a1.8 1.8 0 0 0 3 0L13 4.5z" /></svg>
  ),
  building: (p: P) => (
    <svg {...base} {...p}><rect x="3" y="2" width="10" height="12" rx="1" /><path d="M6 5h1M9 5h1M6 8h1M9 8h1M7 14v-2.5h2V14" /></svg>
  ),
  key: (p: P) => (
    <svg {...base} {...p}><circle cx="5.5" cy="10.5" r="3" /><path d="M7.6 8.4L13 3M11 5l1.5 1.5" /></svg>
  ),
  hook: (p: P) => (
    <svg {...base} {...p}><path d="M6 2.5v6a3 3 0 1 0 6 0v-1M10 5.5l2 2 2-2" /></svg>
  ),
  receipt: (p: P) => (
    <svg {...base} {...p}><path d="M3.5 2h9v12l-2-1.2L8.5 14l-2-1.2L4.5 14l-1-0.6V2z" /><path d="M6 5.5h4M6 8h4" /></svg>
  ),
  menu: (p: P) => (
    <svg {...base} {...p}><path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" /></svg>
  ),
  logout: (p: P) => (
    <svg {...base} {...p}><path d="M6 13.5H3.5a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1H6M10.5 11l3-3-3-3M13.5 8H6" /></svg>
  ),
  download: (p: P) => (
    <svg {...base} {...p}><path d="M8 2.5v8M4.5 7.5L8 11l3.5-3.5M2.5 13.5h11" /></svg>
  ),
  upload: (p: P) => (
    <svg {...base} {...p}><path d="M8 11V3M4.5 6.5L8 3l3.5 3.5M2.5 13.5h11" /></svg>
  ),
  edit: (p: P) => (
    <svg {...base} {...p}><path d="M10.5 2.5l3 3L6 13H3v-3l7.5-7.5z" /></svg>
  ),
  search: (p: P) => (
    <svg {...base} {...p}><circle cx="7" cy="7" r="4.5" /><path d="M10.5 10.5L14 14" /></svg>
  ),
  arrowRight: (p: P) => (
    <svg {...base} {...p}><path d="M3 8h10M9 4l4 4-4 4" /></svg>
  ),
  grid: (p: P) => (
    <svg {...base} {...p}><rect x="2.5" y="2.5" width="4.5" height="4.5" rx="1" /><rect x="9" y="2.5" width="4.5" height="4.5" rx="1" /><rect x="2.5" y="9" width="4.5" height="4.5" rx="1" /><rect x="9" y="9" width="4.5" height="4.5" rx="1" /></svg>
  ),
  kanban: (p: P) => (
    <svg {...base} {...p}><rect x="2" y="2.5" width="3.5" height="11" rx="1" /><rect x="6.25" y="2.5" width="3.5" height="7" rx="1" /><rect x="10.5" y="2.5" width="3.5" height="9" rx="1" /></svg>
  ),
  checklist: (p: P) => (
    <svg {...base} {...p}><path d="M2.5 4l1.2 1.2L6 3M2.5 10l1.2 1.2L6 9M8 4.5h5.5M8 10.5h5.5" /></svg>
  ),
  tag: (p: P) => (
    <svg {...base} {...p}><path d="M2.5 2.5h5l6 6-5 5-6-6v-5z" /><circle cx="5.25" cy="5.25" r="0.9" /></svg>
  ),
  flow: (p: P) => (
    <svg {...base} {...p}><rect x="1.5" y="6" width="3.5" height="4" rx="1" /><rect x="11" y="2" width="3.5" height="4" rx="1" /><rect x="11" y="10" width="3.5" height="4" rx="1" /><path d="M5 8h3m0 0V4h3M8 8v4h3" /></svg>
  ),
  sparkle: (p: P) => (
    <svg {...base} {...p}><path d="M8 2l1.4 3.6L13 7l-3.6 1.4L8 12l-1.4-3.6L3 7l3.6-1.4L8 2zM12.5 11.5l.6 1.4 1.4.6-1.4.6-.6 1.4-.6-1.4-1.4-.6 1.4-.6.6-1.4z" /></svg>
  ),
  send: (p: P) => (
    <svg {...base} {...p}><path d="M2.5 8L13.5 2.5 10 13.5 7.5 8.5 2.5 8z" /></svg>
  ),
  trash: (p: P) => (
    <svg {...base} {...p}><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 9h5.8l.6-9" /></svg>
  ),
  up: (p: P) => (
    <svg {...base} {...p}><path d="M8 12.5v-9M4.5 7L8 3.5 11.5 7" /></svg>
  ),
  down: (p: P) => (
    <svg {...base} {...p}><path d="M8 3.5v9M4.5 9L8 12.5 11.5 9" /></svg>
  ),
  phone: (p: P) => (
    <svg {...base} {...p}><path d="M4 2.5h2l1 3-1.5 1a7 7 0 003 3l1-1.5 3 1v2a1 1 0 01-1 1A10.5 10.5 0 013 3.5a1 1 0 011-1z" /></svg>
  ),
  mail: (p: P) => (
    <svg {...base} {...p}><rect x="2" y="3.5" width="12" height="9" rx="1.5" /><path d="M2.5 4.5L8 9l5.5-4.5" /></svg>
  ),
  note: (p: P) => (
    <svg {...base} {...p}><path d="M3.5 2.5h6l3 3v8h-9v-11z" /><path d="M9.5 2.5v3h3M5.5 8.5h5M5.5 11h3" /></svg>
  ),
  calendar: (p: P) => (
    <svg {...base} {...p}><rect x="2.5" y="3.5" width="11" height="10" rx="1.5" /><path d="M2.5 6.5h11M5.5 2v3M10.5 2v3" /></svg>
  ),
  keyboard: (p: P) => (
    <svg {...base} {...p}><rect x="1.5" y="4" width="13" height="8" rx="1.5" /><path d="M4 6.5h.01M6.5 6.5h.01M9 6.5h.01M11.5 6.5h.01M5 9.5h6" /></svg>
  ),
  globe: (p: P) => (
    <svg {...base} {...p}><circle cx="8" cy="8" r="6" /><path d="M2 8h12M8 2c1.7 1.8 2.5 3.8 2.5 6S9.7 12.2 8 14C6.3 12.2 5.5 10.2 5.5 8S6.3 3.8 8 2z" /></svg>
  ),
};

export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <rect x="1" y="1" width="22" height="22" rx="6" fill="var(--accent)" />
      <path d="M7 17L12 6l5 11M9.2 13h5.6" stroke="var(--accent-fg)" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
