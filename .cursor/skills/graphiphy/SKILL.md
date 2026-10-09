---
name: graphiphy
description: Token and typography discipline for the Arbiter web app. Maps the design tokens in apps/web/src/app/globals.css to Tailwind classes and blocks raw colours, ad hoc shadows and second typefaces. Use when adding CSS, Tailwind classes or new components in apps/web. Complements impeccable (slop detection) and design-taste-frontend (layout and copy).
version: 2.0.0
---

# Graphiphy

Tokens, not taste. This skill checks that new UI reads from the design system that exists. Arbiter has no visual `DESIGN.md` yet (`docs/DESIGN.md` is the system design); `apps/web/src/app/globals.css` is the visual source of truth until one is written.

## Read first

1. `apps/web/src/app/globals.css`: the `:root` tokens (light), the `prefers-color-scheme: dark` overrides and the `@theme inline` block that exposes them to Tailwind.
2. `apps/web/src/components/ui/`: button, card, badge, input, table, dialog, toast. Use these before writing a new primitive.

## Rules

- Colours only through token names: `bg`, `surface`, `subtle`, `hover`, `border`, `border-strong`, `fg`, `muted`, `faint`, `accent`, `accent-hover`, `accent-fg`, `accent-subtle`, `ok`, `warn`, `danger`, `info`, `violet` and their `-subtle` pairs, `ring`. No raw hex, `rgb(`, or Tailwind palette colours (`gray-*`, `blue-*`) in components. Every token has a dark value; a new colour without one breaks dark mode.
- Status colours carry meaning: `ok` delivered or passed, `warn` waiting or at risk, `danger` blocked or failed, `info` neutral system state, `violet` inline tags (`.tag-chip`). Do not use them for decoration.
- Type: the system stack in `--font-sans`, `--font-mono` for tags, ids and code. No webfont downloads. Numbers in tables use `.tabular`.
- Elevation: only `shadow-card` and `shadow-pop`. No other shadows, gradients, glow or blur (the dialog backdrop is the one exception).
- Focus: the global `:focus-visible` ring stays; never remove an outline without a visible replacement.
- Motion: none that `prefers-reduced-motion` does not switch off (globals.css already enforces it).
- Every visible string goes through `t()` with a key in `apps/web/messages/en.json` (`npm run i18n:check`).
- A new token needs the owner's approval and goes into `globals.css` (light and dark) with a `docs/decisions.md` entry.

## Check

On the changed files:

```
grep -nE "#[0-9a-fA-F]{3,8}\b|rgb\(|shadow-(sm|md|lg|xl|2xl)|gradient|(bg|text|border)-(gray|slate|zinc|neutral|red|blue|green|yellow)-[0-9]" <files>
```

Every hit is removed or justified in the review. Then run the impeccable `detect` and the `design-reviewer` subagent.
