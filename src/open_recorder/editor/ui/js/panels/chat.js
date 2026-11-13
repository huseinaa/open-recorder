// The AI tab: connect first, then chat. Every answer that changed the timeline shows what changed
// and can be undone in one click.
import { undo } from '../actions.js';
import { call, quiet } from '../bridge.js';
import { duration, h, iconButton } from '../dom.js';
import { icon } from '../icons.js';
import { loadState, set, state, subscribe } from '../store.js';
import { setupView } from './setup.js';

const SUGGESTIONS = [
  'Cut the silences',
  'Remove the repeated takes',
  'Make it vertical for Reels',
  'Blur the top right corner for the first 5 seconds',
  'Put the sound of the face clip on its own lane',
];

export function mount(el) {
  let setup = null;
  const render = () => {
    setup && setup.dispose && setup.dispose();
    setup = null;
    const ai = state.ai;
    if (!ai || !ai.ready || !ai.transcriber.engine) {
      setup = setupView();
      el.replaceChildren(h('div', { class: 'ai', style: { overflow: 'auto' } },
        h('div', { class: 'ai-intro' }, h('h3', {}, 'Edit by asking'),
          h('p', {}, 'Tell the AI what to cut, move or blur, and it changes the timeline for you. It runs on your own Claude or ChatGPT subscription.'),
          setup)));
      return;
    }
    el.replaceChildren(chatView());
  };
  render();
  if (state.project && !state.chat.length) quiet('chat_history').then(res => res && res.ok && set({ chat: res.chat }));
  const off = subscribe(keys => {
    if (keys.has('ai')) render();
    else if (keys.has('chat') || keys.has('aiBusy')) refreshMessages();
    else if (keys.has('transcripts') || keys.has('media')) refreshStatus();
  });
  return () => { off(); setup && setup.dispose && setup.dispose(); };
}

let messagesEl = null, statusEl = null, suggestEl = null;

function chatView() {
  messagesEl = h('div', { class: 'chat', 'aria-live': 'polite' });
  statusEl = h('div', { class: 'ai-status' });
  suggestEl = h('div', { class: 'suggest' });
  const input = h('textarea', { class: 'input', rows: '3', placeholder: 'Ask for an edit, like "cut the silences" or "remove the first take"' });
  const send = async () => {
    const text = input.value.trim();
    if (!text || state.aiBusy) return;
    input.value = '';
    await ask(text);
  };
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    e.stopPropagation();
  });
  const provider = state.ai.providers[state.ai.primary] || Object.values(state.ai.providers).find(p => p.connected);
  const view = h('div', { class: 'ai' }, statusEl, messagesEl, suggestEl,
    h('div', { class: 'composer' },
      h('div', { class: 'box' }, input, h('button', { class: 'icon-btn send', title: 'Send (Enter)', onclick: send, html: icon('send') })),
      h('div', { class: 'foot' }, h('span', {}, `${provider ? provider.label : 'AI'} on your subscription. Every edit is one Ctrl+Z.`),
        h('span', { style: { flex: '1' } }),
        iconButton('trash', 'Clear the chat', async () => { const res = await call('chat_clear'); set({ chat: res.chat }); }))));
  refreshMessages();
  refreshStatus();
  return view;
}

async function ask(text) {
  set({ aiBusy: true, chat: [...state.chat, { role: 'user', text }] });
  const res = await quiet('chat_send', text, state.playhead, state.selection);
  if (res && res.state) loadState(res.state);
  set({ aiBusy: false, chat: res && res.chat ? res.chat : [...state.chat, { role: 'assistant', text: (res && res.error) || 'No answer', error: true }] });
}

function refreshMessages() {
  if (!messagesEl) return;
  messagesEl.replaceChildren();
  const chat = state.chat || [];
  const lastChange = [...chat].reverse().find(m => m.role === 'assistant' && m.changed);
  for (const m of chat) {
    if (m.role === 'user') { messagesEl.append(h('div', { class: 'msg user' }, m.text)); continue; }
    const el = h('div', { class: `msg assistant ${m.error ? 'error' : ''}` }, h('div', { class: 'text' }, m.text));
    if (m.changed) {
      const diff = (m.after ?? 0) - (m.before ?? 0);
      const what = Math.abs(diff) >= 0.05
        ? `<b>${diff < 0 ? `${Math.abs(diff).toFixed(1)} s shorter` : `${diff.toFixed(1)} s longer`}</b>, now ${duration(m.after)}`
        : `<b>${m.ops} change${m.ops === 1 ? '' : 's'}</b> made`;
      const card = h('div', { class: 'change-card' }, h('span', { class: 'what', html: what }));
      if (m === lastChange && state.undo && state.undo.startsWith('AI:')) card.append(h('button', { class: 'btn', onclick: undo, html: `${icon('undo')}<span>Undo</span>` }));
      el.append(card);
    }
    const meta = [m.provider && (m.provider === 'claude' ? 'Claude' : 'Codex'), m.note, m.changed && !m.transcribed ? 'no transcript yet, worked from the silences' : ''].filter(Boolean);
    if (meta.length) el.append(h('div', { class: 'meta' }, meta.join('. ')));
    messagesEl.append(el);
  }
  if (state.aiBusy) {
    const p = state.ai.providers[state.ai.primary];
    messagesEl.append(h('div', { class: 'msg assistant' }, h('div', { class: 'thinking' }, h('span', { class: 'spinner' }), `${p ? p.label : 'The AI'} is editing…`)));
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
  suggestEl.replaceChildren(...(chat.length ? [] : SUGGESTIONS.map(s => h('button', { onclick: () => ask(s) }, s))));
}

function refreshStatus() {
  if (!statusEl) return;
  const t = state.ai.transcriber;
  const voices = Object.values(state.media).filter(m => m.voice);
  const used = new Set(state.project ? state.project.lanes.flatMap(l => l.clips.map(c => c.media)) : []);
  const onTimeline = voices.filter(m => used.has(m.key));
  const tr = onTimeline.map(m => state.transcripts[m.key] || null);
  const working = tr.filter(x => x && (x.state === 'working' || x.state === 'queued'));
  const done = tr.filter(x => x && x.state === 'done').length;
  statusEl.replaceChildren();
  if (t.engine === 'skip' || !t.engine) {
    statusEl.append(h('span', {}, 'No transcript: the AI can cut silences but cannot hear words.'),
      h('button', { class: 'btn ghost', onclick: () => set({ ai: { ...state.ai, transcriber: { ...t, engine: '' } } }) }, 'Set up'));
  } else if (working.length) {
    const p = working.find(x => x.state === 'working');
    statusEl.append(h('span', { class: 'spinner' }), h('span', {}, `Transcribing ${working.length} take${working.length > 1 ? 's' : ''}`),
      h('div', { class: 'progress' }, h('i', { style: { width: `${Math.round(((p && p.progress) || 0) * 100)}%` } })));
  } else if (onTimeline.length && done < onTimeline.length) {
    statusEl.append(h('span', {}, `${onTimeline.length - done} take${onTimeline.length - done > 1 ? 's' : ''} not transcribed`),
      h('button', { class: 'btn ghost', onclick: () => quiet('transcribe') }, 'Transcribe'));
  } else if (onTimeline.length) {
    statusEl.append(h('span', { class: 'pill ok', html: `${icon('check')}Transcribed` }), h('span', {}, 'The AI knows what you said.'));
  } else {
    statusEl.append(h('span', {}, 'Add a take to the timeline, then ask for an edit.'));
  }
}
