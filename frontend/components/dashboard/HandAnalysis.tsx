import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import type { GestureEvent } from "../../types/contracts";

type Point = { x: number; y: number };
type Finger = "palm" | "thumb" | "index" | "middle" | "ring" | "pinky";

type HandAnalysisProps = {
  active: boolean;
  preview: string | null;
  hands: Point[][];
  latestGesture: GestureEvent | null;
  actionReport: string | null;
};

const connections: ReadonlyArray<readonly [number, number, Finger]> = [
  [0, 1, "palm"], [1, 2, "thumb"], [2, 3, "thumb"], [3, 4, "thumb"],
  [0, 5, "palm"], [5, 6, "index"], [6, 7, "index"], [7, 8, "index"],
  [5, 9, "palm"], [9, 10, "middle"], [10, 11, "middle"], [11, 12, "middle"],
  [9, 13, "palm"], [13, 14, "ring"], [14, 15, "ring"], [15, 16, "ring"],
  [13, 17, "palm"], [0, 17, "palm"], [17, 18, "pinky"], [18, 19, "pinky"], [19, 20, "pinky"],
];

const contour = [0, 1, 2, 3, 4, 8, 7, 6, 5, 9, 10, 11, 12, 16, 15, 14, 13, 17, 18, 19, 20, 0];
const fingertips = [4, 8, 12, 16, 20];
const extendedFingerChecks: ReadonlyArray<readonly [number, number]> = [[4, 3], [8, 6], [12, 10], [16, 14], [20, 18]];

function HandOverlay({ hands }: { hands: Point[][] }) {
  return (
    <svg className="kyra-hand-analysis__overlay" aria-hidden="true" viewBox="0 0 1 1" preserveAspectRatio="none">
      <defs>
        <linearGradient id="kyra-hand-palm" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--aqua)" stopOpacity="0.16" />
          <stop offset="1" stopColor="var(--sky)" stopOpacity="0.05" />
        </linearGradient>
      </defs>
      {hands.map((hand, handIndex) => {
        if (hand.length < 21) return null;
        const points = (indices: number[]) => indices.map((index) => `${hand[index].x},${hand[index].y}`).join(" ");
        const extended = new Set(extendedFingerChecks.filter(([tip, joint]) => hand[tip].y < hand[joint].y).map(([tip]) => tip));
        const palm = [0, 5, 9, 13, 17];
        const center = palm.reduce((point, index) => ({ x: point.x + hand[index].x / palm.length, y: point.y + hand[index].y / palm.length }), { x: 0, y: 0 });
        const left = Math.max(0, Math.min(...hand.map((point) => point.x)) - 0.035);
        const top = Math.max(0, Math.min(...hand.map((point) => point.y)) - 0.035);
        const right = Math.min(1, Math.max(...hand.map((point) => point.x)) + 0.035);
        const bottom = Math.min(1, Math.max(...hand.map((point) => point.y)) + 0.035);
        return (
          <motion.g
            className="kyra-hand-analysis__hand"
            key={`hand-${handIndex}`}
            initial={{ opacity: 0, scale: 0.985 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.12, ease: "easeOut" }}
            style={{ transformBox: "fill-box", transformOrigin: "center" }}
          >
            <rect className="kyra-hand-analysis__reticle" x={left} y={top} width={right - left} height={bottom - top} rx="0.018" />
            <polygon className="kyra-hand-analysis__palm" points={points(palm)} />
            {[5, 6, 7].map((row) => (
              <polyline className="kyra-hand-analysis__web" key={`${handIndex}-web-${row}`} points={points([row, row + 4, row + 8, row + 12])} />
            ))}
            {fingertips.map((tip) => (
              <line className="kyra-hand-analysis__web-spoke" key={`${handIndex}-spoke-${tip}`} x1={center.x} y1={center.y} x2={hand[tip].x} y2={hand[tip].y} />
            ))}
            <polyline className="kyra-hand-analysis__contour" points={points(contour)} />
            <motion.circle
              className="kyra-hand-analysis__palm-center"
              cx={center.x}
              cy={center.y}
              r="0.012"
              animate={{ cx: center.x, cy: center.y }}
              transition={{ duration: 0.1, ease: "easeOut" }}
            />
            {connections.map(([start, end, finger]) => (
              <motion.line
                className={`kyra-hand-analysis__bone kyra-hand-analysis__bone--${finger}`}
                key={`${handIndex}-${start}-${end}`}
                x1={hand[start].x}
                y1={hand[start].y}
                x2={hand[end].x}
                y2={hand[end].y}
                animate={{ x1: hand[start].x, y1: hand[start].y, x2: hand[end].x, y2: hand[end].y }}
                transition={{ duration: 0.1, ease: "easeOut" }}
              />
            ))}
            {hand.map((point, pointIndex) => (
              <motion.circle
                className={`kyra-hand-analysis__joint${fingertips.includes(pointIndex) ? " kyra-hand-analysis__joint--tip" : ""}${extended.has(pointIndex) ? " kyra-hand-analysis__joint--active" : ""}`}
                key={`${handIndex}-joint-${pointIndex}`}
                cx={point.x}
                cy={point.y}
                r={fingertips.includes(pointIndex) ? "0.008" : "0.0045"}
                animate={{ cx: point.x, cy: point.y }}
                transition={{ duration: 0.1, ease: "easeOut" }}
              />
            ))}
          </motion.g>
        );
      })}
    </svg>
  );
}

