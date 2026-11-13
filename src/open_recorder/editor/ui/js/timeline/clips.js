// The lanes and their clips, plus the thumbnail strips and waveforms painted inside them. Only the
// part of each clip that is in view gets painted, so a long clip at a deep zoom stays cheap.
import { quiet } from '../bridge.js';
import { h } from '../dom.js';
import { icon } from '../icons.js';
import { clipKind, set, state } from '../store.js';
import { laneTops, xAt } from './geometry.js';

const images = new Map();     // strip url -> Image
const asking = new Set();     // media keys whose waveform is on its way

function stripImage(url, onload) {
  let img = images.get(url);
  if (!img) {
    img = new Image();
    img.onload = onload;
    img.src = url;
    images.set(url, img);
  }
  return img.complete && img.naturalWidth ? img : null;
}

function wave(key, repaint) {
  if (state.waves[key]) return state.waves[key];
  if (!asking.has(key)) {
    asking.add(key);
    quiet('waveform', key).then(res => {
      if (res && res.ok && res.wave) set({ waves: { ...state.waves, [key]: res.wave } });
      repaint();
    });
  }
  return null;
}

const KIND_ICON = { face: 'face', screen: 'screen', video: 'video', image: 'image', audio: 'audio', blur: 'blur' };

export function renderLanes(container, repaint) {
  container.replaceChildren();
  const sel = new Set(state.selection);
  for (const { lane, h: height } of laneTops()) {
    const row = h('div', { class: `lane ${lane.locked ? 'locked' : ''}`, dataset: { lane: lane.id }, style: { height: `${height}px` } });
    for (const clip of lane.clips) {
      const kind = clipKind(lane, clip);
      const m = state.media[clip.media];
      const name = lane.kind === 'blur' ? `Blur ${Math.round(clip.strength)}` : (m?.name || clip.media);
      const w = (clip.src_out - clip.src_in) * state.pps;
      const el = h('div', {
        class: `clip k-${kind} ${sel.has(clip.id) ? 'selected' : ''} ${!clip.audio && lane.kind === 'audio' ? 'muted-audio' : ''}`,
        dataset: { clip: clip.id, lane: lane.id }, style: { left: `${xAt(clip.start)}px`, width: `${Math.max(3, w)}px` },
        title: name,
      }, h('canvas'), h('div', { class: 'label', html: `${icon(KIND_ICON[kind])}${clip.link ? icon('link') : ''}<span>${escape(name)}</span>` }),
      h('div', { class: 'edge l', dataset: { edge: 'l' } }), h('div', { class: 'edge r', dataset: { edge: 'r' } }));
      row.append(el);
    }
    container.append(row);
  }
  container.append(h('div', { class: 'tl-tail' }));
  paintVisible(container, repaint);
}

function escape(s) {
  return String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);
}

export function paintVisible(container, repaint) {
  const scroll = container.closest('.tl-scroll');
  if (!scroll) return;
  const v0 = scroll.scrollLeft, v1 = v0 + scroll.clientWidth;
  for (const el of container.querySelectorAll('.clip')) {
    const left = parseFloat(el.style.left), width = parseFloat(el.style.width);
    const a = Math.max(left, v0 - 50), b = Math.min(left + width, v1 + 50);
    const canvas = el.firstChild;
    if (b <= a) { canvas.width = 0; continue; }
    const { lane, clip } = lookup(el.dataset.lane, el.dataset.clip);
    if (!clip) continue;
    paintClip(canvas, lane, clip, a - left, b - a, el.clientHeight, repaint);
  }
}

function lookup(laneId, clipId) {
  const lane = state.project.lanes.find(l => l.id === laneId);
  return { lane, clip: lane && lane.clips.find(c => c.id === clipId) };
}

function paintClip(canvas, lane, clip, offset, width, height, repaint) {
  const dpr = window.devicePixelRatio || 1;
  canvas.style.left = `${offset}px`;
  canvas.style.width = `${width}px`;
  canvas.width = Math.ceil(width * dpr);
  canvas.height = Math.ceil(height * dpr);
  const g = canvas.getContext('2d');
  g.scale(dpr, dpr);
  const m = state.media[clip.media];
  if (!m || lane.kind === 'blur') return;
  const pps = state.pps;
  const showVideo = lane.kind === 'video' && clip.video && m.strip;
  if (showVideo) {
    const img = stripImage(m.strip.url, repaint);
    if (img) {
      const th = height, tw = m.strip.tile_w * (th / m.strip.tile_h);
      const start = Math.floor(offset / tw) * tw;
      g.globalAlpha = 0.9;
      for (let x = start; x < offset + width; x += tw) {
        const src = clip.src_in + x / pps;
        const i = m.kind === 'image' ? 0 : Math.min(m.strip.tiles - 1, Math.max(0, Math.floor(src / m.strip.every)));
        g.drawImage(img, i * m.strip.tile_w, 0, m.strip.tile_w, m.strip.tile_h, x - offset, 0, tw, th);
      }
      g.globalAlpha = 1;
      g.fillStyle = 'rgba(0,0,0,0.25)';
      g.fillRect(0, 0, width, 18);
    }
  }
  if (clip.audio && m.has_audio) {
    const data = wave(m.key, repaint);
    if (!data) return;
    const band = showVideo ? height * 0.38 : height - 20;
    const mid = height - band / 2 - 2;
    g.fillStyle = showVideo ? 'rgba(255,255,255,0.75)' : 'rgba(255,255,255,0.7)';
    const per = data.per_second, peaks = data.peaks;
    for (let x = 0; x < width; x += 2) {
      const s0 = clip.src_in + (offset + x) / pps, s1 = clip.src_in + (offset + x + 2) / pps;
      let peak = 0;
      for (let i = Math.floor(s0 * per); i <= Math.floor(s1 * per) && i < peaks.length; i++) peak = Math.max(peak, peaks[i] || 0);
      const hgt = Math.max(1, Math.sqrt(peak) * band * (clip.volume ?? 1));
      g.fillRect(x, mid - hgt / 2, 1.5, hgt);
    }
  }
}

