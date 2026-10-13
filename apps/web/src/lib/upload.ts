// Direct upload of a source file, with progress.
//
// 1. POST /uploads (through the proxy) returns a ticket: a URL, method and headers.
// 2. The browser PUTs the bytes with XMLHttpRequest (fetch has no upload progress):
//    - backend "s3": straight to the presigned bucket URL, so large files never pass
//      through Cloudflare (its proxied request bodies are capped) or our servers;
//    - backend "local" (dev, e2e): to the API's signed blob endpoint via /api/proxy.
// 3. POST /uploads/{id}/complete registers the file and returns it, like POST /files.
// When the API has no direct uploads (404/405/501, e.g. mock mode), it falls back to the
// multipart POST /files, with the same XHR progress.

import { api, ApiError, newIdempotencyKey, parseError } from "./api";
import type { Translator } from "./i18n/core";
import type { UploadedFile, UploadTicket } from "./types";

export type UploadProgress = { loaded: number; total: number; phase: "sending" | "processing" };

function guessType(file: File): string {
  return file.type && file.type.includes("/") ? file.type : "application/octet-stream";
}

/** Same-origin path for the local backend's blob URL; the presigned S3 URL is used as is. */
function targetUrl(ticket: UploadTicket): string {
  if (ticket.backend === "s3") return ticket.url;
  const u = new URL(ticket.url, window.location.origin);
  return `/api/proxy/uploads/${encodeURIComponent(ticket.upload_id)}/blob${u.search}`;
}

function xhrSend(
  t: Translator,
  method: string,
  url: string,
  body: Blob | FormData,
  headers: Record<string, string>,
  onProgress?: (loaded: number, total: number) => void,
  signal?: AbortSignal,
): Promise<{ status: number; text: string }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(method, url);
    for (const [k, v] of Object.entries(headers)) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(e.loaded, e.total);
    };
    xhr.onload = () => resolve({ status: xhr.status, text: xhr.responseText });
    xhr.onerror = () => reject(new ApiError(0, "network_error", t("upload.interrupted")));
    xhr.onabort = () => reject(new ApiError(0, "aborted", t("upload.cancelled")));
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(body);
  });
}

async function errorFrom(status: number, text: string): Promise<ApiError> {
  return parseError(new Response(text || null, { status, headers: { "content-type": "application/json" } }));
}

async function multipartFallback(
  t: Translator,
  file: File,
  sourceLang: string,
  onProgress?: (p: UploadProgress) => void,
  signal?: AbortSignal,
): Promise<UploadedFile> {
  const form = new FormData();
  form.set("file", file);
  form.set("source_lang", sourceLang);
  const res = await xhrSend(
    t,
    "POST",
    "/api/proxy/files",
    form,
    { Accept: "application/json", "Idempotency-Key": newIdempotencyKey() },
    (loaded, total) => onProgress?.({ loaded, total, phase: loaded >= total ? "processing" : "sending" }),
    signal,
  );
  if (res.status < 200 || res.status >= 300) throw await errorFrom(res.status, res.text);
  return JSON.parse(res.text) as UploadedFile;
}

export async function uploadSourceFile(
  t: Translator,
  file: File,
  sourceLang: string,
  onProgress?: (p: UploadProgress) => void,
  signal?: AbortSignal,
): Promise<UploadedFile> {
  const contentType = guessType(file);
  let ticket: UploadTicket;
  try {
    ticket = await api.createUpload({ filename: file.name, size: file.size, content_type: contentType, source_lang: sourceLang });
  } catch (e) {
    // Direct uploads unavailable (older API, mock mode): use the multipart endpoint.
    if (e instanceof ApiError && (e.status === 405 || e.status === 501 || (e.status === 404 && e.code !== "module_disabled"))) {
      return multipartFallback(t, file, sourceLang, onProgress, signal);
    }
    throw e;
  }
  onProgress?.({ loaded: 0, total: file.size, phase: "sending" });
  const put = await xhrSend(
    t,
    ticket.method,
    targetUrl(ticket),
    file,
    ticket.headers,
    (loaded, total) => onProgress?.({ loaded, total, phase: "sending" }),
    signal,
  );
  if (put.status < 200 || put.status >= 300) {
    if (ticket.backend === "s3") throw new ApiError(put.status, "storage_error", t("upload.storageFailed"));
    throw await errorFrom(put.status, put.text);
  }
  onProgress?.({ loaded: file.size, total: file.size, phase: "processing" });
  return api.completeUpload(ticket.upload_id);
}
