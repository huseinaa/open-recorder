// Keyboard shortcuts, the Premiere ones where they exist.
import { deleteSelected, record, redo, seek, splitAtPlayhead, step, togglePlay, undo, pause, zoom } from './actions.js';
import { openExport } from './nav.js';
import { projectDuration, set, state } from './store.js';

const TOOLS = { v: 'select', c: 'razor', b: 'ripple', h: 'hand' };

function typing(e) {
  const t = e.target;
  return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
}

export function install() {
  document.addEventListener('keydown', e => {
    if (state.screen !== 'editor' || typing(e) || document.querySelector('.modal-backdrop')) return;
    const k = e.key.toLowerCase();
    const ctrl = e.ctrlKey || e.metaKey;
    let handled = true;
    if (ctrl && k === 'z' && !e.shiftKey) undo();
    else if (ctrl && (k === 'y' || (k === 'z' && e.shiftKey))) redo();
    else if (ctrl && k === 'e') openExport();
    else if (ctrl && k === 'a') set({ selection: state.project.lanes.flatMap(l => l.clips.map(c => c.id)) });
    else if (ctrl) handled = false;
    else if (k === ' ') togglePlay();
    else if (TOOLS[k]) set({ tool: TOOLS[k] });
    else if (k === 's') splitAtPlayhead();
    else if (k === 'delete' || k === 'backspace') deleteSelected(e.shiftKey);
    else if (k === 'arrowleft') step(e.shiftKey ? -(state.project.sequence.fps || 30) : -1);
    else if (k === 'arrowright') step(e.shiftKey ? (state.project.sequence.fps || 30) : 1);
    else if (k === 'home') { pause(); seek(0); }
    else if (k === 'end') { pause(); seek(projectDuration()); }
    else if (k === 'k') pause();
    else if (k === 'l') { if (!state.playing) togglePlay(); }
    else if (k === 'j') { pause(); seek(state.playhead - 1); }
    else if (k === 'r') record();
    else if (k === '=' || k === '+') zoom(1.25);
    else if (k === '-') zoom(0.8);
    else if (k === 'escape') set({ selection: [] });
    else handled = false;
    if (handled) e.preventDefault();
  });
}
