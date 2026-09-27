import RainfallChart from './RainfallChart.jsx'
import { rankColor, formatArea, formatVolume, formatCoord } from './format.js'

export default function ResultsPanel({ results, selectedRank, onSelectRank }) {
  if (!results) return null

  const { rainfall, area_summary, candidates, metadata } = results
  const rainfallNote =
    rainfall.source === 'open-meteo'
      ? `Live Open-Meteo average over ${rainfall.years_averaged} years`
      : 'Offline fallback value (rainfall service unreachable)'

  return (
    <div className="results">
      <section className="card rainfall-card">
        <h3>Rainfall for this area</h3>
        <div className="big-number">
          {rainfall.annual_rainfall_mm.toLocaleString()} <span>mm/yr</span>
        </div>
        <p className="muted small">{rainfallNote}</p>
        <RainfallChart monthly={rainfall.monthly_climatology_mm} />
        <p className="muted small">
          DEM {area_summary.grid_resolution} · elevation {area_summary.elevation_min_m}–
          {area_summary.elevation_max_m} m · analysed in {metadata.total_processing_time_s}s
        </p>
      </section>

      <h3 className="section-title">Suggested pond sites ({candidates.length})</h3>
      {candidates.map((c) => {
        const color = rankColor(c.rank)
        const selected = c.rank === selectedRank
        const wv = c.water_volume
        return (
          <section
            key={c.rank}
            className={`card candidate ${selected ? 'selected' : ''}`}
            style={{ borderLeftColor: color }}
            onClick={() => onSelectRank(c.rank)}
          >
            <div className="candidate-head">
              <span className="rank-dot" style={{ background: color }} />
              <strong>Rank {c.rank}</strong>
              <span className="muted small">{formatCoord(c.location.latitude, c.location.longitude)}</span>
            </div>

            <div className="headline-volume">
              <span className="label">Water collectable / year</span>
              <span className="value">{formatVolume(wv.expected_collectable_m3)}</span>
            </div>

            <dl className="stats">
              <div>
                <dt>Catchment area</dt>
                <dd>{formatArea(c.catchment.area_sq_m)}</dd>
              </div>
              <div>
                <dt>Pond footprint</dt>
                <dd>{formatArea(c.pond_footprint.area_sq_m)}</dd>
              </div>
              <div>
                <dt>Annual runoff in</dt>
                <dd>{formatVolume(wv.annual_runoff_m3)}</dd>
              </div>
              <div>
                <dt>Basin capacity</dt>
                <dd>{formatVolume(wv.storage_capacity_m3)}</dd>
              </div>
              <div>
                <dt>Ground slope</dt>
                <dd>{c.location.slope_deg}°</dd>
              </div>
              <div>
                <dt>Suitability</dt>
                <dd>{(c.suitability.suitability_score * 100).toFixed(0)}%</dd>
              </div>
            </dl>

            <p className="muted small limit-note">
              Collectable volume is limited by the{' '}
              {wv.limiting_factor === 'catchment_runoff' ? 'incoming runoff' : 'basin size'} ·
              assumed depth {c.pond_footprint.assumed_depth_m} m · runoff coeff {wv.runoff_coefficient}
              {c.pond_footprint.capped ? ' · very flat ground, would need an engineered dam' : ''}
            </p>
          </section>
        )
      })}
    </div>
  )
}
