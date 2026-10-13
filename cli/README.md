# arbiter-strings

Push source strings to Arbiter and pull translations back, from a laptop or a CI job. One file,
no dependencies, Node 18 or newer.

## Configure

Create `arbiter.strings.json` in your repository root:

```json
{
  "apiUrl": "https://api.your-arbiter-host.example",
  "projectId": "spj_01J...",
  "tokenEnv": "ARBITER_TOKEN",
  "branch": "main",
  "files": [
    { "path": "src/locales/{lang}.json", "format": "json_nested" },
    { "path": "android/app/src/main/res/values-{android}/strings.xml", "format": "android" }
  ]
}
```

| Field | Meaning |
|---|---|
| `apiUrl` | Base URL of the Arbiter API (without `/v1`) |
| `projectId` | The string project id (Strings, project page, header) |
| `tokenEnv` | Environment variable holding an Arbiter API key (Settings, API keys). Default `ARBITER_TOKEN` |
| `branch` | Optional string branch to push to and pull from. Default `main` |
| `files[].path` | File path per language. `{lang}` is `pt-BR`, `{lang_}` is `pt_BR`, `{android}` is `pt-rBR` |
| `files[].format` | One of the formats from `GET /v1/strings/formats`; omit to detect from the extension |
| `files[].namespace` | Optional namespace, when several files share key names |
| `langs` | Optional list of target languages; default all target languages of the project |
| `minState`, `fallback` | Pull defaults: lowest state to include, and whether to fill gaps with the base text |

For the base language the path of the base locale is used (for Android point a second entry at
`values/strings.xml` if your base file has no qualifier).

## Use

```
ARBITER_TOKEN=... node cli/arbiter-strings.mjs push                 # upload the base files
ARBITER_TOKEN=... node cli/arbiter-strings.mjs push --with-translations
ARBITER_TOKEN=... node cli/arbiter-strings.mjs pull                 # write every target language
ARBITER_TOKEN=... node cli/arbiter-strings.mjs pull --lang de --min-state reviewed
ARBITER_TOKEN=... node cli/arbiter-strings.mjs release --label 2.4.0
ARBITER_TOKEN=... node cli/arbiter-strings.mjs status
```

`push` options: `--archive-missing` archives keys that are no longer in the base file, `--tag <t>`
tags every pushed key, `--branch <b>` targets a branch, `--dry-run` sends nothing.
Translations with a blocking QA issue (a changed placeholder, broken ICU, a missing plural form)
are never written by `pull` unless the API is asked for them, so a bad translation cannot crash
the app.

## GitHub Actions

```yaml
name: strings
on:
  push:
    branches: [main]
    paths: ["src/locales/en.json"]
  schedule:
    - cron: "17 3 * * *"
jobs:
  sync:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - run: node cli/arbiter-strings.mjs push
        env:
          ARBITER_TOKEN: ${{ secrets.ARBITER_TOKEN }}
      - run: node cli/arbiter-strings.mjs pull --min-state reviewed
        env:
          ARBITER_TOKEN: ${{ secrets.ARBITER_TOKEN }}
      - uses: peter-evans/create-pull-request@v7
        with:
          title: "chore: update translations"
          branch: arbiter/translations
          commit-message: "chore: update translations"
```

## Over the air

Published releases are served without auth at
`/ota/<public id>/<version or latest>/<lang>.json` (and `manifest.json`), with an `ETag` and
long-lived caching on versioned paths. Private projects need the distribution token from the
project page, sent as the `X-Distribution-Token` header or `?token=`.
