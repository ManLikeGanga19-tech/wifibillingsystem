import * as maplibregl from 'maplibre-gl';
// maplibre-gl builds its web-worker URL DYNAMICALLY (`new URL(`./${name}`, base)`), which Vite
// can't statically analyse — so a production build never emits `maplibre-gl-worker.mjs`, the
// worker fails to load, GeoJSON sources never process, and no pins render (the raster basemap,
// which needs no worker, still shows — exactly the "map but no markers" bug). Fix: import the
// worker as an asset Vite DOES emit (?url) and register it once, before any Map is created. The
// worker file is self-contained, so a plain URL works. Dev worked only because maplibre was
// excluded from bundling; this makes production behave the same.
// ?worker&url makes Vite BUILD the worker through its own pipeline (so its module format and
// output match how it bundles everything else) and hand back the emitted URL — more robust than
// a raw ?url copy of the dist file.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';

maplibregl.setWorkerUrl(workerUrl);

export { maplibregl };
