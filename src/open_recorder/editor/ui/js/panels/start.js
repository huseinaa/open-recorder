// The start screen: Record now, New project, and the recent projects. On first launch it asks
// for the root folder instead.
import { record } from '../actions.js';
import { call, on } from '../bridge.js';
import { escapeHtml, h, menu, modal, toast, when } from '../dom.js';
import { icon } from '../icons.js';
import { set, state } from '../store.js';

const ASPECTS = [
  { id: '16:9', label: 'Landscape', hint: 'YouTube, lessons', w: 48, h: 27 },
  { id: '9:16', label: 'Vertical', hint: 'Reels, Shorts, TikTok', w: 21, h: 37 },
  { id: '1:1', label: 'Square', hint: 'Feed posts', w: 32, h: 32 },
  { id: '4:5', label: 'Portrait', hint: 'Instagram feed', w: 28, h: 35 },
];

let root = null;
let openStateFn = null;

export function mount(el, { openState }) {
  openStateFn = openState;
  root = h('div', { class: 'start' });
  el.replaceChildren(root);
  render();
  refresh();
  return () => { root = null; };
}

on('project-poster', p => {
  if (!root) return;
  const card = root.querySelector(`[data-path="${CSS.escape(p.path)}"] .thumb`);
  if (card) { card.style.backgroundImage = `url("${p.poster}")`; card.innerHTML = ''; }
});

async function refresh() {
  if (!state.boot || state.boot.needs_root) return;
  try {
    const res = await call('projects');
    set({ boot: { ...state.boot, projects: res.projects } });
    render();
  } catch (e) { /* toast shown */ }
}

function render() {
  if (!root) return;
  const boot = state.boot || {};
  const inner = h('div', { class: 'start-inner' });
  root.replaceChildren(inner);
  if (boot.needs_root) return inner.append(welcome(boot));

  inner.append(
    h('h1', {}, 'Record, cut, export.'),
    h('p', { class: 'lede' }, 'Record your screen and face as separate tracks, then edit them here, with an AI that can make the cuts for you.'),
    h('div', { class: 'tiles' },
      h('button', { class: 'tile', onclick: record },
        h('span', { class: 'rec-orb' }),
        h('div', {}, h('h2', {}, 'Record now'), h('p', {}, 'Saves straight into your recordings folder. Edit it after, or never.'))),
      h('button', { class: 'tile', onclick: newProject },
        h('span', { class: 'plus-orb', html: icon('plus') }),
        h('div', {}, h('h2', {}, 'New project'), h('p', {}, 'Name it and pick a canvas. Every take you record in it lands on the timeline.')))),
  );

  const projects = boot.projects || [];
  inner.append(h('div', { class: 'section-head' }, h('h2', {}, 'Recent projects'),
    h('button', { class: 'btn ghost', onclick: openFolder, html: `${icon('folderOpen')}<span>Open a folder</span>` })));
  if (!projects.length) {
    inner.append(h('div', { class: 'empty-note' }, 'No projects yet. Start one with New project, or record a take with Record now.'));
  } else {
    inner.append(h('div', { class: 'projects' }, projects.map(card)));
  }
  inner.append(h('div', { class: 'start-foot' },
    h('span', { html: `${icon('folder')}` }),
    h('span', {}, 'Recordings and projects are saved in '), h('b', {}, boot.root),
    h('button', { class: 'btn ghost', onclick: () => call('open_path', boot.root) }, 'Show'),
    h('button', { class: 'btn ghost', onclick: () => chooseRoot(false) }, 'Change')));
}

function card(p) {
  const thumb = h('div', { class: 'thumb', html: p.poster ? '' : icon(p.quick ? 'record' : 'video') });
  if (p.poster) thumb.style.backgroundImage = `url("${p.poster}")`;
  const takes = p.takes === 1 ? '1 take' : `${p.takes} takes`;
  const cardBtn = h('button', { class: 'project-card', dataset: { path: p.path }, onclick: () => open(p),
    title: p.path }, thumb,
    h('div', { class: 'meta' }, h('b', {}, p.name), h('span', {}, `${when(p.modified)}, ${takes}`)));
  const showMenu = (x, y) => menu(x, y, [
    !p.quick && { label: 'Rename', icon: 'rename', run: () => renameProject(p) },
    { label: 'Show in folder', icon: 'folderOpen', run: () => call('open_path', p.path) },
    !p.quick && '-',
    !p.quick && { label: 'Delete', icon: 'trash', run: () => deleteProject(p) },
  ].filter(Boolean));
  const more = h('button', { class: 'icon-btn card-more', title: 'Rename, delete…', 'aria-label': `More for ${p.name}`,
    html: icon('more'), onclick: e => {
      e.stopPropagation();
      const r = e.currentTarget.getBoundingClientRect();
      showMenu(r.left, r.bottom + 4);
    } });
  const cell = h('div', { class: 'project-cell' }, cardBtn, more);
  cell.addEventListener('contextmenu', e => { e.preventDefault(); showMenu(e.clientX, e.clientY); });
  return cell;
}

