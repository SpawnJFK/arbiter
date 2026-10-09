# .beads

Beads (`bd`, pinned 1.3.1, MIT) holds Arbiter's executable work graph: one bead per phase plus the work items under it. `HYPERPOWER.md` explains where it fits.

| File | Tracked | Purpose |
| --- | --- | --- |
| `config.yaml` | yes | prefix `arbiter`, export and import path `issues.jsonl`, no Dolt remote |
| `issues.jsonl` | yes | the graph as JSONL, the only thing that moves between machines |
| `.gitignore` | yes | keeps the per-machine Dolt store and runtime files out of git |
| `metadata.json` | yes, once `bd init` writes it in P00 | store metadata |
| `embeddeddolt/`, locks, logs | no | local store, rebuilt from `issues.jsonl` |

State today: `issues.jsonl` is empty. P00 installs `bd` from `.hyperpower/tools/registry.json` (SHA256 checked), runs `bd init --prefix arbiter` (or `bd bootstrap --yes` once the file has content), creates one bead per phase with `blocks` dependencies in order, writes each id into `hyperpower.json` `phases.P0x.beadId`, and exports with `bd export -o .beads/issues.jsonl`.

Rules:
- After any bead change: `bd export -o .beads/issues.jsonl` and commit it. The pre-push hook warns when the live store and the file differ.
- Phase beads are closed only by `npm run hp -- gate P0x --product`, which reads the bead back and refuses a close it cannot verify.
- Steps: `docs/runbooks/bootstrap-fresh-clone.md`.
