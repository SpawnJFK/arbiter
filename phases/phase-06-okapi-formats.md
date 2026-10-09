# P06: More formats via Okapi

## Goal

Long-tail file formats through an Okapi Framework sidecar behind the existing `FormatHandler` interface, producing the same tagged text model as the Python handlers.

## Scope

1. Okapi Framework sidecar (Java service) in compose, internal network only, pinned version, licence recorded in `.hyperpower/tools/registry.json` style notes (Apache-2.0 expected; verify).
2. `FormatHandler` adapter that calls the sidecar and converts to and from tagged text (`⟦n⟧`).
3. IDML, DITA and at least three more formats with round-trip tests.
4. Parity check against the Python handlers for overlapping formats; differences documented in a decision entry.
5. Upload validation lists supported formats from the handler registry.
6. J-01 extended: a quote and delivery for one Okapi format end to end.

## Human-only steps

None expected.

## Declared spend

None: the sidecar runs on the existing host. If memory requires a larger server type, that is declared and approved first.

## Acceptance

Round-trip tests green in `npm run verify`; the extended J-01 PROVEN; `npm run hp -- verify` clean.

## Exit gate

`npm run hp -- gate P06 --product` exits 0 and the P06 bead reads back closed.

## Out of scope

Connectors (P05), enterprise (P07).
