// Moving and resizing a layer right on the canvas: a box with corner handles around the selected
// clip, edges that snap to the canvas edges and centre, and a small bar for mask and fit.
import { edit } from '../bridge.js';
import { h, iconButton } from '../dom.js';
import { canvasSize, focusClip, linkedIds, set, state } from '../store.js';

const SNAP_PX = 8;

export class Handles {
  constructor(overlay, player, getScale) {
    this.overlay = overlay;
    this.player = player;
    this.getScale = getScale;
    overlay.addEventListener('pointerdown', e => this.pick(e));
  }

  target() {
    if (!state.project) return null;
    const { lane, clip } = focusClip();
    if (!clip || lane.kind === 'audio' || !clip.video && lane.kind !== 'blur' || lane.hidden || lane.locked) return null;
    const t = state.playhead;
    const end = clip.start + clip.src_out - clip.src_in;
    if (t < clip.start - 1e-4 || t >= end) return null;
    return { lane, clip };
  }

  render() {
    this.overlay.replaceChildren();
    const found = this.target();
    if (!found) return;
    const { lane, clip } = found;
    const t = this.player.previews.get(clip.id) || clip.transform;
    const [W, H] = canvasSize();
    const s = this.getScale();
    const box = h('div', { class: `sel-box ${t.mask === 'circle' ? 'round' : ''}` },
      ...['nw', 'ne', 'sw', 'se'].map(c => h('div', { class: `hd ${c}`, dataset: { corner: c } })));
    Object.assign(box.style, { left: `${t.x * W * s}px`, top: `${t.y * H * s}px`, width: `${t.w * W * s}px`, height: `${t.h * H * s}px` });
    box.addEventListener('pointerdown', e => this.drag(e, clip, lane, e.target.dataset.corner || null));
    this.overlay.append(box);
    if (lane.kind !== 'blur') this.overlay.append(this.minibar(clip, t, W, H, s));
  }

  minibar(clip, t, W, H, s) {
    const id = clip.id;
    const mask = m => () => edit([{ op: 'set_mask', clips: [id], mask: m }], 'Mask');
    const bar = h('div', { class: 'minibar' },
      iconButton('noMask', 'No mask', mask('none'), { class: t.mask === 'none' ? 'on' : '' }),
      iconButton('circle', 'Circle mask', mask('circle'), { class: t.mask === 'circle' ? 'on' : '' }),
      iconButton('square', 'Square mask', mask('square'), { class: t.mask === 'square' ? 'on' : '' }),
      h('span', { class: 'sep' }),
      iconButton('fit', 'Fit: show the whole picture', () => edit([{ op: 'set_transform', clips: [id], fit: 'contain' }], 'Fit'),
        { class: t.fit === 'contain' ? 'on' : '' }),
      iconButton('fill', 'Fill: cover the box, crop the edges', () => edit([{ op: 'set_transform', clips: [id], fit: 'cover' }], 'Fill'),
        { class: t.fit === 'cover' ? 'on' : '' }),
      h('span', { class: 'sep' }),
      iconButton('reset', 'Back to the default place', () => edit([{ op: 'reset_layout', clips: [id] }], 'Reset layout')));
    const top = t.y * H * s - 40;
    const below = (t.y + t.h) * H * s + 8;
    Object.assign(bar.style, { left: `${Math.max(4, t.x * W * s)}px`, top: `${top > 4 ? top : below}px` });
    return bar;
  }

  pick(e) {
    if (e.target !== this.overlay) return;
    const [W, H] = canvasSize();
    const s = this.getScale();
    const r = this.overlay.getBoundingClientRect();
    const x = (e.clientX - r.left) / s / W, y = (e.clientY - r.top) / s / H;
    const t = state.playhead;
    for (const lane of state.project?.lanes || []) {     // top lane first
      if (lane.kind === 'audio' || lane.hidden) continue;
      for (const c of lane.clips) {
        const end = c.start + c.src_out - c.src_in;
        const b = c.transform;
        if (t >= c.start && t < end && x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h) {
          set({ selection: state.link ? linkedIds(c.id) : [c.id], focus: c.id });
          return;
        }
      }
    }
    set({ selection: [] });
  }

  drag(e, clip, lane, corner) {
    e.preventDefault();
    e.stopPropagation();
    const [W, H] = canvasSize();
    const s = this.getScale();
    const start = { ...clip.transform };
    const x0 = e.clientX, y0 = e.clientY;
    const free = lane.kind === 'blur' || e.shiftKey;
    const aspect = (start.w * W) / (start.h * H);
    let current = start;
    const target = e.currentTarget;
    target.setPointerCapture(e.pointerId);
    const move = ev => {
      const dx = (ev.clientX - x0) / s / W, dy = (ev.clientY - y0) / s / H;
      const t = { ...start };
      if (!corner) {
        t.x = start.x + dx; t.y = start.y + dy;
        snapMove(t, s, W, H);
      } else {
        const left = corner.includes('w'), up = corner.includes('n');
        let w = Math.max(0.03, start.w + (left ? -dx : dx));
        let hh = Math.max(0.03, start.h + (up ? -dy : dy));
        if (!free) hh = (w * W) / aspect / H;
        t.w = w; t.h = hh;
        t.x = left ? start.x + start.w - w : start.x;
        t.y = up ? start.y + start.h - hh : start.y;
      }
      current = t;
      this.player.preview(clip.id, t);
      this.render();
    };
    const up = async () => {
      target.removeEventListener('pointermove', move);
      const changed = ['x', 'y', 'w', 'h'].some(k => Math.abs(current[k] - start[k]) > 1e-4);
      if (changed) await edit([{ op: 'set_transform', clips: [clip.id], x: current.x, y: current.y, w: current.w, h: current.h }],
        corner ? 'Resize layer' : 'Move layer');
      this.player.preview(clip.id, null);
      this.render();
    };
    target.addEventListener('pointermove', move);
    target.addEventListener('pointerup', up, { once: true });
  }
}

// Snap a moved box's edges and centre to the canvas edges and centre.
function snapMove(t, s, W, H) {
  const tolX = SNAP_PX / s / W, tolY = SNAP_PX / s / H;
  const xs = [[t.x, 0], [t.x + t.w, 1], [t.x + t.w / 2, 0.5]];
  for (const [edge, line] of xs) if (Math.abs(edge - line) < tolX) { t.x += line - edge; break; }
  const ys = [[t.y, 0], [t.y + t.h, 1], [t.y + t.h / 2, 0.5]];
  for (const [edge, line] of ys) if (Math.abs(edge - line) < tolY) { t.y += line - edge; break; }
}
