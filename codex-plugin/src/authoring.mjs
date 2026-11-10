import {Decoration, ViewPlugin, gutter, GutterMarker, WidgetType} from '@codemirror/view';
import {RangeSetBuilder, StateEffect, StateField} from '@codemirror/state';
import {foldService} from '@codemirror/language';
import {autocompletion, startCompletion, snippet} from '@codemirror/autocomplete';
import {structure, slideBoundaries} from './structure.mjs';
import {roleDescription} from './role-help.mjs';
import {chartTypes, wrapElement, snippetTemplate, ratioLine} from './insertions.mjs';

const recipes = __MATSUGIT_TEMPLATES__;
export const compactMarkup = StateEffect.define();
export const slideSeparators = StateEffect.define();
const separatorState = StateField.define({create: () => false,
  update(value, tr) { for (const effect of tr.effects) if (effect.is(slideSeparators)) value = effect.value; return value; }});
const compactState = StateField.define({create: () => false,
  update(value, tr) { for (const effect of tr.effects) if (effect.is(compactMarkup)) value = effect.value; return value; }});
const roleGroup = role => ({Section: 'section', Slide: 'slide', Claim: 'claim', Region: 'region',
  takeaway: 'takeaway', source: 'notes', notes: 'notes', 'agent-comment': 'review'}[role] || 'layout');

class Marker extends GutterMarker {
  constructor(role, closing) { super(); this.role = role; this.closing = closing; }
  eq(other) { return other.role === this.role && other.closing === this.closing; }
  toDOM() {
    const el = document.createElement('button');
    el.type = 'button';
    el.className = `ff-gutter-marker ff-role-${roleGroup(this.role)}`;
    el.textContent = this.closing ? '-' : ({Section: 'S', Slide: 'T', Claim: 'C', Region: 'R', takeaway: '!', 'agent-comment': 'A'}[this.role] || '+');
    el.title = `${this.closing ? 'End ' : ''}${this.role}`;
    el.dataset.role = this.role; el.dataset.closing = String(!!this.closing);
    el.setAttribute('aria-label', roleDescription(this.role, this.closing).label);
    return el;
  }
}

