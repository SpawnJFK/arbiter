// End-to-end test of the whole product against a REAL backend (no mock mode).
//
// Prerequisites (see README "End-to-end test"):
//   - API on :8000 and the pipeline worker running, demo data seeded (arbiter.cli seed-demo)
//   - this app built WITHOUT NEXT_PUBLIC_API_MOCK and started on :3000
// Run:
//   node e2e/real-flow.mjs            (BASE_URL, PYTHON, SHOTS_DIR, DEMO_PASSWORD optional)
//
// Flow: register a company -> upload .md -> 4 tiers -> order auto -> delivered -> download +
// evidence PDF; upload .docx -> order full -> reviewer clears the queue in the cockpit (A, E +
// Ctrl+Enter) -> PM sees it delivered; glossary terms -> job with a blocked segment shows up in
// Exceptions; admin sees reviewers and payouts; the assistant sets up an agency from an English
// description; CRM, deals, a pharma job with two reviews and client approval; admin exports the UI
// catalog as XLIFF for "de", fills targets, imports (placeholder errors first), enables "de", and the
// PM switches language and sees German strings with English fallback. Then every section added by
// the module builds opens once: engines, own models, software strings (create, push JSON, translate,
// release, OTA bundle), the workbench editor (edit and confirm a segment), the auditor (XLIFF
// audit), vendors (create, suggested for a job), capacity, billing, pricing, settings team, audit
// log and modules with add-ons, queries, purchase orders, vendor invoices, admin billing and
// engines. Screenshots: screenshots/real-*.png.
import { chromium } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync, readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const API_ORIGIN = process.env.API_ORIGIN ?? "http://localhost:8000"; // public OTA bundles
const SHOTS = path.resolve(process.env.SHOTS_DIR ?? path.join(here, "..", "screenshots"));
const PYTHON = process.env.PYTHON ?? path.resolve(here, "../../../services/api/.venv/bin/python");
const DEMO_PASSWORD = process.env.DEMO_PASSWORD ?? "demo-password-123";
const SECOND_REVIEWER = process.env.SECOND_REVIEWER ?? "reviewer2@demo.test";
const AGENCY_PROMPT =
  "We are Northwind Language Services. Our clients are Acme Ltd, Beta Pharma and Gamma Soft. Workflow: MT, then QE, then review, then a second review for pharma, then client approval. Price 0.08 EUR per word. I want a dashboard with revenue, margin and overdue jobs.";
const T = 90_000; // generous timeout for pipeline work
mkdirSync(SHOTS, { recursive: true });

// ---------------------------------------------------------------- fixtures
const work = mkdtempSync(path.join(os.tmpdir(), "arbiter-e2e-"));
const mdPath = path.join(work, "release-notes.md");
writeFileSync(
  mdPath,
  "# Release notes\n\nOpen the **settings** page to download your invoice.\n\nClick Save to keep your changes.\n",
);
const docxPath = path.join(work, "user-guide.docx");
execFileSync(PYTHON, [
  "-I",
  "-c",
  `import sys, docx
d = docx.Document()
d.add_heading("User guide", level=1)
p = d.add_paragraph("Select ")
p.add_run("Export").bold = True
p.add_run(" to create a report.")
d.add_paragraph("Your changes are saved automatically.")
d.save(sys.argv[1])`,
  docxPath,
]);
const leafletPath = path.join(work, "patient-leaflet.md");
writeFileSync(leafletPath, "# Patient leaflet\n\nTake one tablet twice a day with water.\n\nKeep out of the reach of children.\n");
// workflows with second_review need a second, senior reviewer; the seed has only one reviewer.
execFileSync(PYTHON, [path.join(here, "ensure_reviewer.py"), SECOND_REVIEWER, DEMO_PASSWORD], { stdio: ["ignore", "ignore", "inherit"] });
const glossaryMdPath = path.join(work, "billing-faq.md");
writeFileSync(glossaryMdPath, "# Billing\n\nYou can download every invoice from the billing page.\n");

const plainPath = path.join(work, "welcome.txt");
writeFileSync(plainPath, "Welcome to the new dashboard.\n\nYour reports are ready.\n");
const xliffPath = path.join(work, "audit-sample.xlf");
writeFileSync(
  xliffPath,
  `<?xml version="1.0" encoding="UTF-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <file original="ui.txt" source-language="en" target-language="de" datatype="plaintext">
    <body>
      <trans-unit id="1"><source>Save your changes.</source><target>Speichern Sie Ihre Änderungen.</target></trans-unit>
      <trans-unit id="2"><source>Download the invoice.</source><target>Laden Sie die Rechnung herunter.</target></trans-unit>
      <trans-unit id="3"><source>Open the settings page.</source><target>Open the settings page.</target></trans-unit>
    </body>
  </file>
</xliff>
`,
);

