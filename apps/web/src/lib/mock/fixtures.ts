// Fixture data for mock mode (NEXT_PUBLIC_API_MOCK=1). Everything here is fictional.
import type {
  Dispute,
  Glossary,
  Invoice,
  Job,
  LedgerEntry,
  Org,
  OrgWithUsage,
  Payout,
  Project,
  ReviewerProfile,
  ReviewerTest,
  Segment,
  Task,
  Term,
  TermQuestion,
  Threshold,
  TmHit,
  User,
  Webhook,
  ApiKey,
  ExceptionItem,
  EngineScore,
} from "../types";

const HOUR = 3600_000;
const DAY = 24 * HOUR;

export function iso(offsetMs: number, base = Date.now()): string {
  return new Date(base + offsetMs).toISOString().replace(/\.\d{3}Z$/, "Z");
}

let counter = 0;
export function newId(prefix: string): string {
  counter += 1;
  const rand = Math.random().toString(36).slice(2, 8).toUpperCase();
  return `${prefix}_01J${rand}${counter.toString(36).toUpperCase()}`;
}

export const ORG: Org = {
  id: "org_01JHALDEN",
  name: "Halden Instruments",
  slug: "halden",
  plan: "growth",
  default_tier: "hybrid",
  no_reviewer_policy: "wait",
  ai_subprocessors_opt_in: false,
  regulated: true,
  vertical: "medical_devices",
  data_retention_days: 365,
};

export const USERS: Record<string, User> = {
  pm: { id: "usr_01JPM", email: "pm@demo.test", name: "Mira Kovač", role: "pm", org_id: ORG.id },
  client: { id: "usr_01JCLIENT", email: "client@demo.test", name: "Jonas Berg", role: "client", org_id: ORG.id },
  reviewer: { id: "usr_01JREV", email: "reviewer@demo.test", name: "Léa Fontaine", role: "reviewer", org_id: null },
  admin: { id: "usr_01JADMIN", email: "admin@demo.test", name: "Platform Ops", role: "admin", org_id: null },
};

// ---- Segments -------------------------------------------------------------

interface SegSeed {
  src: string;
  de: string;
  fr: string;
}

