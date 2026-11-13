// The time ruler, drawn only for the part of the timeline in view (so any zoom works).
import { state } from '../store.js';
import { PAD, RULER_H } from './geometry.js';

const STEPS = [1 / 30, 0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800];

function label(t, step) {
  const m = Math.floor(t / 60), s = t % 60;
  if (step < 1) return `${m}:${s.toFixed(step < 0.5 ? 2 : 1).padStart(step < 0.5 ? 5 : 4, '0')}`;
  return `${m}:${String(Math.round(s)).padStart(2, '0')}`;
}

export function drawRuler(canvas, scrollLeft, width) {
  const dpr = window.devicePixelRatio || 1;
  canvas.style.left = `${scrollLeft}px`;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${RULER_H}px`;
  canvas.width = Math.ceil(width * dpr);
  canvas.height = RULER_H * dpr;
  const g = canvas.getContext('2d');
  g.scale(dpr, dpr);
  g.clearRect(0, 0, width, RULER_H);
  const pps = state.pps;
  const step = STEPS.find(s => s * pps >= 80) || STEPS[STEPS.length - 1];
  const minor = step / 5;
  const t0 = Math.max(0, (scrollLeft - PAD) / pps);
  const t1 = (scrollLeft + width - PAD) / pps;
  const css = getComputedStyle(document.documentElement);
  g.strokeStyle = css.getPropertyValue('--line-strong').trim() || '#3a3d43';
  g.fillStyle = css.getPropertyValue('--muted').trim() || '#8e929a';
  g.font = '11px "Segoe UI Variable Text", "Segoe UI", sans-serif';
  g.textBaseline = 'top';
  g.beginPath();
  for (let t = Math.floor(t0 / minor) * minor; t <= t1 + minor; t += minor) {
    const x = Math.round(PAD + t * pps - scrollLeft) + 0.5;
    const major = Math.abs(t / step - Math.round(t / step)) < 1e-6;
    g.moveTo(x, major ? 12 : 20);
    g.lineTo(x, RULER_H);
    if (major) g.fillText(label(Math.round(t / step) * step, step), x + 4, 3);
  }
  g.stroke();
}
