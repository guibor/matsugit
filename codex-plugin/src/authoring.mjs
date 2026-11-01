import {Decoration, ViewPlugin, gutter, GutterMarker} from '@codemirror/view';
import {RangeSetBuilder} from '@codemirror/state';
import {foldService} from '@codemirror/language';
import {autocompletion, startCompletion} from '@codemirror/autocomplete';
import {structure} from './structure.mjs';

const recipes = __FOLIOFORGE_TEMPLATES__;
const roleGroup = role => ({Section: 'section', Slide: 'slide', Claim: 'claim', Region: 'region',
  takeaway: 'takeaway', source: 'notes', notes: 'notes', 'agent-comment': 'review'}[role] || 'layout');

class Marker extends GutterMarker {
  constructor(role, closing) { super(); this.role = role; this.closing = closing; }
  eq(other) { return other.role === this.role && other.closing === this.closing; }
  toDOM() {
    const el = document.createElement('span');
    el.className = `ff-gutter-marker ff-role-${roleGroup(this.role)}`;
    el.textContent = this.closing ? '-' : ({Section: 'S', Slide: 'T', Claim: 'C', Region: 'R', takeaway: '!', 'agent-comment': 'A'}[this.role] || '+');
    el.title = `${this.closing ? 'End ' : ''}${this.role}`;
    el.setAttribute('aria-label', el.title);
    return el;
  }
}

export function authoringExtensions({isOrg, enabled}) {
  // Folding asks about each visible line; parse once per document, not per line.
  const cache = new WeakMap();
  const parsed = state => {
    const org = isOrg(), previous = cache.get(state.doc);
    if (previous?.org === org) return previous.result;
    const result = structure(state.doc.toString(), org);
    cache.set(state.doc, {org, result});
    return result;
  };
  const semantic = ViewPlugin.fromClass(class {
    constructor(view) { this.build(view); }
    update(update) { if (update.docChanged) this.build(update.view); }
    build(view) {
      this.outline = parsed(view.state);
      const lines = new Map(this.outline.markers.map(item => [view.state.doc.lineAt(item.from).from, item]));
      const marks = new RangeSetBuilder(), decorations = [];
      for (const [from, item] of [...lines].sort((a, b) => a[0] - b[0])) {
        marks.add(from, from, new Marker(item.role, item.closing));
        decorations.push(Decoration.line({class: `ff-source-role ff-role-${roleGroup(item.role)}`}).range(from));
      }
      this.markers = marks.finish(); this.decorations = Decoration.set(decorations);
    }
  }, {decorations: value => value.decorations});
  return [semantic,
    gutter({class: 'ff-semantic-gutter', markers: view => view.plugin(semantic).markers}),
    foldService.of((state, from) => {
      const block = parsed(state).blocks.find(block => block.from === from);
      return block ? {from: block.startEnd, to: block.to} : null;
    }),
    autocompletion({override: [context => {
      if (!enabled()) return null;
      const line = context.state.doc.lineAt(context.pos);
      const prefix = line.text.slice(0, context.pos - line.from);
      const slash = /^\s*\/[-\w]*$/.test(prefix);
      if (!slash && !context.explicit) return null;
      const outline = parsed(context.state);
      if (outline.literals.some(range => context.pos >= range.from && context.pos <= range.to)
          || outline.blocks.some(block => block.role === 'agent-comment' && context.pos > block.from && context.pos < block.to)) return null;
      return {from: slash ? line.from + prefix.indexOf('/') : context.pos,
        validFor: /^\/[-\w]*$/,
        options: Object.entries(recipes).map(([name, recipe]) => ({
          label: '/' + name, detail: recipe.kind, type: 'keyword',
          info: recipe[isOrg() ? 'org' : 'markdown'],
          apply(view, _completion, from, to) {
            let value = recipe[isOrg() ? 'org' : 'markdown'].replaceAll('review-INSERT_ID', 'review-' + crypto.randomUUID().replaceAll('-', '').slice(0, 12));
            const before = view.state.doc.sliceString(0, from);
            if (before && !before.endsWith('\n\n')) value = (before.endsWith('\n') ? '\n' : '\n\n') + value;
            if (to < view.state.doc.length && !view.state.doc.sliceString(to, to + 1).startsWith('\n')) value += '\n';
            view.dispatch({changes: {from, to, insert: value}, selection: {anchor: from + value.length}, userEvent: 'input.complete'});
            view.focus();
          },
        }))};
    }], maxRenderedOptions: 30, aboveCursor: true}),
  ];
}

export function insertMenu(editor) { editor.focus(); startCompletion(editor); }