const SEEDS: SegSeed[] = [
  {
    src: "⟦1⟧Warning:⟦/1⟧ Do not use the pump if the housing is cracked.",
    de: "⟦1⟧Warnung:⟦/1⟧ Verwenden Sie die Infusionspumpe nicht, wenn das Gehäuse gerissen ist.",
    fr: "⟦1⟧Avertissement :⟦/1⟧ N'utilisez pas la pompe si le boîtier est fissuré.",
  },
  {
    src: "Press ⟦2⟧Start⟦/2⟧ to begin the infusion.",
    de: "Drücken Sie ⟦2⟧Start⟦/2⟧, um die Infusion zu beginnen.",
    fr: "Appuyez sur ⟦2⟧Démarrer⟦/2⟧ pour lancer la perfusion.",
  },
  {
    src: "Set the flow rate between 0.5 mL/h and 999 mL/h.",
    de: "Stellen Sie die Flussrate zwischen 5 mL/h und 999 mL/h ein.",
    fr: "Réglez le débit entre 0,5 mL/h et 999 mL/h.",
  },
  {
    src: "The occlusion alarm sounds when downstream pressure exceeds the limit.",
    de: "Der Okklusionsalarm ertönt, wenn der Druck stromabwärts den Grenzwert überschreitet.",
    fr: "L'alarme d'occlusion retentit lorsque la pression en aval dépasse la limite.",
  },
  {
    src: "Clean the device with a soft, lint-free cloth.",
    de: "Reinigen Sie das Gerät mit einem weichen, fusselfreien Tuch.",
    fr: "Nettoyez l'appareil avec un chiffon doux non pelucheux.",
  },
  {
    src: "See ⟦3⟧Section 4.2⟦/3⟧ for battery replacement.",
    de: "Informationen zum Batteriewechsel finden Sie in ⟦3⟧Abschnitt 4.2⟦/3⟧.",
    fr: "Voir la ⟦3⟧section 4.2⟦/3⟧ pour le remplacement de la batterie.",
  },
  {
    src: "Only trained clinical staff may operate the device.",
    de: "Nur geschultes klinisches Personal darf das Medizinprodukt bedienen.",
    fr: "Seul un personnel clinique formé peut utiliser le dispositif.",
  },
  {
    src: "Store between 5 °C and 40 °C.",
    de: "Zwischen 5 °C und 40 °C lagern.",
    fr: "Conserver entre 5 °C et 40 °C.",
  },
  {
    src: "If the screen shows ⟦4/⟧ E-12, contact service.",
    de: "Wenn auf dem Display ⟦4/⟧ E-12 angezeigt wird, wenden Sie sich an den Kundendienst.",
    fr: "Si l'écran affiche ⟦4/⟧ E-12, contactez le service technique.",
  },
  {
    src: "The bolus function delivers an additional dose on demand.",
    de: "Die Bolusfunktion verabreicht bei Bedarf eine zusätzliche Dosis.",
    fr: "La fonction bolus administre une dose supplémentaire à la demande.",
  },
  {
    src: "Check the line for air bubbles before connecting it to the patient.",
    de: "Prüfen Sie die Leitung vor dem Anschluss an den Patienten auf Luftblasen.",
    fr: "Vérifiez l'absence de bulles d'air dans la tubulure avant de la connecter au patient.",
  },
  {
    src: "Battery life: up to 12 hours at 25 mL/h.",
    de: "Akkulaufzeit: bis zu 12 Stunden bei 25 mL/h.",
    fr: "Autonomie de la batterie : jusqu'à 12 heures à 25 mL/h.",
  },
  {
    src: "⟦5⟧Caution:⟦/5⟧ Federal law restricts this device to sale by or on the order of a physician.",
    de: "⟦5⟧Vorsicht:⟦/5⟧ Laut US-Bundesgesetz darf dieses Produkt nur von einem Arzt oder auf ärztliche Anordnung verkauft werden.",
    fr: "⟦5⟧Attention :⟦/5⟧ La loi fédérale américaine limite la vente de ce dispositif aux médecins ou sur prescription médicale.",
  },
  {
    src: "Dispose of the device according to local regulations.",
    de: "Entsorgen Sie das Gerät gemäß den örtlichen Vorschriften.",
    fr: "Éliminez le dispositif conformément à la réglementation locale.",
  },
  {
    src: "The keypad locks automatically after 60 seconds of inactivity.",
    de: "Die Tastatur wird nach 60 Sekunden Inaktivität automatisch gesperrt.",
    fr: "Le clavier se verrouille automatiquement après 60 secondes d'inactivité.",
  },
  {
    src: "Tap ⟦6⟧History⟦/6⟧ to view the last 500 events.",
    de: "Tippen Sie auf ⟦6⟧Verlauf⟦/6⟧, um die letzten 500 Ereignisse anzuzeigen.",
    fr: "Touchez ⟦6⟧Historique⟦/6⟧ pour afficher les 500 derniers événements.",
  },
];

type SegProfile = Pick<Segment, "state" | "decision" | "reasons" | "qe_score" | "engine" | "origin" | "tm_match"> & {
  control?: boolean;
};

