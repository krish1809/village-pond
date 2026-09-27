# Demo Video — Speaking Script (~2.5 minutes)
Read the plain text aloud. The `(...)` notes are click cues — don't say them.
Tip: pre-run the sample area once before recording so results appear instantly.

---

Hi, I'm Rishi, and this is my Village Pond Planning System. It answers a simple
question for any piece of village land — where should a rainwater-harvesting pond
go, how much land drains into it, and how much water it could actually collect.

(show the app)

The idea is this: I pick an area on the map, and the backend downloads a real
elevation model for exactly that area from OpenTopography. From the terrain it works
out how water flows — it fills small pits, computes flow direction and flow
accumulation — and then scores each spot for how good a pond site it is, while
avoiding steep ground and anything sitting inside an existing stream. For the best
sites it traces the catchment and combines it with historical rainfall to estimate
the water volume.

Let me show it. I'll search for my area here.

(search a place, or click "Go to sample area")

Now I select the land — I can just frame it and click "Select this area", or draw a
rectangle with two clicks. It even tells me the size.

(click "Select this area", then "Analyse selected area")

And here are the results, all on the map. These faint lines are the elevation
contours. The blue is the existing drainage — the streams. And notice the suggested
ponds are placed away from that blue, because the system never puts a pond inside a
watercourse.

(point at contours, blue drainage, then the pond markers)

The sites are ranked best-first by a suitability score that combines the topographic
wetness and position indices. So Rank 1 here has a catchment of about six thousand
two hundred square metres feeding a pond footprint of roughly two thousand six
hundred, and it can collect around nineteen hundred cubic metres of water a year.
Rank 2 and Rank 3 are smaller — around eight hundred cubic metres each — on smaller
catchments.

(read the actual on-screen numbers for your run; point at Rank 1, 2, 3 in the panel)

Each pond is a filled shape labelled with its area, and the dashed outline is its
catchment — the land that feeds it. One thing worth pointing out: the catchment is
always at least as large as the pond, because the pond can only sit in the low part
of the land that drains into it.

That water-volume figure comes from two limits — how much runoff the catchment
delivers in a year, which is the runoff coefficient times the rainfall times the
catchment area, and how much the basin can physically hold, measured from the
terrain. The collectable volume is the smaller of the two. This chart then shows the
depth the pond would need to hold a full year's runoff, and below it is the area's
monthly rainfall.

(scroll the side panel; point at the storage curve and rainfall chart)

I can switch to satellite to see the real ground, and I can download the result as
an image, GeoJSON, or JSON.

(toggle satellite; hover the download buttons)

It works anywhere, not just here — for example, over the Lonar crater it correctly
keeps the ponds off the existing lake and the steep rim.

(optional: quickly show Lonar)

Under the hood it's a single lightweight FastAPI service that serves both the site
and the API, deployed on the university servers within a tight memory limit, with
caching so repeat areas are instant.

So — pick an area, and you get a suggested pond, its catchment, and the water it can
collect, computed from real data and shown on the map. The code and report are on
GitHub, and the app is live at the link in the description. Thanks for watching.
