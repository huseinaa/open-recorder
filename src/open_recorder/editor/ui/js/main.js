// Boot: wait for Python, show the start screen (or the project left open), and route the events
// Python pushes (new takes, the recorder closing, thumbnails, transcripts, files dropped in).
import { addRecording } from './actions.js';
import { call, on, ready } from './bridge.js';
import { toast } from './dom.js';
import { openState, showStart } from './nav.js';
import { install } from './shortcuts.js';
import { loadState, set, state } from './store.js';

let refreshTimer = 0;
function refreshSoon() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(async () => {
    if (!state.project) return;
    try { loadState((await call('state')).state); } catch (e) { /* toast shown */ }
  }, 250);
}

function wireEvents() {
  on('take', async p => {
    set({ recording: true, fresh: p.id });
    if (p.in_project && p.state) {
      loadState(p.state);
      toast(p.added ? `Take added to the timeline (${Math.round(p.seconds || 0)} s)` : 'Take saved to this project', 'ok');
    } else if (state.screen === 'start') {
      toast(`Take saved (${Math.round(p.seconds || 0)} s)`, 'ok', { label: 'Edit this take', run: async () => {
        try {
          const res = await call('open_quick');
          openState(res.state);
          await addRecording(p.id);
        } catch (e) { /* toast shown */ }
      } });
    }
    if (p.problems) toast('The take was saved with problems. See the recorder log.', 'error');
  });
  on('recorder', p => {
    if (p.state === 'closed') set({ recording: false });
    if (p.state === 'busy') { set({ recording: false }); toast('The recorder is already open somewhere else. Close it first.', 'error'); }
  });
  on('media-extra', p => { if (p.folder === state.folder) refreshSoon(); });
  on('transcript', p => {
    if (p.folder !== state.folder) return;
    set({ transcripts: { ...state.transcripts, [p.key]: p } });
    if (p.state === 'failed') toast(`Transcription failed: ${p.message}`, 'error');
  });
  on('files-dropped', async p => {
    if (state.screen !== 'editor') return toast('Open a project first, then drop files into it.');
    try {
      const res = await call('add_paths', p.paths);
      loadState(res.state);
      if (!res.keys.length) return toast('Those files are not video, image or sound files.', 'error');
      window.dispatchEvent(new CustomEvent('or-files-added', { detail: { keys: res.keys, x: p.x, y: p.y } }));
    } catch (e) { /* toast shown */ }
  });
}

async function boot() {
  install();
  await ready();
  wireEvents();
  try {
    const res = await call('boot');
    set({ boot: res, ai: res.ai, recording: res.recording });
    if (res.open) openState(res.open);
    else showStart(res);
  } catch (e) {
    document.getElementById('app').textContent = 'Open Recorder could not start. See the log.';
  }
}

boot();
