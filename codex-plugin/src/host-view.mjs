export function cursorHost(context, info) {
  return /\bcursor\b/i.test(`${context?.userAgent || ''} ${info?.name || ''}`);
}

export function inlineEditorHeight(context) {
  if (context?.displayMode !== 'inline') return null;
  const dimensions = context.containerDimensions || {};
  // A host may assign a fixed height or cap the app's requested height.
  const limits = [dimensions.height, dimensions.maxHeight]
    .filter(value => Number.isFinite(value) && value > 0);
  return Math.min(760, ...limits);
}
