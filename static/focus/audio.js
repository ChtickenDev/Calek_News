let ctx = null;

function getCtx() {
  if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (ctx.state === 'suspended') ctx.resume();
  return ctx;
}

function tone(freq, type, start, duration, gainPeak, fadeOut = true) {
  const ac = getCtx();
  const osc = ac.createOscillator();
  const gain = ac.createGain();
  osc.connect(gain);
  gain.connect(ac.destination);
  osc.type = type;
  osc.frequency.setValueAtTime(freq, start);
  gain.gain.setValueAtTime(0, start);
  gain.gain.linearRampToValueAtTime(gainPeak, start + 0.02);
  if (fadeOut) gain.gain.exponentialRampToValueAtTime(0.001, start + duration);
  osc.start(start);
  osc.stop(start + duration + 0.05);
}

export function initAudio() {
  getCtx();
}

export function playLeafGrow() {
  const ac = getCtx();
  const t = ac.currentTime;
  tone(880, 'sine', t, 0.3, 0.04);
  tone(1320, 'sine', t + 0.05, 0.2, 0.02);
}

export function playBranchGrow() {
  const ac = getCtx();
  const t = ac.currentTime;
  tone(220, 'sine', t, 0.4, 0.05);
  tone(330, 'sine', t + 0.1, 0.3, 0.03);
}

export function playSessionEnd() {
  const ac = getCtx();
  const t = ac.currentTime;
  // Pentatonic arpeggio
  const notes = [261.6, 329.6, 392, 523.3, 659.3];
  notes.forEach((f, i) => {
    tone(f, 'sine', t + i * 0.18, 1.2, 0.12);
    tone(f * 2, 'sine', t + i * 0.18, 0.8, 0.03);
  });
  // Low resonance
  tone(130.8, 'sine', t, 2, 0.08);
}

export function playAbandon() {
  const ac = getCtx();
  const t = ac.currentTime;
  tone(300, 'sawtooth', t, 0.3, 0.06);
  tone(250, 'sawtooth', t + 0.15, 0.4, 0.05);
  tone(200, 'sawtooth', t + 0.3, 0.5, 0.04);
}

export function playPrune() {
  const ac = getCtx();
  const t = ac.currentTime;
  tone(600, 'sine', t, 0.15, 0.08);
  tone(400, 'sine', t + 0.1, 0.2, 0.05);
}

export function playTickle() {
  const ac = getCtx();
  const t = ac.currentTime;
  tone(1200, 'sine', t, 0.08, 0.03);
}
