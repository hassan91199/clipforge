import { describe, expect, it, vi } from "vitest";
import { extractSseRecords, parseSseRecord, streamGenerate } from "./generateStream";
import type { GenerateEvent } from "./stageTracker";

describe("extractSseRecords", () => {
  it("extracts one complete record and no remainder", () => {
    const { records, rest } = extractSseRecords('data: {"event":"stage_start"}\n\n');
    expect(records).toEqual(['{"event":"stage_start"}']);
    expect(rest).toBe("");
  });

  it("holds back an incomplete trailing record", () => {
    const { records, rest } = extractSseRecords(
      'data: {"event":"stage_start"}\n\ndata: {"event":"stage_d',
    );
    expect(records).toEqual(['{"event":"stage_start"}']);
    expect(rest).toBe('data: {"event":"stage_d');
  });

  it("extracts multiple records arriving in one chunk", () => {
    const { records, rest } = extractSseRecords(
      'data: {"a":1}\n\ndata: {"a":2}\n\ndata: {"a":3}\n\n',
    );
    expect(records).toEqual(['{"a":1}', '{"a":2}', '{"a":3}']);
    expect(rest).toBe("");
  });

  it("ignores blank/non-data lines", () => {
    const { records } = extractSseRecords("\n\ndata: {\"a\":1}\n\n\n\n");
    expect(records).toEqual(['{"a":1}']);
  });
});

describe("parseSseRecord", () => {
  it("parses a JSON event payload", () => {
    expect(parseSseRecord('{"event":"note","message":"hi"}')).toEqual({
      event: "note",
      message: "hi",
    });
  });
});

function fakeStreamResponse(chunks: string[]): Response {
  let i = 0;
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(encoder.encode(chunks[i]));
        i += 1;
      } else {
        controller.close();
      }
    },
  });
  return new Response(body, { status: 200 });
}

describe("streamGenerate", () => {
  it("delivers events split arbitrarily across chunk boundaries", async () => {
    const full = 'data: {"event":"stage_start","stage":"script"}\n\n' +
      'data: {"event":"stage_done","stage":"script","seconds":1.2}\n\n' +
      'data: {"event":"result","video_url":"/api/runs/r1/video"}\n\n';
    // Split mid-record to prove the buffer carries partial data across reads.
    const splitPoint = 40;
    const chunks = [full.slice(0, splitPoint), full.slice(splitPoint)];
    const fetchImpl = vi.fn(async () => fakeStreamResponse(chunks));

    const events: GenerateEvent[] = [];
    await streamGenerate(
      "http://api.example",
      {
        prompt: "x",
        openai_api_key: "k",
        replicate_api_token: "t",
        num_images: 3,
        video_duration: "30",
      },
      (event) => events.push(event),
      fetchImpl as unknown as typeof fetch,
    );

    expect(events).toEqual([
      { event: "stage_start", stage: "script" },
      { event: "stage_done", stage: "script", seconds: 1.2 },
      { event: "result", video_url: "/api/runs/r1/video" },
    ]);
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://api.example/api/generate",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("delivers a single error event for a quota-blocked run", async () => {
    const chunks = ['data: {"event":"error","message":"Daily demo limit reached (100 runs today)"}\n\n'];
    const fetchImpl = vi.fn(async () => fakeStreamResponse(chunks));

    const events: GenerateEvent[] = [];
    await streamGenerate(
      "http://api.example",
      {
        prompt: "x",
        openai_api_key: "k",
        replicate_api_token: "t",
        num_images: 3,
        video_duration: "30",
      },
      (event) => events.push(event),
      fetchImpl as unknown as typeof fetch,
    );

    expect(events).toEqual([
      { event: "error", message: "Daily demo limit reached (100 runs today)" },
    ]);
  });

  it("rejects when the response is not ok", async () => {
    const fetchImpl = vi.fn(async () => new Response(null, { status: 500 }));

    await expect(
      streamGenerate(
        "http://api.example",
        {
          prompt: "x",
          openai_api_key: "k",
          replicate_api_token: "t",
          num_images: 3,
          video_duration: "30",
        },
        () => {},
        fetchImpl as unknown as typeof fetch,
      ),
    ).rejects.toThrow("generate request failed: 500");
  });
});