function profileFor(i: number, delivered: boolean): SegProfile {
  const pick = i % 8;
  const base: SegProfile[] = [
    {
      state: "auto_approved",
      decision: "auto_approve",
      qe_score: 93.5,
      engine: "llm-primary",
      origin: "mt",
      tm_match: null,
      reasons: ["QE 93.5 clears threshold 80 + band 8", "All mandatory terms present", "Tags and numbers match source"],
    },
    {
      state: "auto_approved",
      decision: "auto_approve",
      qe_score: 98,
      engine: null,
      origin: "tm",
      tm_match: 101,
      reasons: ["TM context match (101%)", "Approved by Halden reviewers on 2026-06-14"],
    },
    {
      state: "needs_review",
      decision: "blocked",
      qe_score: 41,
      engine: "llm-primary",
      origin: "mt",
      tm_match: null,
      reasons: ["Number mismatch: source 0.5 mL/h, target 5 mL/h", "Safety-critical sentence (dosage)", "Senate escalated to human"],
    },
    {
      state: "reviewed",
      decision: "ai_reviewed",
      qe_score: 81.5,
      engine: "llm-primary",
      origin: "editor",
      tm_match: null,
      reasons: ["QE 81.5 inside the senate band (72 to 88)", "Senate 3/3 approve after one revision", "Reviewer agent fixed term order"],
    },
    {
      state: "in_review",
      decision: "review",
      qe_score: 62,
      engine: "nmt-fallback",
      origin: "mt",
      tm_match: 78,
      reasons: ["Forbidden term used: Gerät (use Medizinprodukt)", "Senate split 2/1, routed to human"],
    },
    {
      state: "auto_approved",
      decision: "auto_approve",
      qe_score: 89,
      engine: "llm-primary",
      origin: "mt",
      tm_match: 85,
      reasons: ["QE 89 clears threshold 80 + band 8", "TM fuzzy 85% used as reference"],
      control: true,
    },
    {
      state: "reviewed",
      decision: "reviewed",
      qe_score: 69,
      engine: "llm-challenger",
      origin: "human",
      tm_match: null,
      reasons: ["Regulatory boilerplate requires human sign-off", "Edited by reviewer (2 minor errors annotated)"],
    },
    {
      state: "auto_approved",
      decision: "senate",
      qe_score: 84,
      engine: "llm-primary",
      origin: "mt",
      tm_match: null,
      reasons: ["QE 84 inside the senate band", "Senate 2/3 approve, dissent: style only"],
    },
  ];
  const p = { ...base[pick] };
  if (delivered) p.state = "delivered";
  return p;
}

export function makeSegments(lang: "de" | "fr" | "other", count: number, delivered = false): Segment[] {
  const out: Segment[] = [];
  for (let i = 0; i < count; i++) {
    const seed = SEEDS[i % SEEDS.length];
    const p = profileFor(i, delivered);
    const target = lang === "fr" ? seed.fr : lang === "de" ? seed.de : seed.de;
    out.push({
      id: `seg_01J${lang.toUpperCase()}${String(i + 1).padStart(4, "0")}`,
      seq: i,
      source_tagged: seed.src,
      target_tagged: target,
      state: p.state,
      origin: p.origin,
      engine: p.engine,
      tm_match: p.tm_match,
      qe_score: p.qe_score,
      decision: p.decision,
      reasons: p.reasons,
      signals: { length_ratio: 1.12, tag_check: "ok", number_check: i % 8 === 2 ? "fail" : "ok" },
      reviewer_id: p.state === "reviewed" ? "rev_01JLEA" : null,
      is_control_sample: Boolean(p.control),
    });
  }
  return out;
}

// ---- Projects and jobs -----------------------------------------------------

