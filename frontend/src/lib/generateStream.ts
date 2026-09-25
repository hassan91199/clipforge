/**
 * Drives clipforge/api.py's POST /api/generate SSE stream.
 *
 * EventSource only supports GET, and this endpoint takes a JSON body, so the
 * stream is read by hand: fetch() with a ReadableStream body, split on the
 * `data: ...\n\n` framing clipforge/api.py's _sse() writes.
 */

import type { GenerateEvent } from "./stageTracker";

export interface GenerateRequest {
  prompt: string;
  openai_api_key: string;
  replicate_api_token: string;
  // Omitted (or undefined) means automatic: the backend derives scene count
  // from the script's sentence structure instead of a fixed number.
  num_images?: number;
  video_duration: string;
}

/**
 * Splits a growing text buffer on the SSE record separator ("\n\n").
 *
 * Returns the complete records found and whatever incomplete tail is left,
 * so the caller can keep appending to it as more chunks arrive. Pulled out
 * of the fetch-reading loop so the framing logic is testable without a real
 * stream.
 */
export function extractSseRecords(buffer: string): { records: string[]; rest: string } {
  const parts = buffer.split("\n\n");
  const rest = parts.pop() ?? "";
  const records = parts
    .map((part) => part.trim())
    .filter((part) => part.startsWith("data: "))
    .map((part) => part.slice("data: ".length));
  return { records, rest };
}

export function parseSseRecord(record: string): GenerateEvent {
  return JSON.parse(record) as GenerateEvent;
}

/**
 * POSTs to `${apiBaseUrl}/api/generate` and calls onEvent for each parsed
 * SSE event as it arrives. Resolves once the stream ends; rejects on a
 * network-level failure (a pipeline failure instead arrives as a normal
 * `{event: "error"}` payload via onEvent, not a rejection).
 */
export async function streamGenerate(
  apiBaseUrl: string,
  request: GenerateRequest,
  onEvent: (event: GenerateEvent) => void,
  fetchImpl: typeof fetch = fetch,
): Promise<void> {
  const response = await fetchImpl(`${apiBaseUrl}/api/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok || !response.body) {
    throw new Error(`generate request failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { records, rest } = extractSseRecords(buffer);
    buffer = rest;
    for (const record of records) {
      onEvent(parseSseRecord(record));
    }
  }

  buffer += decoder.decode();
  const { records } = extractSseRecords(`${buffer}\n\n`);
  for (const record of records) {
    onEvent(parseSseRecord(record));
  }
}
