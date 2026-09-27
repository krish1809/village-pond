import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet-draw'
import 'leaflet/dist/leaflet.css'
import 'leaflet-draw/dist/leaflet.draw.css'
import { rankColor, formatArea, formatVolume } from './format.js'

// Default view: the sample contour area (a village in Chhattisgarh, India), so
// the map opens somewhere with usable terrain. The user can pan anywhere — the
// analysis works for any region, it isn't tied to this location.
const DEFAULT_CENTER = [21.25, 81.295]
const DEFAULT_ZOOM = 14

export default function MapView({ results, selectedRank, onSelectRank, onBboxDrawn, drawToken }) {
  const mapRef = useRef(null)
  const selectionLayerRef = useRef(null)
  const resultLayerRef = useRef(null)
  const drawerRef = useRef(null)

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

    const map = L.map('map', { center: DEFAULT_CENTER, zoom: DEFAULT_ZOOM, layers: [satellite] })
    L.control.layers({ Satellite: satellite, Streets: streets }, {}, { position: 'topright' }).addTo(map)

    selectionLayerRef.current = L.featureGroup().addTo(map)
    resultLayerRef.current = L.featureGroup().addTo(map)

    // When a rectangle is finished, hand its bounds up as a bbox.
    map.on(L.Draw.Event.CREATED, (e) => {
      selectionLayerRef.current.clearLayers()
      const layer = e.layer
      selectionLayerRef.current.addLayer(layer)
      const b = layer.getBounds()
      onBboxDrawn([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()])
    })

    mapRef.current = map
    return () => map.remove()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // --- Start rectangle-drawing when the parent bumps drawToken ---
  useEffect(() => {
    if (!mapRef.current || drawToken === 0) return
    if (drawerRef.current) drawerRef.current.disable()
    resultLayerRef.current.clearLayers()
    drawerRef.current = new L.Draw.Rectangle(mapRef.current, {
      shapeOptions: { color: '#f5c518', weight: 2, fillOpacity: 0.05, dashArray: '6 4' },
    })
    drawerRef.current.enable()
  }, [drawToken])

  // --- Draw the analysis result overlays whenever results/selection change ---
  useEffect(() => {
    const layerGroup = resultLayerRef.current
    if (!layerGroup) return
    layerGroup.clearLayers()
    if (!results) return

    results.candidates.forEach((cand) => {
      const color = rankColor(cand.rank)
      const isSelected = cand.rank === selectedRank

      // Catchment — dashed outline (the land draining toward the pond).
      L.geoJSON(cand.catchment.boundary, {
        style: {
          color,
          weight: isSelected ? 2.5 : 1.5,
          fill: false,
          dashArray: '6 5',
          opacity: isSelected ? 0.95 : 0.55,
        },
      }).addTo(layerGroup)

      // Pond footprint — filled (the water body itself).
      L.geoJSON(cand.pond_footprint.boundary, {
        style: {
          color,
          weight: 2,
          fillColor: color,
          fillOpacity: isSelected ? 0.6 : 0.35,
          opacity: isSelected ? 1 : 0.7,
        },
      }).addTo(layerGroup)

      // Pond location marker — a circle so we don't depend on Leaflet's image
      // marker assets (which break under bundlers).
      const marker = L.circleMarker([cand.location.latitude, cand.location.longitude], {
        radius: isSelected ? 9 : 6,
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

    // Frame the results the first time they arrive (or when they change).
    if (layerGroup.getLayers().length > 0) {
      mapRef.current.fitBounds(layerGroup.getBounds(), { padding: [40, 40], maxZoom: 16 })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results, selectedRank])

  return <div id="map" className="map" />
}
