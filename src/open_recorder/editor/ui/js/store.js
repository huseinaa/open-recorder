// The page's state. Python owns the project; the page holds the latest copy plus view state
// (selection, playhead, zoom, tool). Panels subscribe and re-render on the keys they care about.
export const state = {
  screen: 'boot',          // boot, start, editor
  boot: null,              // what boot() returned: root, projects, version
  project: null, media: {}, folder: '', name: '', exports: '', undo: null, redo: null,
  selection: [],           // clip ids
  focus: null,             // the clip clicked last: Effect Controls and the canvas handles show it
  playhead: 0, playing: false,
  pps: 60, tool: 'select', snap: true, link: true,
  sideTab: 'inspector',
  ai: null, chat: [], aiBusy: false,
  transcripts: {},         // media key -> {state, progress, message}
  waves: {},               // media key -> peaks
  recording: false,
  safe: false,
  fresh: null,             // a take id to highlight in the media bin
};

const listeners = new Set();
let pending = new Set();
let frame = 0;

export function set(patch) {
  Object.assign(state, patch);
  for (const k of Object.keys(patch)) pending.add(k);
  if (!frame) frame = requestAnimationFrame(flush);
}

function flush() {
  frame = 0;
  const keys = pending;
  pending = new Set();
  for (const fn of listeners) {
    try { fn(keys); } catch (e) { console.error(e); }
  }
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function loadState(s) {
  if (!s) return;
  const ids = new Set();
  for (const lane of s.project.lanes) for (const c of lane.clips) ids.add(c.id);
  const transcripts = { ...state.transcripts };
  for (const [k, m] of Object.entries(s.media)) if (m.transcript && !transcripts[k]) transcripts[k] = m.transcript;
  set({ project: s.project, media: s.media, folder: s.folder, name: s.name, exports: s.exports, undo: s.undo,
    redo: s.redo, selection: state.selection.filter(id => ids.has(id)), transcripts });
}

// ---------- lookups ----------
export function clipEnd(c) { return c.start + (c.src_out - c.src_in); }

export function projectDuration(p = state.project) {
  if (!p) return 0;
  let end = 0;
  for (const lane of p.lanes) for (const c of lane.clips) end = Math.max(end, clipEnd(c));
  return end;
}

export function findClip(id, p = state.project) {
  if (!p) return {};
  for (const lane of p.lanes) for (const clip of lane.clips) if (clip.id === id) return { lane, clip };
  return {};
}

export function linkedIds(id) {
  const { clip } = findClip(id);
  if (!clip) return [];
  if (!clip.link || !state.link) return [id];
  const out = [];
  for (const lane of state.project.lanes) for (const c of lane.clips) if (c.link === clip.link) out.push(c.id);
  return out;
}

// The clip to show in Effect Controls: the focused one, when everything selected is it or linked to it.
export function focusClip() {
  const sel = state.selection;
  if (!sel.length) return {};
  const found = findClip(sel.includes(state.focus) ? state.focus : sel[0]);
  if (!found.clip) return {};
  const group = new Set([found.clip.id]);
  if (found.clip.link) for (const lane of state.project.lanes) for (const c of lane.clips) if (c.link === found.clip.link) group.add(c.id);
  return sel.every(id => group.has(id)) ? found : {};
}

export function canvasSize(p = state.project) {
  return { '16:9': [1920, 1080], '9:16': [1080, 1920], '1:1': [1080, 1080], '4:5': [1080, 1350] }[p?.sequence?.aspect] || [1920, 1080];
}

export function clipKind(lane, clip) {
  if (lane.kind === 'blur') return 'blur';
  if (lane.kind === 'audio' || !clip.video) return 'audio';
  const m = state.media[clip.media];
  if (m?.role === 'camera' || lane.role === 'face') return 'face';
  if (m?.role === 'screen' || lane.role === 'screen') return 'screen';
  return m?.kind === 'image' ? 'image' : 'video';
}