export function makeProjectsAndJobs(now = Date.now()): { projects: Project[]; jobs: Job[]; segments: Record<string, Segment[]> } {
  const projects: Project[] = [
    {
      id: "prj_01JIFU42",
      name: "IFU v4.2, infusion pump P300",
      source_lang: "en",
      target_langs: ["de", "fr", "ja"],
      tier: "hybrid",
      content_type: "regulatory",
      due_at: iso(3 * DAY, now),
      created_at: iso(-2 * DAY, now),
    },
    {
      id: "prj_01JREL10",
      name: "Release notes 2026.10",
      source_lang: "en",
      target_langs: ["de", "es"],
      tier: "full",
      content_type: "software_ui",
      due_at: iso(1 * DAY, now),
      created_at: iso(-1 * DAY, now),
    },
    {
      id: "prj_01JSUPQ4",
      name: "Support macros Q4",
      source_lang: "en",
      target_langs: ["pt-BR"],
      tier: "hybrid",
      content_type: "support",
      due_at: null,
      created_at: iso(-9 * DAY, now),
    },
  ];

  const job = (j: Partial<Job> & Pick<Job, "id" | "project_id" | "target_lang" | "state">): Job => ({
    file_id: "fil_01JIFU42",
    filename: "P300_IFU_v4.2.docx",
    source_lang: "en",
    tier: "hybrid",
    content_type: "regulatory",
    segment_count: 48,
    word_count: 6120,
    auto_approved_count: 0,
    review_count: 0,
    ai_reviewed_count: 0,
    progress: 0,
    threshold: 80,
    revenue: "673.20",
    cost: "281.55",
    margin: "391.65",
    failure_reason: null,
    due_at: iso(3 * DAY, now),
    delivered_at: null,
    created_at: iso(-2 * DAY, now),
    ...j,
  });

  const jobs: Job[] = [
    job({
      id: "job_01JIFUDE",
      project_id: "prj_01JIFU42",
      target_lang: "de",
      state: "review",
      progress: 0.72,
      auto_approved_count: 18,
      ai_reviewed_count: 12,
      review_count: 7,
    }),
    job({
      id: "job_01JIFUFR",
      project_id: "prj_01JIFU42",
      target_lang: "fr",
      state: "delivered",
      progress: 1,
      auto_approved_count: 18,
      ai_reviewed_count: 12,
      review_count: 18,
      delivered_at: iso(-3 * HOUR, now),
    }),
    job({
      id: "job_01JIFUJA",
      project_id: "prj_01JIFU42",
      target_lang: "ja",
      state: "running",
      progress: 0.35,
      revenue: "734.40",
      cost: "312.10",
      margin: "422.30",
    }),
    job({
      id: "job_01JRELDE",
      project_id: "prj_01JREL10",
      target_lang: "de",
      state: "running",
      tier: "full",
      content_type: "software_ui",
      filename: "release-notes-2026.10.md",
      file_id: "fil_01JREL10",
      segment_count: 32,
      word_count: 1840,
      progress: 0.55,
      threshold: 76,
      revenue: "110.40",
      cost: "41.20",
      margin: "69.20",
      due_at: iso(1 * DAY, now),
      created_at: iso(-1 * DAY, now),
    }),
    job({
      id: "job_01JRELES",
      project_id: "prj_01JREL10",
      target_lang: "es",
      state: "failed",
      tier: "full",
      content_type: "software_ui",
      filename: "release-notes-2026.10.md",
      file_id: "fil_01JREL10",
      segment_count: 32,
      word_count: 1840,
      progress: 0.2,
      threshold: 76,
      revenue: "110.40",
      cost: "8.10",
      margin: "102.30",
      failure_reason: "Source file has 3 unbalanced inline tags in segment 14; fix the source and re-upload.",
      due_at: iso(1 * DAY, now),
      created_at: iso(-1 * DAY, now),
    }),
    job({
      id: "job_01JSUPPT",
      project_id: "prj_01JSUPQ4",
      target_lang: "pt-BR",
      state: "delivered",
      tier: "hybrid",
      content_type: "support",
      filename: "macros-q4.csv",
      file_id: "fil_01JSUPQ4",
      segment_count: 210,
      word_count: 9400,
      progress: 1,
      auto_approved_count: 171,
      ai_reviewed_count: 39,
      review_count: 0,
      threshold: 74,
      revenue: "282.00",
      cost: "61.40",
      margin: "220.60",
      due_at: null,
      delivered_at: iso(-8 * DAY, now),
      created_at: iso(-9 * DAY, now),
    }),
  ];

  const segments: Record<string, Segment[]> = {
    job_01JIFUDE: makeSegments("de", 48),
    job_01JIFUFR: makeSegments("fr", 48, true),
    job_01JIFUJA: [],
    job_01JRELDE: makeSegments("other", 32).slice(0, 18),
    job_01JRELES: [],
    job_01JSUPPT: makeSegments("other", 40, true),
  };
  return { projects, jobs, segments };
}

// ---- Linguistic assets -----------------------------------------------------

export const GLOSSARIES: Glossary[] = [
  { id: "gls_01JMED", name: "Medical devices core", content_type: "regulatory", version: 14, term_count: 6 },
  { id: "gls_01JUI", name: "Product UI strings", content_type: "software_ui", version: 3, term_count: 3 },
];

