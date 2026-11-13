// The editor workspace: four panels in a grid with draggable splitters, sizes remembered.
import { quiet } from '../bridge.js';
import { clamp, h } from '../dom.js';
import * as media from './media.js';
import * as monitor from './monitor.js';
import * as side from './side.js';
import * as timeline from './timeline.js';

const DEFAULTS = { left: 280, right: 340, bottom: 330 };

export function mount(el) {
  const ws = h('div', { class: 'workspace' });
  const areas = {
    media: h('section', { class: 'panel area-media' }),
    monitor: h('section', { class: 'panel area-monitor' }),
    side: h('section', { class: 'panel area-side' }),
    timeline: h('section', { class: 'panel area-timeline' }),
  };
  ws.append(...Object.values(areas));
  el.replaceChildren(ws);

  const sizes = { ...DEFAULTS };
  const apply = () => {
    ws.style.setProperty('--left', `${sizes.left}px`);
    ws.style.setProperty('--right', `${sizes.right}px`);
    ws.style.setProperty('--bottom', `${sizes.bottom}px`);
    place();
    window.dispatchEvent(new Event('or-layout'));
  };
  const v1 = h('div', { class: 'splitter v' }), v2 = h('div', { class: 'splitter v' }), hz = h('div', { class: 'splitter h' });
  ws.append(v1, v2, hz);
  const place = () => {
    const H = ws.clientHeight, W = ws.clientWidth;
    v1.style.left = `${sizes.left}px`; v1.style.height = `${H - sizes.bottom}px`;
    v2.style.left = `${W - sizes.right}px`; v2.style.height = `${H - sizes.bottom}px`;
    hz.style.top = `${H - sizes.bottom}px`;
  };
  const drag = (handle, fn) => handle.addEventListener('pointerdown', e => {
    handle.setPointerCapture(e.pointerId);
    handle.classList.add('drag');
    const move = ev => { fn(ev); apply(); };
    const up = () => {
      handle.classList.remove('drag');
      handle.removeEventListener('pointermove', move);
      quiet('save_prefs', { panels: sizes });
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', up, { once: true });
  });
  drag(v1, e => { sizes.left = clamp(e.clientX - ws.getBoundingClientRect().left, 200, 460); });
  drag(v2, e => { sizes.right = clamp(ws.getBoundingClientRect().right - e.clientX, 280, 560); });
  drag(hz, e => { sizes.bottom = clamp(ws.getBoundingClientRect().bottom - e.clientY, 180, ws.clientHeight - 240); });
  window.addEventListener('resize', place);

  const unmounts = [
    media.mount(areas.media),
    monitor.mount(areas.monitor),
    side.mount(areas.side),
    timeline.mount(areas.timeline),
  ];
  quiet('prefs').then(res => {
    if (res && res.ok && res.prefs && res.prefs.panels) Object.assign(sizes, res.prefs.panels);
    apply();
  });
  apply();
  return () => {
    window.removeEventListener('resize', place);
    unmounts.forEach(fn => fn && fn());
  };
}

