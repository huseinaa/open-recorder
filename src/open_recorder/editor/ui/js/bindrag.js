// Dragging a take or a file from the Project panel onto the timeline, with plain pointer events.
// HTML5 drag and drop runs through Windows' own drag and drop inside WebView2, which did not
// deliver these drops reliably, and doing it ourselves lets the timeline show where it will land.
// Files dragged in from Explorer still use the real drag and drop (see main.js).
import { h } from './dom.js';

const listeners = new Set();
const START_PX = 5;  // how far the pointer moves before a press becomes a drag (so double-click still works)

/** fn({ phase: 'move' | 'drop' | 'cancel', payload, x, y }) for every drag; returns the unsubscribe. */
export function onBinDrag(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Call from a pointerdown on a Project panel item. */
export function startBinDrag(e, payload, label) {
  if (e.button !== 0) return;
  const x0 = e.clientX, y0 = e.clientY;
  let ghost = null;
  const emit = (phase, x, y) => listeners.forEach(fn => fn({ phase, payload, x, y }));

  const move = ev => {
    if (!ghost) {
      if (Math.hypot(ev.clientX - x0, ev.clientY - y0) < START_PX) return;
      ghost = h('div', { class: 'drag-ghost' }, label);
      document.body.append(ghost);
      document.body.classList.add('bin-dragging');
    }
    ghost.style.transform = `translate(${ev.clientX + 14}px, ${ev.clientY + 12}px)`;
    emit('move', ev.clientX, ev.clientY);
  };
  const finish = (phase, x, y) => {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
    window.removeEventListener('pointercancel', cancel);
    window.removeEventListener('keydown', escape, true);
    if (!ghost) return;
    ghost.remove();
    document.body.classList.remove('bin-dragging');
    emit(phase, x, y);
  };
  const up = ev => finish('drop', ev.clientX, ev.clientY);
  const cancel = () => finish('cancel', -1, -1);
  const escape = ev => {
    if (ev.key !== 'Escape' || !ghost) return;
    ev.stopPropagation();
    cancel();
  };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
  window.addEventListener('pointercancel', cancel);
  window.addEventListener('keydown', escape, true);
}
