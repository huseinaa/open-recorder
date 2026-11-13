// Effect Controls: the selected clip's position, size, mask, opacity, volume and blur, as values
// you can drag (scrub) or type. With nothing selected it shows the canvas settings.
import { deleteSelected, selectedClip, splitAtPlayhead } from '../actions.js';
import { edit } from '../bridge.js';
import { duration, h, iconButton } from '../dom.js';
import { icon } from '../icons.js';
import { canvasSize, clipEnd, state, subscribe } from '../store.js';

export function mount(el) {
  const render = () => el.replaceChildren(build());
  render();
  return subscribe(keys => {
    if (keys.has('selection') || keys.has('project') || keys.has('focus')) {
      if (el.contains(document.activeElement) && document.activeElement.classList.contains('scrub')) return;
      render();
    }
  });
}

function build() {
  if (!state.project) return h('div');
  const { lane, clip } = selectedClip();
  if (state.selection.length > 1 && !clip) return multi();
  if (!clip) return canvasSettings();
  const m = state.media[clip.media];
  const wrap = h('div', { class: 'fx' });
  const name = lane.kind === 'blur' ? 'Blur' : (m?.name || clip.media);
  wrap.append(h('div', { class: 'fx-title' }, h('b', {}, name),
    h('span', { class: 'tabular' }, `${lane.name}, ${duration(clip.start)} to ${duration(clipEnd(clip))} (${(clip.src_out - clip.src_in).toFixed(2)} s)`)));
  const id = clip.id;
  const t = clip.transform;
  const [W, H] = canvasSize();
  const set = (props, label) => edit([{ op: 'set_transform', clips: [id], ...props }], label);

  if (lane.kind !== 'audio' && (clip.video || lane.kind === 'blur')) {
    wrap.append(section(lane.kind === 'blur' ? 'Box' : 'Motion',
      row('Position', pair(
        scrub(Math.round(t.x * W), v => set({ x: v / W }, 'Move layer'), { step: 1, suffix: '' }),
        scrub(Math.round(t.y * H), v => set({ y: v / H }, 'Move layer'), { step: 1 }))),
      row('Size', pair(
        scrub(Math.round(t.w * W), v => set(lane.kind === 'blur' ? { w: v / W } : { w: v / W, h: (v / W) * (t.h / t.w) }, 'Resize layer'), { step: 2, min: 8 }),
        scrub(Math.round(t.h * H), v => set(lane.kind === 'blur' ? { h: v / H } : { h: v / H, w: (v / H) * (t.w / t.h) }, 'Resize layer'), { step: 2, min: 8 }))),
      lane.kind !== 'blur' && row('Fit', seg([['contain', 'Fit'], ['cover', 'Fill']], t.fit, v => set({ fit: v }, v === 'cover' ? 'Fill' : 'Fit')), null),
      lane.kind !== 'blur' && row('Opacity', scrub(Math.round((t.opacity ?? 1) * 100), v => set({ opacity: v / 100 }, 'Opacity'),
        { min: 0, max: 100, suffix: '%' }), () => set({ opacity: 1 }, 'Opacity')),
    ));
  }
  if (lane.kind === 'video' && clip.video) {
    wrap.append(section('Shape',
      row('Mask', seg([['none', 'None'], ['circle', 'Circle'], ['square', 'Square']], t.mask,
        v => edit([{ op: 'set_mask', clips: [id], mask: v }], 'Mask')), null),
      t.mask === 'square' && row('Corners', scrub(Math.round((t.radius ?? 0.18) * 200), v =>
        edit([{ op: 'set_mask', clips: [id], mask: 'square', radius: v / 200 }], 'Corners'), { min: 0, max: 100, suffix: '%' })),
      h('div', { class: 'fx-actions' },
        h('button', { class: 'btn', onclick: () => edit([{ op: 'reset_layout', clips: [id] }], 'Reset layout'),
          html: `${icon('reset')}<span>Default place</span>` }))));
  }
  if (lane.kind === 'blur') {
    wrap.append(section('Blur', row('Strength', scrub(Math.round(clip.strength), v =>
      edit([{ op: 'set_blur', clips: [id], strength: v }], 'Blur strength'), { min: 1, max: 100 }))));
  }
  if (clip.audio || (m && m.has_audio && lane.kind !== 'blur')) {
    wrap.append(section('Audio',
      row('Volume', scrub(Math.round((clip.volume ?? 1) * 100), v => edit([{ op: 'set_volume', clips: [id], volume: v / 100 }], 'Volume'),
        { min: 0, max: 200, suffix: '%' }), () => edit([{ op: 'set_volume', clips: [id], volume: 1 }], 'Volume')),
      lane.kind === 'video' && clip.audio && h('div', { class: 'fx-actions' },
        h('button', { class: 'btn', onclick: () => edit([{ op: 'detach_audio', clip: id }], 'Detach audio'),
          html: `${icon('detach')}<span>Put the sound on its own lane</span>` }))));
  }
  wrap.append(h('div', { class: 'fx-actions' },
    h('button', { class: 'btn', onclick: splitAtPlayhead, html: `${icon('split')}<span>Split</span>` }),
    clip.link ? h('button', { class: 'btn', onclick: () => edit([{ op: 'unlink', clips: [id] }], 'Unlink'), html: `${icon('unlink')}<span>Unlink</span>` }) : null,
    h('button', { class: 'btn danger', onclick: () => deleteSelected(false), html: `${icon('trash')}<span>Delete</span>` })));
  return wrap;
}