function gestureLabel(gesture: string) {
  return gesture.toLowerCase().replace(/_/g, " ");
}

export function HandAnalysis({ active, preview, hands, latestGesture, actionReport }: HandAnalysisProps) {
  const hasPreview = active && preview !== null;
  const [previewRatio, setPreviewRatio] = useState<number | null>(null);

  return (
    <section className="kyra-hand-analysis" aria-labelledby="hand-analysis-title">
      <div className="kyra-hand-analysis__heading">
        <div>
          <p className="kyra-dashboard__eyebrow">Local vision system</p>
          <h2 id="hand-analysis-title">Hand analysis</h2>
        </div>
        <span className={`kyra-hand-analysis__status${hands.length ? " kyra-hand-analysis__status--tracking" : ""}`}>
          <span aria-hidden="true" />
          {active ? hands.length ? "Tracking" : "Searching" : "Camera off"}
        </span>
      </div>

      <div className="kyra-hand-analysis__body">
        <div
          className={`kyra-hand-analysis__preview${hands.length ? " kyra-hand-analysis__preview--tracking" : ""}`}
          style={previewRatio ? { aspectRatio: previewRatio } : undefined}
          aria-label="Live camera preview with MediaPipe hand landmarks"
        >
          {hasPreview ? <img src={preview} alt="Local live camera preview" onLoad={(event) => {
            const image = event.currentTarget;
            if (image.naturalHeight) setPreviewRatio(image.naturalWidth / image.naturalHeight);
          }} /> : null}
          {hasPreview ? <HandOverlay hands={hands} /> : <p>{active ? "Waiting for a camera frame…" : "Start the camera to begin local hand analysis."}</p>}
          {hasPreview ? <span className="kyra-hand-analysis__live-label">LIVE <i /> LOCAL</span> : null}
          {hasPreview && hands.length ? <span className="kyra-hand-analysis__node-label">LANDMARKS / HAND <b>21</b></span> : null}
        </div>

        <div className="kyra-hand-analysis__telemetry" aria-live="polite">
          <div className="kyra-hand-analysis__metric">
            <span className="kyra-hand-analysis__label">Hands in frame</span>
            <strong>{active ? hands.length : "—"}</strong>
          </div>
          <div className="kyra-hand-analysis__metric">
            <span className="kyra-hand-analysis__label">Latest gesture</span>
            <strong className="kyra-hand-analysis__gesture-value">
              <AnimatePresence mode="wait" initial={false}>
                <motion.span key={latestGesture?.event_id ?? "none"} initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.16 }}>
                  {latestGesture ? gestureLabel(latestGesture.gesture) : "—"}
                </motion.span>
              </AnimatePresence>
            </strong>
          </div>
          <div className="kyra-hand-analysis__metric kyra-hand-analysis__metric--confidence">
            <span className="kyra-hand-analysis__label">Gesture confidence</span>
            <strong>{latestGesture ? `${Math.round(latestGesture.confidence * 100)}%` : "—"}</strong>
            {latestGesture ? <span className="kyra-hand-analysis__confidence-track"><motion.i initial={false} animate={{ width: `${latestGesture.confidence * 100}%` }} transition={{ duration: 0.24, ease: "easeOut" }} /></span> : null}
          </div>
          <p className="kyra-hand-analysis__note">Landmarks are processed on this agent. Confidence is shown only after a gesture is recognized.</p>
        </div>
      </div>

      <AnimatePresence initial={false}>
        {actionReport ? <motion.p key={actionReport} className="kyra-hand-analysis__report" role="status" initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -3 }} transition={{ duration: 0.18 }}>{actionReport}</motion.p> : null}
      </AnimatePresence>
    </section>
  );
}
