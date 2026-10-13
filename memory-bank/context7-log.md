# Context7 log

Append-only. One line per library lookup before code was written against it.

Format: `date | library | version or Context7 id | source (context7 or fallback) | what was confirmed`

A gate fails if a library touched in the phase has no line here with a version.

---

2026-10-09 | all libraries used by the build up to commit 32e8cd0 (FastAPI, SQLAlchemy 2, Alembic, pydantic v2, psycopg 3, pgvector, Next.js 16.4, React 19.3, Tailwind 4, Playwright) | versions in services/api/pyproject.toml and apps/web/package-lock.json | fallback | The cloud build sessions had no Context7 (open item 5 in activeContext.md). APIs were written against installed package sources and `apps/web/node_modules/next/dist/docs/`. P00 item 16 re-checks the conventions the code relies on in Context7 and logs each one here.
2026-10-09 | Node.js built-ins (child_process spawn, fetch, AbortSignal.timeout) for the root scripts in scripts/ | Node 24.21 | fallback | No Context7 in the install session; behaviour confirmed by running every script under Node 24.21 (verify, verify:e2e, sql verifier, git hooks). spawn of npm.cmd on Windows uses shell: true because Node refuses .cmd without a shell; unproven on Windows until P00.
2026-10-13 | boto3 / botocore bedrock-runtime Converse | boto3 1.43.112, service model 2023-09-30 | fallback | No Context7 in the session. Request and response shapes (modelId, system, messages, inferenceConfig.maxTokens/temperature; output.message.content, usage.inputTokens/outputTokens; error codes ThrottlingException etc.) read from the installed botocore service-2.json; the Stubber validates both against it in tests.
2026-10-13 | cryptography Fernet / MultiFernet | cryptography 50.0.2 | fallback | Read from the installed package (Fernet(key), MultiFernet([...]).encrypt/decrypt, InvalidToken).
2026-10-13 | pyjwt RS256 encode/decode with headers | pyjwt 2.15.1 | fallback | Installed package source: jwt.encode(claims, pem, algorithm="RS256", headers={"kid": ...}).
2026-10-13 | Vertex AI Anthropic rawPredict, service account jwt-bearer token exchange | REST, no SDK | fallback | Public docs from memory plus one web search: body anthropic_version "vertex-2023-10-16", model in the URL; multi-region host pattern aiplatform.{us,eu}.rep.googleapis.com confirmed for "us" only. Check the EU host in the Google console before the first EU customer (D-052).
2026-10-13 | Together AI and Fireworks AI fine-tuning REST | REST | fallback | Written from public docs without Context7; covered by MockTransport tests only. One small real job per provider before customer use (D-054).
