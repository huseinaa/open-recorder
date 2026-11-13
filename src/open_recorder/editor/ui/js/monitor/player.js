// Playback for the monitor. Each clip gets its own <video>, <img>, <audio> or blur layer, laid out
// in canvas pixels. A master clock drives the timeline, and each element is kept within a few
// frames of it. Good enough to judge cuts; the export is the exact render.
import { canvasSize, clipEnd, projectDuration, set, state } from '../store.js';

const EPS = 1e-4;
const DRIFT_PLAYING = 0.25;   // seconds of drift tolerated while playing before a re-seek
const LOOKAHEAD = 6;          // create elements for clips starting within this many seconds

export class Player {
  constructor(stage, audioBox) {
    this.stage = stage;
    this.audioBox = audioBox;
    this.items = [];
    this.els = new Map();     // clip id -> {el, media, kind}
    this.playing = false;
    this.t = 0;
    this.raf = 0;
    this.previews = new Map(); // clip id -> transform being dragged
  }

  setProject(project, media) {
    this.project = project;
    this.media = media;
    const items = [];
    if (project) {
      project.lanes.forEach((lane, i) => {
        for (const clip of lane.clips) items.push({ lane, clip, z: 1000 - i, end: clipEnd(clip) });
      });
    }
    this.items = items;
    const live = new Set(items.map(i => i.clip.id));
    for (const [id, rec] of this.els) {
      if (!live.has(id) || rec.media !== this.mediaUrl(items.find(i => i.clip.id === id))) this.drop(id);
    }
    this.sync(true);
  }

  mediaUrl(item) {
    if (!item) return null;
    return item.lane.kind === 'blur' ? 'blur' : (this.media[item.clip.media] || {}).url || null;
  }

  drop(id) {
    const rec = this.els.get(id);
    if (!rec) return;
    if (rec.video) { rec.video.pause(); rec.video.removeAttribute('src'); rec.video.load(); }
    rec.el.remove();
    this.els.delete(id);
  }

  ensure(item) {
    let rec = this.els.get(item.clip.id);
    if (rec) return rec;
    const { lane, clip } = item;
    const m = this.media[clip.media] || {};
    let el, video = null;
    if (lane.kind === 'blur') {
      el = document.createElement('div');
      el.className = 'layer blur';
    } else if (lane.kind === 'audio' || !clip.video || m.kind === 'audio') {
      el = video = document.createElement('audio');
      el.preload = 'auto';
      el.src = m.url;
      this.audioBox.append(el);
      rec = { el, video, media: m.url, audioOnly: true };
      this.els.set(clip.id, rec);
      return rec;
    } else if (m.kind === 'image') {
      el = document.createElement('div');
      el.className = 'layer';
      const img = document.createElement('img');
      img.src = m.url;
      img.draggable = false;
      el.append(img);
    } else {
      el = document.createElement('div');
      el.className = 'layer';
      video = document.createElement('video');
      video.preload = 'auto';
      video.playsInline = true;
      video.disablePictureInPicture = true;
      video.src = m.url;
      el.append(video);
    }
    el.dataset.clip = clip.id;
    this.stage.append(el);
    rec = { el, video, media: this.mediaUrl(item) };
    this.els.set(clip.id, rec);
    return rec;
  }

  layout(item, rec) {
    if (rec.audioOnly) return;
    const [W, H] = canvasSize(this.project);
    const t = this.previews.get(item.clip.id) || item.clip.transform;
    const s = rec.el.style;
    const w = t.w * W, h = t.h * H;
    s.left = `${t.x * W}px`; s.top = `${t.y * H}px`; s.width = `${w}px`; s.height = `${h}px`;
    s.zIndex = item.z;
    s.opacity = t.opacity ?? 1;
    const r = (t.radius ?? 0.18) * Math.min(w, h);
    s.borderRadius = t.mask === 'circle' ? '50%' : t.mask === 'square' ? `${r}px` : '0';
    s.clipPath = t.mask === 'circle' ? `circle(${Math.min(w, h) / 2}px at 50% 50%)` : t.mask === 'square' ? `inset(0 round ${r}px)` : 'none';
    rec.el.classList.toggle('cover', t.fit === 'cover');
    if (item.lane.kind === 'blur') s.setProperty('--blur', `${item.clip.strength / 2}px`);
  }

  preview(id, transform) {
    if (transform) this.previews.set(id, transform); else this.previews.delete(id);
    const item = this.items.find(i => i.clip.id === id);
    const rec = this.els.get(id);
    if (item && rec) this.layout(item, rec);
  }

  sync(force = false) {
    const t = this.t;
    for (const item of this.items) {
      const { clip, lane } = item;
      const active = clip.start - EPS <= t && t < item.end - EPS;
      const near = clip.start > t && clip.start - t < LOOKAHEAD;
      if (!active && !near && !this.els.has(clip.id)) continue;
      const rec = this.ensure(item);
      this.layout(item, rec);
      const visible = active && !lane.hidden;
      if (!rec.audioOnly) rec.el.style.display = visible ? '' : 'none';
      const v = rec.video;
      if (!v) continue;
      v.muted = !clip.audio || lane.muted;
      v.volume = Math.min(1, Math.max(0, clip.volume ?? 1));
      const desired = clip.src_in + (t - clip.start);
      if (active) {
        if (this.playing) {
          if (v.paused) { v.currentTime = desired; v.play().catch(() => {}); }
          else if (Math.abs(v.currentTime - desired) > DRIFT_PLAYING) v.currentTime = desired;
        } else {
          if (!v.paused) v.pause();
          if (force || Math.abs(v.currentTime - desired) > 0.02) v.currentTime = desired;
        }
      } else {
        if (!v.paused) v.pause();
        if (near && Math.abs(v.currentTime - clip.src_in) > 0.05 && v.readyState >= 1) v.currentTime = clip.src_in;
      }
    }
  }

  seek(t) {
    this.t = Math.max(0, t);
    if (this.playing) { this.t0 = this.t; this.base = performance.now(); }
    this.sync(true);
  }

  play() {
    const end = projectDuration(this.project);
    if (end <= 0) return;
    if (this.t >= end - 0.05) this.t = 0;
    this.playing = true;
    this.t0 = this.t;
    this.base = performance.now();
    set({ playing: true });
    this.sync(true);
    const loop = () => {
      if (!this.playing) return;
      this.t = this.t0 + (performance.now() - this.base) / 1000;
      if (this.t >= end) { this.t = end; this.pause(); set({ playhead: end }); return; }
      set({ playhead: this.t });
      this.sync(false);
      this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
  }

  pause() {
    this.playing = false;
    cancelAnimationFrame(this.raf);
    for (const rec of this.els.values()) if (rec.video && !rec.video.paused) rec.video.pause();
    if (state.playing) set({ playing: false });
  }

  toggle() { this.playing ? this.pause() : this.play(); }

  destroy() {
    this.pause();
    for (const id of [...this.els.keys()]) this.drop(id);
  }
}