export const TERMS: Term[] = [
  t("gls_01JMED", "infusion pump", "Infusionspumpe", "mandatory", "Never shorten to Pumpe in safety statements."),
  t("gls_01JMED", "device", "Medizinprodukt", "preferred", "In regulatory text use Medizinprodukt; Gerät only in UI."),
  t("gls_01JMED", "Gerät", null, "forbidden", "Too informal for IFU body text.", "de", "de"),
  t("gls_01JMED", "P300", null, "do_not_translate", "Product name."),
  t("gls_01JMED", "occlusion", "Okklusion", "mandatory", null),
  t("gls_01JMED", "bolus", "Bolus", "mandatory", null),
  t("gls_01JUI", "Start", "Start", "do_not_translate", "Matches the hardware key label."),
  t("gls_01JUI", "History", "Verlauf", "mandatory", null),
  t("gls_01JUI", "Settings", "Einstellungen", "preferred", null),
];

function t(
  glossary_id: string,
  source_term: string,
  target_term: string | null,
  kind: Term["kind"],
  note: string | null,
  source_lang = "en",
  target_lang = "de",
): Term {
  return {
    id: newId("trm"),
    glossary_id,
    source_lang,
    target_lang,
    source_term,
    target_term,
    kind,
    case_sensitive: kind === "do_not_translate",
    note,
    valid_from: "2026-03-01T00:00:00Z",
    valid_to: null,
  };
}

export const TM_ENTRIES: TmHit[] = [
  {
    entry_id: "tmu_01JA",
    kind: "approved",
    score: 1,
    source_tagged: "Press ⟦1⟧Start⟦/1⟧ to begin.",
    target_tagged: "Drücken Sie ⟦1⟧Start⟦/1⟧, um zu beginnen.",
  },
  {
    entry_id: "tmu_01JB",
    kind: "approved",
    score: 0.86,
    source_tagged: "Clean the device with a damp cloth.",
    target_tagged: "Reinigen Sie das Medizinprodukt mit einem feuchten Tuch.",
  },
  {
    entry_id: "tmu_01JC",
    kind: "imported",
    score: 0.74,
    source_tagged: "The occlusion alarm cannot be muted.",
    target_tagged: "Der Okklusionsalarm kann nicht stummgeschaltet werden.",
  },
  {
    entry_id: "tmu_01JD",
    kind: "approved",
    score: 0.71,
    source_tagged: "Store the infusion pump in a dry place.",
    target_tagged: "Lagern Sie die Infusionspumpe an einem trockenen Ort.",
  },
];

export const TERM_QUESTIONS: TermQuestion[] = [
  {
    id: "tq_01JA",
    source_term: "free-flow protection",
    source_lang: "en",
    target_lang: "de",
    options: ["Freiflussschutz", "Free-Flow-Schutz", "Schutz vor freiem Durchfluss"],
    status: "open",
  },
  {
    id: "tq_01JB",
    source_term: "KVO rate",
    source_lang: "en",
    target_lang: "fr",
    options: ["débit KVO", "débit de maintien de veine ouverte (MVO)"],
    status: "open",
  },
  {
    id: "tq_01JC",
    source_term: "drip chamber",
    source_lang: "en",
    target_lang: "ja",
    options: ["点滴筒", "ドリップチャンバー"],
    status: "answered",
  },
];

export const EXCEPTIONS: ExceptionItem[] = [
  {
    kind: "overdue",
    job_id: "job_01JIFUJA",
    segment_id: null,
    reason: "No active en>ja reviewer with regulatory domain. Policy is wait: the job will not fall back to AI review.",
    created_at: iso(-40 * 60_000),
  },
  {
    kind: "job_failed",
    job_id: "job_01JRELES",
    segment_id: null,
    reason: "Source file has 3 unbalanced inline tags in segment 14.",
    created_at: iso(-5 * HOUR),
  },
  {
    kind: "segment_blocked",
    job_id: "job_01JIFUDE",
    segment_id: "seg_01JDE0003",
    reason: "Dosage number mismatch (0.5 vs 5 mL/h) persisted after review; needs PM sign-off.",
    created_at: iso(-2 * HOUR),
  },
  {
    kind: "term_question",
    job_id: "job_01JIFUDE",
    segment_id: "seg_01JDE0011",
    reason: "Reviewer asked how to translate free-flow protection.",
    created_at: iso(-1 * HOUR),
  },
  {
    kind: "term_question",
    job_id: "job_01JRELDE",
    segment_id: null,
    reason: "Auto-approval suspended for software_ui > de after 2 escaped errors in control samples.",
    created_at: iso(-26 * HOUR),
  },
];

