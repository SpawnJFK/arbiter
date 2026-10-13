# P01: Measurement harness

## Goal

Prove, on one real language pair with real providers, whether the QE judge and senate can decide which segments ship without a human. English to Serbian is the first measurement pair: a test instrument, not the target market. The output is numbers from real runs (auto-approve rate, escaped-error rate with a confidence interval, senate agreement, cost per word), each tied to a replayable ledger record, and a threshold decision or a documented gap. If the owner has AWS Bedrock or Google Vertex access, the EU processing route (D-079) is measured on the same set.

## Already built (not re-done here)

The full pipeline, engines (Anthropic, OpenAI, DeepL, Google Basic v2, Bedrock, Vertex, OpenAI-compatible), engine keys in the database with BYOK resolution, routing rules and budgets (D-056 to D-058), the EU region filter (D-057), QE judge (MQM-Core), review senate with arbitration, calibration with control samples (`python -m arbiter.cli calibrate`), evidence pack JSON + PDF with the `processing` block. None of it has run with a real key.

## Scope

1. **Provider keys.** The owner creates the keys (human step A). The agent writes them into `services/api/.env` as `ARBITER_*` settings (names from `.env.example`), never prints them, and confirms each provider with one minimal authenticated call. `ARBITER_ENV=dev`, not test. Engine budgets (`engine_budgets`) are set per provider to the phase ceiling so the router stops before the cap.
2. **Smoke run per engine.** One small real job (a few segments) through each configured engine and through judge plus senate. Record model ids, prompt version (`PROMPT_VERSION`, `ASSISTANT_PROMPT_VERSION`), token counts and cost per call in `evidence/p01/smoke-<engine>.json`. This is INT-01.
3. **EU route (only if human step C was done).** One job for an org with `processing_region = eu` and the `eu_processing` add-on through Bedrock (EU inference profile) and/or Vertex (`eu`): confirm the exact profile id or host against the provider console, record the region the provider reports, and check the evidence pack `processing` block says `eu` for every call. Also prove the negative: with the EU engines removed, the job fails with `no EU engine configured` and nothing is sent elsewhere. This is INT-03. If step C is skipped, INT-03 stays UNPROVEN and moves to "before the first EU customer" in P03.
4. **Reference set.** Real EN to SR documents across at least 3 content types (for example UI strings, help or documentation, marketing or legal-style prose), only documents the owner has the right to use (his own or openly licensed). A qualified EN to SR linguist labels MQM errors per segment (human step B). Source texts and labels live outside git under `storagePolicy.artifactRoot` (`E:/.artifacts/arbiter/p01/`); the repo gets only a manifest with file hashes, segment counts per content type, labeller role and labelling date (`evidence/p01/refset-manifest.json`). No customer or agency names in any file.
5. **Harness.** A `python -m arbiter.cli measure` command (new, tested with mock providers like everything else) that runs the pipeline on the reference set, compares the decide step with the labels and writes a run file: per segment score, decision, label, engine, region, cost; per content type auto rate, escaped-error rate with a Wilson 95 % interval, senate agreement, cost per word. A second mode recomputes the report from a stored run file without calling any provider; that recompute is what the ledger verifier replays.
6. **Threshold sweep.** Escaped-error rate against auto-approve rate per content type over a threshold grid, from the stored run files, written as a table (and a chart if useful) in the report. If the EU route ran, the same sweep for the EU judge, side by side.
7. **Control samples.** Exercise the 2 % blind control-sample flow on the measurement jobs and run `calibrate --dry-run` on the result; record what it would change.
8. **Report.** `docs/measurements/p01-en-sr.md`: setup (models, prompt versions, regions, dates, segment counts), the numbers, the sweep, the proposed thresholds, and the gap if `escaped_error_target` is not met. Numbers only from the stored runs; each number names its ledger record.
9. **Decision.** A `docs/decisions.md` entry: thresholds adopted per content type for EN to SR, or the reason they are not, and what changes before more languages are calibrated in P04.

## Human-only steps

