import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { after, test } from "node:test";
import ts from "typescript";

const browserVoiceSource = await readFile(new URL("../lib/browser-voice.ts", import.meta.url), "utf8");
const compiledBrowserVoice = ts.transpileModule(
  browserVoiceSource.replaceAll("import.meta.env.BASE_URL", '"/"'),
  { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } },
).outputText;
const modulePath = join(tmpdir(), `kyra-browser-voice-${process.pid}-${Date.now()}.mjs`);
await writeFile(modulePath, compiledBrowserVoice, "utf8");
const { startBrowserVoice } = await import(pathToFileURL(modulePath).href);
after(async () => import("node:fs/promises").then(({ rm }) => rm(modulePath, { force: true })));

class FakeTrack extends EventTarget {
  kind = "audio";
  readyState = "live";
  muted = false;
  stopped = false;

  stop() {
    this.stopped = true;
    this.readyState = "ended";
  }
}

class FakeNode {
  disconnected = false;
  connect() {}
  disconnect() { this.disconnected = true; }
}

class FakeAudioContext {
  static instances = [];
  sampleRate = 48_000;
  state = "running";
  destination = {};
  audioWorklet = { addModule: async () => undefined };
  closed = false;

  constructor() { FakeAudioContext.instances.push(this); }
  async resume() { this.state = "running"; }
  async close() { this.closed = true; this.state = "closed"; }
  createMediaStreamSource() { this.source = new FakeNode(); return this.source; }
  createGain() { this.gain = Object.assign(new FakeNode(), { gain: { value: 1 } }); return this.gain; }
}

class FakeAudioWorkletNode extends FakeNode {
  static instances = [];
  constructor() {
    super();
    this.port = { closed: false, onmessage: null, close() { this.closed = true; } };
    FakeAudioWorkletNode.instances.push(this);
  }
}

function installBrowser(getUserMedia) {
  FakeAudioContext.instances = [];
  FakeAudioWorkletNode.instances = [];
  const descriptors = new Map(["window", "navigator", "AudioContext", "AudioWorkletNode"].map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const windowValue = {
    isSecureContext: true,
    AudioContext: FakeAudioContext,
    AudioWorkletNode: FakeAudioWorkletNode,
    btoa: globalThis.btoa.bind(globalThis),
  };
  Object.defineProperty(globalThis, "window", { configurable: true, value: windowValue });
  Object.defineProperty(globalThis, "AudioContext", { configurable: true, value: FakeAudioContext });
  Object.defineProperty(globalThis, "AudioWorkletNode", { configurable: true, value: FakeAudioWorkletNode });
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { mediaDevices: { getUserMedia } },
  });
  return () => {
    for (const [key, descriptor] of descriptors) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else Reflect.deleteProperty(globalThis, key);
    }
  };
}

function makeStream(track = new FakeTrack()) {
  return {
    track,
    getAudioTracks: () => [track],
    getTracks: () => [track],
  };
}

test("microphone permission success enters listening and stop releases every capture resource", async () => {
  const stream = makeStream();
  const states = [];
  const restore = installBrowser(async () => stream);
  try {
    const session = await startBrowserVoice(() => undefined, () => undefined, (state) => states.push(state));
    assert.deepEqual(states, ["requesting_permission", "ready", "listening"]);
    session.stop();
    assert.equal(stream.track.stopped, true);
    assert.equal(FakeAudioContext.instances[0].source.disconnected, true);
    assert.equal(FakeAudioContext.instances[0].gain.disconnected, true);
    assert.equal(FakeAudioWorkletNode.instances[0].disconnected, true);
    assert.equal(FakeAudioWorkletNode.instances[0].port.closed, true);
    assert.equal(FakeAudioContext.instances[0].closed, true);
    assert.equal(states.at(-1), "disconnected");
  } finally {
    restore();
  }
});

