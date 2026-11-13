// Setting up the AI: connect Claude or Codex (the user's own subscription, through the CLI they
// installed and signed into), then pick how speech is transcribed. Used by the AI tab and Settings.
import { call, on, quiet } from '../bridge.js';
import { h, toast } from '../dom.js';
import { icon } from '../icons.js';
import { set, state } from '../store.js';

const BLURB = {
  claude: 'Uses your Claude plan through Claude Code.',
  codex: 'Uses your ChatGPT plan through the Codex CLI.',
};
const LOGIN = { claude: 'claude', codex: 'codex login' };

let progress = null;  // the Whisper download, while it runs
const views = new Set();
on('transcriber-progress', p => { progress = p; views.forEach(fn => fn()); });
on('transcriber-ready', t => {
  progress = null;
  set({ ai: { ...state.ai, transcriber: t } });
  toast('Whisper is ready. Your takes will be transcribed in the background.', 'ok');
  views.forEach(fn => fn());
});

export function setupView({ showTranscriber = true } = {}) {
  const root = h('div');
  const checking = new Set();
  const render = () => {
    const ai = state.ai;
    if (!ai) return;
    root.replaceChildren();
    root.append(h('div', { class: 'step-title' }, 'Connect an AI'),
      h('p', { class: 'muted', style: { margin: '-4px 0 10px', fontSize: 'var(--fs-sm)' } }, 'One is enough. Connect both and the second answers when the first is out of usage.'),
      h('div', { class: 'cards' }, ...Object.values(ai.providers).map(p => providerCard(p, checking, render))));
    if (Object.values(ai.providers).filter(p => p.connected).length > 1) {
      root.append(h('div', { class: 'card' }, h('div', { class: 'top' }, h('b', {}, 'Ask first'),
        h('div', { class: 'seg' }, ...Object.values(ai.providers).map(p => h('button', {
          class: ai.primary === p.name ? 'on' : '', onclick: async () => {
            const res = await call('ai_options', { ai_primary: p.name });
            set({ ai: res });
            render();
          } }, p.label)))),
        h('p', {}, 'The other one answers when the first is out of usage or signed out.')));
    }
    if (showTranscriber && ai.ready) root.append(transcriberView(render));
  };
  views.add(render);
  render();
  root.dispose = () => views.delete(render);
  return root;
}

function providerCard(p, checking, render) {
  const busy = checking.has(p.name);
  const status = p.connected ? h('span', { class: 'pill ok', html: `${icon('check')}Connected` })
    : !p.installed ? h('span', { class: 'pill' }, 'Not installed') : h('span', { class: 'pill warn' }, 'Not connected');
  const check = async () => {
    checking.add(p.name);
    render();
    try {
      const res = await call('ai_check', p.name);
      set({ ai: res.summary });
      const s = res.status;
      if (s.state === 'connected') toast(`${p.label} is connected`, 'ok');
      else toast(s.message, 'error');
    } catch (e) { /* toast shown */ }
    checking.delete(p.name);
    render();
  };
  const actions = h('div', { class: 'row' });
  if (busy) actions.append(h('span', { class: 'thinking' }, h('span', { class: 'spinner' }), 'Checking, this takes a few seconds…'));
  else if (p.connected) actions.append(h('button', { class: 'btn ghost', onclick: async () => {
    set({ ai: (await call('ai_disconnect', p.name)) });
    render();
  } }, 'Disconnect'));
  else if (!p.installed) actions.append(
    h('button', { class: 'btn', onclick: () => quiet('open_url', p.install_url) }, 'How to install'),
    h('button', { class: 'btn ghost', onclick: check }, 'I installed it, check again'));
  else actions.append(h('button', { class: 'btn primary', onclick: check }, `Connect ${p.label}`));
  const body = [h('p', {}, BLURB[p.name] || '')];
  if (p.installed && !p.connected && !busy) {
    body.push(h('p', { html: `Signed in already? Press Connect. If not, open a terminal and run <code>${LOGIN[p.name]}</code> first.` }));
  }
  return h('div', { class: `card ${p.connected ? 'on' : ''}` }, h('div', { class: 'top' }, h('b', {}, p.label), status), ...body, actions);
}

