// Commands shared by buttons, shortcuts, the inspector and the timeline.
import { call, edit } from './bridge.js';
import { clamp, toast } from './dom.js';
import { focusClip, loadState, projectDuration, set, state } from './store.js';

export const ctx = { player: null };   // the monitor's player, set when the editor opens

export function seek(t) {
  t = clamp(t, 0, Math.max(projectDuration(), 0));
  set({ playhead: t });
  ctx.player && ctx.player.seek(t);
}

export function togglePlay() { ctx.player && ctx.player.toggle(); }
export function pause() { ctx.player && ctx.player.pause(); }

export function step(frames) {
  const fps = state.project?.sequence?.fps || 30;
  pause();
  seek(Math.round(state.playhead * fps + frames) / fps);
}

export async function undo() {
  try {
    const res = await call('undo');
    loadState(res.state);
    if (res.label) toast(`Undone: ${res.label}`);
  } catch (e) { /* toast shown */ }
}

export async function redo() {
  try {
    const res = await call('redo');
    loadState(res.state);
    if (res.label) toast(`Redone: ${res.label}`);
  } catch (e) { /* toast shown */ }
}

export function select(ids, add = false, focus = null) {
  set({ selection: add ? [...new Set([...state.selection, ...ids])] : ids, focus: focus ?? ids[0] ?? null });
}

export async function splitAtPlayhead() {
  const clips = state.selection.length ? state.selection : null;
  await edit([{ op: 'split', t: state.playhead, clips, link: state.link }], 'Split');
}

export async function deleteSelected(ripple = false) {
  if (!state.selection.length) return;
  const op = ripple ? 'ripple_delete' : 'delete';
  const notes = await edit([{ op, clips: state.selection, link: state.link }], ripple ? 'Ripple delete' : 'Delete');
  if (notes && ripple && notes[0] && notes[0].includes('gap stays')) toast('Deleted. The gap stays because other lanes have clips there.');
  set({ selection: [] });
}

export async function addRecording(id, start = null) {
  return edit([{ op: 'add_recording', recording: id, start }], 'Add take');
}

export async function addMedia(key, lane = null, start = null) {
  return edit([{ op: 'add_clip', media: key, lane, start }], 'Add clip');
}

export async function record() {
  try {
    const res = await call('record');
    if (res.started) set({ recording: true });
    else toast(res.message || 'The recorder is already open');
  } catch (e) { /* toast shown */ }
}

export function selectedClip() {
  return focusClip();
}

export function zoom(factor, anchorTime = null) {
  set({ pps: clamp(state.pps * factor, 4, 480), zoomAnchor: anchorTime });
}
