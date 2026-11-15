# Known limitations

NextCrop is a **decision-support prototype built in a 48-hour challenge**. It is not an agronomic recommendation system and must not be used on its own to decide what to plant. Everything below is already stated, in shorter form, inside the app.

## What the numbers mean
- **Suitability index (0–10000)** comes from FAO GAEZ v5 (`RES05-SUX`). It is the *potential* of the land for a crop under the chosen input level (default: rain-fed, high input). It is **not a yield and not a profit**. Classes: ≥8000 very suitable, 6000–7999 suitable, 4000–5999 moderate, 2000–3999 marginal, <2000 very marginal.
- **One cell, one answer.** A cell is 5 arc-minutes (about 80–85 km²). Results are not for a single field and the app says so.
- **No overall score.** Each rotation option shows its components (mean suitability, same-family neighbours, legume, days left in the year). A single total would only restate weights we chose, which are not evidence.
- **The order of seasons inside a year is not scheduled.** GAEZ gives one best start day per crop standing alone, not for a crop that follows another, so `sequence` is a listing, not a calendar. The shortest GAEZ cycle length is used so that multi-cropping is not ruled out; real cycles can be longer.

## What NASA data does and does not do
- The **ranking of options is driven by FAO GAEZ plus explicit rules**, not by NASA data.
- NASA data feeds the NASA tab (temperature, NDVI), the pipeline's checks, and the **moisture check** of each option in the six demo areas. The moisture check is an annotation: it never changes the order of the options.
- Moisture check: it compares the days an option needs with the number of consecutive moist days of the area (months where rain ≥ 0.5 × ET0, the FAO AEZ growing-period criterion). The criterion does not depend on the crop (paddy rice needs more water than half of ET0, so its real limit is tighter), it uses monthly means over the years with data (a dry or wet year can differ), and it applies only in rain-fed modes and within 60 km of a demo area. Temperature limits and the start month of each season are **not** checked.
- Rain is **CHIRPS v3**, not NASA. NASA POWER rain was found to differ from CHIRPS by up to 2.3× in one area and is not used.
- NDVI uses only measured, quality-checked MODIS composites; interpolated values are never shown as measurements.
- NASA SMAP soil moisture, MCD12Q1 land cover, NASADEM elevation and GFSAD30 cropland are in the database but not yet shown in the interface.
- **Nothing is a forecast.** Charts are multi-year monthly averages (2015–2025). There is no climate projection or what-if scenario yet.

## Coverage
- Suitability and the temperature chart cover all of Vietnam. **Rain, NDVI and the moisture check exist only around six demo areas**, each about 10 km across. Only one of the six locations was verified in the example data; the other five are estimated coordinates (see `pipeline/config.yaml`).
- Province outlines on the map are **geoBoundaries 2008** and do not follow the 2025 mergers; province names in the area list may differ from today's administrative names.
- Points in Laos, Cambodia or southern China that fall inside the data rectangle are refused only by the interface (the API has no country layer yet; DATA-14).

## Missing on purpose (listed in every result under `missing`)
Income and prices, erosion, specific soil condition, a real field calendar, water source and household resources. The app does not invent them.

## Engineering
- The API uses one shared database connection with a lock, which is enough for a demo but not for many simultaneous users.
- The API runs every request in a read-only transaction, but a dedicated read-only database role has not been created yet.
- English UI text and English crop names were drafted with AI help and have not been reviewed by a native speaker; English crop names live in `pipeline/src/rotation/crop_names.py`, not in the database.
- Base-map imagery is Esri World Imagery loaded at run time; its terms of use have not been reviewed.
- On screens narrower than 760 px the right-hand card (summary and NASA tabs) is hidden.
