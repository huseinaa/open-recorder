// The only way the page talks to Python: call() for requests, on() for pushed events.
import { toast } from './dom.js';
import { loadState, state } from './store.js';

export function ready() {
  return new Promise(resolve => {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.boot) return resolve();
    window.addEventListener('pywebviewready', () => resolve(), { once: true });
  });
}

export async function call(name, ...args) {
  let res;
  try {
    res = await window.pywebview.api[name](...args);
  } catch (e) {
    res = { ok: false, error: String(e && e.message || e) };
  }
  if (!res || res.ok === false) {
    const message = (res && res.error) || 'Something went wrong';
    toast(message, 'error');
    const err = new Error(message);
    err.handled = true;
    throw err;
  }
  return res;
}

// quiet(): the same call, but the caller deals with the error itself
export async function quiet(name, ...args) {
  try { return await window.pywebview.api[name](...args); } catch (e) { return { ok: false, error: String(e) }; }
}

// Apply ops to the open project and take the new state. Returns the notes, or null on error.
export async function edit(ops, label = 'Edit') {
  if (!state.project) return null;
  try {
    const res = await call('apply', ops, label);
    loadState(res.state);
    return res.notes || [];
  } catch (e) {
    return null;
  }
}

const handlers = {};
window.OR = {
  emit(name, payload) { (handlers[name] || []).forEach(fn => { try { fn(payload); } catch (e) { console.error(e); } }); },
};

export function on(name, fn) {
  (handlers[name] ||= []).push(fn);
}
