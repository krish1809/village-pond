import { useState } from 'react'

// Place search using OpenStreetMap's Nominatim geocoder (free, no key). Lets the
// user jump the map to a village/town/city, then select land there or nearby.
// We search on submit (not per keystroke) to stay within Nominatim's usage policy.

export default function Search({ onPick }) {
  const [q, setQ] = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function runSearch(e) {
    e.preventDefault()
    const query = q.trim()
    if (!query) return
    setLoading(true)
    setError(null)
    setResults([])
    try {
      const url =
        'https://nominatim.openstreetmap.org/search?format=json&limit=6&q=' +
        encodeURIComponent(query)
      const resp = await fetch(url, { headers: { Accept: 'application/json' } })
      const data = await resp.json()
      if (!Array.isArray(data) || data.length === 0) {
        setError('No places found. Try a different name.')
      } else {
        setResults(data)
      }
    } catch (err) {
      setError('Search failed — check your connection and try again.')
    } finally {
      setLoading(false)
    }
  }

  function pick(r) {
    setResults([])
    setQ(r.display_name.split(',').slice(0, 2).join(', '))
    onPick(parseFloat(r.lat), parseFloat(r.lon))
  }

  return (
    <div className="search">
      <form onSubmit={runSearch} className="search-row">
        <input
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search a village, town or city…"
          aria-label="Search a place"
        />
        <button type="submit" className="btn primary search-btn" disabled={loading}>
          {loading ? '…' : 'Search'}
        </button>
      </form>
      {error && <p className="muted small search-error">{error}</p>}
      {results.length > 0 && (
        <ul className="search-results">
          {results.map((r) => (
            <li key={r.place_id} onClick={() => pick(r)}>
              {r.display_name}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
