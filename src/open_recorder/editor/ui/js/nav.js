// Which screen is showing (start or editor), and the top bar that goes with it.
import { record, redo, undo } from './actions.js';
import { call } from './bridge.js';
import { h, iconButton } from './dom.js';
import { icon } from './icons.js';
import { LOGO_MARK } from './logo.js';
import { loadState, set, state, subscribe } from './store.js';
import * as start from './panels/start.js';
import * as workspace from './panels/workspace.js';

const app = () => document.getElementById('app');
let unmount = null;

export function showStart(boot) {
  unmount && unmount();
  set({ screen: 'start', project: null, media: {}, selection: [], playhead: 0, playing: false, boot: boot || state.boot });
  renderTopbar();
  unmount = start.mount(app(), { openState });
}

export function showEditor() {
  unmount && unmount();
  set({ screen: 'editor' });
  renderTopbar();
  unmount = workspace.mount(app());
}

export function openState(s) {
  set({ selection: [], playhead: 0, chat: [] });
  loadState(s);
  showEditor();
}

export async function goHome() {
  try {
    const res = await call('close_project');
    showStart(res);
  } catch (e) { /* toast shown */ }
}

export async function openSettings() {
  const { openSettings: open } = await import('./panels/settings.js');
  open();
}

export async function openExport() {
  if (!state.project) return;
  const { openExport: open } = await import('./panels/export.js');
  open();
}

function renderTopbar() {
  const bar = document.getElementById('topbar');
  bar.replaceChildren();
  bar.append(h('div', { class: 'brand-mark' }, h('span', { class: 'mark', html: LOGO_MARK }), h('span', {}, 'Open Recorder')));
  if (state.screen === 'editor') {
    bar.append(iconButton('home', 'Back to projects', goHome));
    bar.append(h('div', { class: 'crumb' }, h('b', { id: 'project-name' }, state.name)));
    bar.append(h('div', { class: 'spacer' }));
    const rec = h('button', { class: `record-btn ${state.recording ? 'live' : ''}`, id: 'record-btn', onclick: record,
      title: 'Record a take into this project (R)' }, h('span', { class: 'dot' }), state.recording ? 'Recording…' : 'Record');
    const undoBtn = iconButton('undo', 'Undo (Ctrl+Z)', undo, { disabled: !state.undo });
    const redoBtn = iconButton('redo', 'Redo (Ctrl+Shift+Z)', redo, { disabled: !state.redo });
    undoBtn.id = 'undo-btn';
    redoBtn.id = 'redo-btn';
    bar.append(rec, h('div', { class: 'group' }, undoBtn, redoBtn),
      h('button', { class: 'btn primary', onclick: openExport, html: `${icon('export')}<span>Export</span>` }));
  } else {
    bar.append(h('div', { class: 'spacer' }));
  }
  bar.append(iconButton('settings', 'Settings', openSettings));
}

subscribe(keys => {
  if (state.screen !== 'editor') return;
  if (keys.has('undo') || keys.has('redo')) {
    const u = document.getElementById('undo-btn'), r = document.getElementById('redo-btn');
    if (u) { u.disabled = !state.undo; u.title = state.undo ? `Undo ${state.undo} (Ctrl+Z)` : 'Nothing to undo'; }
    if (r) { r.disabled = !state.redo; r.title = state.redo ? `Redo ${state.redo} (Ctrl+Shift+Z)` : 'Nothing to redo'; }
  }
  if (keys.has('name')) {
    const n = document.getElementById('project-name');
    if (n) n.textContent = state.name;
  }
  if (keys.has('recording')) {
    const b = document.getElementById('record-btn');
    if (b) {
      b.classList.toggle('live', state.recording);
      b.lastChild.textContent = state.recording ? 'Recording…' : 'Record';
    }
  }
});
