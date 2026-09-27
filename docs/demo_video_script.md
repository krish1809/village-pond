# Demo Video Script — AI-based Village Pond Planning System
**Target length: ≤ 5 minutes.** Narration is in plain text; `[ON SCREEN]` lines are what to show/do.

> **Before you record (important):**
> - Open the live app at **http://10.1.75.79:5228/** and **run the sample-area analysis once** so it's cached — then in the recording the result comes back instantly instead of waiting ~12 s. (Or keep talking during the wait.)
> - Have a second area in mind (e.g. **Lonar crater**) and pre-run it too, so both are cached.
> - Full-screen the browser; zoom the page so text is readable on video.
> - Nothing secret is on screen (the API key lives only in a server-side `.env`).

---

## 0:00 – 0:30 · Introduction
**Narration:**
"Hi, I'm Rishi. This is my Village Pond Planning System. The problem it solves is simple to state but hard to do by hand: for a piece of village land, *where should you build a rainwater-harvesting pond*, how much land drains into it, and how much water could it actually collect? Normally that's judged by eye. My web app works it out automatically from real terrain and rainfall data, and shows everything on a map."

`[ON SCREEN]` The app open at the home screen, sidebar and map visible.

---

## 0:30 – 1:15 · How it works (the algorithm, briefly)
**Narration:**
"When you select an area, the backend downloads a real elevation model for exactly that patch from OpenTopography. From that it rebuilds the terrain and figures out how water flows: it fills tiny artificial pits, computes flow direction with the D8 method, and then flow accumulation — basically, how much land drains through each point. It scores every location for how good a pond site it is, using two standard measures, the topographic wetness index and the topographic position index, and it throws out anything too steep or sitting inside an existing stream. For the sites that survive, it traces the catchment that drains into them, and combines that with historical rainfall from Open-Meteo to estimate the water volume and the depth the pond would need."

`[ON SCREEN]` Optional: briefly show the report's architecture diagram (Figure 1) or just keep the app on screen.

---

## 1:15 – 1:50 · Interface tour + selecting an area
**Narration:**
"Let me show it. On the left I can search any place by name — let's go to our sample village area."

`[ON SCREEN]` Type a place in **Find a place** (or click **Go to sample area**); map flies there.

**Narration:**
"Now I select the land. I can either frame the area and hit *Select this area*, or draw a rectangle by clicking two corners. It shows the size, and warns me if the box is too big or too small."

`[ON SCREEN]` Click **Select this area**; point at the "Selected: … km ✓" readout.

---

## 1:50 – 3:15 · Run the analysis + walk through the results
**Narration:**
"Now I click *Analyse selected area*."

`[ON SCREEN]` Click **Analyse selected area**. (If cached, results appear instantly.)

**Narration:**
"Here are the results, all drawn on the map. The faint lines are the elevation contours generated from the terrain. The blue is the existing drainage — the streams and channels. And notice the suggested ponds are placed *away* from that blue network — the system deliberately never puts a pond inside a watercourse, exactly like a real planner wouldn't."

`[ON SCREEN]` Point at contours, then the blue drainage, then the three ranked pond markers.

**Narration:**
"Each suggested pond is a filled shape labelled with its area, and the dashed outline around it is its catchment — the land that drains into it. On the right, for each site I get the numbers: the catchment area, the pond footprint, how much runoff comes in per year, the basin's storage capacity, and the headline figure — the water it can realistically collect in a year."

`[ON SCREEN]` Hover a pond to show the label/popup; scroll the side panel showing Rank 1's stats.

**Narration:**
"There's also this storage curve — it shows how the stored volume grows with depth, and marks the depth the pond would need to hold a full year's runoff. And down here is the area's monthly rainfall. One nice consistency check: the catchment is always at least as large as the pond itself, because a pond can only sit in the low part of the land that feeds it."

`[ON SCREEN]` Point at the storage-curve chart, then the rainfall chart.

---

## 3:15 – 3:45 · Map layers + downloads
**Narration:**
"I can switch the base map to satellite to see the real ground under the results."

`[ON SCREEN]` Use the layers control (top-right) to toggle **Satellite**.

**Narration:**
"And everything is exportable — I can download a rendered map image, a GeoJSON I can open in QGIS, or the full JSON of the analysis."

`[ON SCREEN]` Click **Map PNG** (or **GeoJSON**/**JSON**) to show a download.

---

## 3:45 – 4:20 · Second example (it generalises + stays correct)
**Narration:**
"It isn't tied to one place — it works anywhere. Here's the Lonar crater. Watch what it does: it keeps the ponds off the existing crater lake and off the steep crater rim, and suggests feasible spots in the drainable land around it. That's the exclusion logic working on a real, recognisable feature."

`[ON SCREEN]` Search **Lonar**, select an area around the crater, analyse; point out that ponds avoid the lake and the steep rim.

---

## 4:20 – 4:45 · Architecture & engineering
**Narration:**
"Under the hood it's one lightweight FastAPI process that serves both the website and the API. It's deployed on the university servers, which are capped at 512 megabytes of RAM, so I kept it dependency-light, cached the elevation and rainfall data so repeat areas are instant, and made every external call fail gracefully. It's also covered by 71 automated tests."

`[ON SCREEN]` Optional: show the API docs at **/docs**, or the GitHub repo.

---

## 4:45 – 5:00 · Wrap-up
**Narration:**
"So: pick an area, and you get a suggested pond, its catchment, and the water it can collect — computed from real data and visualised on the map. The code and this report are on GitHub, and the app is live at the link in the description. Thanks for watching."

`[ON SCREEN]` Home screen or the results view; end card with the GitHub + live URL.

---

### Quick shot list (if you prefer bullet form)
1. Home screen — intro.
2. (Optional) architecture diagram — algorithm overview.
3. Search / go to sample area.
4. Select area → Analyse.
5. Map overlays: contours, drainage (blue), ponds, catchments.
6. Side panel: catchment, footprint, runoff, capacity, collectable volume, required depth.
7. Storage curve + rainfall chart.
8. Satellite toggle.
9. Downloads (PNG / GeoJSON / JSON).
10. Lonar example — avoids lake + steep rim.
11. /docs or GitHub — architecture/tests mention.
12. End card with links.
