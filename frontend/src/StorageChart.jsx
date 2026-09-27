// Inline-SVG stage–volume curve for a pond: how stored volume grows with water
// depth, with the depth needed to hold one year's runoff marked.

export default function StorageChart({ curve, requiredDepth, annualRunoff }) {
  if (!curve || curve.length === 0) return null

  const W = 260
  const H = 110
  const padL = 34
  const padR = 8
  const padT = 8
  const padB = 20

  const maxDepth = Math.max(...curve.map((p) => p.depth_m))
  const maxVol = Math.max(...curve.map((p) => p.volume_m3), annualRunoff || 0, 1)

  const x = (d) => padL + (d / maxDepth) * (W - padL - padR)
  const y = (v) => H - padB - (v / maxVol) * (H - padT - padB)

  const linePts = curve.map((p) => `${x(p.depth_m).toFixed(1)},${y(p.volume_m3).toFixed(1)}`).join(' ')
  const areaPts = `${x(0)},${y(0)} ${linePts} ${x(maxDepth)},${y(0)}`

  const runoffY = annualRunoff != null ? y(Math.min(annualRunoff, maxVol)) : null
  const reqX = requiredDepth != null ? x(Math.min(requiredDepth, maxDepth)) : null

  return (
    <svg className="storage-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Storage curve">
      {/* axes */}
      <line x1={padL} y1={padT} x2={padL} y2={H - padB} className="axis" />
      <line x1={padL} y1={H - padB} x2={W - padR} y2={H - padB} className="axis" />

      {/* volume-vs-depth curve */}
      <polygon points={areaPts} fill="#2563eb" opacity="0.14" />
      <polyline points={linePts} fill="none" stroke="#2563eb" strokeWidth="2" />

      {/* annual runoff level */}
      {runoffY != null && (
        <>
          <line x1={padL} y1={runoffY} x2={W - padR} y2={runoffY} className="ref-line" />
          <text x={W - padR} y={runoffY - 3} textAnchor="end" className="chart-label">
            1 yr runoff
          </text>
        </>
      )}

      {/* required depth */}
      {reqX != null && (
        <>
          <line x1={reqX} y1={padT} x2={reqX} y2={H - padB} className="ref-line" />
          <text x={reqX} y={padT + 8} textAnchor="middle" className="chart-label">
            {requiredDepth} m
          </text>
        </>
      )}

      <text x={padL - 4} y={padT + 6} textAnchor="end" className="axis-label">m³</text>
      <text x={W - padR} y={H - 6} textAnchor="end" className="axis-label">depth →</text>
    </svg>
  )
}
