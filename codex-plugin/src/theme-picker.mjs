export function themeChoices(catalog = {}, selected = '') {
  const names = new Set((catalog.themes || []).filter(name => typeof name === 'string' && name));
  // Recovery can refer to a theme that is currently unavailable; never silently
  // replace that explicit selection with the default or edit the source.
  if (selected) names.add(selected);
  return [{value: '', label: catalog.default ? `${catalog.default} (default)` : 'Project default'},
    ...[...names].sort().map(name => ({value: name, label: name}))];
}

export function updateThemePicker(select, catalog, selected = select.value) {
  select.replaceChildren(...themeChoices(catalog, selected).map(({value, label}) => {
    const option = select.ownerDocument.createElement('option');
    option.value = value; option.textContent = label;
    return option;
  }));
  select.value = selected;
}