function renameProject(p) {
  modal(close => {
    const name = h('input', { class: 'input', value: p.name, maxlength: 80 });
    const save = async () => {
      const next = name.value.trim();
      if (!next || next === p.name) return close();
      try {
        const res = await call('rename_project', p.path, next);
        close();
        set({ boot: { ...state.boot, projects: res.projects } });
        render();
      } catch (e) { /* toast shown */ }
    };
    name.addEventListener('keydown', e => { if (e.key === 'Enter') save(); });
    setTimeout(() => name.select(), 40);
    return [
      h('h2', {}, 'Rename project'),
      h('p', { class: 'sub' }, 'Its folder gets the new name too.'),
      h('div', { class: 'field' }, h('label', {}, 'Name'), name),
      h('div', { class: 'actions' }, h('button', { class: 'btn', onclick: close }, 'Cancel'),
        h('button', { class: 'btn primary', onclick: save }, 'Rename')),
    ];
  });
}

function deleteProject(p) {
  const what = !p.takes ? 'The project folder' : `The project folder, with ${p.takes === 1 ? 'its 1 take' : `its ${p.takes} takes`} and exports,`;
  modal(close => {
    const remove = async e => {
      e.currentTarget.disabled = true;
      try {
        const res = await call('delete_project', p.path);
        close();
        set({ boot: { ...state.boot, projects: res.projects } });
        render();
        toast(`"${p.name}" is in the Recycle Bin`, 'ok');
      } catch (err) { e.currentTarget.disabled = false; }
    };
    return [
      h('h2', {}, `Delete "${p.name}"?`),
      h('p', { class: 'sub' }, `${what} goes to the Recycle Bin. You can restore it from there.`),
      h('div', { class: 'actions' }, h('button', { class: 'btn primary', onclick: close }, 'Cancel'),
        h('button', { class: 'btn danger', onclick: remove }, 'Delete project')),
    ];
  });
}

async function open(p) {
  try {
    const res = p.quick ? await call('open_quick') : await call('open_project', p.path);
    openStateFn(res.state);
  } catch (e) { /* toast shown */ }
}

async function openFolder() {
  try {
    const res = await call('open_folder_dialog');
    if (!res.cancelled) openStateFn(res.state);
  } catch (e) { /* toast shown */ }
}

function welcome(boot) {
  return h('div', { class: 'welcome' },
    h('img', { class: 'welcome-logo', src: 'img/logo.svg', alt: '' }),
    h('h2', {}, 'Where should your recordings go?'),
    h('p', {}, 'Pick one folder. Record now saves takes straight into it, and each project you create becomes a folder inside it.'),
    h('div', { class: 'row' },
      h('button', { class: 'btn primary big', onclick: () => chooseRoot(false) }, 'Choose a folder'),
      h('button', { class: 'btn big', onclick: () => chooseRoot(true), title: boot.default_root }, 'Use Videos\\Open Recorder')));
}

async function chooseRoot(useDefault) {
  try {
    const res = await call('choose_root', useDefault);
    if (res.cancelled) return;
    set({ boot: res });
    render();
    refresh();
  } catch (e) { /* toast shown */ }
}

function newProject() {
  let aspect = (state.boot?.prefs?.aspect) || '16:9';
  modal(close => {
    const name = h('input', { class: 'input', placeholder: 'Day 3, Brick Breaker', maxlength: 80 });
    const picks = h('div', { class: 'aspects' });
    const draw = () => picks.replaceChildren(...ASPECTS.map(a => h('button', {
      class: `aspect ${a.id === aspect ? 'on' : ''}`, onclick: () => { aspect = a.id; draw(); }, type: 'button' },
      h('span', { class: 'shape', style: { width: `${a.w}px`, height: `${a.h}px` } }),
      h('span', {}, `${a.label} ${a.id}`), h('small', {}, a.hint))));
    draw();
    const create = async () => {
      try {
        const res = await call('create_project', name.value.trim() || 'Untitled project', aspect);
        close();
        openStateFn(res.state);
      } catch (e) { /* toast shown */ }
    };
    name.addEventListener('keydown', e => { if (e.key === 'Enter') create(); });
    return [
      h('h2', {}, 'New project'),
      h('p', { class: 'sub', html: `It becomes a folder inside <b>${escapeHtml(state.boot?.root || '')}</b>.` }),
      h('div', { class: 'field' }, h('label', {}, 'Name'), name),
      h('div', { class: 'field' }, h('label', {}, 'Canvas'), picks),
      h('div', { class: 'actions' }, h('button', { class: 'btn', onclick: close }, 'Cancel'),
        h('button', { class: 'btn primary', onclick: create }, 'Create project')),
    ];
  });
}
