// Settings: the root folder, takes landing on the timeline, the AI and its model.
import { call, quiet } from '../bridge.js';
import { h, modal } from '../dom.js';
import { set, state } from '../store.js';
import { setupView } from './setup.js';

const CLAUDE_MODELS = [['sonnet', 'Sonnet (fast, recommended)'], ['opus', 'Opus (strongest, slower)'], ['haiku', 'Haiku (fastest)'], ['', 'Claude Code default']];
const EFFORTS = [['low', 'Low'], ['medium', 'Medium'], ['high', 'High']];

export async function openSettings() {
  const [summary, prefsRes] = await Promise.all([quiet('ai_summary'), quiet('prefs')]);
  if (summary && summary.ok) set({ ai: summary });
  const prefs = (prefsRes && prefsRes.prefs) || {};
  let setup = null;
  modal(close => {
    const root = state.boot?.root || '';
    const autoAdd = h('button', { class: `switch ${prefs.auto_add !== false ? 'on' : ''}`, role: 'switch', 'aria-label': 'Add new takes to the timeline' });
    autoAdd.addEventListener('click', async () => {
      prefs.auto_add = prefs.auto_add === false;
      autoAdd.classList.toggle('on', prefs.auto_add !== false);
      await quiet('save_prefs', { auto_add: prefs.auto_add });
    });
    const opts = state.ai?.options || {};
    const pick = (key, list, value) => {
      const sel = h('select', { class: 'input' }, ...list.map(([v, label]) => h('option', { value: v, selected: v === value }, label)));
      sel.addEventListener('change', async () => set({ ai: await call('ai_options', { [key]: sel.value }) }));
      return sel;
    };
    setup = setupView();
    return [
      h('h2', {}, 'Settings'),
      h('p', { class: 'sub' }, `Open Recorder ${state.boot?.version || ''}`),
      h('div', { class: 'field' }, h('label', {}, 'Recordings and projects folder'),
        h('div', { style: { display: 'flex', gap: '8px', alignItems: 'center' } },
          h('span', { style: { flex: '1', userSelect: 'text', wordBreak: 'break-all' } }, root || 'Not chosen yet'),
          h('button', { class: 'btn', onclick: async () => {
            const res = await call('choose_root', false);
            if (!res.cancelled) { set({ boot: res }); close(); }
          } }, 'Change'))),
      h('div', { class: 'field' }, h('label', {}, 'Recording into a project'),
        h('div', { style: { display: 'flex', gap: '10px', alignItems: 'center' } }, autoAdd, h('span', {}, 'Put each new take at the end of the timeline'))),
      h('div', { class: 'field' }, h('label', {}, 'Claude model and effort'),
        h('div', { style: { display: 'flex', gap: '8px' } }, pick('claude_model', CLAUDE_MODELS, opts.claude_model), pick('claude_effort', EFFORTS, opts.claude_effort))),
      setup,
      h('div', { class: 'actions' }, h('button', { class: 'btn primary', onclick: close }, 'Done')),
    ];
  }, { wide: true, onClose: () => setup && setup.dispose && setup.dispose() });
}
