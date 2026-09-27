import { useState } from 'react'
import MapView from './MapView.jsx'
import ResultsPanel from './ResultsPanel.jsx'
import { analyzeArea } from './api.js'

export default function App() {
  const [bbox, setBbox] = useState(null)
  const [drawToken, setDrawToken] = useState(0)
  const [results, setResults] = useState(null)
  const [selectedRank, setSelectedRank] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const [gridSize, setGridSize] = useState(70)
  const [numCandidates, setNumCandidates] = useState(3)

  function startDrawing() {
    setError(null)
    setResults(null)
    setBbox(null)
    setDrawToken((t) => t + 1)
  }

  async function runAnalysis() {
    if (!bbox) return
    setLoading(true)
    setError(null)
    setResults(null)
    try {
      const data = await analyzeArea({ bbox, gridSize, numCandidates })
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
            <h3>1 · Select a land area</h3>
            <p className="muted small">
              Click below, then drag a rectangle on the map over the terrain you want to assess.
            </p>
            <button className="btn primary" onClick={startDrawing}>
              {bbox ? 'Redraw area' : 'Select area on map'}
            </button>
            {bbox && (
              <p className="muted small bbox-line">
                Selected: {bbox[1].toFixed(4)}, {bbox[0].toFixed(4)} → {bbox[3].toFixed(4)}, {bbox[2].toFixed(4)}
              </p>
            )}

            <h3 className="mt">2 · Options</h3>
            <label className="field">
              <span>Detail (grid resolution): {gridSize}</span>
              <input
                type="range" min="40" max="100" step="10"
                value={gridSize}
                onChange={(e) => setGridSize(Number(e.target.value))}
              />
            </label>
            <label className="field">
              <span>Candidate sites: {numCandidates}</span>
              <input
                type="range" min="1" max="5" step="1"
                value={numCandidates}
                onChange={(e) => setNumCandidates(Number(e.target.value))}
              />
            </label>

            <h3 className="mt">3 · Analyse</h3>
            <button className="btn accent" onClick={runAnalysis} disabled={!bbox || loading}>
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
            onBboxDrawn={setBbox}
            drawToken={drawToken}
          />
        </main>
      </div>
    </div>
  )
}
