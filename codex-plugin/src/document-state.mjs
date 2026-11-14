// These are independent observations, not stages of a single workflow.
// In particular a local draft may be newer than the last verified live site.
export function documentState({dirty, connected, conflict, incoming, receipt, fileDigest, git}) {
  const sent = !!receipt?.revision;
  const verified = sent && receipt.stage === 'published' && receipt.deployed_revision === receipt.revision;
  return {
    draft:{label:conflict ? 'Needs review' : incoming ? 'Update ready' : dirty ? 'Draft' : connected ? 'Saved' : 'Local copy',
      detail:conflict ? 'Both versions are retained.' : incoming ? 'Incoming file edits are waiting for your acceptance. Your draft is unchanged.' : dirty ? 'Edits are not saved to the file.' : connected ? 'Matches the last file version read.' : 'No file connection.'},
    commit:{label:git?.source_sha256 && fileDigest ? (git.source_sha256 === fileDigest ? 'Saved version committed' : 'Saved version differs from commit') : 'Commit state unknown',
      detail:git?.revision ? `Local file commit ${git.revision.slice(0,8)}.` : 'No verified local commit for this file.'},
    sent:{label:sent ? 'Sent' : 'Not sent from this workspace', revision:receipt?.revision || null,
      matchesFile:sent && fileDigest ? fileDigest === receipt.source_sha256 : null,
      detail:sent ? 'Last recorded push, not a fresh check of the remote branch.' : 'No local push receipt.', at:receipt?.pushed_at || null},
    live:{label:verified ? 'Live' : receipt?.stage === 'building' ? 'Building' : receipt?.stage === 'failed' ? 'Site failed' : 'Live version unknown',
      revision:verified ? receipt.deployed_revision : null, at:receipt?.checked_at || null,
      detail:verified ? 'Verified at the last site check; later changes may exist.' : 'A link or successful push does not verify deployment.'},
  };
}
