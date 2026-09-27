import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { rankColor, formatArea, formatVolume, elevationColor } from './format.js'

// Default view: a village area near Raipur, Chhattisgarh — the same place the
// Phase 2 contour sample covers, so it opens somewhere with a known-good result.
// The analysis works for any region the user selects.
export const SAMPLE_CENTER = [21.2517, 81.297]
export const SAMPLE_ZOOM = 15
const DEFAULT_CENTER = SAMPLE_CENTER
const DEFAULT_ZOOM = SAMPLE_ZOOM

export default function MapView({ results, selectedRank, onSelectRank, onBboxDrawn, drawToken, captureToken, jumpToken, flyTarget, flyToken }) {
  const mapRef = useRef(null)
  const selectionLayerRef = useRef(null)
  const resultLayerRef = useRef(null)

  // Two-click drawing state (kept in refs so the map event handlers, added once,
  // always see the current values).
  const drawingRef = useRef(false)
  const firstCornerRef = useRef(null)
  const rubberRef = useRef(null)

  function finishDrawing() {
    drawingRef.current = false
    firstCornerRef.current = null
    if (rubberRef.current) {
      rubberRef.current.remove()
      rubberRef.current = null
    }
    if (mapRef.current) mapRef.current.getContainer().style.cursor = ''
  }

  function rectFromCorners(a, b) {
    return [[Math.min(a.lat, b.lat), Math.min(a.lng, b.lng)],
            [Math.max(a.lat, b.lat), Math.max(a.lng, b.lng)]]
  }

  // --- One-time map setup ---
  useEffect(() => {
    const satellite = L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      { attribution: 'Imagery © Esri', maxZoom: 19 },
    )
    const streets = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors',
      maxZoom: 19,
    })

    // Plain OpenStreetMap as the default base; Esri satellite imagery as a toggle.
    const map = L.map('map', { center: DEFAULT_CENTER, zoom: DEFAULT_ZOOM, layers: [streets] })
    L.control.layers({ Map: streets, Satellite: satellite }, {}, { position: 'topright' }).addTo(map)

    selectionLayerRef.current = L.featureGroup().addTo(map)
    resultLayerRef.current = L.featureGroup().addTo(map)

    // --- Two-click rectangle drawing (reliable on a touchpad, unlike drag) ---
    map.on('click', (e) => {
      if (!drawingRef.current) return
      if (!firstCornerRef.current) {
        // First corner: remember it and start a rubber-band rectangle.
        firstCornerRef.current = e.latlng
        rubberRef.current = L.rectangle(rectFromCorners(e.latlng, e.latlng), {
          color: '#f5c518', weight: 2, fillOpacity: 0.08, dashArray: '6 4',
        }).addTo(map)
      } else {
        // Second corner: finalise the selection.
        const c1 = firstCornerRef.current
        const c2 = e.latlng
        selectionLayerRef.current.clearLayers()
        L.rectangle(rectFromCorners(c1, c2), {
          color: '#f5c518', weight: 2, fillOpacity: 0.06, dashArray: '6 4',
        }).addTo(selectionLayerRef.current)
        onBboxDrawn([Math.min(c1.lng, c2.lng), Math.min(c1.lat, c2.lat),
                     Math.max(c1.lng, c2.lng), Math.max(c1.lat, c2.lat)])
        finishDrawing()
      }
    })

    // Rubber-band: follow the cursor after the first corner is placed.
    map.on('mousemove', (e) => {
      if (!drawingRef.current || !firstCornerRef.current || !rubberRef.current) return
      rubberRef.current.setBounds(rectFromCorners(firstCornerRef.current, e.latlng))
    })

    mapRef.current = map
    return () => map.remove()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // --- Enter two-click drawing mode when the parent bumps drawToken ---
  useEffect(() => {
    if (!mapRef.current || drawToken === 0) return
    finishDrawing()
    selectionLayerRef.current.clearLayers()
    resultLayerRef.current.clearLayers()
    drawingRef.current = true
    mapRef.current.getContainer().style.cursor = 'crosshair'
  }, [drawToken])

  // --- Recenter on the sample area when the parent bumps jumpToken ---
  useEffect(() => {
    if (!mapRef.current || jumpToken === 0) return
    mapRef.current.setView(SAMPLE_CENTER, SAMPLE_ZOOM)
  }, [jumpToken])

  // --- Fly to a searched place when the parent bumps flyToken ---
  useEffect(() => {
    if (!mapRef.current || flyToken === 0 || !flyTarget) return
    mapRef.current.flyTo(flyTarget, 15, { duration: 1.0 })
  }, [flyToken])

  // --- "Use current map view": select the centre ~70% of what's on screen ---
  useEffect(() => {
    if (!mapRef.current || captureToken === 0) return
    finishDrawing()
    resultLayerRef.current.clearLayers()

    const b = mapRef.current.getBounds()
    const latC = (b.getSouth() + b.getNorth()) / 2
    const lonC = (b.getWest() + b.getEast()) / 2
    const halfLat = ((b.getNorth() - b.getSouth()) / 2) * 0.7
    const halfLon = ((b.getEast() - b.getWest()) / 2) * 0.7
    const south = latC - halfLat
    const north = latC + halfLat
    const west = lonC - halfLon
    const east = lonC + halfLon

    selectionLayerRef.current.clearLayers()
    L.rectangle([[south, west], [north, east]], {
      color: '#f5c518', weight: 2, fillOpacity: 0.06, dashArray: '6 4',
    }).addTo(selectionLayerRef.current)

    onBboxDrawn([west, south, east, north])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [captureToken])

  // --- Draw the analysis result overlays whenever results/selection change ---
  useEffect(() => {
    const layerGroup = resultLayerRef.current
    if (!layerGroup) return
    layerGroup.clearLayers()
    if (!results) return

    // Contour lines from the DEM — drawn first (underneath), like a topo map.
    const contours = results.contours || []
    if (contours.length) {
      const lo = results.area_summary.elevation_min_m
      const hi = results.area_summary.elevation_max_m
      contours.forEach((c) => {
        const latlngs = c.coordinates.map(([lon, lat]) => [lat, lon])
        L.polyline(latlngs, {
          color: elevationColor(c.elevation, lo, hi),
          weight: 1.4,
          opacity: 0.9,
          interactive: false,
        }).addTo(layerGroup)
      })
    }

    results.candidates.forEach((cand) => {
      const color = rankColor(cand.rank)
      const isSelected = cand.rank === selectedRank

      // Catchment — bold dashed outline (the land draining toward the pond).
      L.geoJSON(cand.catchment.boundary, {
        style: {
          color,
          weight: isSelected ? 3.5 : 2,
          fill: false,
          dashArray: '8 6',
          opacity: isSelected ? 1 : 0.7,
        },
      }).addTo(layerGroup)

      // Pond footprint — solid filled water region, clearly visible, labelled
      // with its approximate area so the pond boundary reads on the map.
      const pondLayer = L.geoJSON(cand.pond_footprint.boundary, {
        style: {
          color: '#ffffff',
          weight: isSelected ? 3 : 2,
          fillColor: color,
          fillOpacity: isSelected ? 0.8 : 0.55,
          opacity: 1,
        },
      }).addTo(layerGroup)
      pondLayer.bindTooltip(
        `Rank ${cand.rank} pond ≈ ${formatArea(cand.pond_footprint.area_sq_m)}`,
        { permanent: isSelected, direction: 'top', className: 'pond-label', opacity: 0.95 },
      )

      // Pond location marker — a circle (no dependency on Leaflet marker images).
      const marker = L.circleMarker([cand.location.latitude, cand.location.longitude], {
        radius: isSelected ? 10 : 7,
        color: '#ffffff',
        weight: 2,
        fillColor: color,
        fillOpacity: 1,
      }).addTo(layerGroup)

      marker.bindPopup(
        `<b style="color:${color}">Rank ${cand.rank} — suggested pond</b><br/>` +
          `Pond area: ${formatArea(cand.pond_footprint.area_sq_m)}<br/>` +
          `Catchment: ${formatArea(cand.catchment.area_sq_m)}<br/>` +
          `Collectable water: <b>${formatVolume(cand.water_volume.expected_collectable_m3)}</b>/yr`,
      )
      marker.on('click', () => onSelectRank(cand.rank))
      if (isSelected) marker.openPopup()
    })

    if (layerGroup.getLayers().length > 0) {
      mapRef.current.fitBounds(layerGroup.getBounds(), { padding: [40, 40], maxZoom: 17 })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results, selectedRank])

  return <div id="map" className="map" />
}
