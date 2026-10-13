class KyraVoiceCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.preRoll = [];
    this.preRollSamples = 0;
    this.samples = [];
    this.sampleCount = 0;
    this.silenceSamples = 0;
    this.active = false;
    this.silenceLimit = Math.round(globalThis.sampleRate * 0.65);
    this.maximumSamples = globalThis.sampleRate * 8;
    this.preRollLimit = Math.round(globalThis.sampleRate * 0.2);
  }

  process(inputs, outputs) {
    const input = inputs[0]?.[0];
    const output = outputs[0]?.[0];
    if (output) output.fill(0);
    if (!input?.length) return true;

    let squareSum = 0;
    for (let index = 0; index < input.length; index += 1) squareSum += input[index] * input[index];
    const voiced = Math.sqrt(squareSum / input.length) >= 0.012;
    const frame = input.slice();

    if (voiced) {
      if (!this.active) {
        this.samples = this.preRoll;
        this.sampleCount = this.preRollSamples;
        this.preRoll = [];
        this.preRollSamples = 0;
      }
      this.active = true;
      this.silenceSamples = 0;
      this.samples.push(frame);
      this.sampleCount += frame.length;
    } else if (this.active) {
      this.samples.push(frame);
      this.sampleCount += frame.length;
      this.silenceSamples += frame.length;
    } else {
      this.preRoll.push(frame);
      this.preRollSamples += frame.length;
      while (this.preRollSamples > this.preRollLimit && this.preRoll.length) {
        this.preRollSamples -= this.preRoll.shift().length;
      }
    }

    if (this.active && (this.silenceSamples >= this.silenceLimit || this.sampleCount >= this.maximumSamples)) {
      if (this.sampleCount >= Math.round(globalThis.sampleRate * 0.25)) {
        const utterance = new Float32Array(this.sampleCount);
        let offset = 0;
        for (const samples of this.samples) {
          utterance.set(samples, offset);
          offset += samples.length;
        }
        this.port.postMessage(utterance, [utterance.buffer]);
      }
      this.samples = [];
      this.sampleCount = 0;
      this.silenceSamples = 0;
      this.active = false;
    }
    return true;
  }
}

registerProcessor("kyra-voice-capture", KyraVoiceCaptureProcessor);
