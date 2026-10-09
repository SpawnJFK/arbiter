# P01: Measurement harness

## Goal

Prove, on one real language pair with real providers, whether the QE judge and senate can decide which segments ship without a human. English to Serbian is the first measurement pair: a test instrument, not the target market. The output is numbers from real runs (auto-approve rate, escaped-error rate with a confidence interval, senate agreement, cost per word), each tied to a replayable ledger record, and a threshold decision or a documented gap.

## Already built (not re-done here)

The full pipeline, engines (Anthropic, OpenAI, DeepL, Google Basic v2), QE judge (MQM-Core), review senate with arbitration, calibration with control samples (`arbiter/quality/calibration.py`, `python -m arbiter.cli calibrate`), evidence pack JSON + PDF, and the automated `alembic upgrade head` equals `create_all` check. None of it has run with a real key.

## Scope

1. **Provider keys.** The owner creates the keys (human step A). The agent writes them into `services/api/.env` as `ARBITER_*` settings (names from `.env.example`), never prints them, and confirms each provider with one minimal authenticated call. `ARBITER_ENV=dev`, not test.
2. **Smoke run per engine.** One small real job (a few segments) through each configured engine and through judge plus senate. Record model ids, prompt version (`PROMPT_VERSION`, `ASSISTANT_PROMPT_VERSION`), token counts and cost per call in `evidence/p01/smoke-<engine>.json`. This is INT-01 (Anthropic judge and senate) and INT-02 (DeepL and/or Google MT).
3. **Reference set.** Real EN to SR documents across at least 3 content types (for example UI strings, help or documentation, marketing or legal-style prose), only documents the owner has the right to use (his own or openly licensed). A qualified EN to SR linguist labels MQM errors per segment (human step B). Source texts and labels live outside git under `storagePolicy.artifactRoot` (`E:/.artifacts/arbiter/p01/`); the repo gets only a manifest with file hashes, segment counts per content type, labeller role and labelling date (`evidence/p01/refset-manifest.json`). No customer or agency names in any file.
4. **Harness.** A `python -m arbiter.cli measure` command (new, tested with mock providers like everything else) that runs the pipeline on the reference set, compares the decide step with the labels and writes a run file: per segment score, decision, label, engine, cost; per content type auto rate, escaped-error rate with a Wilson 95 % interval, senate agreement, cost per word. A second mode recomputes the report from a stored run file without calling any provider; that recompute is what the ledger verifier replays.
5. **Threshold sweep.** Escaped-error rate against auto-approve rate per content type over a threshold grid, from the stored run files, written as a table (and a chart if useful) in the report.
6. **Control samples.** Exercise the 2 % blind control-sample flow on the measurement jobs and run `calibrate --dry-run` on the result; record what it would change.
7. **Report.** `docs/measurements/p01-en-sr.md`: setup (models, prompt versions, dates, segment counts), the numbers, the sweep, the proposed thresholds, and the gap if `escaped_error_target` is not met. Numbers only from the stored runs; each number names its ledger record.
8. **Decision.** A `docs/decisions.md` entry: thresholds adopted per content type for EN to SR, or the reason they are not, and what changes before more languages are calibrated in P04.

## Human-only steps

**A. Provider accounts and keys, each with a spend cap.**
1. Anthropic (required): https://console.anthropic.com, Settings, "API Keys", "Create Key", name `arbiter-p01`. Then Settings, "Limits", set a monthly spend limit no higher than the P01 budget. Paste the key into the Cursor chat as `ARBITER_ANTHROPIC_API_KEY=...`.
2. DeepL (at least one MT engine): https://www.deepl.com/your-account/keys, "Create key". In account settings set a cost control limit. Paste as `ARBITER_DEEPL_API_KEY=...`.
3. Google Cloud Translation Basic (optional second MT engine): https://console.cloud.google.com, create a project, enable "Cloud Translation API", APIs & Services, Credentials, "Create credentials", "API key", restrict it to Cloud Translation API. Set a budget alert under Billing, Budgets & alerts. Paste as `ARBITER_GOOGLE_API_KEY=...`.
4. OpenAI (optional, for embeddings or as a second LLM): https://platform.openai.com/api-keys, "Create new secret key"; set a monthly budget under Settings, Limits. Paste as `ARBITER_OPENAI_API_KEY=...`.
5. Success looks like: the agent reports one authenticated call per provider as VERIFIED, without showing any key.

**B. Reference documents and labels.**
1. Put the EN source documents (and any existing human SR translations) into `E:\.artifacts\arbiter\p01\source\`, one folder per content type.
2. The labeller marks MQM errors per segment in the sheet the agent generates (`E:\.artifacts\arbiter\p01\labels\`): category, severity, short note. The agent explains the MQM-Core categories in the sheet header.
3. Tell the agent "labels done" with the labeller's role (for example "certified EN to SR translator"), no name needed.

## Declared spend

Provider API usage only, up to the budget the owner states when he says "apply" (suggested ceiling: 50 EUR for the whole phase). The harness estimates cost before each run from `arbiter/engines/pricing.py` and stops when the next run would exceed the remaining budget. No servers, no subscriptions.

## Acceptance

- INT-01 and INT-02: smoke runs recorded with model versions and cost, replayable records (`cli` recompute of the stored smoke files' totals).
- INT-03: threshold sweep report on the human-labelled EN to SR set, escaped-error rate per threshold with confidence intervals, replayable record whose verifier recomputes the report from the stored run file and checks the numbers in `docs/measurements/p01-en-sr.md`.
- Evidence pack (JSON + PDF) exists for every measurement job.
- Commands: `npm run verify` exit 0 (the new `measure` command has mock-provider tests), `npm run hp -- verify` 0 broken.

## Exit gate

`npm run hp -- gate P01 --product` exits 0 and the P01 bead reads back closed.

## Out of scope

Deployment, backups and the restore drill (P02). Calibrating more languages (P04). Any change that makes tests call a real provider.
