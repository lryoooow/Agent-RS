# Third-party notices

## satvis

The satellite orbit workspace includes a pinned build of [Flowm/satvis](https://github.com/Flowm/satvis), copyright Florian Mauracher and contributors, used under the MIT License. The deployed build includes its `LICENSE.txt` file.

Agent-RS keeps satvis in an isolated iframe and uses its documented URL parameters for satellite selection, task location, time and scene configuration. Satellite orbital elements are refreshed from CelesTrak when the vendor build is produced and are bundled as a static fallback.