class BlockLabel extends WidgetType {
  constructor(item, org, from, to, line, count, adjustable) {
    super(); Object.assign(this, {item, org, from, to, line, count, adjustable});
  }
  eq(other) { return this.item.role === other.item.role && this.item.closing === other.item.closing &&
    this.from === other.from && this.line === other.line && this.count === other.count && this.adjustable === other.adjustable; }
  toDOM(view) {
    const el = document.createElement('span');
    el.className = 'ff-block-label';
    const label = this.item.role.replaceAll('-', ' ');
    el.textContent = (this.item.closing ? 'End ' : '') + label[0].toUpperCase() + label.slice(1);
    if (this.item.role === 'chart' && !this.item.closing) {
      const type = /\btype[= ]+"?([a-z0-9]+)/.exec(this.line)?.[1];
      if (type) el.textContent += ' / ' + type;
    }
    el.title = 'Structural label; use the markup toggle to edit the underlying syntax';
    if (this.item.role === 'columns' && !this.item.closing && this.adjustable) {
      const select = document.createElement('select');
      select.setAttribute('aria-label', 'Column proportions');
      const current = /(?:columns\s+|ratio[= ]+"?)([\d.]+(?::[\d.]+)+)/.exec(this.line)?.[1] || (this.count === 3 ? '1:1:1' : '1:1');
      const values = this.count === 3 ? ['1:1:1'] : ['1:1', '2:1', '1:2'];
      if (!values.includes(current)) values.push(current);
      for (const value of values) select.add(new Option(value, value, false, value === current));
      select.onchange = () => view.dispatch({changes:{from:this.from,to:this.to,insert:ratioLine(this.line,select.value,this.org)},userEvent:'input'});
      el.append(select);
    }
    return el;
  }
  ignoreEvent() { return true; }
}

export function authoringExtensions({isOrg, enabled, onError = () => {}}) {
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
    update(update) { if (update.docChanged || update.selectionSet || update.transactions.some(t => t.effects.some(e => e.is(compactMarkup) || e.is(slideSeparators)))) this.build(update.view); }
    build(view) {
      this.outline = parsed(view.state);
      const lines = new Map(this.outline.markers.map(item => [view.state.doc.lineAt(item.from).from, item]));
      const marks = new RangeSetBuilder(), decorations = [];
      if (view.state.field(separatorState)) for (const from of slideBoundaries(this.outline))
        decorations.push(Decoration.line({class: 'ff-slide-boundary'}).range(view.state.doc.lineAt(from).from));
      for (const [from, item] of [...lines].sort((a, b) => a[0] - b[0])) {
        marks.add(from, from, new Marker(item.role, item.closing));
        decorations.push(Decoration.line({class: `ff-source-role ff-role-${roleGroup(item.role)}`}).range(from));
        if (view.state.field(compactState) && !['Section','Slide','Claim','Region'].includes(item.role)) {
          const line = view.state.doc.lineAt(from);
          const block = this.outline.blocks.find(b => b.from === from || b.endFrom === from);
          const editing = view.state.selection.ranges.some(s => s.from <= line.to && s.to >= from);
          if (block && !block.opaque && block.role !== 'agent-comment' && !editing) {
            const body = view.state.doc.sliceString(block.startEnd, block.to);
            const count = (body.match(isOrg() ? /^\s*#\+begin_(?:region|column)\b/gmi : /^####\s|^:{3,}\s+(?:\{\.column\b|column\b)/gm) || []).length;
            const adjustable = !/\bwidth[= ]/.test(body) && [2,3].includes(count);
            decorations.push(Decoration.replace({widget:new BlockLabel(item,isOrg(),from,line.to,line.text,count,adjustable)}).range(from,line.to));
          }
        }
      }
      this.markers = marks.finish(); this.decorations = Decoration.set(decorations, true);
    }
  }, {decorations: value => value.decorations});
  return [compactState, separatorState, semantic,
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
        options: [...Object.entries(recipes), ...chartTypes.map(type => ['chart-' + type,
          {kind:'Chart: selected table or new table',markdown:wrapElement('chart-' + type,'',false),org:wrapElement('chart-' + type,'',true)}])].map(([name, recipe]) => ({
          label: '/' + name, detail: recipe.title || recipe.kind, type: 'keyword',
          // Everyday layouts first; aliases and chart variants after them.
          boost: recipe.rank === undefined ? -50 : 40 - recipe.rank,
          info: recipe[isOrg() ? 'org' : 'markdown'],
          apply(view, _completion, from, to) {
            const selected = view.state.selection.main;
            const wrapping = !selected.empty && !slash && (name.startsWith('chart-') || name.startsWith('takeaway'));
            if (wrapping) { from = selected.from; to = selected.to; }
            let value;
            try {
              value = wrapElement(name, wrapping ? view.state.doc.sliceString(from,to) : '', isOrg())
                ?? recipe[isOrg() ? 'org' : 'markdown'];
            } catch (error) { onError(error.message); return; }
            value = value.replaceAll('review-INSERT_ID', 'review-' + crypto.randomUUID().replaceAll('-', '').slice(0, 12));
            const before = view.state.doc.sliceString(0, from);
            if (before && !before.endsWith('\n\n')) value = (before.endsWith('\n') ? '\n' : '\n\n') + value;
            if (to < view.state.doc.length && !view.state.doc.sliceString(to, to + 1).startsWith('\n')) value += '\n';
            snippet(snippetTemplate(value, !wrapping))(view, _completion, from, to);
            view.focus();
          },
        }))};
    }], maxRenderedOptions: 30, aboveCursor: true}),
  ];
}

export function insertMenu(editor) { editor.focus(); startCompletion(editor); }
export const recipeCatalogue = recipes;
