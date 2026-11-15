// Attribution permits reconciliation, never replacement. Autosave is deliberately
// absent: it controls persistence only, not protection of the current draft.
export function incomingTransition({currentEtag, incomingEtag, agentBases, blocked = false}) {
  if (!currentEtag || !incomingEtag) return 'review';
  if (currentEtag === incomingEtag) return 'unchanged';
  if (blocked) return 'review';
  return Array.isArray(agentBases) && agentBases.includes(currentEtag) ? 'reconcile-agent' : 'review';
}
