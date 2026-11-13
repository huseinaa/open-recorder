// The right panel: Effect Controls and AI as two tabs.
import { h } from '../dom.js';
import { icon } from '../icons.js';
import { set, state, subscribe } from '../store.js';
import * as chat from './chat.js';
import * as inspector from './inspector.js';

export function mount(el) {
  const tabs = h('div', { class: 'tabs', role: 'tablist' });
  const body = h('div', { class: 'panel-body' });
  el.replaceChildren(h('div', { class: 'panel-head' }, tabs), body);
  let current = null, unmount = null;

  const render = () => {
    tabs.replaceChildren(
      h('button', { class: state.sideTab === 'inspector' ? 'on' : '', role: 'tab', onclick: () => set({ sideTab: 'inspector' }) }, 'Effect Controls'),
      h('button', { class: state.sideTab === 'ai' ? 'on' : '', role: 'tab', onclick: () => set({ sideTab: 'ai' }),
        html: `<span style="display:inline-flex;align-items:center;gap:6px">${icon('sparkle')}AI</span>` }));
    if (current !== state.sideTab) {
      unmount && unmount();
      current = state.sideTab;
      body.style.overflow = current === 'ai' ? 'hidden' : 'auto';
      unmount = (current === 'ai' ? chat : inspector).mount(body);
    }
  };
  render();
  const off = subscribe(keys => { if (keys.has('sideTab')) render(); });
  return () => { off(); unmount && unmount(); };
}