// ---- Quality ----------------------------------------------------------------

export const THRESHOLDS: Threshold[] = [
  th("regulatory", "de", 80, 8, 3, false, null),
  th("regulatory", "fr", 79, 8, 3, false, null),
  th("regulatory", "ja", 82, 8, 4, false, null),
  th("software_ui", "de", 76, 8, 2, true, "2 escaped errors in last 200 control samples"),
  th("software_ui", "es", 75, 8, 2, false, null),
  th("support", "pt-BR", 74, 8, 1, false, null),
];

function th(
  content_type: string,
  target_lang: string,
  value: number,
  band_width: number,
  safety_offset: number,
  suspended: boolean,
  reason: string | null,
): Threshold {
  return {
    id: newId("thr"),
    content_type,
    target_lang,
    value,
    band_width,
    safety_offset,
    auto_approval_suspended: suspended,
    suspended_reason: reason,
  };
}

export const ENGINES: EngineScore[] = [
  { engine: "llm-primary", source_lang: "en", target_lang: "de", domain: "regulatory", segments_measured: 18420, mean_qe: 82.4, mean_edit_distance: 0.12, term_adherence: 0.97 },
  { engine: "llm-challenger", source_lang: "en", target_lang: "de", domain: "regulatory", segments_measured: 6110, mean_qe: 80.9, mean_edit_distance: 0.12, term_adherence: 0.97 },
  { engine: "nmt-fallback", source_lang: "en", target_lang: "de", domain: "regulatory", segments_measured: 2380, mean_qe: 74.2, mean_edit_distance: 0.12, term_adherence: 0.97 },
];

// ---- Reviewer --------------------------------------------------------------

export const REVIEWER_PROFILE: ReviewerProfile = {
  id: "rev_01JLEA",
  level: "senior",
  status: "active",
  score: 93,
  pairs: [
    { source_lang: "en", target_lang: "de", status: "active", score: 94 },
    { source_lang: "en", target_lang: "fr", status: "active", score: 91 },
    { source_lang: "de", target_lang: "fr", status: "testing", score: null },
  ],
  domains: ["regulatory", "software_ui"],
  balance: "184.60",
  payout_threshold: "50.00",
  tax_info_complete: false,
  name: "Léa Fontaine",
  email: "reviewer@demo.test",
  country: "FR",
};

export const REVIEWER_TESTS: ReviewerTest[] = [
  { id: "tst_01JENDE", kind: "qualification", source_lang: "en", target_lang: "de", domain: "regulatory", time_limit_min: 30, status: "passed" },
  { id: "tst_01JENFR", kind: "qualification", source_lang: "en", target_lang: "fr", domain: "regulatory", time_limit_min: 30, status: "passed" },
  { id: "tst_01JDEFR", kind: "qualification", source_lang: "de", target_lang: "fr", domain: "general", time_limit_min: 25, status: "available" },
  { id: "tst_01JUIDE", kind: "domain", source_lang: "en", target_lang: "de", domain: "software_ui", time_limit_min: 15, status: "available" },
  { id: "tst_01JLEGDE", kind: "domain", source_lang: "en", target_lang: "de", domain: "legal", time_limit_min: 40, status: "locked" },
];

export const TEST_ITEMS = [
  {
    source: "Disconnect the charger before cleaning the unit.",
    target: "Trennen Sie das Ladegerät, bevor Sie das Gerät reinigen.",
  },
  {
    source: "The alarm volume cannot be set below level 2.",
    target: "Die Alarmlautstärke kann nicht unter Stufe 3 eingestellt werden.",
  },
  {
    source: "Press ⟦1⟧OK⟦/1⟧ to confirm the new rate.",
    target: "Drücken Sie ⟦1⟧OK⟦/1⟧, um die neue Rate zu bestätigen.",
  },
  {
    source: "Replace the filter every 96 hours.",
    target: "Ersetzen Sie den Filter alle 96 Stunden.",
  },
];

