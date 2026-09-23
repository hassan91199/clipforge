/**
 * Pure reducer over clipforge/api.py's SSE event stream.
 *
 * Mirrors clipforge/ui.py's StageTracker: no DOM, no fetch, just a fold from
 * events to display state, so the event contract can be unit-tested the same
 * way the Python side pins it.
 */

export const PIPELINE_STAGES = [
  "script",
  "voiceover",
  "captions",
  "image-prompts",
  "images",
  "render",
] as const;

export type PipelineStage = (typeof PIPELINE_STAGES)[number];

export type StageStatus = "running" | "done";

export interface StageState {
  status: StageStatus;
  seconds: number | null;
}

export type GenerateEvent =
  | { event: "stage_start"; stage: string }
  | { event: "stage_done"; stage: string; seconds: number }
  | { event: "note"; message: string }
  | { event: "pipeline_done"; total_seconds: number }
  | { event: "result"; video_url: string }
  | { event: "error"; message: string };

export interface TrackerState {
  stages: Record<string, StageState>;
  notes: string[];
  totalSeconds: number | null;
  videoUrl: string | null;
  error: string | null;
}

export function initialTrackerState(): TrackerState {
  return { stages: {}, notes: [], totalSeconds: null, videoUrl: null, error: null };
}

/** Folds one SSE event into the previous state, returning a new state object. */
export function applyEvent(state: TrackerState, event: GenerateEvent): TrackerState {
  switch (event.event) {
    case "stage_start":
      return {
        ...state,
        stages: { ...state.stages, [event.stage]: { status: "running", seconds: null } },
      };
    case "stage_done":
      return {
        ...state,
        stages: { ...state.stages, [event.stage]: { status: "done", seconds: event.seconds } },
      };
    case "note":
      return { ...state, notes: [...state.notes, event.message] };
    case "pipeline_done":
      return { ...state, totalSeconds: event.total_seconds };
    case "result":
      return { ...state, videoUrl: event.video_url };
    case "error":
      return { ...state, error: event.message };
    default:
      return state;
  }
}

export function doneStages(state: TrackerState): [string, number][] {
  return Object.entries(state.stages)
    .filter(([, row]) => row.status === "done" && row.seconds !== null)
    .map(([stage, row]) => [stage, row.seconds as number]);
}

export function isDone(state: TrackerState): boolean {
  return state.totalSeconds !== null;
}