test("microphone permission denial reports an error without opening a stream", async () => {
  const states = [];
  const restore = installBrowser(async () => { throw new DOMException("permission denied", "NotAllowedError"); });
  try {
    await assert.rejects(
      startBrowserVoice(() => undefined, () => undefined, (state) => states.push(state)),
      /Microphone permission was denied/,
    );
    assert.deepEqual(states, ["requesting_permission", "error"]);
  } finally {
    restore();
  }
});

test("microphone device failure reports an error", async () => {
  const states = [];
  const restore = installBrowser(async () => { throw new DOMException("device busy", "NotReadableError"); });
  try {
    await assert.rejects(
      startBrowserVoice(() => undefined, () => undefined, (state) => states.push(state)),
      /device busy/,
    );
    assert.deepEqual(states, ["requesting_permission", "error"]);
  } finally {
    restore();
  }
});

test("microphone mute, unmute, AudioContext suspension, and utterance update capture state", async () => {
  const stream = makeStream();
  const states = [];
  const utterances = [];
  const restore = installBrowser(async () => stream);
  try {
    const session = await startBrowserVoice((audio) => utterances.push(audio), () => undefined, (state) => states.push(state));
    stream.track.muted = true;
    stream.track.dispatchEvent(new Event("mute"));
    stream.track.muted = false;
    stream.track.dispatchEvent(new Event("unmute"));
    const context = FakeAudioContext.instances[0];
    context.state = "suspended";
    context.onstatechange();
    context.state = "running";
    context.onstatechange();
    FakeAudioWorkletNode.instances[0].port.onmessage({ data: new Float32Array(12_000).fill(0.2) });
    await new Promise((resolve) => setImmediate(resolve));
    assert.ok(states.includes("ready"));
    assert.equal(states.at(-1), "listening");
    assert.equal(utterances.length, 1);
    assert.ok(utterances[0].length > 0);
    session.stop();
  } finally {
    restore();
  }
});

test("captured utterances are submitted serially and a failed callback does not block later audio", async () => {
  const restore = installBrowser(async () => makeStream());
  let releaseFirst;
  const firstGate = new Promise((resolve) => { releaseFirst = resolve; });
  const calls = [];
  try {
    const session = await startBrowserVoice(async () => {
      const index = calls.filter((item) => item.startsWith("start:")).length + 1;
      calls.push(`start:${index}`);
      if (index === 1) await firstGate;
      if (index === 2) throw new Error("transcription failed");
      calls.push(`done:${index}`);
    }, () => calls.push("error"));
    const processor = FakeAudioWorkletNode.instances[0];
    const data = new Float32Array(12_000).fill(0.2);
    processor.port.onmessage({ data });
    processor.port.onmessage({ data });
    processor.port.onmessage({ data });
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(calls, ["start:1"]);
    releaseFirst();
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(calls, ["start:1", "done:1", "start:2", "error", "start:3", "done:3"]);
    session.stop();
  } finally {
    restore();
  }
});

test("microphone can be explicitly stopped and started again", async () => {
  const streams = [makeStream(), makeStream()];
  let requests = 0;
  const restore = installBrowser(async () => streams[requests++]);
  try {
    const first = await startBrowserVoice(() => undefined, () => undefined);
    first.stop();
    const second = await startBrowserVoice(() => undefined, () => undefined);
    assert.equal(requests, 2);
    second.stop();
    assert.deepEqual(streams.map((stream) => stream.track.stopped), [true, true]);
  } finally {
    restore();
  }
});

test("an ended microphone track releases processing and requests reconnection", async () => {
  const stream = makeStream();
  const states = [];
  const errors = [];
  const restore = installBrowser(async () => stream);
  try {
    await startBrowserVoice(() => undefined, (message) => errors.push(message), (state) => states.push(state));
    stream.track.readyState = "ended";
    stream.track.dispatchEvent(new Event("ended"));
    assert.equal(states.at(-1), "error");
    assert.match(errors[0], /stream ended/);
    assert.equal(FakeAudioContext.instances[0].closed, true);
    assert.equal(FakeAudioWorkletNode.instances[0].port.closed, true);
  } finally {
    restore();
  }
});