export function makeTasks(now = Date.now()): Task[] {
  const seeds = [SEEDS[2], SEEDS[4], SEEDS[12], SEEDS[10]];
  const flagged: Task["flagged_errors"][] = [
    [
      { dimension: "accuracy", severity: "critical", span: "5 mL/h", explanation: "Source says 0.5 mL/h; the number changed." },
    ],
    [{ dimension: "terminology", severity: "major", span: "Gerät", explanation: "Forbidden term. Glossary requires Medizinprodukt." }],
    [{ dimension: "style", severity: "minor", explanation: "Long sentence; consider splitting for readability." }],
    [],
  ];
  const qes = [41, 62, 79, 84];
  return seeds.map((s, i) => ({
    id: `tsk_01J${String(i + 1).padStart(3, "0")}`,
    segment_id: `seg_01JDE${String(i * 3 + 3).padStart(4, "0")}`,
    source_lang: "en",
    target_lang: "de",
    domain: "regulatory",
    source_tagged: s.src,
    target_tagged: s.de,
    context_before: [SEEDS[(i + 15) % SEEDS.length].src],
    context_after: [SEEDS[(i + 1) % SEEDS.length].src],
    terms: TERMS.filter((tm) => tm.glossary_id === "gls_01JMED")
      .slice(0, i % 2 === 0 ? 3 : 4)
      .map((tm) => ({ source_term: tm.source_term, target_term: tm.target_term, kind: tm.kind })),
    qe_score: qes[i],
    flagged_errors: flagged[i],
    hold_expires_at: iso(10 * 60_000, now),
    pay_estimate: ["0.42", "0.38", "0.61", "0.47"][i],
  }));
}

export function makeLedger(now = Date.now()): LedgerEntry[] {
  return [
    { id: "led_01JA", kind: "task", amount: "0.42", created_at: iso(-20 * 60_000, now), ref: "tsk_01J0A1" },
    { id: "led_01JB", kind: "task", amount: "0.31", created_at: iso(-50 * 60_000, now), ref: "tsk_01J0A2" },
    { id: "led_01JC", kind: "control_bonus", amount: "1.50", created_at: iso(-1 * DAY, now), ref: null },
    { id: "led_01JD", kind: "task", amount: "0.55", created_at: iso(-1 * DAY - 3 * HOUR, now), ref: "tsk_01J0A3" },
    { id: "led_01JE", kind: "adjustment", amount: "-0.40", created_at: iso(-2 * DAY, now), ref: "tsk_01J0A4" },
    { id: "led_01JF", kind: "payout", amount: "-120.00", created_at: iso(-14 * DAY, now), ref: null },
  ];
}

// ---- Admin -----------------------------------------------------------------

export const ADMIN_REVIEWERS: ReviewerProfile[] = [
  REVIEWER_PROFILE,
  rp("rev_01JTOM", "Tomasz Wójcik", "PL", "reviewer", "active", 88, [["en", "pl", "active"]], ["general"]),
  rp("rev_01JAIKO", "Aiko Tanaka", "JP", "candidate", "applied", null, [["en", "ja", "testing"]], ["regulatory"]),
  rp("rev_01JMATEO", "Mateo Ruiz", "ES", "candidate", "applied", null, [["en", "es", "testing"], ["en", "pt-BR", "testing"]], ["software_ui", "support"]),
  rp("rev_01JHANNA", "Hanna Lind", "SE", "reviewer", "suspended", 71, [["en", "sv", "suspended"]], ["general"]),
  rp("rev_01JKWAME", "Kwame Mensah", "GH", "candidate", "applied", null, [["en", "fr", "testing"]], ["legal"]),
];

function rp(
  id: string,
  name: string,
  country: string,
  level: string,
  status: string,
  score: number | null,
  pairs: [string, string, string][],
  domains: string[],
): ReviewerProfile {
  return {
    id,
    name,
    email: `${name.split(" ")[0].toLowerCase()}@example.org`,
    country,
    level,
    status,
    score,
    pairs: pairs.map(([s, tl, st]) => ({ source_lang: s, target_lang: tl, status: st, score })),
    domains,
    balance: status === "active" ? "42.10" : "0.00",
    payout_threshold: "50.00",
    tax_info_complete: status === "active",
  };
}

