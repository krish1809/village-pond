import { useState } from 'react'
import MapView from './MapView.jsx'
import ResultsPanel from './ResultsPanel.jsx'
import Search from './Search.jsx'
import { analyzeArea } from './api.js'

// Selection size limits (must match the backend's MIN/MAX_BBOX_SPAN_DEG).
const MIN_SPAN_DEG = 0.002
const MAX_SPAN_DEG = 0.6

function bboxSize(bbox) {
  const [w, s, e, n] = bbox
  const latMid = (s + n) / 2
  const widthKm = (e - w) * 111.32 * Math.cos((latMid * Math.PI) / 180)
  const heightKm = (n - s) * 111.32
  const inRange =
    e - w >= MIN_SPAN_DEG && n - s >= MIN_SPAN_DEG && e - w <= MAX_SPAN_DEG && n - s <= MAX_SPAN_DEG
  const tooBig = e - w > MAX_SPAN_DEG || n - s > MAX_SPAN_DEG
  return { widthKm, heightKm, inRange, tooBig }
}

export default function App() {
  const [bbox, setBbox] = useState(null)
  const [drawToken, setDrawToken] = useState(0)
  const [captureToken, setCaptureToken] = useState(0)
  const [jumpToken, setJumpToken] = useState(0)
  const [results, setResults] = useState(null)
  const [selectedRank, setSelectedRank] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const [numCandidates, setNumCandidates] = useState(3)
  const [drawing, setDrawing] = useState(false)
  const [flyTarget, setFlyTarget] = useState(null)
  const [flyToken, setFlyToken] = useState(0)

  function handleBbox(b) {
    setBbox(b)
    setDrawing(false)
  }

  function flyToPlace(lat, lon) {
    setFlyTarget([lat, lon])
    setFlyToken((t) => t + 1)
  }

  function captureView() {
    setError(null)
    setResults(null)
    setBbox(null)
    setDrawing(false)
    setCaptureToken((t) => t + 1)
  }

  function startDrawing() {
    setError(null)
    setResults(null)
    setBbox(null)
    setDrawing(true)
    setDrawToken((t) => t + 1)
  }

  async function runAnalysis() {
    if (!bbox) return
    setLoading(true)
    setError(null)
    setResults(null)
    try {
      const data = await analyzeArea({ bbox, numCandidates })
      setResults(data)
      setSelectedRank(1)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">◍</span>
          <div>
            <h1>Village Pond Planner</h1>
            <p>Select a land area to find where a pond fits, what drains into it, and how much water it can hold.</p>
          </div>
        </div>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <section className="card controls">
            <h3>1 · Find a place</h3>
            <Search onPick={flyToPlace} />
            <p className="muted small or-line">
              or <button className="linklike" onClick={() => setJumpToken((t) => t + 1)}>go to the sample area</button>
            </p>

            <h3 className="mt">2 · Select the land</h3>
            <p className="muted small">
              Pan/zoom to frame a village-sized patch (~1–3 km across), then:
            </p>
            <button className="btn primary big" onClick={captureView}>
              ◻ Select this area
            </button>
            <p className="muted small or-line">
              or <button className="linklike" onClick={startDrawing}>draw by clicking two corners</button>
            </p>
            {drawing && (
              <p className="muted small draw-hint">
                Click the <b>first corner</b> on the map, then click the <b>opposite corner</b>.
              </p>
            )}
            {bbox && (() => {
              const sz = bboxSize(bbox)
              return (
                <p className={`bbox-line small ${sz.inRange ? 'ok' : 'warn'}`}>
                  Selected: {sz.widthKm.toFixed(1)} × {sz.heightKm.toFixed(1)} km{' '}
                  {sz.inRange ? '✓' : sz.tooBig ? '— too large, zoom in' : '— too small, zoom out'}
                </p>
              )
            })()}

            <h3 className="mt">3 · Options</h3>
            <label className="field">
              <span>Candidate sites: {numCandidates}</span>
              <input
                type="range" min="1" max="5" step="1"
                value={numCandidates}
                onChange={(e) => setNumCandidates(Number(e.target.value))}
              />
            </label>

            <h3 className="mt">4 · Analyse</h3>
            <button
              className="btn accent"
              onClick={runAnalysis}
              disabled={!bbox || loading || (bbox && !bboxSize(bbox).inRange)}
            >
              {loading ? 'Analysing…' : 'Analyse selected area'}
            </button>
            {loading && (
              <p className="muted small">
                Fetching elevation &amp; rainfall and routing water across the terrain…
              </p>
            )}
          </section>

          {error && (
            <div className="card error">
              <strong>Couldn’t analyse this area</strong>
              <p>{error}</p>
            </div>
          )}

          <ResultsPanel results={results} selectedRank={selectedRank} onSelectRank={setSelectedRank} />

          {!results && !error && !loading && (
            <div className="card legend">
              <h3>How to read the map</h3>
              <ul>
                <li><span className="swatch fill" /> filled shape = the pond itself</li>
                <li><span className="swatch dash" /> dashed outline = its catchment (land draining in)</li>
                <li><span className="swatch dot" /> dot = suggested pond location</li>
              </ul>
            </div>
          )}
        </aside>

        <main className="map-wrap">
          <MapView
            results={results}
            selectedRank={selectedRank}
            onSelectRank={setSelectedRank}
            onBboxDrawn={handleBbox}
            drawToken={drawToken}
            captureToken={captureToken}
            jumpToken={jumpToken}
            flyTarget={flyTarget}
            flyToken={flyToken}
          />
        </main>
      </div>
    </div>
  )
}
