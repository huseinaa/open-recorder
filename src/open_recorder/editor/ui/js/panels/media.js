// The Project panel: the takes and files in this project's folder. Drag one onto the timeline,
// or double-click it to add it at the end.
import { addMedia, addRecording } from '../actions.js';
import { call, quiet } from '../bridge.js';
import { duration, h, iconButton, menu, modal, takeLabel, toast } from '../dom.js';
import { startBinDrag } from '../bindrag.js';
import { icon } from '../icons.js';
import { loadState, state, subscribe } from '../store.js';

export function mount(el) {
  const body = h('div', { class: 'panel-body' });
  el.replaceChildren(
    h('div', { class: 'panel-head' }, h('h3', {}, 'Project'),
      iconButton('plus', 'Import files', importFiles),
      iconButton('refresh', 'Look for new files in the folder', rescan),
      iconButton('folderOpen', 'Show the project folder', () => call('open_path', state.folder))),
    body);
  const render = () => body.replaceChildren(list());
  render();
  return subscribe(keys => {
    if (keys.has('media') || keys.has('transcripts') || keys.has('fresh') || keys.has('ai')) render();
  });
}

async function importFiles() {
  try {
    const res = await call('import_files');
    if (!res.cancelled) loadState(res.state);
  } catch (e) { /* toast shown */ }
}

async function rescan() {
  try {
    const res = await call('rescan');
    loadState(res.state);
    toast(res.new.length ? `Found ${res.new.length} new file(s)` : 'No new files in the folder');
  } catch (e) { /* toast shown */ }
}

function recordings() {
  const takes = {}, files = [];
  for (const m of Object.values(state.media)) {
    if (m.recording) (takes[m.recording] ||= {})[m.role] = m;
    else files.push(m);
  }
  return { takes: Object.entries(takes).sort((a, b) => b[0].localeCompare(a[0])), files };
}

function list() {
  const { takes, files } = recordings();
  const wrap = h('div', { class: 'bin' });
  if (!takes.length && !files.length) {
    wrap.append(h('div', { class: 'bin-empty', html:
      `No takes yet.<br>Press <b>Record</b> to record one into this project, or drop video, image and sound files here.` }));
    return wrap;
  }
  if (takes.length) {
    wrap.append(h('div', { class: 'bin-group' }, h('span', {}, 'Takes'), h('span', {}, String(takes.length))));
    for (const [id, parts] of takes) wrap.append(takeItem(id, parts));
  }
  if (files.length) {
    wrap.append(h('div', { class: 'bin-group' }, h('span', {}, 'Files'), h('span', {}, String(files.length))));
    for (const m of files.sort((a, b) => a.name.localeCompare(b.name))) wrap.append(fileItem(m));
  }
  return wrap;
}

function transcriptPill(key) {
  const t = state.transcripts[key];
  if (!t) return null;
  if (t.state === 'done') return h('span', { class: 'pill ok', title: 'Transcribed: the AI knows what was said' }, 'Transcribed');
  if (t.state === 'working') return h('span', { class: 'pill brand' }, `Transcribing ${Math.round((t.progress || 0) * 100)}%`);
  if (t.state === 'queued') return h('span', { class: 'pill' }, 'Waiting to transcribe');
  if (t.state === 'failed') return h('span', { class: 'pill error', title: t.message }, 'Transcript failed');
  return null;
}

function thumb(m, dur) {
  const el = h('div', { class: 'thumb', html: m?.poster ? '' : icon(m?.kind === 'audio' ? 'audio' : m?.kind === 'image' ? 'image' : 'video') });
  if (m?.poster) el.style.backgroundImage = `url("${m.poster}")`;
  if (dur) el.append(h('span', { class: 'dur tabular' }, duration(dur)));
  return el;
}