export function makeDisputes(now = Date.now()): Dispute[] {
  return [
    {
      id: "dsp_01JA",
      task_id: "tsk_01J0A4",
      reviewer_id: "rev_01JLEA",
      reason: "The number in the source was ambiguous (0,5 in the PDF). I followed the source layout.",
      status: "open",
      decision_note: null,
      due_at: iso(2 * DAY, now),
      created_at: iso(-1 * DAY, now),
    },
    {
      id: "dsp_01JB",
      task_id: "tsk_01J0B9",
      reviewer_id: "rev_01JTOM",
      reason: "Control sample marked my edit as wrong but the glossary entry was retired the day before.",
      status: "open",
      decision_note: null,
      due_at: iso(4 * DAY, now),
      created_at: iso(-6 * HOUR, now),
    },
    {
      id: "dsp_01JC",
      task_id: "tsk_01J0C2",
      reviewer_id: "rev_01JHANNA",
      reason: "Skipped task was counted as a timeout.",
      status: "upheld",
      decision_note: "Client-side timer bug confirmed; penalty reversed.",
      due_at: iso(-3 * DAY, now),
      created_at: iso(-7 * DAY, now),
    },
  ];
}

export function makePayouts(now = Date.now()): Payout[] {
  return [
    { id: "pay_01JA", reviewer_id: "rev_01JLEA", amount: "120.00", state: "paid", created_at: iso(-14 * DAY, now) },
    { id: "pay_01JB", reviewer_id: "rev_01JTOM", amount: "86.40", state: "paid", created_at: iso(-14 * DAY, now) },
    { id: "pay_01JC", reviewer_id: "rev_01JHANNA", amount: "52.10", state: "blocked", created_at: iso(-14 * DAY, now) },
  ];
}

export const ADMIN_ORGS: OrgWithUsage[] = [
  { ...ORG, usage: { period: "2026-10", words: 17360, jobs: 4 } },
  {
    id: "org_01JFJORD",
    name: "Fjordline Software",
    slug: "fjordline",
    plan: "starter",
    default_tier: "ai_review",
    no_reviewer_policy: "ai_fallback",
    ai_subprocessors_opt_in: true,
    regulated: false,
    vertical: "software",
    data_retention_days: 90,
    usage: { period: "2026-10", words: 42100, jobs: 4 },
  },
  {
    id: "org_01JCAPRI",
    name: "Capri Legal Partners",
    slug: "capri-legal",
    plan: "growth",
    default_tier: "full",
    no_reviewer_policy: "wait",
    ai_subprocessors_opt_in: false,
    regulated: true,
    vertical: "legal",
    data_retention_days: 30,
    usage: { period: "2026-10", words: 5300, jobs: 4 },
  },
];

// ---- Integrations ----------------------------------------------------------

export const API_KEYS: ApiKey[] = [
  { id: "key_01JCI", name: "CI pipeline", prefix: "ak_7Hq2", scopes: ["projects:write", "projects:read"], created_at: "2026-08-02T09:14:00Z", last_used_at: "2026-10-07T06:02:00Z" },
];

export const WEBHOOKS: Webhook[] = [
  { id: "whk_01JA", url: "https://hooks.halden.example/arbiter", events: ["job.delivered", "job.needs_attention"], active: true },
];

export const INVOICES: Invoice[] = [
  { id: "inv_01J09", number: "ARB-2026-0918", period: "2026-09", total: "2210.40", currency: "EUR", status: "paid", issued_at: "2026-10-01T00:00:00Z" },
  { id: "inv_01J08", number: "ARB-2026-0812", period: "2026-08", total: "1874.90", currency: "EUR", status: "paid", issued_at: "2026-09-01T00:00:00Z" },
  { id: "inv_01J07", number: "ARB-2026-0704", period: "2026-07", total: "960.00", currency: "EUR", status: "paid", issued_at: "2026-08-01T00:00:00Z" },
];
