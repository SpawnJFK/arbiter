#!/usr/bin/env node
// npm run verify:api: the backend half of the ship check, same steps as CI job "api":
// ruff check, ruff format --check, pytest. Runs inside services/api with its .venv
// (Linux/macOS .venv/bin, Windows .venv\Scripts). Needs local Postgres 16 + pgvector with the
// arbiter_test database (deploy/docker-compose.dev.yml). Tests never call real providers.
// Also used as the command of `cli` evidence verifiers (no arguments: the core's cli
// verifier rewrites node arguments into paths).

import path from "node:path";
import { apiPython, root, runSteps } from "./lib/proc.mjs";

const py = apiPython();
if (!py) {
  console.error(
    "[verify:api] services/api/.venv is missing. Create it (P00: `uv venv --python 3.13 services/api/.venv`, then `uv pip install -e services/api[dev]` with that venv's python).",
  );
  process.exit(1);
}

const cwd = path.join(root, "services", "api");
await runSteps("verify:api", [
  { cmd: py, args: ["-m", "ruff", "check", "."], cwd },
  { cmd: py, args: ["-m", "ruff", "format", "--check", "."], cwd },
  { cmd: py, args: ["-m", "pytest", "-q"], cwd },
]);
