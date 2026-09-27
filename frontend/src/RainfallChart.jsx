// A tiny inline-SVG bar chart of the monthly rainfall climatology. No chart
// library — it's a dozen bars, so a handful of <rect>s is lighter and clearer.

const MONTHS = ['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D']

export default function RainfallChart({ monthly }) {
  if (!monthly || monthly.length !== 12) return null
  const max = Math.max(...monthly, 1)
  const W = 260
  const H = 90
  const pad = 16
  const barGap = 3
  const barW = (W - pad * 2) / 12 - barGap

  return (
    <svg className="rainfall-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Monthly rainfall">
      {monthly.map((mm, i) => {
        const h = (mm / max) * (H - pad * 2)
        const x = pad + i * (barW + barGap)
        const y = H - pad - h
        return (
          <g key={i}>
            <rect x={x} y={y} width={barW} height={h} rx="1.5" fill="#3b82f6">
              <title>{`${['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][i]}: ${mm} mm`}</title>
            </rect>
            <text x={x + barW / 2} y={H - 4} textAnchor="middle" className="rainfall-label">
              {MONTHS[i]}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
