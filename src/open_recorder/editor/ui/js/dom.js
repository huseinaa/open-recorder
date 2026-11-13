// Small DOM helpers shared by every panel: building elements, toasts, modals, menus, formatting.
import { icon } from './icons.js';

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on')) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function iconButton(name, title, onclick, extra = {}) {
  return h('button', { class: `icon-btn ${extra.class || ''}`, title, 'aria-label': title, html: icon(name), onclick,
    disabled: extra.disabled });
}

export function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

// ---------- toasts ----------
export function toast(text, kind = '', action = null, ms = 4500) {
  const box = document.getElementById('toasts');
  const el = h('div', { class: `toast ${kind}` }, h('span', {}, text));
  if (action) el.append(h('button', { class: 'btn', onclick: () => { action.run(); el.remove(); } }, action.label));
  el.append(h('button', { class: 'icon-btn', 'aria-label': 'Dismiss', html: icon('close'), onclick: () => el.remove() }));
  box.append(el);
  setTimeout(() => el.remove(), action ? ms * 2 : ms);
  return el;
}

// ---------- modal ----------
export function modal(build, { wide = false, onClose } = {}) {
  const back = h('div', { class: 'modal-backdrop' });
  const box = h('div', { class: `modal ${wide ? 'wide' : ''}`, role: 'dialog', 'aria-modal': 'true' });
  const close = () => { back.remove(); document.removeEventListener('keydown', onKey, true); onClose && onClose(); };
  const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
  back.addEventListener('mousedown', e => { if (e.target === back) close(); });
  document.addEventListener('keydown', onKey, true);
  box.append(...[].concat(build(close)));
  back.append(box);
  document.body.append(back);
  const first = box.querySelector('input, textarea, button.primary');
  first && setTimeout(() => first.focus(), 30);
  return close;
}

// ---------- menu ----------
export function menu(x, y, items) {
  document.querySelectorAll('.menu').forEach(m => m.remove());
  const el = h('div', { class: 'menu', role: 'menu' });
  for (const item of items) {
    if (item === '-') { el.append(h('hr')); continue; }
    el.append(h('button', { role: 'menuitem', html: (item.icon ? icon(item.icon) : '') + `<span>${escapeHtml(item.label)}</span>`,
      onclick: () => { el.remove(); item.run(); } }));
  }
  document.body.append(el);
  const r = el.getBoundingClientRect();
  el.style.left = `${Math.min(x, innerWidth - r.width - 8)}px`;
  el.style.top = `${Math.min(y, innerHeight - r.height - 8)}px`;
  setTimeout(() => document.addEventListener('mousedown', function off(e) {
    if (!el.contains(e.target)) { el.remove(); document.removeEventListener('mousedown', off); }
  }), 0);
}

// ---------- formatting ----------
export function timecode(t, fps = 30) {
  t = Math.max(0, t || 0);
  const frames = Math.floor((t - Math.floor(t)) * fps + 1e-6);
  const s = Math.floor(t) % 60, m = Math.floor(t / 60) % 60, hrs = Math.floor(t / 3600);
  const p = n => String(n).padStart(2, '0');
  return `${p(hrs)}:${p(m)}:${p(s)}:${p(frames)}`;
}

export function duration(t) {
  t = Math.max(0, Math.round(t || 0));
  const m = Math.floor(t / 60), s = t % 60;
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
}

export function when(unix) {
  const d = new Date(unix * 1000), now = new Date();
  const days = Math.floor((now - d) / 86400000);
  const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  if (days < 1 && d.getDate() === now.getDate()) return `Today, ${time}`;
  if (days < 2) return `Yesterday, ${time}`;
  return d.toLocaleDateString([], { day: 'numeric', month: 'short', year: d.getFullYear() === now.getFullYear() ? undefined : 'numeric' });
}

// "20261112_153012" -> "3:30 PM"
export function takeLabel(id) {
  const m = /^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/.exec(id || '');
  if (!m) return id;
  const d = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]);
  return d.toLocaleString([], { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
}

export function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }
