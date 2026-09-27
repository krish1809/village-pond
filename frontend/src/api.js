// Thin wrapper around the backend. The front-end is served by the same FastAPI
// app in production, so these are same-origin calls; in development Vite proxies
// them to the backend (see vite.config.js).

export async function analyzeArea({ bbox, numCandidates, runoffCoefficient }) {
  const body = { bbox, num_candidates: numCandidates }
  if (runoffCoefficient != null) body.runoff_coefficient = runoffCoefficient

  const resp = await fetch('/analyzeArea', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) {
    // FastAPI puts the human-readable message in `detail`.
    const message = data?.detail || `Request failed (${resp.status})`
    throw new Error(typeof message === 'string' ? message : JSON.stringify(message))
  }
  return data
}
