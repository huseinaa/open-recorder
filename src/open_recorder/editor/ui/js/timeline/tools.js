// Mouse work on the timeline. The four tools: Selection (V) moves and trims, Razor (C) splits,
// Ripple trim (B) shortens a clip and closes the gap, Hand (H) pans. Dragging shows the result
// live; the op is sent once, on release, so one drag is one undo step.
import { addMedia, addRecording, pause, seek, select } from '../actions.js';
import { edit } from '../bridge.js';
import { h, toast } from '../dom.js';
import { clipEnd, findClip, linkedIds, set, state } from '../store.js';
import { onBinDrag } from '../bindrag.js';
import { laneTops, snap, tAt, xAt } from './geometry.js';

export function attach({ scroll, content, lanes, ruler, playheadHead }) {
  const point = e => {
    const r = content.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top - ruler.offsetHeight };
  };
  const laneAt = y => laneTops().find(l => y >= l.top && y < l.top + l.h) || null;
  const marker = cls => { const el = h('div', { class: cls }); content.append(el); return el; };

  // ---------- scrubbing: the ruler and the playhead head ----------
  const scrub = e => {
    pause();
    const go = ev => seek(tAt(point(ev).x));
    go(e);
    const move = ev => go(ev);
    const target = e.currentTarget;
    target.setPointerCapture(e.pointerId);
    target.addEventListener('pointermove', move);
    target.addEventListener('pointerup', () => target.removeEventListener('pointermove', move), { once: true });
  };
  ruler.addEventListener('pointerdown', scrub);
  playheadHead.addEventListener('pointerdown', e => { e.stopPropagation(); scrub(e); });

  // ---------- the razor preview line ----------
  let razor = null;
  lanes.addEventListener('pointermove', e => {
    if (state.tool !== 'razor') { razor && razor.remove(); razor = null; return; }
    razor ||= marker('razor-line');
    const s = snap([tAt(point(e).x)], new Set());
    razor.style.left = `${xAt(s ? s.at : tAt(point(e).x))}px`;
  });
  lanes.addEventListener('pointerleave', () => { razor && razor.remove(); razor = null; });

  // ---------- press ----------
  lanes.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    const p = point(e);
    if (state.tool === 'hand') return pan(e);
    const clipEl = e.target.closest('.clip');
    if (!clipEl) {
      pause();
      seek(tAt(p.x));
      if (!e.shiftKey) select([]);
      return;
    }
    const id = clipEl.dataset.clip;
    const { lane, clip } = findClip(id);
    if (!clip) return;
    if (state.tool === 'razor') {
      const s = snap([tAt(p.x)], new Set());
      edit([{ op: 'split', t: s ? s.at : tAt(p.x), clips: [id], link: state.link }], 'Split');
      return;
    }
    if (lane.locked) return toast(`The ${lane.name} lane is locked.`);
    if (!state.selection.includes(id) || !e.shiftKey) select(state.link ? linkedIds(id) : [id], e.shiftKey, id);
    else set({ focus: id });
    const edge = e.target.dataset.edge;
    if (edge) trim(e, clipEl, lane, clip, edge);
    else moveClip(e, clipEl, lane, clip);
  });

  function pan(e) {
    const x0 = e.clientX, y0 = e.clientY, l0 = scroll.scrollLeft, t0 = scroll.scrollTop;
    lanes.setPointerCapture(e.pointerId);
    const move = ev => { scroll.scrollLeft = l0 - (ev.clientX - x0); scroll.scrollTop = t0 - (ev.clientY - y0); };
    lanes.addEventListener('pointermove', move);
    lanes.addEventListener('pointerup', () => lanes.removeEventListener('pointermove', move), { once: true });
  }

  function moveClip(e, clipEl, lane, clip) {
    const ids = state.link ? linkedIds(clip.id) : [clip.id];
    const els = ids.map(id => content.querySelector(`.clip[data-clip="${id}"]`)).filter(Boolean);
    const clips = ids.map(id => findClip(id).clip);
    const exclude = new Set(ids);
    const x0 = point(e).x, startLeft = els.map(el => parseFloat(el.style.left));
    let delta = 0, destLane = lane, moved = false, line = null;
    lanes.setPointerCapture(e.pointerId);
    const move = ev => {
      const p = point(ev);
      if (!moved && Math.abs(p.x - x0) < 3) return;
      moved = true;
      delta = (p.x - x0) / state.pps;
      delta = Math.max(delta, -Math.min(...clips.map(c => c.start)));
      const s = snap(clips.flatMap(c => [c.start + delta, clipEnd(c) + delta]), exclude);
      if (s) delta += s.delta;
      line && line.remove();
      line = s ? marker('snap-line') : null;
      if (line) line.style.left = `${xAt(s.at)}px`;
      els.forEach((el, i) => { el.style.left = `${startLeft[i] + delta * state.pps}px`; el.classList.add('ghost'); });
      const over = laneAt(p.y);
      lanes.querySelectorAll('.lane').forEach(r => r.classList.remove('drop-target', 'drop-bad'));
      destLane = over && over.lane.kind === lane.kind && !over.lane.locked ? over.lane : lane;
      const row = lanes.querySelector(`.lane[data-lane="${destLane.id}"]`);
      if (row && destLane !== lane) { row.classList.add('drop-target'); row.append(clipEl); }
    };
    const up = () => {
      lanes.removeEventListener('pointermove', move);
      line && line.remove();
      if (!moved) return;
      edit([{ op: 'move', clip: clip.id, start: clip.start + delta, lane: destLane.id !== lane.id ? destLane.id : null,
        link: state.link }], 'Move');
    };
    lanes.addEventListener('pointermove', move);
    lanes.addEventListener('pointerup', up, { once: true });
  }

  function trim(e, clipEl, lane, clip, edge) {
    const ripple = state.tool === 'ripple';
    const x0 = point(e).x, left0 = parseFloat(clipEl.style.left), width0 = parseFloat(clipEl.style.width);
    const exclude = new Set(state.link ? linkedIds(clip.id) : [clip.id]);
    const startT = edge === 'l' ? clip.start : clipEnd(clip);
    let edgeT = startT, line = null;
    lanes.setPointerCapture(e.pointerId);
    const move = ev => {
      edgeT = startT + (point(ev).x - x0) / state.pps;
      if (edge === 'l') edgeT = Math.min(Math.max(edgeT, clip.start - clip.src_in, 0), clipEnd(clip) - 0.05);
      else edgeT = Math.max(edgeT, clip.start + 0.05);
      const s = snap([edgeT], exclude);
      if (s) edgeT = s.at;
      line && line.remove();
      line = s ? marker('snap-line') : null;
      if (line) line.style.left = `${xAt(s.at)}px`;
      const dx = (edgeT - startT) * state.pps;
      if (edge === 'l') { clipEl.style.left = `${left0 + dx}px`; clipEl.style.width = `${width0 - dx}px`; }
      else clipEl.style.width = `${Math.max(3, width0 + dx)}px`;
    };
    const up = () => {
      lanes.removeEventListener('pointermove', move);
      line && line.remove();
      if (Math.abs(edgeT - startT) < 1e-3) return;
      const shorter = edge === 'l' ? edgeT > startT : edgeT < startT;
      if (ripple && shorter) {
        const laneIds = [...new Set([...exclude].map(id => findClip(id).lane?.id).filter(Boolean))];
        const [a, b] = edge === 'l' ? [startT, edgeT] : [edgeT, startT];
        edit([{ op: 'cut_range', start: a, end: b, lanes: laneIds, ripple: true }], 'Ripple trim');
      } else {
        edit([{ op: 'trim', clip: clip.id, [edge === 'l' ? 'start' : 'end']: edgeT, link: state.link }], 'Trim');
      }
    };
    lanes.addEventListener('pointermove', move);
    lanes.addEventListener('pointerup', up, { once: true });
  }

  // ---------- drops from the Project panel (anywhere on the timeline, see bindrag.js) ----------
  const inside = (x, y) => {
    const r = scroll.getBoundingClientRect();
    return x >= r.left && x <= r.right && y >= r.top && y <= r.bottom;
  };
  const offBinDrag = onBinDrag(({ phase, payload, x, y }) => {
    lanes.querySelectorAll('.lane').forEach(r => r.classList.remove('drop-target'));
    const over = inside(x, y);
    scroll.classList.toggle('drop-zone', phase === 'move' && over);
    if (!over) return;
    const p = point({ clientX: x, clientY: y });
    if (phase === 'move') {
      const l = laneAt(p.y);
      if (l) lanes.querySelector(`.lane[data-lane="${l.lane.id}"]`)?.classList.add('drop-target');
    } else if (phase === 'drop') {
      placeDrop(payload, p);
    }
  });

  // files dropped from Explorer land here too when they fall on the timeline
  const onFiles = ev => {
    const { keys, x, y } = ev.detail;
    const r = lanes.getBoundingClientRect();
    if (x < r.left || x > r.right || y < r.top || y > r.bottom) return;
    const p = point({ clientX: x, clientY: y });
    placeDrop({ media: keys[0] }, p);
  };
  window.addEventListener('or-files-added', onFiles);

  function placeDrop(item, p) {
    let t = Math.max(0, tAt(p.x));
    const s = snap([t], new Set());
    if (s) t = s.at;
    const over = laneAt(p.y);
    if (item.recording) addRecording(item.recording, t);
    else addMedia(item.media, over ? over.lane.id : null, t);
  }

  return () => {
    window.removeEventListener('or-files-added', onFiles);
    offBinDrag();
  };
}

