import { describe, expect, it } from "vitest";
import {
  applyEvent,
  doneStages,
  initialTrackerState,
  isDone,
  PIPELINE_STAGES,
  type GenerateEvent,
} from "./stageTracker";

function reduce(events: GenerateEvent[]) {
  return events.reduce(applyEvent, initialTrackerState());
}

describe("applyEvent", () => {
  it("marks a stage running on stage_start", () => {
    const state = reduce([{ event: "stage_start", stage: "script" }]);
    expect(state.stages.script).toEqual({ status: "running", seconds: null });
  });

  it("marks a stage done with elapsed seconds on stage_done", () => {
    const state = reduce([
      { event: "stage_start", stage: "script" },
      { event: "stage_done", stage: "script", seconds: 1.5 },
    ]);
    expect(state.stages.script).toEqual({ status: "done", seconds: 1.5 });
  });

  it("appends notes in order", () => {
    const state = reduce([
      { event: "note", message: "title: Curious Cat" },
      { event: "note", message: "another note" },
    ]);
    expect(state.notes).toEqual(["title: Curious Cat", "another note"]);
  });

  it("records total_seconds on pipeline_done", () => {
    const state = reduce([{ event: "pipeline_done", total_seconds: 42.3 }]);
    expect(state.totalSeconds).toBe(42.3);
    expect(isDone(state)).toBe(true);
  });

  it("is not done before pipeline_done arrives", () => {
    const state = reduce([{ event: "stage_start", stage: "script" }]);
    expect(isDone(state)).toBe(false);
  });

  it("records the video url on result", () => {
    const state = reduce([{ event: "result", video_url: "/api/runs/abc123/video" }]);
    expect(state.videoUrl).toBe("/api/runs/abc123/video");
  });

  it("records an error message and does not throw on an error-only stream", () => {
    const state = reduce([{ event: "error", message: "Daily demo limit reached (100 runs today)" }]);
    expect(state.error).toBe("Daily demo limit reached (100 runs today)");
    expect(state.videoUrl).toBeNull();
    expect(isDone(state)).toBe(false);
  });

  it("records an error after some stages already completed", () => {
    const state = reduce([
      { event: "stage_start", stage: "script" },
      { event: "stage_done", stage: "script", seconds: 0.8 },
      { event: "stage_start", stage: "voiceover" },
      { event: "error", message: "boom" },
    ]);
    expect(state.error).toBe("boom");
    expect(state.stages.script).toEqual({ status: "done", seconds: 0.8 });
    expect(state.stages.voiceover).toEqual({ status: "running", seconds: null });
  });

  it("replays a full successful run in pipeline order", () => {
    const events: GenerateEvent[] = PIPELINE_STAGES.flatMap((stage) => [
      { event: "stage_start", stage } as GenerateEvent,
      { event: "stage_done", stage, seconds: 1 } as GenerateEvent,
    ]);
    events.push({ event: "pipeline_done", total_seconds: 6 });
    events.push({ event: "result", video_url: "/api/runs/xyz/video" });

    const state = reduce(events);
    expect(doneStages(state)).toHaveLength(PIPELINE_STAGES.length);
    expect(isDone(state)).toBe(true);
    expect(state.videoUrl).toBe("/api/runs/xyz/video");
    expect(state.error).toBeNull();
  });
});

describe("doneStages", () => {
  it("excludes stages that are still running", () => {
    const state = reduce([
      { event: "stage_start", stage: "script" },
      { event: "stage_done", stage: "script", seconds: 1 },
      { event: "stage_start", stage: "voiceover" },
    ]);
    expect(doneStages(state)).toEqual([["script", 1]]);
  });
});