// ---------------------------------------------------------------- helpers
const steps = [];
const errors = [];
function step(name) {
  steps.push(name);
  console.log(`- ${name}`);
}
async function shot(page, name, fullPage = true) {
  // Never capture a loading skeleton.
  await page.locator('[aria-busy="true"][aria-label="Loading"]').waitFor({ state: "detached", timeout: 15_000 }).catch(() => null);
  await page.waitForLoadState("networkidle").catch(() => null);
  await page.screenshot({ path: path.join(SHOTS, `real-${name}.png`), fullPage });
}
function watch(page, who) {
  page.on("pageerror", (e) => errors.push(`[${who}] ${page.url()}: ${e.message}`));
  page.on("response", (r) => {
    if (r.status() >= 500) errors.push(`[${who}] ${r.status()} ${r.request().method()} ${r.url()}`);
  });
}
const openPages = [];
async function newUser(browser, who) {
  const ctx = await browser.newContext({ baseURL: BASE, viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  const page = await ctx.newPage();
  openPages.push([who, page]);
  watch(page, who);
  return { ctx, page };
}
async function login(page, email, password) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 20_000 });
}
/** Reload `url` until `check()` resolves truthy. */
async function pollPage(page, url, check, { timeout = T, every = 2500, what = "condition" } = {}) {
  const until = Date.now() + timeout;
  for (;;) {
    await page.goto(url);
    if (await check()) return;
    if (Date.now() > until) throw new Error(`timed out waiting for ${what} at ${url}`);
    await page.waitForTimeout(every);
  }
}

/** Wizard: upload -> languages -> quote; returns after the quote step is visible. */
async function quote(page, file, { langs = ["German"], name } = {}) {
  await page.goto("/app/projects/new");
  await page.waitForLoadState("networkidle");
  await page.setInputFiles('input[type="file"]', file);
  if (name) await page.getByLabel("Project name").fill(name);
  await page.getByRole("button", { name: "Upload and continue" }).click();
  for (const l of langs) await page.getByRole("checkbox", { name: new RegExp(`^${l}`) }).check();
  await page.getByRole("button", { name: "Get quote" }).click();
  await page.getByRole("radiogroup", { name: "Service tier" }).waitFor();
}
async function order(page, tier) {
  await page.locator(`label:has(input[name="tier"][value="${tier}"])`).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: /^Start project/ }).click();
  await page.waitForURL(/\/app\/projects\/prj_/, { timeout: 20_000 });
  return page.url();
}
async function firstJobUrl(page) {
  const href = await page.locator('a[href^="/app/jobs/"]').first().getAttribute("href");
  return new URL(href, BASE).toString();
}
/** Open a page and check it rendered: an h1 (or the given heading), no error boundary. */
async function visit(page, url, heading) {
  await page.goto(url);
  await page.waitForLoadState("networkidle").catch(() => null);
  if (await page.getByText("Something went wrong", { exact: true }).count()) throw new Error(`error page at ${url}`);
  if (heading) await page.getByRole("heading", { name: heading, level: 1 }).waitFor({ timeout: 15_000 });
  else await page.locator("h1").first().waitFor({ timeout: 15_000 });
}
/** Call the API as the signed-in user through the web app's server proxy (cookie session). */
async function apiCall(page, method, apiPath, { json, multipart } = {}) {
  const r = await page.request.fetch(`/api/proxy${apiPath}`, {
    method,
    headers: { Accept: "application/json" },
    ...(json !== undefined ? { data: json } : {}),
    ...(multipart ? { multipart } : {}),
  });
  const text = await r.text();
  if (!r.ok()) throw new Error(`${method} ${apiPath} -> ${r.status()}: ${text.slice(0, 300)}`);
  return text ? JSON.parse(text) : null;
}
async function until(fn, { timeout = T, every = 1500, what = "condition" } = {}) {
  const end = Date.now() + timeout;
  for (;;) {
    const v = await fn();
    if (v) return v;
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
    await new Promise((r) => setTimeout(r, every));
  }
}
const stateBadge = (page, label) => page.locator("h1").getByText(label, { exact: true });

/** Accept every task in the cockpit until the queue is empty. Returns how many were accepted. */
async function clearQueue(page) {
  await page.goto("/reviewer/cockpit");
  let n = 0;
  for (let i = 0; i < 80; i++) {
    const source = page.getByRole("region", { name: "Source" });
    const empty = page.getByText("Queue empty", { exact: true });
    await Promise.race([source.waitFor({ timeout: 30_000 }), empty.waitFor({ timeout: 30_000 })]);
    if (await empty.isVisible()) return n;
    const text = await source.innerText();
    await page.keyboard.press("a");
    n++;
    await page
      .waitForFunction(
        (prev) => {
          const r = document.querySelector('section[aria-label="Source"]');
          return !r || r.textContent !== prev || document.body.innerText.includes("Queue empty");
        },
        text,
        { timeout: 20_000 },
      )
      .catch(() => null);
    await page.waitForTimeout(250);
  }
  throw new Error("queue did not empty");
}

