// RoadIQ Voice — AudioWorklet processor for mic capture.
// Runs on the audio rendering thread. Receives Float32 mic samples at the
// browser's native sample rate (audioContext.sampleRate, e.g. 48000),
// downsamples to 16kHz, converts to PCM16, and posts raw bytes back to the
// main thread for sending over the WebSocket to voice_server.py.

class MicCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.inputSampleRate = options.processorOptions.inputSampleRate;
    this.targetSampleRate = 16000;
    this.ratio = this.inputSampleRate / this.targetSampleRate;
    this._carry = [];
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;
    const channel = input[0];

    // Simple linear-interpolation downsample to 16kHz
    this._carry.push(...channel);
    const outLength = Math.floor(this._carry.length / this.ratio);
    if (outLength <= 0) return true;

    const pcm16 = new Int16Array(outLength);
    for (let i = 0; i < outLength; i++) {
      const srcIndex = i * this.ratio;
      const idx0 = Math.floor(srcIndex);
      const idx1 = Math.min(idx0 + 1, this._carry.length - 1);
      const frac = srcIndex - idx0;
      const sample = this._carry[idx0] * (1 - frac) + this._carry[idx1] * frac;
      const clamped = Math.max(-1, Math.min(1, sample));
      pcm16[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
    }

    // Keep leftover samples that didn't map to a full output sample
    this._carry = this._carry.slice(Math.floor(outLength * this.ratio));

    this.port.postMessage(pcm16.buffer, [pcm16.buffer]);
    return true;
  }
}

registerProcessor('mic-capture-processor', MicCaptureProcessor);
