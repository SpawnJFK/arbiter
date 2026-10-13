// Endpoints of the workbench and TM tools (module tms), LQA (module ai) and the auditor.
// Spread into createApi() so both transports (proxy and server) expose them.

import type { Query, Transport } from "./api";
import type { ListResponse, Term } from "./types";
import type {
  Alignment,
  AiMode,
  AssistData,
  Audit,
  AuditSegmentPage,
  AuditSegmentQuery,
  ConcordanceHit,
  DraftCheck,
  EditorFilters,
  EditorSegment,
  EditorSegmentPage,
  FindReplaceInput,
  FindReplaceResult,
  JobLqa,
  LqaSettings,
  MtSuggestion,
  QueryItem,
  SegmentComment,
  TermExtraction,
  TmEntryQuery,
  TmEntryRow,
  TmQa,
} from "./types-workbench";

const enc = encodeURIComponent;

function newKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function workbenchEndpoints(item: Transport) {
  const get = <T>(path: string, query?: Query) => item.request<T>("GET", path, { query });
  const post = <T>(path: string, body?: unknown) => item.request<T>("POST", path, { body });
  const patch = <T>(path: string, body: unknown) => item.request<T>("PATCH", path, { body });
  const put = <T>(path: string, body: unknown) => item.request<T>("PUT", path, { body });
  const job = (id: string) => `/jobs/${enc(id)}`;

  return {
    // Workbench
    editorSegments: (jobId: string, q: EditorFilters & { offset?: number; limit?: number } = {}) =>
      get<EditorSegmentPage>(`${job(jobId)}/editor/segments`, { ...q }),
    checkDraft: (jobId: string, segId: string, target_tagged: string) =>
      post<DraftCheck>(`${job(jobId)}/segments/${enc(segId)}/check`, { target_tagged }),
    assist: (jobId: string, segId: string) => get<AssistData>(`${job(jobId)}/segments/${enc(segId)}/assist`),
    mtSuggest: (jobId: string, segId: string, engine?: string) =>
      post<MtSuggestion>(`${job(jobId)}/segments/${enc(segId)}/mt`, { engine }),
    splitSegment: (jobId: string, segId: string, body: { source_offset: number; target_offset?: number | null }) =>
      post<{ segments: EditorSegment[]; segment_count: number }>(`${job(jobId)}/segments/${enc(segId)}/split`, body),
    mergeNext: (jobId: string, segId: string) =>
      post<{ segment: EditorSegment; segment_count: number }>(`${job(jobId)}/segments/${enc(segId)}/merge-next`),
    lockSegments: (jobId: string, segment_ids: string[], locked: boolean) =>
      post<{ changed: number; locked: boolean }>(`${job(jobId)}/segments/lock`, { segment_ids, locked }),
    findReplace: (jobId: string, body: FindReplaceInput) => post<FindReplaceResult>(`${job(jobId)}/find-replace`, body),
    comments: (jobId: string, q: { segment_id?: string; kind?: string; resolved?: string } = {}) =>
      get<ListResponse<SegmentComment>>(`${job(jobId)}/comments`, { ...q }),
    addComment: (
      jobId: string,
      body: { body: string; kind?: "comment" | "query"; segment_id?: string | null; parent_id?: string | null },
    ) => post<SegmentComment>(`${job(jobId)}/comments`, body),
    resolveComment: (id: string, resolved: boolean) => patch<SegmentComment>(`/comments/${enc(id)}`, { resolved }),
    openQueries: (q: { offset?: number; limit?: number } = {}) => get<ListResponse<QueryItem>>("/queries", { ...q }),
    previewUrl: (jobId: string) => item.downloadUrl(`${job(jobId)}/preview`),
    concordance: (q: { q: string; source_lang: string; target_lang: string; side?: string; limit?: number }) =>
      get<ListResponse<ConcordanceHit>>("/tm/concordance", { ...q }),

    // TM tools
    tmEntries: (q: TmEntryQuery = {}) => get<ListResponse<TmEntryRow>>("/tm/entries", { ...q }),
    updateTmEntry: (id: string, body: { source_tagged?: string; target_tagged?: string; status?: "approved" | "stale" }) =>
      patch<TmEntryRow>(`/tm/entries/${enc(id)}`, body),
    deleteTmEntry: (id: string) => item.request<null>("DELETE", `/tm/entries/${enc(id)}`),
    bulkTmEntries: (ids: string[], action: "delete" | "mark_stale" | "mark_approved") =>
      post<{ changed: number; action: string }>("/tm/entries/bulk", { ids, action }),
    createAlignment: (source: File, target: File, sourceLang: string, targetLang: string) => {
      const form = new FormData();
      form.set("source_file", source);
      form.set("target_file", target);
      form.set("source_lang", sourceLang);
      form.set("target_lang", targetLang);
      return item.request<Alignment>("POST", "/tm/align", { form, idempotencyKey: newKey() });
    },
    alignment: (id: string) => get<Alignment>(`/tm/align/${enc(id)}`),
    commitAlignment: (
      id: string,
      pairs: { index: number; accepted: boolean; source?: string; target?: string }[],
    ) =>
      post<{ imported: number; skipped: number; alignment: Alignment }>(`/tm/align/${enc(id)}/commit`, {
        rights_confirmed: true,
        pairs,
      }),
    extractTerms: (
      glossaryId: string,
      src: { jobId?: string; file?: File; sourceLang?: string; targetLang?: string; minFreq?: number },
    ) => {
      const form = new FormData();
      if (src.jobId) form.set("job_id", src.jobId);
      if (src.file) form.set("file", src.file);
      if (src.sourceLang) form.set("source_lang", src.sourceLang);
      if (src.targetLang) form.set("target_lang", src.targetLang);
      if (src.minFreq) form.set("min_freq", String(src.minFreq));
      return item.request<TermExtraction>("POST", `/glossaries/${enc(glossaryId)}/extract`, { form });
    },
    acceptTerms: (
      glossaryId: string,
      terms: { source_term: string; target_term: string | null; kind: string; source_lang: string; target_lang: string }[],
    ) => post<ListResponse<Term>>(`/glossaries/${enc(glossaryId)}/extract/accept`, { terms }),
    tmQa: (q: { source_lang: string; target_lang: string; glossary_id?: string }) => get<TmQa>("/tm/qa", { ...q }),

    // LQA
    jobLqa: (jobId: string) => get<JobLqa>(`${job(jobId)}/lqa`),
    jobLqaUrl: (jobId: string, kind: "pdf" | "xlsx") => item.downloadUrl(`${job(jobId)}/lqa.${kind}`),
    lqaSettings: () => get<LqaSettings>("/lqa/settings"),
    updateLqaSettings: (body: { threshold?: number; weights?: Record<string, number>; reset?: boolean }) =>
      put<LqaSettings>("/lqa/settings", body),

    // Auditor
    audits: (q: { offset?: number; limit?: number } = {}) => get<ListResponse<Audit>>("/audits", { ...q }),
    audit: (id: string) => get<Audit>(`/audits/${enc(id)}`),
    createAudit: (input: {
      file: File;
      targetFile?: File | null;
      sourceLang: string;
      targetLang: string;
      name?: string;
      glossaryId?: string;
      aiMode: AiMode;
      aiSamplePct?: number;
      threshold?: number | null;
      consistency?: boolean;
    }) => {
      const form = new FormData();
      form.set("file", input.file);
      if (input.targetFile) form.set("target_file", input.targetFile);
      form.set("source_lang", input.sourceLang);
      form.set("target_lang", input.targetLang);
      if (input.name) form.set("name", input.name);
      if (input.glossaryId) form.set("glossary_id", input.glossaryId);
      form.set("ai_mode", input.aiMode);
      if (input.aiSamplePct) form.set("ai_sample_pct", String(input.aiSamplePct));
      if (input.threshold !== null && input.threshold !== undefined) form.set("threshold", String(input.threshold));
      form.set("consistency", String(input.consistency ?? true));
      return item.request<Audit>("POST", "/audits", { form, idempotencyKey: newKey() });
    },
    auditSegments: (id: string, q: AuditSegmentQuery = {}) =>
      get<AuditSegmentPage>(`/audits/${enc(id)}/segments`, { ...q }),
    retryAudit: (id: string) => post<Audit>(`/audits/${enc(id)}/retry`),
    auditExportUrl: (id: string, kind: "report.pdf" | "report.xlsx" | "annotated.xlf") =>
      item.downloadUrl(`/audits/${enc(id)}/${kind}`),
  };
}
