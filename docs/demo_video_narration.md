# Demo Video — Speaking Script (~3 minutes)
Read the plain text aloud. The `(...)` notes are click cues — don't say them.
Tip: pre-run the sample area once before recording so results appear instantly.

---

Hi, I'm Rishi, and this is my Village Pond Planning System. For any piece of village
land it answers three things: where a rainwater-harvesting pond should go, how much
land drains into it, and how much water it could collect.

(show the app)

Here's the idea. I pick an area on the map, and the backend downloads a real
elevation model for exactly that area from OpenTopography. From the terrain it works
out how water flows — it fills small pits, then computes flow direction and flow
accumulation — and scores each spot for how good a pond site it is, using the
topographic wetness and position indices, while avoiding steep ground and existing
streams.

Let me show it. I'll go to my area and select the land — I can frame it and click
"Select this area", or draw a rectangle with two clicks — and then hit Analyse.

(click "Select this area", then "Analyse selected area")

Here are the results on the map. The faint lines are elevation contours, the blue is
the existing drainage, and notice the suggested ponds sit away from that blue,
because the system never places a pond inside a watercourse.

(point at contours, drainage, and the pond markers)

The sites are ranked best-first by the water they can collect. Rank 1 has a catchment of about six thousand square
metres feeding a pond of around two thousand six hundred, and it can collect roughly
nineteen hundred cubic metres of water a year. Ranks 2 and 3 are smaller sites on
smaller catchments.

(read your run's actual numbers; point at Rank 1, 2, 3)

The catchment is always at least as large as the pond, since a pond can only sit in
the low part of the land that feeds it. And the water figure is the smaller of two
limits — the runoff the catchment delivers in a year, and how much the basin can
physically hold, measured from the terrain. This chart shows the depth needed to
hold a year's runoff, and below it is the monthly rainfall.

(point at the storage curve and rainfall chart)

I can switch to satellite, and download the result as an image, GeoJSON, or JSON. It
works anywhere — over the Lonar crater, for instance, it correctly keeps the ponds
off the existing lake and the steep rim.

(toggle satellite / show downloads / optionally show Lonar)

Under the hood it's a single lightweight FastAPI service that serves both the site
and the API, deployed on the university servers within a tight memory limit, with
caching so repeat areas are instant. The code and report are on GitHub, and the app
is live at the link in the description. Thanks for watching.