function takeItem(id, parts) {
  const look = parts.screen || parts.camera;
  const voice = parts.camera || parts.screen;
  const tags = [];
  if (parts.screen) tags.push(h('span', { class: 'pill', html: `${icon('screen')}Screen` }));
  if (parts.camera) tags.push(h('span', { class: 'pill', html: `${icon('face')}Face` }));
  const item = h('div', { class: `bin-item ${state.fresh === id ? 'fresh' : ''}`,
    title: 'Drag onto the timeline, or double-click to add it at the end' },
    thumb(look, Math.max(parts.screen?.duration || 0, parts.camera?.duration || 0)),
    h('div', { class: 'info' }, h('b', {}, `Take, ${takeLabel(id)}`), h('div', { class: 'row' }, ...tags, transcriptPill(voice?.key))));
  item.addEventListener('pointerdown', e => startBinDrag(e, { recording: id }, `Take, ${takeLabel(id)}`));
  item.addEventListener('dblclick', () => addRecording(id));
  item.addEventListener('contextmenu', e => {
    e.preventDefault();
    menu(e.clientX, e.clientY, [
      { label: 'Add to the end of the timeline', icon: 'plus', run: () => addRecording(id) },
      voice && { label: 'Transcribe', icon: 'sparkle', run: () => transcribe([voice.key]) },
      { label: 'Show in folder', icon: 'folderOpen', run: () => call('reveal', look.path) },
      '-',
      { label: 'Delete take', icon: 'trash', run: () => confirmDelete([parts.screen, parts.camera].filter(Boolean), `Take, ${takeLabel(id)}`, true) },
    ].filter(Boolean));
  });
  return item;
}

const outside = key => /^[A-Za-z]:[\\/]/.test(key) || key.startsWith('\\\\');

function clipsUsing(keys) {
  let n = 0;
  for (const lane of state.project.lanes) for (const c of lane.clips) if (keys.includes(c.media)) n++;
  return n;
}

// Files in the project folder go to the Recycle Bin; files linked from elsewhere only leave the project.
function confirmDelete(items, name, isTake = false) {
  const keys = items.map(m => m.key);
  const linked = items.every(m => outside(m.key));
  const used = clipsUsing(keys);
  const what = linked ? `"${name}" is linked from another folder. It leaves this project, and the file stays where it is.`
    : isTake ? `Its screen and camera files go to the Recycle Bin. You can restore them from there.`
    : `The file goes to the Recycle Bin. You can restore it from there.`;
  const onTimeline = used ? ` It's on the timeline ${used === 1 ? 'in 1 clip' : `in ${used} clips`}, which ${used === 1 ? 'is' : 'are'} removed too.` : '';
  modal(close => {
    const remove = async e => {
      e.currentTarget.disabled = true;
      try {
        const res = await call('delete_media', keys);
        close();
        loadState(res.state);
        if (res.failed?.length) toast(`Could not delete ${res.failed.join(', ')}. It may be open somewhere.`, 'error');
        else toast(linked ? `Removed "${name}" from the project` : `"${name}" is in the Recycle Bin`, 'ok');
      } catch (err) { e.currentTarget.disabled = false; }
    };
    return [
      h('h2', {}, linked ? `Remove "${name}"?` : `Delete "${name}"?`),
      h('p', { class: 'sub' }, what + onTimeline),
      h('div', { class: 'actions' }, h('button', { class: 'btn primary', onclick: close }, 'Cancel'),
        h('button', { class: 'btn danger', onclick: remove }, linked ? 'Remove from project' : isTake ? 'Delete take' : 'Delete file')),
    ];
  });
}

function fileItem(m) {
  const kindLabel = { video: 'Video', image: 'Image', audio: 'Sound' }[m.kind] || m.kind;
  const item = h('div', { class: 'bin-item', title: m.path },
    thumb(m, m.kind === 'image' ? 0 : m.duration),
    h('div', { class: 'info' }, h('b', {}, m.name), h('div', { class: 'row' }, h('span', { class: 'pill' }, kindLabel),
      m.voice ? transcriptPill(m.key) : null)));
  item.addEventListener('pointerdown', e => startBinDrag(e, { media: m.key }, m.name));
  item.addEventListener('dblclick', () => addMedia(m.key));
  item.addEventListener('contextmenu', e => {
    e.preventDefault();
    menu(e.clientX, e.clientY, [
      { label: 'Add to the timeline', icon: 'plus', run: () => addMedia(m.key) },
      m.voice && { label: 'Transcribe', icon: 'sparkle', run: () => transcribe([m.key]) },
      { label: 'Show in folder', icon: 'folderOpen', run: () => call('reveal', m.path) },
      '-',
      { label: outside(m.key) ? 'Remove from project' : 'Delete', icon: 'trash', run: () => confirmDelete([m], m.name) },
    ].filter(Boolean));
  });
  return item;
}

async function transcribe(keys) {
  const engine = state.ai?.transcriber?.engine;
  if (!engine || engine === 'skip') return toast('Set up a transcription engine in the AI tab first.');
  await quiet('transcribe', keys);
}
