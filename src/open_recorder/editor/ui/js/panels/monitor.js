// The Program monitor: the canvas at the project's shape, the layers playing on it, the handles
// for the selected layer, and the transport under it.
import { ctx, seek, step, togglePlay } from '../actions.js';
import { edit } from '../bridge.js';
import { duration, h, iconButton, timecode, toast } from '../dom.js';
import { icon } from '../icons.js';
import { Handles } from '../monitor/handles.js';
import { Player } from '../monitor/player.js';
import { canvasSize, projectDuration, set, state, subscribe } from '../store.js';

const ASPECTS = [['16:9', 'Landscape 16:9'], ['9:16', 'Vertical 9:16'], ['1:1', 'Square 1:1'], ['4:5', 'Portrait 4:5']];

export function mount(el) {
  const aspect = h('select', { class: 'input aspect-pick', title: 'Canvas shape' },
    ...ASPECTS.map(([v, label]) => h('option', { value: v }, label)));
  aspect.addEventListener('change', () => changeAspect(aspect.value));
  const safeBtn = iconButton('safe', 'Show the safe zone', () => set({ safe: !state.safe }));
  const body = h('div', { class: 'mon-body' });
  const wrap = h('div', { class: 'stage-wrap' });
  const stage = h('div', { class: 'stage' });
  const overlay = h('div', { class: 'overlay' });
  const audioBox = h('div', { class: 'hidden' });
  const empty = h('div', { class: 'mon-empty' }, 'Record a take or drop a file on the timeline to see it here.');
  wrap.append(stage, overlay);
  body.append(wrap, audioBox, empty);

  const tc = h('span', { class: 'tc tabular' });
  const total = h('span', { class: 'dur tabular' });
  const playBtn = h('button', { class: 'icon-btn play', title: 'Play (Space)', onclick: togglePlay, html: icon('play') });
  el.replaceChildren(
    h('div', { class: 'panel-head mon-head' }, h('h3', {}, 'Program'), safeBtn, aspect),
    body,
    h('div', { class: 'transport' }, tc,
      h('div', { class: 'controls' },
        iconButton('toStart', 'Go to start (Home)', () => seek(0)),
        iconButton('stepBack', 'Back one frame (Left)', () => step(-1)),
        playBtn,
        iconButton('stepFwd', 'Forward one frame (Right)', () => step(1)),
        iconButton('toEnd', 'Go to end (End)', () => seek(projectDuration()))),
      total));

  const player = new Player(stage, audioBox);
  ctx.player = player;
  let scale = 1;
  const handles = new Handles(overlay, player, () => scale);

  const fit = () => {
    const [W, H] = canvasSize();
    const bw = body.clientWidth - 32, bh = body.clientHeight - 32;
    scale = Math.max(0.05, Math.min(bw / W, bh / H));
    Object.assign(wrap.style, { width: `${W * scale}px`, height: `${H * scale}px` });
    Object.assign(stage.style, { width: `${W}px`, height: `${H}px`, transform: `scale(${scale})` });
    drawSafe();
    handles.render();
  };
  const drawSafe = () => {
    overlay.querySelectorAll('.safe').forEach(n => n.remove());
    safeBtn.classList.toggle('on', state.safe);
    if (!state.safe) return;
    const [W, H] = canvasSize();
    const box = state.project?.sequence?.aspect === '9:16'
      ? { x: 0.06, y: 0.14, w: 0.76, h: 0.66 }       // clear of a phone app's top bar, captions and side buttons
      : { x: 0.05, y: 0.05, w: 0.9, h: 0.9 };
    overlay.prepend(h('div', { class: 'safe', style: { left: `${box.x * W * scale}px`, top: `${box.y * H * scale}px`,
      width: `${box.w * W * scale}px`, height: `${box.h * H * scale}px` } }));
  };
  const ro = new ResizeObserver(fit);
  ro.observe(body);
  window.addEventListener('or-layout', fit);

  const refresh = keys => {
    if (keys.has('project') || keys.has('media')) {
      aspect.value = state.project?.sequence?.aspect || '16:9';
      player.setProject(state.project, state.media);
      empty.classList.toggle('hidden', projectDuration() > 0);
      fit();
      total.textContent = duration(projectDuration());
    }
    if (keys.has('playhead')) {
      tc.textContent = timecode(state.playhead, state.project?.sequence?.fps);
      if (!state.playing) { player.t = state.playhead; player.sync(false); }
    }
    if (keys.has('playing')) playBtn.innerHTML = icon(state.playing ? 'pause' : 'play');
    if (keys.has('selection') || keys.has('focus') || keys.has('playhead') || keys.has('project')) handles.render();
    if (keys.has('safe')) drawSafe();
  };
  refresh(new Set(['project', 'playhead', 'playing', 'safe']));
  const off = subscribe(refresh);
  return () => {
    off();
    ro.disconnect();
    window.removeEventListener('or-layout', fit);
    player.destroy();
    ctx.player = null;
  };
}

async function changeAspect(value) {
  if (value === state.project?.sequence?.aspect) return;
  const notes = await edit([{ op: 'set_sequence', aspect: value }], `Canvas ${value}`);
  if (notes) toast(`Canvas is now ${value}.`, '', { label: 'Use the default layout',
    run: () => edit([{ op: 'reset_layout' }], 'Reset layout') });
}
