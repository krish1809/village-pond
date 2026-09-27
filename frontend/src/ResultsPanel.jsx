import { useState } from 'react'
import RainfallChart from './RainfallChart.jsx'
import StorageChart from './StorageChart.jsx'
import { rankColor, formatArea, formatVolume, formatCoord } from './format.js'

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// Bundle the result geometries as a GeoJSON FeatureCollection for GIS tools.
function toGeoJSON(results) {
  const features = []
  results.candidates.forEach((c) => {
    features.push({
      type: 'Feature',
      properties: { kind: 'pond', rank: c.rank, area_sq_m: c.pond_footprint.area_sq_m,
        collectable_m3: c.water_volume.expected_collectable_m3, required_depth_m: c.storage.required_depth_m },
      geometry: c.pond_footprint.boundary,
    })
    features.push({
      type: 'Feature',
      properties: { kind: 'catchment', rank: c.rank, area_sq_m: c.catchment.area_sq_m },
      geometry: c.catchment.boundary,
    })
    features.push({
      type: 'Feature',
      properties: { kind: 'pond_location', rank: c.rank, elevation_m: c.location.elevation_m },
      geometry: { type: 'Point', coordinates: [c.location.longitude, c.location.latitude] },
    })
  })
  if (results.drainage) {
    features.push({ type: 'Feature', properties: { kind: 'drainage_network' }, geometry: results.drainage })
  }
  return { type: 'FeatureCollection', features }
}

export default function ResultsPanel({ results, selectedRank, onSelectRank }) {
  const [pngBusy, setPngBusy] = useState(false)
  if (!results) return null

  const { rainfall, area_summary, candidates, metadata } = results
  const rainfallNote =
    rainfall.source === 'open-meteo'
      ? `Live Open-Meteo average over ${rainfall.years_averaged} years`
      : 'Offline fallback value (rainfall service unreachable)'

  function downloadJSON() {
    saveBlob(new Blob([JSON.stringify(results, null, 2)], { type: 'application/json' }), 'pond-analysis.json')
  }
  function downloadGeoJSON() {
    saveBlob(new Blob([JSON.stringify(toGeoJSON(results))], { type: 'application/geo+json' }), 'pond-analysis.geojson')
  }
  async function downloadPNG() {
    setPngBusy(true)
    try {
      const resp = await fetch('/analyzeArea?format=image', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bbox: area_summary.bbox, num_candidates: candidates.length }),
      })
      if (!resp.ok) throw new Error('render failed')
      saveBlob(await resp.blob(), 'pond-analysis.png')
    } catch {
      // no-op; keep it quiet
    } finally {
      setPngBusy(false)
    }
  }

  return (
    <div className="results">
      <section className="card downloads">
        <h3>Download results</h3>
        <div className="download-row">
          <button className="btn ghost" onClick={downloadPNG} disabled={pngBusy}>
            {pngBusy ? 'Rendering…' : 'Map PNG'}
          </button>
          <button className="btn ghost" onClick={downloadGeoJSON}>GeoJSON</button>
          <button className="btn ghost" onClick={downloadJSON}>JSON</button>
        </div>
      </section>

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
        {area_summary.dem_source && (
          <p className="muted small">Elevation source: {area_summary.dem_source}</p>
        )}
      </section>

      <h3 className="section-title">Suggested pond sites ({candidates.length})</h3>
      {candidates.map((c) => {
        const color = rankColor(c.rank)
        const selected = c.rank === selectedRank
        const wv = c.water_volume
        const st = c.storage
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
                <dt>Required depth</dt>
                <dd>{st.required_depth_m} m{st.holds_annual_runoff ? '' : '+'}</dd>
              </div>
              <div>
                <dt>Suitability</dt>
                <dd>{(c.suitability.suitability_score * 100).toFixed(0)}%</dd>
              </div>
            </dl>

            <p className="muted small chart-caption">
              Storage curve — depth needed to hold a year's runoff: <b>{st.required_depth_m} m</b>
              {st.holds_annual_runoff ? '' : ' (more than modelled — very flat)'}
            </p>
            <StorageChart curve={st.curve} requiredDepth={st.required_depth_m} annualRunoff={wv.annual_runoff_m3} />

            <p className="muted small limit-note">
              Collectable volume is limited by the{' '}
              {wv.limiting_factor === 'catchment_runoff' ? 'incoming runoff' : 'basin size'} ·
              runoff coeff {wv.runoff_coefficient}
              {c.pond_footprint.capped ? ' · very flat ground, would need an engineered dam' : ''}
            </p>
          </section>
        )
      })}
    </div>
  )
}
