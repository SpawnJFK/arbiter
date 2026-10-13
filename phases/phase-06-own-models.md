# P06: Own models in production

## Goal

The first per-client LoRA fine-tune runs on real, consented, human-approved segments from a production customer, is evaluated on the held-out set with the org's judge route, competes on the scoreboard against the general engines, and is used for that client only when the numbers say it is better (D-059, D-088).

## Already built (not re-done here)

`arbiter/training/`: consented dataset export (human-approved segments, one org, one pair, one domain, deterministic train and validation split), Together and Fireworks adapters, the manual provider, `training_jobs` with its state machine, `custom_models` registered as `custom:<id>` engines, `training.poll` and `training.evaluate` work items, admin activation, scoreboard minimum `ARBITER_CUSTOM_MODEL_MIN_EVAL_SEGMENTS`, EU orgs restricted to the manual provider and EU-declared models. Web: `/app/training`. The `custom_models` add-on. All tested with stubbed providers only; the request shapes were written without Context7.

## Scope

1. **Preconditions.** P01 thresholds adopted for the pair, a customer with `training_consent` on and at least `ARBITER_TRAINING_MIN_EXAMPLES` approved segments in one pair and domain. If none exists yet, the phase waits (it does not use synthetic data, D-088).
2. **Provider check.** Context7 or the provider docs for Together and Fireworks fine-tune and serving APIs at their current versions, logged; fix the adapters; one small real job per provider on fictional data the owner owns, under the declared spend.
3. **First real training** for the consenting customer, through the provider the owner picks (decision entry: cost, data location, serving model), dataset manifest (hashes and counts only) in evidence, never segment text in the repo.
4. **Evaluation.** Held-out translation with the new model, judge scoring, `engine_scores` written, comparison report against the general engines with confidence intervals; activation only if it is better on the scoreboard, decided by the admin.
5. **Serving.** The endpoint's region declared truthfully; cost per word compared; budget cap on the endpoint.
6. **Lifecycle.** Consent withdrawal stops training and deactivates the model; retention of datasets and models per org; deletion with evidence.
7. **Subprocessor list** updated with the training and serving provider.
8. New journeys for training and activation, numbered at phase start.

## Human-only steps

Accounts with the chosen training provider: Together (https://api.together.xyz, Settings, API keys) or Fireworks (https://fireworks.ai, account settings, API keys, and the account id); paste as `ARBITER_TOGETHER_API_KEY=...` or `ARBITER_FIREWORKS_API_KEY=...` and `ARBITER_FIREWORKS_ACCOUNT_ID=...`. The customer's consent is given in the product by the customer, not by the owner.

## Declared spend

Training and serving costs, declared with amounts at phase start after the provider prices are read; suggested ceiling for the first training and evaluation 100 EUR. "apply" covers only what is declared then.

## Acceptance

Training, evaluation and activation journeys PROVEN with replayable records; comparison report in `docs/measurements/`; `npm run verify` and `npm run hp -- verify` clean.

## Exit gate

`npm run hp -- gate P06 --product` exits 0 and the P06 bead reads back closed.

## Out of scope

Self-hosted GPUs (D-059). A shared model across clients (never).
