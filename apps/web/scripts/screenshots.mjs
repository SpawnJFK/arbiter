// Takes UI screenshots against a running server in mock mode.
//   NEXT_PUBLIC_API_MOCK=1 npm run build && NEXT_PUBLIC_API_MOCK=1 npm start -- -p 3100
//   BASE_URL=http://localhost:3100 node scripts/screenshots.mjs
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

const BASE = process.env.BASE_URL ?? "http://localhost:3100";
const OUT = path.resolve(process.env.OUT_DIR ?? "screenshots");
const EXTRA = process.env.EXTRA === "1";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();

async function ctx(opts = {}) {
  const c = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, baseURL: BASE, ...opts });
  return c;
}
async function login(c, email) {
  const r = await c.request.post("/api/session", { data: { kind: "login", email, password: "demo" } });
  if (!r.ok()) throw new Error(`login failed ${r.status()}`);
}
const shot = (page, name, fullPage = false) => page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage });

const errors = [];
function watch(page) {
  page.on("pageerror", (e) => errors.push(`${page.url()}: ${e.message}`));
  page.on("console", (m) => m.type() === "error" && errors.push(`${page.url()}: console: ${m.text()}`));
}

// Landing
{
  const c = await ctx();
  const p = await c.newPage();
  watch(p);
  await p.goto("/");
  await shot(p, "landing", true);
  if (EXTRA) {
    const m = await ctx({ viewport: { width: 390, height: 844 } });
    const mp = await m.newPage();
    await mp.goto("/");
    await shot(mp, "landing-mobile", true);
    await m.close();
  }
  await c.close();
}

// Customer: quote step + job detail
{
  const c = await ctx();
  await login(c, "pm@demo.test");
  const p = await c.newPage();
  watch(p);
  await p.goto("/app/projects/new");
  await p.waitForLoadState("networkidle");
  await p.setInputFiles('input[type="file"]', {
    name: "P300_IFU_v4.3.docx",
    mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    buffer: Buffer.alloc(38_000, 97),
  });
  await p.getByRole("button", { name: "Upload and continue" }).click();
  for (const l of ["German", "French", "Japanese"]) await p.getByRole("checkbox", { name: new RegExp(`^${l}`) }).check();
  await p.getByRole("button", { name: "Get quote" }).click();
  await p.getByRole("radiogroup", { name: "Service tier" }).waitFor();
  await shot(p, "new-project-quote", true);

  await p.goto("/app/jobs/job_01JIFUDE");
  await p.getByRole("heading", { name: "Segments" }).waitFor();
  await shot(p, "job-detail");
  if (EXTRA) {
    await p.getByRole("button", { name: "Edit segment 1", exact: true }).click();
    await p.waitForTimeout(300);
    await shot(p, "job-detail-edit");
    for (const route of ["/app", "/app/projects/prj_01JIFU42", "/app/glossaries/gls_01JMED", "/app/tm", "/app/term-questions", "/app/exceptions", "/app/quality", "/app/settings", "/app/settings/api-keys", "/app/settings/webhooks", "/app/settings/billing"]) {
      await p.goto(route);
      await p.waitForLoadState("networkidle");
      await shot(p, `x-${route.replace(/\//g, "_")}`, true);
    }
    const d = await ctx({ colorScheme: "dark" });
    await login(d, "pm@demo.test");
    const dp = await d.newPage();
    await dp.goto("/app/jobs/job_01JIFUDE");
    await dp.getByRole("heading", { name: "Segments" }).waitFor();
    await shot(dp, "job-detail-dark");
    const m = await ctx({ viewport: { width: 390, height: 844 } });
    await login(m, "client@demo.test");
    const mp = await m.newPage();
    await mp.goto("/app/jobs/job_01JIFUFR");
    await mp.getByRole("heading", { name: "Segments" }).waitFor();
    await shot(mp, "job-detail-mobile-client", true);
    await d.close();
    await m.close();
  }
  await c.close();
}

// Reviewer cockpit
{
  const c = await ctx();
  await login(c, "reviewer@demo.test");
  const p = await c.newPage();
  watch(p);
  await p.goto("/reviewer/cockpit");
  await p.getByRole("region", { name: "Source" }).waitFor();
  await shot(p, "cockpit");
  if (EXTRA) {
    await p.keyboard.press("e");
    await p.waitForTimeout(300);
    await shot(p, "cockpit-edit");
    await p.keyboard.press("Escape");
    await p.keyboard.press("?");
    await p.waitForTimeout(200);
    await shot(p, "cockpit-help");
    await p.keyboard.press("Escape");
    for (let i = 0; i < 5; i++) {
      await p.keyboard.press("a");
      await p.waitForTimeout(700);
    }
    await shot(p, "cockpit-empty");
    for (const route of ["/reviewer", "/reviewer/tests", "/reviewer/tests/tst_01JUIDE", "/reviewer/earnings", "/reviewer/disputes"]) {
      await p.goto(route);
      await p.waitForLoadState("networkidle");
      await shot(p, `x-${route.replace(/\//g, "_")}`, true);
    }
    const a = await ctx();
    await login(a, "admin@demo.test");
    const ap = await a.newPage();
    for (const route of ["/admin", "/admin/disputes", "/admin/payouts", "/admin/orgs"]) {
      await ap.goto(route);
      await ap.waitForLoadState("networkidle");
      await shot(ap, `x-${route.replace(/\//g, "_")}`, true);
    }
    for (const route of ["/login", "/register", "/reviewers/apply"]) {
      await ap.goto(route);
      await shot(ap, `x-${route.replace(/\//g, "_")}`, true);
    }
    await a.close();
  }
  await c.close();
}

await browser.close();
if (errors.length) {
  console.log("Browser errors:\n" + errors.join("\n"));
  process.exitCode = 1;
} else console.log("ok");
