// Timeline measurements shared by the ruler, lanes, clips and tools.
import { clipEnd, state } from '../store.js';

export const RULER_H = 28;
export const PAD = 12;                      // px before time zero
export const LANE_H = { video: 58, audio: 46, blur: 34 };
export const SNAP_PX = 8;

export const xAt = t => PAD + t * state.pps;
export const tAt = x => Math.max(0, (x - PAD) / state.pps);
export const laneHeight = lane => LANE_H[lane.kind] || 50;

export function laneTops(project = state.project) {
  const out = [];
  let y = 0;
  for (const lane of project?.lanes || []) {
    out.push({ lane, top: y, h: laneHeight(lane) });
    y += laneHeight(lane);
  }
  return out;
}

// Times a moving edge can snap to: every clip edge (except the ones moving), the playhead, zero.
export function snapTargets(exclude = new Set()) {
  const out = [0, state.playhead];
  for (const lane of state.project?.lanes || []) {
    for (const c of lane.clips) {
      if (exclude.has(c.id)) continue;
      out.push(c.start, clipEnd(c));
    }
  }
  return out;
}

// The nearest target to any of the given times, within SNAP_PX: {delta, at} or null.
export function snap(times, exclude) {
  if (!state.snap) return null;
  const tol = SNAP_PX / state.pps;
  let best = null;
  for (const target of snapTargets(exclude)) {
    for (const t of times) {
      const d = target - t;
      if (Math.abs(d) <= tol && (!best || Math.abs(d) < Math.abs(best.delta))) best = { delta: d, at: target };
    }
  }
  return best;
}
