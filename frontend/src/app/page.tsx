"use client";

import { useState } from "react";
import styles from "./page.module.css";
import {
  applyEvent,
  doneStages,
  initialTrackerState,
  isDone,
  PIPELINE_STAGES,
  type TrackerState,
} from "@/lib/stageTracker";
import { streamGenerate } from "@/lib/generateStream";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";
const VIDEO_DURATION_OPTIONS = ["30", "30-60", "60-90"];

export default function Home() {
  const [prompt, setPrompt] = useState("");
  const [openaiKey, setOpenaiKey] = useState("");
  const [replicateToken, setReplicateToken] = useState("");
  const [numImages, setNumImages] = useState(3);
  const [videoDuration, setVideoDuration] = useState("30");
  const [isRunning, setIsRunning] = useState(false);
  const [tracker, setTracker] = useState<TrackerState>(initialTrackerState());

  const canSubmit =
    prompt.trim() !== "" && openaiKey.trim() !== "" && replicateToken.trim() !== "" && !isRunning;

  async function handleSubmit(formEvent: React.FormEvent) {
    formEvent.preventDefault();
    if (!canSubmit) return;

    setIsRunning(true);
    setTracker(initialTrackerState());

    try {
      await streamGenerate(
        API_BASE_URL,
        {
          prompt,
          openai_api_key: openaiKey,
          replicate_api_token: replicateToken,
          num_images: numImages,
          video_duration: videoDuration,
        },
        (event) => setTracker((state) => applyEvent(state, event)),
      );
    } catch (err) {
      setTracker((state) => ({
        ...state,
        error: err instanceof Error ? err.message : "generate request failed",
      }));
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <div className={styles.page}>
      <main className={styles.main}>
        <h1>ClipForge</h1>
        <p className={styles.subtitle}>
          Text prompt in, a captioned vertical short out. Public demo — bring your own OpenAI and
          Replicate keys, used only for this run and never stored.
        </p>

        <form className={styles.form} onSubmit={handleSubmit}>
          <div className={styles.field}>
            <label htmlFor="prompt">Video prompt</label>
            <textarea
              id="prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Why the sky is blue, explained for curious kids"
              disabled={isRunning}
            />
          </div>

          <div className={styles.field}>
            <label htmlFor="openai-key">OpenAI API key</label>
            <input
              id="openai-key"
              type="password"
              value={openaiKey}
              onChange={(e) => setOpenaiKey(e.target.value)}
              disabled={isRunning}
            />
          </div>

          <div className={styles.field}>
            <label htmlFor="replicate-token">Replicate API token</label>
            <input
              id="replicate-token"
              type="password"
              value={replicateToken}
              onChange={(e) => setReplicateToken(e.target.value)}
              disabled={isRunning}
            />
          </div>

          <div className={styles.row}>
            <div className={styles.field}>
              <label htmlFor="num-images">Scene images ({numImages})</label>
              <input
                id="num-images"
                type="range"
                min={1}
                max={6}
                value={numImages}
                onChange={(e) => setNumImages(Number(e.target.value))}
                disabled={isRunning}
              />
            </div>

            <div className={styles.field}>
              <label htmlFor="video-duration">Target length</label>
              <select
                id="video-duration"
                value={videoDuration}
                onChange={(e) => setVideoDuration(e.target.value)}
                disabled={isRunning}
              >
                {VIDEO_DURATION_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}s
                  </option>
                ))}
              </select>
            </div>
          </div>

          <button type="submit" className={styles.submit} disabled={!canSubmit}>
            {isRunning ? "Generating…" : "Generate video"}
          </button>
          <p className={styles.hint}>Keys stay in this browser tab and are never persisted.</p>
        </form>

        {Object.keys(tracker.stages).length > 0 && (
          <div className={styles.progress}>
            {PIPELINE_STAGES.filter((stage) => stage in tracker.stages).map((stage) => {
              const row = tracker.stages[stage];
              return (
                <div key={stage} className={styles.stageRow} data-status={row.status}>
                  <span>{stage}</span>
                  <span>
                    {row.status === "done" && row.seconds !== null
                      ? `${row.seconds.toFixed(1)}s`
                      : "running…"}
                  </span>
                </div>
              );
            })}
            {tracker.notes.length > 0 && (
              <div className={styles.notes}>
                {tracker.notes.map((note, i) => (
                  <span key={i}>{note}</span>
                ))}
              </div>
            )}
          </div>
        )}

        {tracker.error && <div className={styles.error}>{tracker.error}</div>}

        {tracker.videoUrl && (
          <div className={styles.result}>
            <video src={`${API_BASE_URL}${tracker.videoUrl}`} controls />
            {isDone(tracker) && tracker.totalSeconds !== null && (
              <p>
                Done in {tracker.totalSeconds.toFixed(1)}s ({doneStages(tracker).length} stages)
              </p>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
