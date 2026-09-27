// Small formatting helpers shared by the panel and map popups.

// Per-rank colours, matching the palette used by the backend's PNG renderer so
// the web overlay and the rendered report image tell the same visual story.
export const RANK_COLORS = ['#0033cc', '#009933', '#cc6600', '#aa00aa', '#00aaaa']

export function rankColor(rank) {
  return RANK_COLORS[(rank - 1) % RANK_COLORS.length]
}

// Area: show m² up to a hectare, then hectares.
export function formatArea(m2) {
  if (m2 == null) return '—'
  if (m2 >= 10000) return `${(m2 / 10000).toFixed(2)} ha (${Math.round(m2).toLocaleString()} m²)`
  return `${Math.round(m2).toLocaleString()} m²`
}

// Volume: m³ up to a million, then million-m³ (Mm³).
export function formatVolume(m3) {
  if (m3 == null) return '—'
  if (m3 >= 1e6) return `${(m3 / 1e6).toFixed(2)} million m³`
  return `${Math.round(m3).toLocaleString()} m³`
}

export function formatCoord(lat, lon) {
  return `${lat.toFixed(5)}, ${lon.toFixed(5)}`
}

// Colour a contour line by elevation: green (low) → brown (high), like a topo map.
export function elevationColor(e, lo, hi) {
  const t = hi > lo ? Math.max(0, Math.min(1, (e - lo) / (hi - lo))) : 0.5
  const hue = 95 - t * 75 // ~95 (green) at the low end → ~20 (brown) at the high end
  return `hsl(${hue.toFixed(0)}, 45%, 42%)`
}