**A. Provider accounts and keys, each with a spend cap.**
1. Anthropic (required): open https://console.anthropic.com, sign in, click Settings, then "API Keys", "Create Key", name `arbiter-p01`, copy it. Then Settings, "Limits", set a monthly spend limit no higher than the P01 budget. Paste the key into the Cursor chat as `ARBITER_ANTHROPIC_API_KEY=...`.
2. DeepL (at least one MT engine): open https://www.deepl.com/your-account/keys, click "Create key", copy it. In the account's "Cost control" set a limit. Paste as `ARBITER_DEEPL_API_KEY=...`.
3. Google Cloud Translation Basic (optional second MT engine): open https://console.cloud.google.com, create a project `arbiter-p01`, search "Cloud Translation API" and click "Enable", then APIs & Services, Credentials, "Create credentials", "API key", "Restrict key" to Cloud Translation API. Set a budget alert under Billing, "Budgets & alerts". Paste as `ARBITER_GOOGLE_API_KEY=...`.
4. OpenAI (optional, for embeddings or as a second LLM): open https://platform.openai.com/api-keys, "Create new secret key"; set a monthly budget under Settings, Limits. Paste as `ARBITER_OPENAI_API_KEY=...`.
5. Success looks like: the agent reports one authenticated call per provider as VERIFIED, without showing any key.

**B. Reference documents and labels.**
1. Put the EN source documents (and any existing human SR translations) into `E:\.artifacts\arbiter\p01\source\`, one folder per content type.
2. The labeller marks MQM errors per segment in the sheet the agent generates (`E:\.artifacts\arbiter\p01\labels\`): category, severity, short note. The agent explains the MQM-Core categories in the sheet header.
3. Tell the agent "labels done" with the labeller's role (for example "certified EN to SR translator"), no name needed.

**C. EU route (optional in this phase; needed before the first EU customer).**
- AWS Bedrock:
  1. Open https://console.aws.amazon.com and sign in (or create an account at https://portal.aws.amazon.com/billing/signup).
  2. Top right, switch the region to "Europe (Frankfurt) eu-central-1".
  3. Search "Bedrock", open it, left menu "Model access" (or "Model catalog"), find Anthropic Claude, click "Request access" or "Enable", fill the use-case form if asked, submit. Wait until the status shows "Access granted".
  4. Search "IAM", Users, "Create user" `arbiter-bedrock`, "Attach policies directly", create an inline policy that allows only `bedrock:InvokeModel` and `bedrock:Converse` (the agent gives the JSON), create the user, open it, "Security credentials", "Create access key", choose "Application running outside AWS", copy both values.
  5. Billing, "Budgets", create a monthly cost budget at the EU ceiling below.
  6. Paste into the chat as `ARBITER_AWS_ACCESS_KEY_ID=...` and `ARBITER_AWS_SECRET_ACCESS_KEY=...`.
- Google Vertex AI:
  1. In https://console.cloud.google.com (same or new project), search "Vertex AI API" and click "Enable".
  2. Open "Vertex AI", "Model Garden", search "Claude", open the model card, click "Enable" and accept the terms.
  3. IAM & Admin, Service accounts, "Create service account" `arbiter-vertex`, role "Vertex AI User", then the account, "Keys", "Add key", "Create new key", JSON. The file downloads.
  4. Put the JSON file into `E:\.artifacts\arbiter\secrets\` and tell the agent its file name; the agent loads it into `ARBITER_VERTEX_SERVICE_ACCOUNT_JSON` without printing it, and sets `ARBITER_VERTEX_PROJECT` from the project id.
- Success looks like: the agent reports one EU call per configured route with the region the provider returned.

## Declared spend

Provider API usage only, up to the budget the owner states when he says "apply" (suggested ceiling: 50 EUR for the whole phase, plus up to 20 EUR for the EU route if step C is done). The harness estimates cost before each run from `arbiter/engines/pricing.py` and stops when the next run would exceed the remaining budget; `engine_budgets` caps each provider as a second line. No servers, no subscriptions.

## Acceptance

- INT-01: smoke runs recorded with model versions and cost, replayable records (`cli` recompute of the stored smoke files' totals).
- INT-02: threshold sweep report on the human-labelled EN to SR set, escaped-error rate per threshold with confidence intervals, replayable record whose verifier recomputes the report from the stored run file and checks the numbers in `docs/measurements/p01-en-sr.md`.
- INT-03 (only if step C): EU route smoke with provider-reported region, plus the blocked-without-EU-engine case, replayable record over the stored run file.
- Evidence pack (JSON + PDF) exists for every measurement job.
- Commands: `npm run verify` exit 0 (the new `measure` command has mock-provider tests), `npm run hp -- verify` 0 broken.

## Exit gate

`npm run hp -- gate P01 --product` exits 0 and the P01 bead reads back closed.

## Out of scope

Any cloud resource, deployment, backups (P02). Calibrating more languages (P04). Training own models (P06). Any change that makes tests call a real provider.
