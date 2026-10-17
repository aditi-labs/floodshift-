# FLOODSHIFT Person 1 token models

Six parametric OpenSCAD designs and exported STL meshes. Each token reserves a **flat, centered 30 x 30 mm square** for a separate ArUco marker sticker. The marker identifies the physical instance only; do not encode token class in its ID. The raised outlines and symbols sit outside the tag pad so both the tag and token shape remain visible from above.

| Token | Footprint | Maximum height | Bird's-eye cue | Suggested filament |
|---|---:|---:|---|---|
| Hospital | 55 x 45 mm | 22 mm | Clinical cross silhouette | Red |
| Emergency shelter | 55 x 45 mm | 22 mm | House/pavilion outline and ridge | Blue |
| Food & water shelter | 55 x 45 mm | 22 mm | Canopy posts and bowl glyph | Green |
| Temporary bridge | 70 x 40 mm | 13 mm | Long deck, approaches, end rails | Orange |
| Person/household | 45 x 45 mm | 17 mm | Head, arms, legs around marker | Purple |
| Disaster START | 50 x 50 mm | 13 mm | Octagon and alert rays | Yellow |

STL stores geometry and does not reliably preserve filament color. Choose the suggested color in the slicer or use separate filament colors. The geometry remains identifiable as a single-color print. Place the separately printed 30 mm ArUco tag on the flat center pad after printing.

## Suggested print start

Print flat on the bed with a 0.4 mm nozzle, 0.16–0.20 mm layers, 3 walls, and 15–20% infill. The models are designed without supports. Confirm material and slicer settings with The MILL. Print the bridge first, inspect it from the planned overhead camera height, then print the rest. Verify the tag is readable after applying the marker sticker.