// ---------------------------------------------------------------- run
const browser = await chromium.launch();
let failed = null;
try {
  // 1. Register a company
  const stamp = Date.now().toString(36);
  const email = `e2e-${stamp}@example.com`;
  const cust = await newUser(browser, "pm");
  const { page } = cust;
  await page.goto("/register");
  await page.getByLabel("Company name").fill(`E2E Translations ${stamp}`);
  await page.getByLabel("Your name").fill("Erin Example");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill("e2e-password-123");
  await page.getByRole("button", { name: "Create account" }).click();
  await page.waitForURL(/\/app$/, { timeout: 20_000 });
  step(`registered ${email}`);

  // 2. Markdown -> quote with 4 tiers -> auto
  await quote(page, mdPath, { name: "Release notes (auto)" });
  const tierCount = await page.locator('input[name="tier"]').count();
  if (tierCount !== 4) throw new Error(`expected 4 tiers, got ${tierCount}`);
  await shot(page, "quote");
  step("quote shows 4 tiers");
  const autoProject = await order(page, "auto");
  step("ordered auto tier");
  const autoJob = await firstJobUrl(page);
  await pollPage(page, autoJob, async () => (await stateBadge(page, "Delivered").count()) > 0, { what: "auto job delivered" });
  await shot(page, "job-auto-delivered", false);
  step("auto job delivered");

  // 3. Download + evidence PDF
  const [dl] = await Promise.all([page.waitForEvent("download"), page.getByRole("link", { name: "Download" }).click()]);
  const dlPath = path.join(work, dl.suggestedFilename());
  await dl.saveAs(dlPath);
  const translated = readFileSync(dlPath, "utf8");
  if (!translated.includes("#")) throw new Error(`downloaded file looks wrong: ${translated.slice(0, 80)}`);
  step(`download ok (${dl.suggestedFilename()}, ${translated.length} bytes)`);
  const [pdf] = await Promise.all([page.waitForEvent("download"), page.getByRole("link", { name: "Evidence PDF" }).click()]);
  const pdfPath = path.join(work, pdf.suggestedFilename());
  await pdf.saveAs(pdfPath);
  if (readFileSync(pdfPath).subarray(0, 4).toString() !== "%PDF") throw new Error("evidence is not a PDF");
  step(`evidence PDF ok (${pdf.suggestedFilename()})`);
  void autoProject;

  // 4. DOCX -> full tier
  await quote(page, docxPath, { name: "User guide (full)" });
  const fullProject = await order(page, "full");
  const fullJob = await firstJobUrl(page);
  await pollPage(page, fullJob, async () => (await stateBadge(page, "Review").count()) > 0, { what: "full job in review" });
  await shot(page, "job-full-review", false);
  step("full-tier job waiting for human review");

  // 5. Reviewer clears the queue from the cockpit
  const rev = await newUser(browser, "reviewer");
  await login(rev.page, "reviewer@demo.test", DEMO_PASSWORD);
  await rev.page.goto("/reviewer/cockpit");
  let accepted = 0;
  let edited = 0;
  for (let i = 0; i < 60; i++) {
    const source = rev.page.getByRole("region", { name: "Source" });
    const empty = rev.page.getByText("Queue empty", { exact: true });
    await Promise.race([source.waitFor({ timeout: 30_000 }), empty.waitFor({ timeout: 30_000 })]);
    if (await empty.isVisible()) break;
    if (i === 0) await shot(rev.page, "cockpit", false);
    const before = await rev.page.getByRole("timer", { name: "Hold time left" }).count();
    if (!before) throw new Error("task without hold timer");
    const taskText = await source.innerText();
    if (edited === 0 && accepted >= 1) {
      await rev.page.keyboard.press("e");
      const editor = rev.page.getByRole("textbox", { name: "Edited target" });
      await editor.waitFor();
      await rev.page.keyboard.press("End");
      await rev.page.keyboard.type(" (geprüft)");
      if (edited === 0) await shot(rev.page, "cockpit-edit", false);
      await rev.page.keyboard.press("Control+Enter");
      edited++;
    } else {
      await rev.page.keyboard.press("a");
      accepted++;
    }
    // Wait until the task changes (next task or queue empty).
    await rev.page.waitForFunction(
      (prev) => {
        const r = document.querySelector('section[aria-label="Source"]');
        return !r || r.textContent !== prev || document.body.innerText.includes("Queue empty");
      },
      taskText,
      { timeout: 20_000 },
    ).catch(() => null);
    await rev.page.waitForTimeout(300);
  }
  await rev.page.getByText("Queue empty", { exact: true }).waitFor({ timeout: 30_000 });
  await shot(rev.page, "cockpit-empty", false);
  step(`reviewer cleared the queue (accepted ${accepted}, edited ${edited})`);
  if (edited < 1) throw new Error("no edit was submitted");

  // 6. PM: full job delivered
  await pollPage(page, fullJob, async () => (await stateBadge(page, "Delivered").count()) > 0, { what: "full job delivered" });
  await shot(page, "job-full-delivered", false);
  step("full-tier job delivered after human review");
  void fullProject;

  // 7. Glossary -> blocked segment -> Exceptions
  await page.goto("/app/glossaries");
  await page.getByRole("button", { name: "New glossary" }).first().click();
  await page.getByLabel("Name").fill("Billing terms");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.waitForURL(/\/app\/glossaries\/gls_/);
  async function addTerm(source, target, kind) {
    await page.getByRole("button", { name: "Add term" }).click();
    const dlg = page.getByRole("dialog");
    await dlg.getByRole("textbox", { name: "Source term", exact: true }).fill(source);
    await dlg.locator(`label:has(input[name="kind"])`).filter({ hasText: kind }).click();
    await dlg.getByRole("textbox", { name: kind === "Forbidden" ? "Forbidden target term" : "Target term", exact: true }).fill(target);
    await dlg.getByRole("button", { name: "Add term" }).click();
    await dlg.waitFor({ state: "hidden" });
  }
  await addTerm("invoice", "Rechnung", "Mandatory");
  // The mock MT applies mandatory terms, so a forbidden term matching its output is what blocks.
  await addTerm("download", "döwnlöád", "Forbidden");
  await page.getByText("Rechnung").first().waitFor();
  await shot(page, "glossary");
  step("glossary with a mandatory and a forbidden term");
  await quote(page, glossaryMdPath, { name: "Billing FAQ" });
  await order(page, "auto");
  const glJob = await firstJobUrl(page);
  await pollPage(page, glJob, async () => (await stateBadge(page, "Review").count()) > 0, { what: "job blocked in review" });
  await pollPage(page, "/app/exceptions", async () => (await page.getByText("Segment blocked").count()) > 0, { what: "blocked exception" });
  await shot(page, "exceptions");
  step("blocked segment listed in Exceptions");
  await page.getByRole("link", { name: "Fix or approve the segment" }).first().click();
  await page.getByRole("heading", { name: "Segments" }).waitFor();
  await shot(page, "job-blocked-segment", false);
  step("exception links to the job filtered on blocked segments");

  // 8. Admin
  const adm = await newUser(browser, "admin");
  await login(adm.page, "admin@demo.test", DEMO_PASSWORD);
  await adm.page.goto("/admin");
  await adm.page.getByText("reviewer@demo.test").first().waitFor();
  await shot(adm.page, "admin-reviewers");
  await adm.page.goto("/admin/payouts");
  await adm.page.getByRole("heading", { name: "Payouts", exact: true }).waitFor();
  await shot(adm.page, "admin-payouts");
  step("admin sees reviewers and payouts");

  // 9. A new reviewer applies and takes a qualification test (error spans are sent as text)
  const nr = await newUser(browser, "applicant");
  await nr.page.goto("/reviewers/apply");
  await nr.page.getByLabel("Full name").fill("Ana Applicant");
  await nr.page.getByLabel("Country").fill("DE");
  await nr.page.getByLabel("Email").fill(`applicant-${stamp}@example.com`);
  await nr.page.getByLabel("Password").fill("e2e-password-123");
  await nr.page.getByLabel("Pair 1 target language").selectOption("de");
  await nr.page.getByRole("button", { name: "General" }).click();
  await nr.page.getByRole("button", { name: "Apply", exact: true }).click();
  await nr.page.waitForURL(/\/reviewer$/, { timeout: 20_000 });
  await nr.page.goto("/reviewer/tests");
  await nr.page.getByRole("link", { name: "Start" }).first().click();
  await nr.page.getByRole("button", { name: "Start test" }).click();
  await nr.page.getByRole("timer").waitFor();
  // Select the first word of item 1's machine translation and mark it.
  await nr.page.evaluate(() => {
    const el = document.querySelector('[aria-label="Machine translation for item 1"] span');
    if (!el || !el.firstChild) throw new Error("no MT text");
    const text = el.firstChild.textContent ?? "";
    const end = Math.max(1, text.indexOf(" ") > 0 ? text.indexOf(" ") : text.length);
    const r = document.createRange();
    r.setStart(el.firstChild, 0);
    r.setEnd(el.firstChild, end);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(r);
  });
  await nr.page.getByRole("button", { name: "Mark selection" }).first().click();
  await nr.page.getByText(/“.+”/).first().waitFor();
  await shot(nr.page, "test-taking", false);
  await nr.page.getByRole("button", { name: "Submit test" }).click();
  await nr.page.getByText(/^(Passed|Not passed this time)$/).waitFor({ timeout: 20_000 });
  await shot(nr.page, "test-result", false);
  step(`applicant took a test: ${await nr.page.getByText(/^(Passed|Not passed this time)$/).innerText()}`);

  // 10. Agency OS: the assistant sets up the workspace from an English description
  await page.goto("/app/assistant");
  await page.waitForLoadState("networkidle");
  await page.getByLabel("Message the assistant").fill(AGENCY_PROMPT);
  await page.keyboard.press("Enter");
  const planCard = page.getByRole("group", { name: "Proposed plan" });
  await planCard.waitFor({ timeout: 60_000 });
  const actionCount = await planCard.getByRole("checkbox").count();
  if (actionCount < 5) throw new Error(`plan has only ${actionCount} actions`);
  await planCard.getByRole("button", { name: "Apply all" }).click();
  await planCard.getByText("All applied").waitFor({ timeout: 30_000 });
  const failedChips = await planCard.getByText(/^Failed:/).count();
  if (failedChips) throw new Error(`${failedChips} plan actions failed`);
  await shot(page, "assistant-applied", false);
  step(`assistant plan applied (${actionCount} actions)`);

  await page.goto("/app/crm");
  for (const name of ["Acme Ltd", "Beta Pharma", "Gamma Soft"]) await page.getByRole("link", { name, exact: true }).waitFor();
  await page.goto("/app/workflows");
  const pharmaLink = page.getByRole("link", { name: /pharma/i }).first();
  await pharmaLink.waitFor();
  await pharmaLink.click();
  await page.getByRole("heading", { name: "Steps" }).waitFor();
  await shot(page, "workflow-editor", true);
  await page.goto("/app");
  const dashSelect = page.getByLabel("Dashboard");
  await dashSelect.waitFor();
  const dashOption = await dashSelect.locator("option").filter({ hasNotText: "(default)" }).first().getAttribute("value");
  await dashSelect.selectOption(dashOption);
  await page.waitForURL(/dashboard=/);
  await shot(page, "dashboard", true);
  step("accounts, the pharma workflow and the new dashboard exist");

  // 11. CRM: deal + task on Beta Pharma, drag the deal on the board
  await page.goto("/app/crm");
  await page.getByRole("link", { name: "Beta Pharma", exact: true }).click();
  await page.waitForURL(/\/app\/crm\/acc_/);
  const accountUrl = page.url();
  await page.getByRole("tab", { name: /Deals/ }).click();
  await page.getByRole("button", { name: "New deal" }).click();
  let dlg = page.getByRole("dialog");
  await dlg.getByLabel("Title").fill("Clinical trial documents, 4 languages");
  await dlg.getByLabel(/^Value/).fill("8400");
  await dlg.getByRole("button", { name: "Create deal" }).click();
  await dlg.waitFor({ state: "hidden" });
  await page.getByRole("tab", { name: /Activities/ }).click();
  await page.getByRole("button", { name: "Task", exact: true }).click();
  await page.getByLabel("Activity text").fill("Send the signed MSA to Beta Pharma procurement");
  await page.getByRole("button", { name: "Add task" }).click();
  await page.getByText("Send the signed MSA").waitFor();
  await shot(page, "crm-account", true);
  await page.goto("/app/crm/deals");
  const card = page.locator("li[draggable]").filter({ hasText: "Clinical trial documents" });
  await card.dragTo(page.getByRole("region", { name: "Proposal column" }));
  await page.getByRole("region", { name: "Proposal column" }).getByText("Clinical trial documents, 4 languages", { exact: true }).waitFor({ timeout: 10_000 });
  await shot(page, "deals-kanban", false);
  step("deal created and dragged to Proposal; task added");

  // 12. Project for Beta Pharma with the 2-review + client approval workflow
  await page.goto(accountUrl);
  await page.locator("main").getByRole("link", { name: "New project" }).click();
  await page.waitForURL(/projects\/new\?account=/);
  await page.waitForLoadState("networkidle");
  await page.setInputFiles('input[type="file"]', leafletPath);
  await page.getByLabel("Project name").fill("Patient leaflet (pharma)");
  await page.getByRole("button", { name: "Upload and continue" }).click();
  await page.getByRole("checkbox", { name: /^German/ }).check();
  await page.getByRole("button", { name: "Get quote" }).click();
  await page.getByRole("radiogroup", { name: "Service tier" }).waitFor();
  const wfValue = await page.getByLabel("Workflow", { exact: true }).inputValue();
  if (!wfValue) throw new Error("account workflow was not prefilled");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: /^Start project/ }).click();
  await page.waitForURL(/\/app\/projects\/prj_/, { timeout: 20_000 });
  const pharmaJob = await firstJobUrl(page);
  await pollPage(page, pharmaJob, async () => (await stateBadge(page, "Review").count()) > 0, { what: "pharma job in review" });
  step("pharma project started with the account's workflow");

  const r1 = await clearQueue(rev.page);
  const r2user = await newUser(browser, "reviewer2");
  await login(r2user.page, SECOND_REVIEWER, DEMO_PASSWORD);
  const r2 = await clearQueue(r2user.page);
  step(`first review by reviewer@demo.test (${r1} tasks), second review by ${SECOND_REVIEWER} (${r2} tasks)`);

  await pollPage(page, pharmaJob, async () => (await page.getByRole("region", { name: "Client approval" }).count()) > 0, { what: "client approval banner" });
  await shot(page, "job-client-approval", false);
  await page.getByRole("button", { name: "Approve and deliver" }).click();
  await pollPage(page, pharmaJob, async () => (await stateBadge(page, "Delivered").count()) > 0, { what: "pharma job delivered" });
  await shot(page, "job-pharma-delivered", false);
  step("client approved, job delivered");

  // Extra screens worth a look in real mode
  for (const [route, name] of [
    ["/app/quality", "quality"],
    ["/app/settings/billing", "billing"],
  ]) {
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    await shot(page, name);
  }
  await rev.page.goto("/reviewer/earnings");
  await rev.page.waitForLoadState("networkidle");
  await shot(rev.page, "reviewer-earnings");

  // 13. Localization: export XLIFF for "de", translate, import, enable, switch the PM's UI
  const ap = adm.page;
  await ap.goto("/admin/languages");
  await ap.getByRole("heading", { name: "Languages", level: 1 }).waitFor();
  const existingDe = ap.getByRole("button", { name: "Delete Deutsch" });
  if (await existingDe.count()) {
    await existingDe.click();
    await ap.getByRole("dialog").getByRole("button", { name: "Delete", exact: true }).click();
    await ap.getByRole("button", { name: "Delete Deutsch" }).waitFor({ state: "detached" });
  }
  await ap.getByRole("button", { name: "Add language" }).first().click();
  let ld = ap.getByRole("dialog");
  await ld.getByLabel("Language code").fill("de");
  await ld.getByLabel("Name", { exact: true }).fill("Deutsch");
  await ld.getByRole("button", { name: "Add", exact: true }).click();
  await ld.waitFor({ state: "hidden" });
  await ap.getByRole("switch", { name: "Enable Deutsch" }).waitFor();

  const [download] = await Promise.all([ap.waitForEvent("download"), ap.getByRole("link", { name: "Export Deutsch as XLIFF" }).click()]);
  const xliff = readFileSync(await download.path(), "utf8");
  if (!/<xliff [^>]*version="2\.1"[^>]*srcLang="en"[^>]*trgLang="de"/.test(xliff)) throw new Error("export is not XLIFF 2.1 en -> de");
  const units = (xliff.match(/<unit /g) ?? []).length;
  const fill = (xml, translations) =>
    Object.entries(translations).reduce((x, [key, target]) => {
      const re = new RegExp(`(<unit id="${key.replace(/[.]/g, "\\.")}">[\\s\\S]*?</source>)`);
      if (!re.test(x)) throw new Error(`unit ${key} missing from the export`);
      return x.replace(re, `$1\n        <target>${target.replace(/&/g, "&amp;").replace(/</g, "&lt;")}</target>`);
    }, xml);
  const GERMAN = {
    "app.layout.projects": "Projekte",
    "app.layout.newProject": "Neues Projekt",
    "app.layout.dashboard": "Übersicht",
    "components.shell.signOut": "Abmelden",
    "app.dashboardView.widgets": "Widgets ({count})",
    "app.assistant.chat.actionsApplied": "{count, plural, one {# Aktion angewendet} other {# Aktionen angewendet}}",
  };
  const importFile = async (xml, name) => {
    const file = path.join(work, name);
    writeFileSync(file, xml);
    await ap.getByRole("button", { name: "Import translations into Deutsch" }).click();
    const dlg2 = ap.getByRole("dialog");
    await dlg2.locator('input[type="file"]').setInputFiles(file);
    await dlg2.getByRole("button", { name: "Import", exact: true }).click();
    return dlg2;
  };
  // A broken placeholder is rejected with a per-key error and nothing is saved.
  let dlgImport = await importFile(fill(xliff, { ...GERMAN, "app.dashboardView.widgets": "Widgets ({anzahl})" }), "de-broken.xlf");
  const phList = dlgImport.getByRole("list", { name: "Placeholder mismatches" });
  await phList.getByText("app.dashboardView.widgets").waitFor({ timeout: 15_000 });
  await phList.getByText("expected {count}, got {anzahl}").waitFor();
  await shot(ap, "languages-placeholder-error", false);
  await dlgImport.getByRole("button", { name: "Cancel" }).click();
  dlgImport = await importFile(fill(xliff, GERMAN), "de.xlf");
  await dlgImport.waitFor({ state: "hidden", timeout: 15_000 });
  await ap.getByText("Translations imported into Deutsch").waitFor();
  await ap.getByRole("switch", { name: "Enable Deutsch" }).check();
  await ap.getByText("Deutsch is enabled").waitFor();
  await ap.getByRole("row", { name: /Deutsch/ }).getByText(`${Object.keys(GERMAN).length} of ${units.toLocaleString("en")} keys`).waitFor();
  await shot(ap, "languages", false);
  step(`admin exported XLIFF (${units} units), a placeholder mismatch was rejected, ${Object.keys(GERMAN).length} German strings imported, de enabled`);

  await page.goto("/app");
  await page.getByLabel("Interface language").selectOption("de");
  const nav = page.getByRole("navigation", { name: "Main" });
  await nav.getByRole("link", { name: "Projekte", exact: true }).waitFor({ timeout: 15_000 });
  await nav.getByRole("link", { name: "Neues Projekt", exact: true }).waitFor();
  await nav.getByRole("link", { name: "Exceptions", exact: true }).waitFor(); // not translated: English fallback
  if ((await page.locator("html").getAttribute("lang")) !== "de") throw new Error('<html lang> is not "de"');
  await shot(page, "locale-de", false);
  await page.getByLabel("Oberflächensprache").or(page.getByLabel("Interface language")).selectOption("en");
  await nav.getByRole("link", { name: "Projects", exact: true }).waitFor({ timeout: 15_000 });
  step("PM switched to Deutsch: translated nav with English fallback, then back to English");

  // 14. Modules merged in parallel: every new section opens and its main flow works.
  // Engines and own models (module engine)
  await visit(page, "/app/engines", "Engines");
  await visit(page, "/app/training", "Own models");
  step("engines and own models pages render");

  // Software strings: create a project in the UI, push a JSON file, translate, release, OTA
  await visit(page, "/app/strings", "Software strings");
  await page.getByRole("button", { name: "New string project" }).first().click();
  const sd = page.getByRole("dialog");
  await sd.getByLabel("Name", { exact: true }).fill(`App strings ${stamp}`);
  await sd.getByRole("checkbox", { name: /\(de\)$/ }).check();
  await sd.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByText("String project created").first().waitFor({ timeout: 15_000 });
  const sp = (await apiCall(page, "GET", "/strings/projects")).items.find((x) => x.name === `App strings ${stamp}`);
  if (!sp) throw new Error("string project not found after create");
  const pushed = await apiCall(page, "POST", `/strings/projects/${sp.id}/push`, {
    multipart: {
      file: { name: "en.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify({ "home.title": "Welcome back", "home.cta": "Open your reports" })) },
      format: "json",
    },
  });
  if (pushed.created !== 2) throw new Error(`push created ${pushed.created} keys, expected 2`);
  const batch = await apiCall(page, "POST", `/strings/projects/${sp.id}/translate`, { json: { mode: "translate" } });
  await until(async () => ["done", "failed"].includes((await apiCall(page, "GET", `/strings/projects/${sp.id}/batches/${batch.id}`)).status), { what: "strings batch" });
  const keys = await apiCall(page, "GET", `/strings/projects/${sp.id}/keys?langs=de`);
  const missing = keys.items.filter((k) => !k.translations?.de?.value);
  if (missing.length) throw new Error(`untranslated after translate: ${missing.map((k) => k.name).join(", ")}`);
  const rel = await apiCall(page, "POST", `/strings/projects/${sp.id}/releases`, { json: { version_label: "1.0.0", publish: true } });
  if (rel.status !== "published") throw new Error(`release status ${rel.status}`);
  const ota = await fetch(`${API_ORIGIN}/ota/${sp.public_id}/latest/de.json`);
  const bundle = ota.ok ? await ota.json() : null;
  if (!bundle || !bundle["home.title"]) throw new Error(`OTA bundle missing keys (${ota.status})`);
  await visit(page, `/app/strings/${sp.id}`);
  await shot(page, "strings-project", false);
  step(`strings: project created, 2 keys pushed, translated, release ${rel.version_label} published, OTA bundle served`);

  // Workbench editor: a full-tier job waiting for review, edit and confirm one segment
  await quote(page, plainPath, { name: "Editor check" });
  await order(page, "full");
  const editorJobUrl = await firstJobUrl(page);
  const editorJobId = editorJobUrl.split("/").pop();
  await until(async () => (await apiCall(page, "GET", `/jobs/${editorJobId}`)).state === "review", { what: "editor job in review" });
  await visit(page, `/app/jobs/${editorJobId}/editor`);
  const box = page.getByRole("textbox", { name: "Translation" });
  await box.waitFor({ timeout: 20_000 });
  await box.click();
  await page.keyboard.press("Control+A");
  await page.keyboard.type("Willkommen im neuen Dashboard.");
  await page.getByRole("button", { name: /^Confirm/ }).click();
  await until(
    async () => (await apiCall(page, "GET", `/jobs/${editorJobId}/segments`)).items.some((x) => (x.target_tagged ?? "").includes("Willkommen im neuen Dashboard.")),
    { what: "edited segment saved" },
  );
  await shot(page, "editor", false);
  step("workbench editor opened and saved an edited segment");

  // Auditor: upload a small XLIFF, the audit completes
  await visit(page, "/app/auditor", "Quality auditor");
  await page.getByLabel("Bilingual file").setInputFiles(xliffPath);
  await page.getByLabel("Name", { exact: true }).fill("E2E audit");
  await page.getByRole("button", { name: "Start audit" }).click();
  await page.waitForURL(/\/app\/auditor\/[^/]+$/, { timeout: 20_000 });
  const auditId = page.url().split("/").pop();
  const audit = await until(
    async () => {
      const a = await apiCall(page, "GET", `/audits/${auditId}`);
      if (a.state === "failed") throw new Error(`audit failed: ${a.error ?? ""}`);
      return a.state === "done" ? a : null;
    },
    { what: "audit done" },
  );
  await visit(page, `/app/auditor/${auditId}`);
  await shot(page, "auditor-report", false);
  step(`auditor: XLIFF audited (${audit.segments_total} segments, MQM ${audit.mqm_score ?? "-"}, ${audit.verdict ?? "no verdict"})`);

  // Vendors: create one in the UI, then it is suggested for the editor job's review step
  await visit(page, "/app/vendors");
  await page.getByRole("button", { name: "New vendor" }).first().click();
  const vd = page.getByRole("dialog");
  await vd.getByLabel("Name", { exact: true }).fill(`Vera Vendor ${stamp}`);
  await vd.getByLabel("E-mail").fill(`vera-${stamp}@vendors.example`);
  await vd.getByLabel("Language pairs").fill("en>de");
  await vd.getByRole("button", { name: "Create vendor" }).click();
  await page.getByText("Vendor created").first().waitFor({ timeout: 15_000 });
  const sugg = await apiCall(page, "GET", `/jobs/${editorJobId}/assignment-suggestions?step=human_review`);
  if (!sugg.items.some((r) => (r.name ?? "").includes(`Vera Vendor ${stamp}`))) {
    throw new Error(`vendor not suggested: ${JSON.stringify(sugg.items.map((r) => r.name))}`);
  }
  await visit(page, "/app/capacity");
  step("vendor created and suggested for the review step; capacity page renders");

  // Billing and pricing, settings team / audit log / modules
  await visit(page, "/app/settings/billing");
  await shot(page, "settings-billing", false);
  const pub = await newUser(browser, "public");
  await visit(pub.page, "/pricing", "Pricing");
  await pub.page.getByText("Business", { exact: true }).first().waitFor({ timeout: 15_000 });
  await pub.ctx.close();
  step("billing settings and the public pricing page render");
  await visit(page, "/app/settings/team");
  await visit(page, "/app/settings/audit");
  await page.getByRole("cell", { name: "project.created" }).or(page.getByText("project.created")).first().waitFor({ timeout: 15_000 });
  await visit(page, "/app/settings/modules");
  await page.getByText("Add-ons", { exact: true }).first().waitFor({ timeout: 15_000 });
  await shot(page, "settings-modules", false);
  step("settings: team, audit log, modules with add-ons render");
  for (const url of ["/app/queries", "/app/purchase-orders", "/app/vendor-invoices"]) await visit(page, url);
  await visit(ap, "/admin/billing");
  await visit(ap, "/admin/engines");
  step("queries, purchase orders, vendor invoices, admin billing and admin engines render");
} catch (e) {
  failed = e;
  for (const [who, p] of openPages) await p.screenshot({ path: path.join(SHOTS, `failure-${who}.png`), fullPage: true }).catch(() => null);
} finally {
  await browser.close();
}

console.log(`\n${steps.length} steps passed`);
if (errors.length) console.log(`Browser/HTTP errors:\n  ${errors.join("\n  ")}`);
if (failed) {
  console.error(`FAILED: ${failed.message}`);
  process.exit(1);
}
if (errors.length) process.exit(1);
console.log("E2E OK");
