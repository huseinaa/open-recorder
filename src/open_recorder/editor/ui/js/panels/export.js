// Export: name, quality, then a progress bar, then show the file.
import { pause } from '../actions.js';
import { call, on, quiet } from '../bridge.js';
import { duration, h, modal } from '../dom.js';
import { icon } from '../icons.js';
import { canvasSize, projectDuration, state } from '../store.js';

const QUALITY = [['high', 'High', 'Biggest file, for YouTube'], ['normal', 'Normal', 'Good for most uses'], ['small', 'Small', 'For sharing quickly']];
let listener = null;
on('export-progress', p => listener && listener('progress', p));
on('export-done', p => listener && listener('done', p));

export async function openExport() {
  pause();
  if (projectDuration() <= 0) return modal(close => [h('h2', {}, 'Nothing to export yet'),
    h('p', { class: 'sub' }, 'Put a take on the timeline first.'),
    h('div', { class: 'actions' }, h('button', { class: 'btn primary', onclick: close }, 'OK'))]);
  const prefs = (await quiet('prefs'))?.prefs || {};
  let quality = prefs.export_quality || 'normal';
  modal(close => {
    const body = h('div');
    const name = h('input', { class: 'input', value: state.name, maxlength: 80 });
    const [W, H] = canvasSize();
    const form = () => {
      const seg = h('div', { class: 'seg' }, ...QUALITY.map(([v, label, hint]) =>
        h('button', { class: v === quality ? 'on' : '', title: hint, onclick: () => { quality = v; body.replaceChildren(...form()); } }, label)));
      return [
        h('h2', {}, 'Export video'),
        h('p', { class: 'sub tabular' }, `MP4, ${W} × ${H}, ${state.project.sequence.fps} fps, ${duration(projectDuration())}. Saved in the project's Exports folder.`),
        h('div', { class: 'field' }, h('label', {}, 'File name'), name),
        h('div', { class: 'field' }, h('label', {}, 'Quality'), seg),
        h('div', { class: 'actions' }, h('button', { class: 'btn', onclick: close }, 'Cancel'),
          h('button', { class: 'btn primary', onclick: start, html: `${icon('export')}<span>Export</span>` })),
      ];
    };
    const running = (fraction) => [
      h('h2', {}, 'Exporting…'),
      h('p', { class: 'sub' }, 'You can keep editing; the export uses the timeline as it was when you pressed Export.'),
      h('div', { class: 'progress' }, h('i', { style: { width: `${Math.round(fraction * 100)}%` } })),
      h('p', { class: 'muted tabular', style: { marginTop: '8px' } }, `${Math.round(fraction * 100)}%`),
      h('div', { class: 'actions' }, h('button', { class: 'btn', onclick: () => quiet('export_cancel') }, 'Cancel export')),
    ];
    async function start() {
      try {
        await call('export_start', name.value.trim() || state.name, quality);
        body.replaceChildren(...running(0));
        listener = (kind, p) => {
          if (kind === 'progress') body.replaceChildren(...running(p.fraction));
          else {
            listener = null;
            body.replaceChildren(...(p.ok ? [
              h('h2', {}, 'Exported'),
              h('p', { class: 'sub' }, p.path),
              h('div', { class: 'actions' }, h('button', { class: 'btn', onclick: () => call('reveal', p.path) }, 'Show in folder'),
                h('button', { class: 'btn primary', onclick: () => { call('open_path', p.path); close(); } }, 'Play it')),
            ] : [
              h('h2', {}, p.message === 'Export cancelled' ? 'Export cancelled' : 'Export failed'),
              h('p', { class: 'sub', style: { userSelect: 'text' } }, p.message),
              h('div', { class: 'actions' }, h('button', { class: 'btn', onclick: close }, 'Close'),
                h('button', { class: 'btn primary', onclick: () => body.replaceChildren(...form()) }, 'Try again')),
            ]));
          }
        };
      } catch (e) { /* toast shown */ }
    }
    body.replaceChildren(...form());
    return body;
  });
}
