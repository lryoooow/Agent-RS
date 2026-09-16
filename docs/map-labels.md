# Map names and roads

The previous World_Boundaries_and_Places raster was disabled by default and
could be covered by uploaded imagery. Its street-scale reference tiles in the
tested Beijing / Guangdong areas were transparent, including the separate
World_Transportation service.

The satellite imagery remains Esri World Imagery (maximum native zoom 18).
The transparent reference overlay uses OpenFreeMap's OpenMapTiles vector tiles:
https://tiles.openfreemap.org/planet . Chinese names take priority, falling back
to each feature's local name. Reference data uses Web Mercator tiles derived from
geographic coordinates, so no GCJ-02 offset is introduced into uploaded imagery.

Names/roads start enabled. The `地名道路` button remembers its setting in
`agent-rs.map-labels.v1`. Zooming reveals towns, streets, water names, mountain
names and selected POIs where the source has data. The overlay does not promise
complete names for every rural road. Names are reference data, not analysis results.

Drawing order, shared by the primary and swipe maps:
satellite → uploaded imagery → analysis results → reference roads/names → ROI/drawing/grid.

The production HTML CSP must allow `https://tiles.openfreemap.org` in `connect-src`
for TileJSON, PBF tiles and glyphs. `deploy/serve.py` is the deployment wrapper
installed at `/etc/agent-rs/serve.py`; the API security policy is unchanged.
MapLibre's compact attribution control exposes Esri and the required
OpenMapTiles / OpenStreetMap credits.

Provider documentation: https://openfreemap.org/quick_start/ and
https://openfreemap.org/ . The public instance requires no account or API key.
