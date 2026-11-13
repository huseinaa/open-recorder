// The Timeline panel: toolbar, track headers, ruler, lanes and playhead.
import { deleteSelected, splitAtPlayhead, zoom } from '../actions.js';
import { edit } from '../bridge.js';
import { h, iconButton, menu, timecode } from '../dom.js';
import { icon } from '../icons.js';
import { projectDuration, set, state, subscribe } from '../store.js';
import { paintVisible, renderLanes } from '../timeline/clips.js';
import { PAD, tAt, xAt } from '../timeline/geometry.js';
import { renderHeads } from '../timeline/heads.js';
import { drawRuler } from '../timeline/ruler.js';
import { attach } from '../timeline/tools.js';

const TOOLS = [['select', 'select', 'Selection (V): move and trim'], ['razor', 'razor', 'Razor (C): click a clip to split it'],
  ['ripple', 'ripple', 'Ripple trim (B): shorten a clip and close the gap'], ['hand', 'hand', 'Hand (H): drag to pan']];

export function mount(el) {
  const toolBtns = TOOLS.map(([id, ic, title]) => {
    const b = iconButton(ic, title, () => set({ tool: id }));
    b.dataset.tool = id;
    return b;
  });
  const snapBtn = iconButton('magnet', 'Snap to edges and the playhead', () => set({ snap: !state.snap }));
  const linkBtn = iconButton('link', 'Linked selection: face and screen move together', () => set({ link: !state.link }));
  const slider = h('input', { type: 'range', min: '0', max: '1000', title: 'Zoom' });
  slider.addEventListener('input', () => set({ pps: sliderToPps(+slider.value) }));
  const tc = h('span', { class: 'timecode tabular' });
  const addLane = h('button', { class: 'btn ghost', html: `${icon('plus')}<span>Lane</span>`, onclick: e => {
    const r = e.currentTarget.getBoundingClientRect();
    menu(r.left, r.bottom + 4, [
      { label: 'Video lane (B-roll, images)', icon: 'video', run: () => edit([{ op: 'add_lane', kind: 'video' }], 'Add lane') },
      { label: 'Audio lane (music, sound)', icon: 'audio', run: () => edit([{ op: 'add_lane', kind: 'audio' }], 'Add lane') },
      { label: 'Blur lane', icon: 'blur', run: () => edit([{ op: 'add_lane', kind: 'blur' }], 'Add lane') },
      '-',
      { label: 'Blur a box at the playhead (3 s)', icon: 'blur', run: () => edit([{ op: 'add_blur', start: state.playhead, end: state.playhead + 3 }], 'Add blur') },
    ]);
  } });

  const heads = h('div', { class: 'tl-heads-inner' });
  const rulerCanvas = h('canvas');
  const ruler = h('div', { class: 'tl-ruler' }, rulerCanvas);
  const lanes = h('div', { class: 'tl-lanes' });
  const playheadHead = h('div', { class: 'head' });
  const playhead = h('div', { class: 'playhead' }, playheadHead);
  const empty = h('div', { class: 'tl-empty' }, 'Drag a take from the Project panel here, or press Record.');
  const content = h('div', { class: 'tl-content' }, ruler, lanes, playhead, empty);
  const scroll = h('div', { class: 'tl-scroll' }, content);
  const root = h('div', { class: 'tl' },
    h('div', { class: 'tl-toolbar' }, ...toolBtns, h('span', { class: 'sep' }), snapBtn, linkBtn, h('span', { class: 'sep' }),
      iconButton('split', 'Split at the playhead (S)', splitAtPlayhead),
      iconButton('trash', 'Delete the selected clips (Delete, Shift+Delete to close the gap)', () => deleteSelected(false)),
      h('span', { class: 'sep' }), addLane, h('span', { class: 'spacer' }),
      iconButton('zoomOut', 'Zoom out (-)', () => zoom(0.8)), slider, iconButton('zoomIn', 'Zoom in (+)', () => zoom(1.25)),
      h('button', { class: 'btn ghost', onclick: fitAll, title: 'Fit the whole timeline' }, 'Fit'),
      h('span', { class: 'sep' }), tc),
    h('div', { class: 'tl-body' }, h('div', { class: 'tl-heads' }, heads), scroll));
  el.replaceChildren(root);

  const repaint = () => requestAnimationFrame(() => paintVisible(lanes, repaint));
  const sizeContent = () => {
    const width = Math.max(scroll.clientWidth, xAt(projectDuration() + Math.max(30, scroll.clientWidth / state.pps * 0.5)));
    content.style.width = `${width}px`;
  };
  const drawRulerNow = () => drawRuler(rulerCanvas, scroll.scrollLeft, scroll.clientWidth);
  const placePlayhead = () => {
    playhead.style.left = `${xAt(state.playhead)}px`;
    tc.textContent = timecode(state.playhead, state.project?.sequence?.fps);
    if (state.playing) {  // keep the playhead in view while playing
      const x = xAt(state.playhead);
      if (x > scroll.scrollLeft + scroll.clientWidth - 40) scroll.scrollLeft = x - 60;
    }
  };
  const renderAll = () => {
    if (!state.project) return;
    sizeContent();
    renderHeads(heads);
    renderLanes(lanes, repaint);
    empty.classList.toggle('hidden', projectDuration() > 0);
    drawRulerNow();
    placePlayhead();
  };
  function fitAll() {
    const d = Math.max(projectDuration(), 10);
    set({ pps: Math.max(4, (scroll.clientWidth - PAD - 40) / d) });
  }
  const syncTools = () => {
    root.className = `tl tool-${state.tool}`;
    toolBtns.forEach(b => b.classList.toggle('on', b.dataset.tool === state.tool));
    snapBtn.classList.toggle('on', state.snap);
    linkBtn.classList.toggle('on', state.link);
    slider.value = String(ppsToSlider(state.pps));
  };

  scroll.addEventListener('scroll', () => {
    heads.style.transform = `translateY(${-scroll.scrollTop}px)`;
    drawRulerNow();
    repaint();
  });
  scroll.addEventListener('wheel', e => {
    if (e.ctrlKey) {
      e.preventDefault();
      const r = scroll.getBoundingClientRect();
      const anchor = tAt(e.clientX - r.left + scroll.scrollLeft);
      const offset = e.clientX - r.left;
      set({ pps: Math.min(480, Math.max(4, state.pps * (e.deltaY < 0 ? 1.15 : 0.87))), zoomAnchor: { t: anchor, offset } });
    } else if (!e.shiftKey && Math.abs(e.deltaY) > Math.abs(e.deltaX) && e.altKey) {
      e.preventDefault();
      scroll.scrollLeft += e.deltaY;
    }
  }, { passive: false });
  const ro = new ResizeObserver(() => { sizeContent(); drawRulerNow(); repaint(); });
  ro.observe(scroll);
  const detach = attach({ scroll, content, lanes, ruler, playheadHead });

  renderAll();
  syncTools();
  if (state.project && projectDuration() > 0) requestAnimationFrame(fitAll);
  const off = subscribe(keys => {
    if (keys.has('pps')) {
      const anchor = state.zoomAnchor && typeof state.zoomAnchor === 'object' ? state.zoomAnchor
        : { t: state.playhead, offset: xAt(state.playhead) - scroll.scrollLeft };
      renderAll();
      scroll.scrollLeft = Math.max(0, xAt(anchor.t) - anchor.offset);
      state.zoomAnchor = null;
    } else if (keys.has('project') || keys.has('media') || keys.has('selection') || keys.has('waves')) {
      renderAll();
    } else if (keys.has('playhead')) {
      placePlayhead();
    }
    if (keys.has('tool') || keys.has('snap') || keys.has('link') || keys.has('pps')) syncTools();
  });
  return () => { off(); ro.disconnect(); detach(); };
}

// the zoom slider is logarithmic: 4 to 480 px per second
const LO = Math.log(4), HI = Math.log(480);
function sliderToPps(v) { return Math.exp(LO + (HI - LO) * v / 1000); }
function ppsToSlider(p) { return Math.round((Math.log(p) - LO) / (HI - LO) * 1000); }
