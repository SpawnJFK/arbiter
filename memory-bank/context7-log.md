# Context7 log

Append-only. One line per library lookup before code was written against it.

Format: `date | library | version or Context7 id | source (context7 or fallback) | what was confirmed`

A gate fails if a library touched in the phase has no line here with a version.

---

2026-10-09 | all libraries used by the build up to commit 32e8cd0 (FastAPI, SQLAlchemy 2, Alembic, pydantic v2, psycopg 3, pgvector, Next.js 16.4, React 19.3, Tailwind 4, Playwright) | versions in services/api/pyproject.toml and apps/web/package-lock.json | fallback | The cloud build sessions had no Context7 (open item 5 in activeContext.md). APIs were written against installed package sources and `apps/web/node_modules/next/dist/docs/`. P00 item 16 re-checks the conventions the code relies on in Context7 and logs each one here.
2026-10-09 | Node.js built-ins (child_process spawn, fetch, AbortSignal.timeout) for the root scripts in scripts/ | Node 24.21 | fallback | No Context7 in the install session; behaviour confirmed by running every script under Node 24.21 (verify, verify:e2e, sql verifier, git hooks). spawn of npm.cmd on Windows uses shell: true because Node refuses .cmd without a shell; unproven on Windows until P00.
2026-10-13 | boto3 / botocore (S3 client, generate_presigned_url put_object/get_object, head_object, Config addressing_style) | 1.43.112 | fallback | No Context7 in this build session; confirmed against the installed sources and exercised with moto 5.2.4 (mock_aws) in tests/api/test_api_ops_storage.py and test_api_ops_uploads.py.
2026-10-13 | posthog (python) | 7.68.0 | fallback | Posthog(project_api_key, host=, privacy_mode=, disable_geoip=, enable_exception_autocapture=), capture(event, distinct_id=, properties=) keyword-only, $ai_generation property names read from posthog/ai/utils.py.
2026-10-13 | opentelemetry-sdk, exporter-otlp-proto-http, instrumentation-fastapi, instrumentation-sqlalchemy | 1.45.1 / 0.66b1 | fallback | FastAPIInstrumentor.instrument_app(app, excluded_urls=), SQLAlchemyInstrumentor().instrument(engine=, enable_commenter=), OTLPSpanExporter(endpoint=, headers=) signatures read with inspect from the installed packages.
2026-10-13 | posthog-js | 1.434.18 (pinned, older than two weeks) | fallback | Config keys (api_host, persistence, autocapture, capture_pageview "history_change", capture_exceptions, disable_session_recording, disable_surveys, advanced_disable_flags, mask_all_text, mask_all_element_attributes, person_profiles) read from node_modules/@posthog/types/dist/posthog-config.d.ts; tsc passes.
2026-10-13 | Kamal 2 config keys, GitHub Actions (docker/build-push-action@v6, actions/attest-build-provenance@v2, tailscale/github-action@v3) | kamal ~> 2.7 | fallback | rubygems.org is blocked in the build session, so `kamal config` could not run; YAML parsed and workflows checked with actionlint 1.7 (pip actionlint-py). P02 must run `kamal config -d staging` with real env before the first deploy.
2026-10-13 | cryptography (Fernet, MultiFernet, HKDF), pyjwt (PyJWK, get_unverified_header, decode with audience/issuer/require, RSAAlgorithm.to_jwk), httpx (MockTransport, BasicAuth), FastAPI router-level dependencies, Starlette pure ASGI middleware | cryptography 50.0.2, pyjwt 2.15.1, httpx 0.28, FastAPI as installed | fallback | Platform module build (modules, roles, audit, OIDC SSO) ran in a parallel worktree without Context7. Signatures were read from the installed packages with inspect.signature and confirmed by the tests in services/api/tests/platform (fake IdP with local RSA keys).
