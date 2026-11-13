// Track headers: the lane name (double-click to rename), hide, mute and lock, and a menu to move
// or delete the lane.
import { edit } from '../bridge.js';
import { h, iconButton, menu } from '../dom.js';
import { state } from '../store.js';
import { laneTops } from './geometry.js';

const TAG = { face: 'var(--clip-face)', screen: 'var(--clip-screen)', video: 'var(--clip-video)', audio: 'var(--clip-audio)',
  blur: 'var(--clip-blur)' };

export function renderHeads(container) {
  container.replaceChildren();
  state.project.lanes.forEach((lane, index) => {
    const tops = laneTops();
    const height = tops[index].h;
    const name = h('div', { class: 'name', title: 'Double-click to rename' }, lane.name);
    name.addEventListener('dblclick', () => rename(name, lane));
    const set = (key, value, label) => edit([{ op: 'set_lane', lane: lane.id, [key]: value }], label);
    const buttons = [];
    if (lane.kind !== 'audio') {
      buttons.push(iconButton(lane.hidden ? 'eyeOff' : 'eye', lane.hidden ? 'Show this lane' : 'Hide this lane',
        () => set('hidden', !lane.hidden, lane.hidden ? 'Show lane' : 'Hide lane'), { class: lane.hidden ? 'on' : '' }));
    }
    if (lane.kind !== 'blur') {
      buttons.push(iconButton(lane.muted ? 'mute' : 'speaker', lane.muted ? 'Unmute this lane' : 'Mute this lane',
        () => set('muted', !lane.muted, lane.muted ? 'Unmute lane' : 'Mute lane'), { class: lane.muted ? 'on' : '' }));
    }
    buttons.push(iconButton(lane.locked ? 'lock' : 'unlock', lane.locked ? 'Unlock this lane' : 'Lock this lane',
      () => set('locked', !lane.locked, lane.locked ? 'Unlock lane' : 'Lock lane'), { class: lane.locked ? 'on' : '' }));
    const row = h('div', { class: 'lane-head', style: { height: `${height}px` } },
      h('span', { class: 'tag', style: { background: TAG[lane.role] || TAG[lane.kind] } }), name, ...buttons);
    row.addEventListener('contextmenu', e => {
      e.preventDefault();
      menu(e.clientX, e.clientY, [
        { label: 'Rename', run: () => rename(name, lane) },
        index > 0 && { label: 'Move up', run: () => edit([{ op: 'reorder_lane', lane: lane.id, index: index - 1 }], 'Move lane') },
        index < state.project.lanes.length - 1 && { label: 'Move down', run: () => edit([{ op: 'reorder_lane', lane: lane.id, index: index + 1 }], 'Move lane') },
        '-',
        { label: 'Delete lane', icon: 'trash', run: () => edit([{ op: 'remove_lane', lane: lane.id }], 'Delete lane') },
      ].filter(Boolean));
    });
    container.append(row);
  });
}

function rename(nameEl, lane) {
  const input = h('input', { class: 'input', value: lane.name, maxlength: 40 });
  nameEl.replaceChildren(input);
  input.focus();
  input.select();
  let done = false;
  const finish = save => {
    if (done) return;
    done = true;
    const value = input.value.trim();
    if (save && value && value !== lane.name) edit([{ op: 'set_lane', lane: lane.id, name: value }], 'Rename lane');
    else nameEl.textContent = lane.name;
  };
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') finish(true);
    if (e.key === 'Escape') finish(false);
    e.stopPropagation();
  });
  input.addEventListener('blur', () => finish(true));
}
