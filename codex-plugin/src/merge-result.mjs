export function mergeResult(plan, choices = []) {
  let index = 0;
  return plan.segments.map(segment => {
    if ('text' in segment) return segment.text;
    const choice = choices[index++];
    if (typeof choice !== 'string') throw Error('Resolve every conflict before applying the merge.');
    return choice;
  }).join('');
}