function multi() {
  const ids = state.selection;
  return h('div', { class: 'fx' },
    h('div', { class: 'fx-title' }, h('b', {}, `${ids.length} clips selected`), h('span', {}, 'Linked clips are selected together.')),
    h('div', { class: 'fx-actions' },
      h('button', { class: 'btn', onclick: () => edit([{ op: 'link', clips: ids }], 'Link'), html: `${icon('link')}<span>Link them</span>` }),
      h('button', { class: 'btn', onclick: () => edit([{ op: 'unlink', clips: ids }], 'Unlink'), html: `${icon('unlink')}<span>Unlink</span>` }),
      h('button', { class: 'btn danger', onclick: () => deleteSelected(false), html: `${icon('trash')}<span>Delete</span>` }),
      h('button', { class: 'btn', onclick: () => deleteSelected(true) }, 'Delete and close the gap')));
}

function canvasSettings() {
  const seq = state.project.sequence;
  const [W, H] = canvasSize();
  return h('div', { class: 'fx' },
    h('div', { class: 'fx-title' }, h('b', {}, state.name), h('span', { class: 'tabular' }, `${W} × ${H}, ${seq.fps} fps, ${duration(projectDurationSafe())}`)),
    section('Canvas',
      row('Shape', seg([['16:9', '16:9'], ['9:16', '9:16'], ['1:1', '1:1'], ['4:5', '4:5']], seq.aspect,
        v => edit([{ op: 'set_sequence', aspect: v }], `Canvas ${v}`)), null),
      row('Frame rate', seg([['24', '24'], ['30', '30'], ['60', '60']], String(seq.fps),
        v => edit([{ op: 'set_sequence', fps: +v }], 'Frame rate')), null),
      h('div', { class: 'fx-actions' }, h('button', { class: 'btn', onclick: () => edit([{ op: 'reset_layout' }], 'Reset layout'),
        html: `${icon('reset')}<span>Put face and screen in their default places</span>` }))),
    h('div', { class: 'fx-empty', html:
      'Select a clip to change its position, mask or volume.<br><br>' +
      '<span class="kbd">Space</span> play &nbsp; <span class="kbd">S</span> split &nbsp; <span class="kbd">Del</span> delete<br>' +
      '<span class="kbd">V</span> select &nbsp; <span class="kbd">C</span> razor &nbsp; <span class="kbd">B</span> ripple trim &nbsp; <span class="kbd">H</span> hand' }));
}

function projectDurationSafe() {
  let end = 0;
  for (const lane of state.project.lanes) for (const c of lane.clips) end = Math.max(end, clipEnd(c));
  return end;
}

// ---------- building blocks ----------
function section(title, ...rows) {
  return h('div', { class: 'fx-section' }, h('h4', {}, title), ...rows.filter(Boolean));
}

function row(label, control, reset) {
  const lab = h('label', { class: control && control.scrubber ? '' : 'static' }, label);
  if (control && control.scrubber) control.scrubber(lab);
  return h('div', { class: 'fx-row' }, lab, control,
    reset ? iconButton('reset', `Reset ${label.toLowerCase()}`, reset) : h('span'));
}

function pair(a, b) {
  const el = h('div', { class: 'pair' }, a, b);
  el.scrubber = lab => a.scrubber && a.scrubber(lab);
  return el;
}

function seg(options, value, onpick) {
  return h('div', { class: 'seg' }, ...options.map(([v, label]) =>
    h('button', { class: v === value ? 'on' : '', onclick: () => v !== value && onpick(v) }, label)));
}

// A number you can type, or change by dragging its label left and right (Shift for bigger steps).
function scrub(value, commit, { step = 1, min = -100000, max = 100000, suffix = '' } = {}) {
  const input = h('input', { class: 'scrub', value: `${value}${suffix}`, inputmode: 'numeric' });
  const read = () => parseFloat(String(input.value).replace(/[^\d.-]/g, ''));
  const clampV = v => Math.min(max, Math.max(min, v));
  const send = v => { if (Number.isFinite(v) && v !== value) commit(clampV(v)); };
  input.addEventListener('focus', () => { input.value = String(value); input.select(); });
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') { input.blur(); }
    else if (e.key === 'Escape') { input.value = String(value); input.blur(); }
    else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault();
      input.value = String(clampV(read() + (e.key === 'ArrowUp' ? 1 : -1) * step * (e.shiftKey ? 10 : 1)));
    }
    e.stopPropagation();
  });
  input.addEventListener('blur', () => { send(read()); input.value = `${value}${suffix}`; });
  input.scrubber = label => {
    label.addEventListener('pointerdown', e => {
      label.setPointerCapture(e.pointerId);
      const x0 = e.clientX;
      let v = value;
      const move = ev => {
        v = clampV(Math.round(value + (ev.clientX - x0) * step * (ev.shiftKey ? 10 : 1)));
        input.value = `${v}${suffix}`;
      };
      label.addEventListener('pointermove', move);
      label.addEventListener('pointerup', () => { label.removeEventListener('pointermove', move); send(v); }, { once: true });
    });
  };
  return input;
}
