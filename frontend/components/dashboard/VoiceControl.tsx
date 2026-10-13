import { AnimatePresence, motion } from "motion/react";
import type { Intent } from "../../types/contracts";
import { StateTransition } from "../motion/StateTransition";
import { GlassPanel } from "../ui/GlassPanel";
import { NeumorphicButton } from "../ui/NeumorphicButton";

export type VoiceHistoryItem = {
  id: string;
  transcript: string;
  timestamp: string;
};

type VoiceControlProps = {
  microphoneActive: boolean;
  microphoneAvailable: boolean;
  microphoneEnabled: boolean;
  transcript: string | null;
  phase: string | null;
  language: string | null;
  message: string | null;
  intent: Intent | null;
  history: VoiceHistoryItem[];
  busy: boolean;
  onToggle: () => void;
};

const unknown = "Not reported";

function timeLabel(timestamp: string) {
  return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date(timestamp));
}

function statusLabel(microphoneActive: boolean, microphoneAvailable: boolean, microphoneEnabled: boolean, phase: string | null) {
  if (!microphoneEnabled) return "Disabled";
  if (!microphoneAvailable) return "Unsupported";
  if (phase === "processing") return "Processing";
  if (phase === "understanding") return "Understanding";
  if (phase === "error" || phase === "unrecognized") return "Needs attention";
  if (microphoneActive) return "Listening";
  return "Off";
}

function statusMotionState(microphoneActive: boolean, microphoneAvailable: boolean, microphoneEnabled: boolean, phase: string | null) {
  if (!microphoneEnabled) return "offline" as const;
  if (!microphoneAvailable || phase === "error" || phase === "unrecognized") return "error" as const;
  if (phase === "processing" || phase === "understanding") return "thinking" as const;
  return microphoneActive ? "listening" as const : "idle" as const;
}

function languageLabel(language: string | null) {
  if (language === "ur") return "Urdu";
  if (language === "en") return "English";
  return language ?? "Auto detect";
}

export function VoiceControl({ microphoneActive, microphoneAvailable, microphoneEnabled, transcript, phase, language, message, intent, history, busy, onToggle }: VoiceControlProps) {

  return (
    <GlassPanel className="kyra-voice-control" tone="strong" aria-labelledby="voice-control-title">
      <div className="kyra-dashboard__panel-heading">
        <div>
          <p className="kyra-dashboard__eyebrow">Voice control</p>
          <h2 id="voice-control-title">Listen and understand</h2>
        </div>
        <StateTransition className="kyra-dashboard__state" state={statusMotionState(microphoneActive, microphoneAvailable, microphoneEnabled, phase)}>
          {statusLabel(microphoneActive, microphoneAvailable, microphoneEnabled, phase)}
        </StateTransition>
      </div>

      <div className="kyra-voice-control__live">
        <div>
          <span className="kyra-voice-control__label">Latest transcript</span>
          <p className="kyra-voice-control__transcript"><AnimatePresence mode="wait" initial={false}><motion.span key={transcript ?? "empty-transcript"} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -3 }} transition={{ duration: 0.16 }}>{transcript ?? "No transcript reported."}</motion.span></AnimatePresence></p>
          <small>Language: {languageLabel(language)}</small>
        </div>
        <div>
          <span className="kyra-voice-control__label">Validated intent</span>
          <p className="kyra-voice-control__intent"><AnimatePresence mode="wait" initial={false}><motion.span key={intent?.name ?? "empty-intent"} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -3 }} transition={{ duration: 0.16 }}>{intent?.name ?? "No intent reported."}</motion.span></AnimatePresence></p>
          <small>{intent ? `${Math.round(intent.confidence * 100)}% confidence` : unknown}</small>
        </div>
      </div>
      {message ? <p className="kyra-voice-control__message" aria-live="polite">{message}</p> : null}

      <div className="kyra-voice-control__footer">
        <NeumorphicButton disabled={busy || !microphoneAvailable || !microphoneEnabled} onClick={onToggle} size="sm" tone={microphoneActive ? "danger" : "primary"}>
          {busy ? "Updating..." : microphoneActive ? "Stop listening" : "Start listening"}
        </NeumorphicButton>
        <dl className="kyra-voice-control__settings">
          <div><dt>Speech-to-text</dt><dd>Local Faster Whisper</dd></div>
          <div><dt>Language</dt><dd>{languageLabel(language)}</dd></div>
          <div><dt>Listening mode</dt><dd>Continuous</dd></div>
        </dl>
      </div>

      <div className="kyra-voice-control__history">
        <div className="kyra-dashboard__panel-heading"><span className="kyra-voice-control__label">Session command history</span><span className="kyra-dashboard__state">{history.length} reported</span></div>
        {history.length === 0 ? <p className="kyra-dashboard__empty">No voice commands reported.</p> : <motion.ul layout initial={false}>
          <AnimatePresence initial={false}>
            {history.map((item) => <motion.li key={item.id} layout="position" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.18 }}><span>{item.transcript}</span><time dateTime={item.timestamp}>{timeLabel(item.timestamp)}</time></motion.li>)}
          </AnimatePresence>
        </motion.ul>}
      </div>
    </GlassPanel>
  );
}