function transcriberView(render) {
  const t = state.ai.transcriber;
  const wrap = h('div');
  wrap.append(h('div', { class: 'step-title' }, 'Transcription'),
    h('p', { class: 'muted', style: { margin: '-4px 0 10px', fontSize: 'var(--fs-sm)' } }, 'Lets the AI know what you said, so it can cut retakes and mistakes, not just silences.'));
  const whisperOn = t.engine === 'whisper', aaiOn = t.engine === 'assemblyai';

  // Whisper
  const size = h('select', { class: 'input', style: { width: 'auto' } },
    ...Object.entries(t.whisper.sizes).map(([k, mb]) => h('option', { value: k, selected: k === t.whisper.size },
      `${k[0].toUpperCase()}${k.slice(1)}, ${mb >= 1000 ? (mb / 1000).toFixed(1) + ' GB' : mb + ' MB'}${k === 'small' ? ' (recommended)' : ''}`)));
  const whisper = h('div', { class: `card ${whisperOn ? 'on' : ''}` },
    h('div', { class: 'top' }, h('b', {}, 'Whisper'), h('span', { class: 'pill ok' }, 'Free'),
      whisperOn && t.ready ? h('span', { class: 'pill ok', html: `${icon('check')}In use` }) : null),
    h('p', {}, 'Runs on this PC, nothing is uploaded. One download the first time. Slower than AssemblyAI on long takes.'));
  if (progress && !progress.failed) {
    const bar = h('div', { class: `progress ${progress.fraction < 0 ? 'indeterminate' : ''}` }, h('i', { style: { width: `${Math.max(0, progress.fraction) * 100}%` } }));
    whisper.append(bar, h('p', {}, progress.message));
  } else {
    if (progress && progress.failed) whisper.append(h('p', { style: { color: 'var(--error)' } }, progress.message));
    whisper.append(h('div', { class: 'row' }, size, h('button', { class: whisperOn && t.ready ? 'btn' : 'btn primary', onclick: async () => {
      progress = { fraction: -1, message: 'Starting…' };
      render();
      try {
        const res = await call('use_whisper', size.value);
        set({ ai: { ...state.ai, transcriber: res.transcriber } });
        if (!res.transcriber.downloading) progress = null;
      } catch (e) { progress = null; }
      render();
    } }, whisperOn && t.ready ? 'Use this size' : t.whisper.downloaded ? 'Use Whisper' : 'Download and use')));
  }

  // AssemblyAI
  const key = h('input', { class: 'input', type: 'password', placeholder: aaiOn ? 'Key saved. Paste a new one to replace it' : 'Paste your AssemblyAI API key' });
  const aai = h('div', { class: `card ${aaiOn ? 'on' : ''}` },
    h('div', { class: 'top' }, h('b', {}, 'AssemblyAI'), h('span', { class: 'pill brand' }, 'More accurate'),
      aaiOn ? h('span', { class: 'pill ok', html: `${icon('check')}In use` }) : null),
    h('p', {}, 'Better with mixed languages and fast speech. Needs your own key from assemblyai.com; the sound of each take is uploaded to them.'),
    h('div', { class: 'row' }, key, h('button', { class: 'btn', onclick: async e => {
      if (!key.value.trim()) return toast('Paste the key first.');
      e.currentTarget.disabled = true;
      try {
        const res = await call('use_assemblyai', key.value.trim());
        if (res.ok) { set({ ai: { ...state.ai, transcriber: res.transcriber } }); toast('AssemblyAI is connected', 'ok'); }
        else toast(res.message, 'error');
      } catch (err) { /* toast shown */ }
      render();
    } }, 'Connect')));

  wrap.append(h('div', { class: 'cards' }, whisper, aai));
  if (!t.engine) {
    wrap.append(h('div', { class: 'row', style: { marginTop: '8px' } }, h('button', { class: 'btn ghost', onclick: async () => {
      const res = await call('skip_transcriber');
      set({ ai: { ...state.ai, transcriber: res.transcriber } });
      render();
    } }, 'Not now, use the AI without a transcript')));
  }
  return wrap;
}
