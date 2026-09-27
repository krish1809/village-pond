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

Each pond is a filled shape with its area, and the dashed outline is its catchment —
the land that feeds it. On the right I get the numbers for each site: the catchment
area, the pond footprint, the yearly runoff, and the key figure — the water it can
collect in a year. This chart shows the depth the pond needs to hold a full year's
runoff, and below it is the area's monthly rainfall.

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
