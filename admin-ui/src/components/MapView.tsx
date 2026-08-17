import { createElement, useEffect, useRef, useState, type ComponentType } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { maplibregl } from '../utils/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import {
  MapPin, RadioTower, Router as RouterIcon, Home, UserPlus, Loader2, AlertTriangle,
  Satellite, Map as MapGlyph, Flame, Building2, X, LocateFixed,
  Waypoints, Server, Box, GitMerge, Split, CircleDot, Milestone, Circle, HardHat,
} from 'lucide-react';
import { api, type MapData, type MapLayer, type MapPoint, type FibreType, type FleetData } from '../api/client';
import { getPosition, watchPosition } from '../utils/geolocate';
import { navLinks } from '../utils/nav';
import MapPicker from './MapPicker';
import { toast } from './ui';

type MLMap = maplibregl.Map;
type StyleSpecification = maplibregl.StyleSpecification;
type IconType = ComponentType<{ className?: string; size?: number; color?: string; strokeWidth?: number }>;

const WORLD_CENTER: [number, number] = [37.9, 0.2];
const TAB_FOR: Record<MapLayer, string> = {
  towers: 'network', clients: 'pppoe_clients', routers: 'mikrotik', leads: 'leads',
  fibre: 'fibre_plant',
};
// `heat` layers plot as a demand HEATMAP as well as pins (leads → where to expand next).
const LAYERS: { id: MapLayer; label: string; color: string; Icon: IconType; heat?: boolean }[] = [
  { id: 'towers', label: 'Towers', color: '#6D28D9', Icon: RadioTower },
  { id: 'clients', label: 'Clients', color: '#2563EB', Icon: Home },
  { id: 'routers', label: 'Routers', color: '#0F766E', Icon: RouterIcon },
  { id: 'leads', label: 'Leads', color: '#DB2777', Icon: UserPlus, heat: true },
  // Fibre is rendered by a DEDICATED block (per-type icons, no clustering, plus span lines), not
  // the generic loop — but it's in LAYERS so it gets a toolbar toggle, a legend row and a count.
  { id: 'fibre', label: 'Fibre', color: '#0E7490', Icon: Waypoints },
];

// A lucide icon per fibre-plant type, so an ODP reads differently from a pole at a glance.
const FIBRE_TYPE_ICON: Record<FibreType, IconType> = {
  olt_pop: Server, cabinet: Box, splice_closure: GitMerge, splitter: Split,
  odp: CircleDot, pole: Milestone, handhole: Circle, other: Circle,
};
const FIBRE_TYPES = Object.keys(FIBRE_TYPE_ICON) as FibreType[];
const FIBRE_TYPE_LABEL: Record<FibreType, string> = {
  olt_pop: 'OLT / POP', cabinet: 'Cabinet (FDT)', splice_closure: 'Splice closure',
  splitter: 'Splitter', odp: 'ODP', pole: 'Pole', handhole: 'Handhole', other: 'Other',
};

const STATUS_KEY: { label: string; color: string }[] = [
  { label: 'Active / online', color: '#228B22' },
  { label: 'Suspended / pending', color: '#B26B00' },
  { label: 'Offline / cancelled', color: '#B22222' },
];

function statusColor(s: string): string {
  const v = (s || '').toLowerCase();
  if (['up', 'online', 'active'].includes(v)) return '#228B22';
  if (['suspended', 'pending', 'pending_install'].includes(v)) return '#B26B00';
  if (['offline', 'cancelled', 'down'].includes(v)) return '#B22222';
  return '#6B7280';
}

// A live, key-free basemap: OSM streets + Esri satellite, toggled below.
function baseStyle(): StyleSpecification {
  return {
    version: 8,
    sources: {
      streets: {
        type: 'raster', tileSize: 256,
        tiles: ['https://a.tile.openstreetmap.org/{z}/{x}/{y}.png'],
        attribution: '© OpenStreetMap contributors',
      },
      satellite: {
        type: 'raster', tileSize: 256,
        tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
        attribution: 'Imagery © Esri',
      },
    },
    layers: [
      { id: 'base-streets', type: 'raster', source: 'streets', layout: { visibility: 'visible' } },
      { id: 'base-satellite', type: 'raster', source: 'satellite', layout: { visibility: 'none' } },
    ],
  };
}

/** Turn a lucide icon into a white map-marker image (no emoji, exact UI icons). Rasterises the
 *  SVG through a canvas — map.loadImage rejects SVG data-URLs, which would abort the whole
 *  load handler. Best-effort: a failure just means no glyph, never a broken map. */
async function addLucideIcon(map: MLMap, id: string, Icon: IconType) {
  if (map.hasImage(id)) return;
  const svg = renderToStaticMarkup(createElement(Icon, { color: '#ffffff', strokeWidth: 2.5, size: 22 }));
  const url = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  const image = new Image(44, 44);
  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve();
    image.onerror = reject;
    image.src = url;
  });
  const c = document.createElement('canvas');
  c.width = c.height = 44;
  c.getContext('2d')!.drawImage(image, 0, 0, 44, 44);
  if (!map.hasImage(id)) map.addImage(id, c.getContext('2d')!.getImageData(0, 0, 44, 44), { pixelRatio: 2 });
}

export default function MapView(
  { onNavigate, canViewFleet = false }: { onNavigate: (tab: string) => void; canViewFleet?: boolean },
) {
  const holder = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const [data, setData] = useState<MapData | null>(null);
  const [fleet, setFleet] = useState<FleetData | null>(null);   // live technician positions (dispatchers)
  const [error, setError] = useState('');
  const [basemap, setBasemap] = useState<'streets' | 'satellite'>('streets');
  const [visible, setVisible] = useState<Record<MapLayer, boolean>>({
    towers: true, clients: true, routers: true, leads: true, fibre: true,
  });
  const [heatmap, setHeatmap] = useState(false); // leads: heatmap vs pins
  const [showFleet, setShowFleet] = useState(true); // dispatchers: live technician layer on/off
  const [showBiz, setShowBiz] = useState(false); // "set business location" modal
  const [bizSet, setBizSet] = useState(false);   // hide the prompt after saving

  const navRef = useRef(onNavigate);
  navRef.current = onNavigate;
  const [mapReady, setMapReady] = useState(false);
  const addedRef = useRef(false);

  // "You are here" live dot (our own control — see the map-create effect for why not GeolocateControl).
  const dotRef = useRef<maplibregl.Marker | null>(null);
  const watchStopRef = useRef<(() => void) | null>(null);
  const [locating, setLocating] = useState(false); // waiting on the first fix
  const [tracking, setTracking] = useState(false); // dot is live and following

  const stopLocate = () => {
    watchStopRef.current?.();
    watchStopRef.current = null;
    dotRef.current?.remove();
    dotRef.current = null;
    setTracking(false);
    setLocating(false);
  };

  const toggleLocate = () => {
    const map = mapRef.current;
    if (!map) return;
    if (tracking || locating) { stopLocate(); return; }
    setLocating(true);
    let first = true;
    watchStopRef.current = watchPosition(
      ({ lat, lng }) => {
        setLocating(false);
        setTracking(true);
        if (!dotRef.current) {
          const el = document.createElement('div');
          el.className = 'wifios-here-dot';
          dotRef.current = new maplibregl.Marker({ element: el }).setLngLat([lng, lat]).addTo(map);
        } else {
          dotRef.current.setLngLat([lng, lat]);
        }
        if (first) { map.flyTo({ center: [lng, lat], zoom: 15, duration: 0 }); first = false; }
      },
      (msg) => { stopLocate(); toast('error', msg); },
    );
  };

  // Tear the watch down if the component unmounts mid-track.
  useEffect(() => () => { watchStopRef.current?.(); }, []);

  useEffect(() => {
    api.map.points().then(setData).catch(() => setError('Could not load the map data.'));
  }, []);

  // Dispatchers (fleet.view) poll the live technician fleet. Silent — a failed poll never
  // disturbs the map. Every 20s so dots track movement without hammering the server.
  useEffect(() => {
    if (!canViewFleet) return;
    let alive = true;
    const load = () => api.fleet.list().then((f) => { if (alive) setFleet(f); }).catch(() => {});
    load();
    const id = window.setInterval(load, 20_000);
    return () => { alive = false; window.clearInterval(id); };
  }, [canViewFleet]);

  // Create the map ONCE, decoupled from data. Keying this on [] (not [data]) is what makes it
  // StrictMode-safe: the fast local data fetch can otherwise resolve mid-probe and race the
  // create→destroy→create cycle, which wedges MapLibre (load never fires). Map first, data later.
  useEffect(() => {
    if (!holder.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: holder.current, style: baseStyle(), center: WORLD_CENTER, zoom: 5,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    // The "you are here" dot is driven by our own Locate button (toggleLocate) rather than
    // MapLibre's GeolocateControl: that control fires ONE high-accuracy request, which spins
    // forever on a desktop with no GPS. Our watchPosition() races a coarse network fix so the
    // dot appears fast and then follows movement — the same path the form "use my location" uses.
    const ro = new ResizeObserver(() => map.resize());
    ro.observe(holder.current);
    map.on('load', () => {
      map.resize();
      setMapReady(true);
    });
    return () => { ro.disconnect(); map.remove(); mapRef.current = null; setMapReady(false); addedRef.current = false; };
  }, []);

  // Once the map is loaded AND we have data, add the layers (once).
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !data || addedRef.current) return;
    addedRef.current = true;

    const hover = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 16 });
    for (const layer of LAYERS) {
      if (layer.id === 'fibre') continue;   // rendered by the dedicated fibre block below
      const features = (data.layers[layer.id] || []).map((pt) => ({
        type: 'Feature' as const,
        geometry: { type: 'Point' as const, coordinates: [pt.lng, pt.lat] },
        properties: { ...pt, statusColor: statusColor(pt.status), layer: layer.id },
      }));
      // Heat layers don't cluster (a heatmap needs the raw points); the rest do.
      map.addSource(layer.id, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features },
        cluster: !layer.heat, clusterMaxZoom: 13, clusterRadius: 44,
      });
      if (layer.heat) {
        // Demand heatmap — density of open leads. Hidden until the Heatmap toggle turns it on.
        map.addLayer({
          id: `${layer.id}-heat`, type: 'heatmap', source: layer.id,
          layout: { visibility: 'none' },
          paint: {
            'heatmap-weight': 1,
            'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 8, 1, 15, 3],
            'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 8, 18, 15, 45],
            'heatmap-opacity': 0.75,
            'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'],
              0, 'rgba(0,0,0,0)', 0.2, '#fde68a', 0.4, '#fb923c', 0.7, '#ef4444', 1, '#b91c1c'],
          },
        });
      }
      map.addLayer({
        id: `${layer.id}-cluster`, type: 'circle', source: layer.id,
        filter: ['has', 'point_count'],
        paint: {
          'circle-color': layer.color, 'circle-opacity': 0.9,
          'circle-radius': ['step', ['get', 'point_count'], 15, 10, 21, 50, 28],
          'circle-stroke-width': 2, 'circle-stroke-color': '#fff',
        },
      });
      map.addLayer({
        id: `${layer.id}-pt`, type: 'circle', source: layer.id,
        filter: ['!', ['has', 'point_count']],
        paint: {
          'circle-radius': 13, 'circle-color': ['get', 'statusColor'],
          'circle-stroke-width': 2.5, 'circle-stroke-color': '#fff',
        },
      });
      // Icons layer on top when ready — a failed glyph never blocks the status-coloured discs.
      addLucideIcon(map, `icon-${layer.id}`, layer.Icon).then(() => {
        if (map.getSource(layer.id) && !map.getLayer(`${layer.id}-icon`)) {
          map.addLayer({
            id: `${layer.id}-icon`, type: 'symbol', source: layer.id,
            filter: ['!', ['has', 'point_count']],
            layout: { 'icon-image': `icon-${layer.id}`, 'icon-size': 0.62, 'icon-allow-overlap': true },
          });
        }
      }).catch(() => {});

      map.on('click', `${layer.id}-cluster`, (e) => {
        const f = e.features?.[0];
        const src = map.getSource(layer.id) as maplibregl.GeoJSONSource;
        src.getClusterExpansionZoom(f?.properties?.cluster_id).then((z) =>
          map.easeTo({ center: (f!.geometry as GeoJSON.Point).coordinates as [number, number], zoom: z }));
      });
      map.on('mousemove', `${layer.id}-pt`, (e) => {
        const f = e.features?.[0];
        if (!f) return;
        map.getCanvas().style.cursor = 'pointer';
        hover.setLngLat((f.geometry as GeoJSON.Point).coordinates as [number, number])
          .setDOMContent(card(f.properties as unknown as MapPoint, layer))
          .addTo(map);
      });
      map.on('mouseleave', `${layer.id}-pt`, () => { map.getCanvas().style.cursor = ''; hover.remove(); });
      map.on('mouseenter', `${layer.id}-cluster`, () => (map.getCanvas().style.cursor = 'pointer'));
      map.on('mouseleave', `${layer.id}-cluster`, () => (map.getCanvas().style.cursor = ''));
      map.on('click', `${layer.id}-pt`, () =>
        navRef.current(TAB_FOR[layer.id]));
    }

    // ---- FIBRE PLANT: span lines (under the pins) + type-icon points ---------------------------
    // Spans FIRST so the route sits beneath every pin. Both are plain GeoJSON, so they ride the
    // same worker the other layers do — verified in a production build, not just dev.
    const spanFeatures = (data.fibre_spans || []).map((s) => ({
      type: 'Feature' as const,
      geometry: { type: 'LineString' as const, coordinates: [[s.from_lng, s.from_lat], [s.to_lng, s.to_lat]] },
      properties: { id: s.id, status: s.status, cable_type: s.cable_type },
    }));
    map.addSource('fibre-spans', { type: 'geojson', data: { type: 'FeatureCollection', features: spanFeatures } });
    // Insert below the first pin layer that exists, so cables never cover the discs.
    const firstPin = ['towers-cluster', 'clients-cluster', 'routers-cluster', 'leads-pt']
      .find((id) => map.getLayer(id));
    map.addLayer({
      id: 'fibre-spans-line', type: 'line', source: 'fibre-spans',
      layout: { visibility: visible.fibre ? 'visible' : 'none', 'line-cap': 'round' },
      paint: {
        'line-color': ['match', ['get', 'status'],
          'down', '#B22222', 'needs_attention', '#B26B00', '#0E7490'],
        'line-width': ['interpolate', ['linear'], ['zoom'], 8, 1.5, 15, 3.5],
        'line-opacity': 0.85,
      },
    }, firstPin);

    const fibreFeatures = (data.layers.fibre || []).map((pt) => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [pt.lng, pt.lat] },
      properties: { ...pt, statusColor: statusColor(pt.status), layer: 'fibre' },
    }));
    // No clustering: spans connect to SPECIFIC points, so points must stay individually visible.
    map.addSource('fibre', { type: 'geojson', data: { type: 'FeatureCollection', features: fibreFeatures } });
    map.addLayer({
      id: 'fibre-pt', type: 'circle', source: 'fibre',
      layout: { visibility: visible.fibre ? 'visible' : 'none' },
      paint: {
        'circle-radius': 12, 'circle-color': ['get', 'statusColor'],
        'circle-stroke-width': 2.5, 'circle-stroke-color': '#fff',
      },
    });
    // One icon per type, chosen by the point's `ptype`, with 'other' as the fallback.
    Promise.all(FIBRE_TYPES.map((t) => addLucideIcon(map, `fibre-${t}`, FIBRE_TYPE_ICON[t])))
      .then(() => {
        if (!map.getSource('fibre') || map.getLayer('fibre-icon')) return;
        map.addLayer({
          id: 'fibre-icon', type: 'symbol', source: 'fibre',
          layout: {
            visibility: visible.fibre ? 'visible' : 'none',
            'icon-image': ['match', ['get', 'ptype'],
              ...FIBRE_TYPES.flatMap((t) => [t, `fibre-${t}`]),
              'fibre-other'] as unknown as string,
            'icon-size': 0.5, 'icon-allow-overlap': true,
          },
        });
      }).catch(() => {});
    map.on('mousemove', 'fibre-pt', (e) => {
      const f = e.features?.[0];
      if (!f) return;
      map.getCanvas().style.cursor = 'pointer';
      hover.setLngLat((f.geometry as GeoJSON.Point).coordinates as [number, number])
        .setDOMContent(fibreCard(f.properties as unknown as MapPoint))
        .addTo(map);
    });
    map.on('mouseleave', 'fibre-pt', () => { map.getCanvas().style.cursor = ''; hover.remove(); });
    map.on('click', 'fibre-pt', () => navRef.current(TAB_FOR.fibre));

    // Where to open. THE PINS MUST BE VISIBLE — a location you just set is useless if it opens
    // somewhere else. So: if there are ANY placed assets, frame ALL of them (plus the device,
    // if it'll share, so "where am I" is in shot too). Only when there's nothing placed yet do
    // we open on the device location / business location / Kenya.
    const hasPins = !!data.center; // center is null only when nothing is placed
    if (hasPins) {
      getPosition()
        .then((c) => fitToData(map, data, [c.lng, c.lat])) // frame pins + me
        .catch(() => fitToData(map, data));                // just the pins if no location
    } else if (data.business_location) {
      map.flyTo({ center: [data.business_location.lng, data.business_location.lat], zoom: 13, duration: 0 });
    } else {
      getPosition()
        .then((c) => map.flyTo({ center: [c.lng, c.lat], zoom: 14, duration: 0 }))
        .catch(() => {});
    }
  }, [mapReady, data]);

  // NB: these toggles guard on the LAYER existing, not isStyleLoaded() — the latter is
  // transiently false while tiles stream, and bailing on it made toggles silently no-op.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getLayer('base-streets')) return;
    map.setLayoutProperty('base-streets', 'visibility', basemap === 'streets' ? 'visible' : 'none');
    map.setLayoutProperty('base-satellite', 'visibility', basemap === 'satellite' ? 'visible' : 'none');
  }, [basemap]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    for (const layer of LAYERS) {
      const on = visible[layer.id];
      // For a heat layer with the heatmap toggled on: show the heat surface, hide the pins.
      const asHeat = !!layer.heat && heatmap;
      const set = (sfx: string, v: boolean) => {
        const id = `${layer.id}-${sfx}`;
        if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', v ? 'visible' : 'none');
      };
      set('heat', on && asHeat);
      for (const sfx of ['cluster', 'pt', 'icon']) set(sfx, on && !asHeat);
    }
    // The fibre span lines follow the fibre toggle too (the loop only covers the -pt/-icon/-cluster
    // suffixes; the line layer is 'fibre-spans-line').
    if (map.getLayer('fibre-spans-line')) {
      map.setLayoutProperty('fibre-spans-line', 'visibility', visible.fibre ? 'visible' : 'none');
    }
  }, [visible, heatmap, mapReady]);

  // ---- LIVE TECHNICIAN FLEET (dispatchers only) ---------------------------------------------
  // Added once, its data refreshed by the poll effect above; a hard-hat pin coloured live/stale.
  const fleetAddedRef = useRef(false);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !canViewFleet || fleetAddedRef.current) return;
    fleetAddedRef.current = true;
    const hover = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 16 });
    map.addSource('fleet', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    map.addLayer({
      id: 'fleet-pt', type: 'circle', source: 'fleet',
      paint: {
        'circle-radius': 13,
        'circle-color': ['case', ['get', 'is_live'], '#059669', '#94A3B8'],
        'circle-stroke-width': 3, 'circle-stroke-color': '#fff',
      },
    });
    addLucideIcon(map, 'icon-fleet', HardHat).then(() => {
      if (map.getSource('fleet') && !map.getLayer('fleet-icon')) {
        map.addLayer({
          id: 'fleet-icon', type: 'symbol', source: 'fleet',
          layout: { 'icon-image': 'icon-fleet', 'icon-size': 0.55, 'icon-allow-overlap': true },
        });
      }
    }).catch(() => {});
    map.on('mousemove', 'fleet-pt', (e) => {
      const f = e.features?.[0];
      if (!f) return;
      map.getCanvas().style.cursor = 'pointer';
      hover.setLngLat((f.geometry as GeoJSON.Point).coordinates as [number, number])
        .setDOMContent(fleetCard(f.properties as unknown as FleetProps))
        .addTo(map);
    });
    map.on('mouseleave', 'fleet-pt', () => { map.getCanvas().style.cursor = ''; hover.remove(); });
  }, [mapReady, canViewFleet]);

  // Push fleet data into the source whenever a poll returns OR the source has just been added
  // (mapReady in the deps closes the race where the first poll lands before the layer exists).
  useEffect(() => {
    const map = mapRef.current;
    const src = map?.getSource('fleet') as maplibregl.GeoJSONSource | undefined;
    if (!src || !fleet) return;
    src.setData({
      type: 'FeatureCollection',
      features: fleet.members.map((m) => ({
        type: 'Feature' as const,
        geometry: { type: 'Point' as const, coordinates: [Number(m.lng), Number(m.lat)] },
        properties: { ...m },
      })),
    });
  }, [fleet, mapReady, canViewFleet]);

  // Fleet visibility toggle.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    for (const id of ['fleet-pt', 'fleet-icon']) {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', showFleet ? 'visible' : 'none');
    }
  }, [showFleet, fleet, mapReady]);

  const totalUnplaced = data
    ? Object.values(data.unplaced).reduce<number>((a, b) => a + Number(b), 0)
    : 0;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-lg font-bold font-mono uppercase tracking-wide flex items-center gap-2">
            <MapPin className="h-5 w-5" /> Map
          </h1>
          <p className="text-sm text-[#141414]/60">Towers, clients, routers and leads on a live map.</p>
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          {LAYERS.map((l) => (
            <button
              key={l.id}
              onClick={() => setVisible((v) => ({ ...v, [l.id]: !v[l.id] }))}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-bold font-mono uppercase border cursor-pointer ${
                visible[l.id] ? 'text-white border-[#141414]' : 'bg-white text-[#141414]/40 border-[#141414]/30'
              }`}
              style={visible[l.id] ? { background: l.color, borderColor: l.color } : undefined}
            >
              <l.Icon className="h-3.5 w-3.5" />
              {l.label} {data ? data.counts[l.id] : ''}
            </button>
          ))}
          <button
            onClick={() => setHeatmap((h) => !h)}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-bold font-mono uppercase border cursor-pointer ${
              heatmap ? 'bg-[#DB2777] text-white border-[#DB2777]' : 'bg-white text-[#141414]/60 border-[#141414]/40'
            }`}
            title="Show open leads as a demand heatmap — where to expand next"
          >
            <Flame className="h-3.5 w-3.5" /> Heatmap
          </button>
          {canViewFleet && (
            <button
              onClick={() => setShowFleet((v) => !v)}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-bold font-mono uppercase border cursor-pointer ${
                showFleet ? 'bg-[#059669] text-white border-[#059669]' : 'bg-white text-[#141414]/60 border-[#141414]/40'
              }`}
              title="Show your technicians' live positions"
            >
              <HardHat className="h-3.5 w-3.5" /> Technicians {fleet ? fleet.members.length : ''}
            </button>
          )}
          <button
            onClick={toggleLocate}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-bold font-mono uppercase border cursor-pointer ${
              tracking || locating ? 'bg-[#2563EB] text-white border-[#2563EB]' : 'bg-white text-[#141414]/60 border-[#141414]/40'
            }`}
            title="Show where you're standing — a live dot that follows you"
          >
            {locating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <LocateFixed className="h-3.5 w-3.5" />}
            {tracking ? 'Locating' : locating ? 'Finding…' : 'Locate me'}
          </button>
          <button
            onClick={() => setBasemap((b) => (b === 'streets' ? 'satellite' : 'streets'))}
            className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-bold font-mono uppercase border border-[#141414] bg-[#141414] text-white cursor-pointer"
            title="Switch between street and satellite view"
          >
            {basemap === 'streets'
              ? <><Satellite className="h-3.5 w-3.5" /> Satellite</>
              : <><MapGlyph className="h-3.5 w-3.5" /> Streets</>}
          </button>
        </div>
      </div>

      {error && <div className="text-sm text-[#B22222]">{error}</div>}

      {totalUnplaced > 0 && (
        <div className="flex items-center gap-2 text-xs bg-[#FFF8EC] border border-[#B26B00]/30 text-[#B26B00] px-3 py-2">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>
            <b>{totalUnplaced}</b> record{totalUnplaced > 1 ? 's' : ''} without a location
            {data && ` (${data.unplaced.towers} towers, ${data.unplaced.clients} clients, ${data.unplaced.routers} routers, ${data.unplaced.leads} leads)`}
            {' '}— drop a pin on them from their edit page to see them here.
          </span>
        </div>
      )}

      {data && !data.business_location && !bizSet && (
        <div className="flex items-center gap-2 text-xs bg-[#EAF3FF] border border-[#2563EB]/30 text-[#1D4ED8] px-3 py-2">
          <Building2 className="h-4 w-4 shrink-0" />
          <span className="flex-1">
            Set your <b>business location</b> so the map always opens at your base of operations.
          </span>
          <button
            onClick={() => setShowBiz(true)}
            className="font-bold font-mono uppercase text-[10px] border border-[#2563EB] text-[#2563EB] px-2 py-1 cursor-pointer hover:bg-[#2563EB] hover:text-white"
          >
            Set location
          </button>
        </div>
      )}

      {showBiz && (
        <SetBusinessLocationModal
          onClose={() => setShowBiz(false)}
          onSaved={(lat, lng) => {
            setShowBiz(false);
            setBizSet(true);
            mapRef.current?.flyTo({ center: [lng, lat], zoom: 14, duration: 0 });
          }}
        />
      )}

      {/* Full-width map (no flex width race) with the legend as an overlay card. The map div
          carries an explicit height/width so MapLibre always has a size to render into. */}
      <div className="relative border border-[#141414] w-full">
        {!data && !error && (
          <div className="absolute inset-0 z-10 flex items-center justify-center text-sm text-[#141414]/50 bg-[#e7edf2]">
            <Loader2 className="h-4 w-4 animate-spin mr-2" /> Loading map…
          </div>
        )}
        <div ref={holder} style={{ height: '74vh', width: '100%' }} />

        {/* The guide — what each pin means. */}
        <aside className="absolute top-3 left-3 z-10 w-52 bg-white/95 border border-[#141414] p-3 shadow-sm hidden sm:block">
          <p className="text-[10px] font-mono uppercase tracking-wider text-[#141414]/40 mb-2">What the pins mean</p>
          <div className="space-y-2">
            {LAYERS.map((l) => (
              <div key={l.id} className="flex items-center gap-2 text-xs">
                <span className="w-6 h-6 rounded-full flex items-center justify-center text-white shrink-0" style={{ background: l.color }}>
                  <l.Icon className="h-3.5 w-3.5" />
                </span>
                <span className="font-bold">{l.label}</span>
                <span className="ml-auto text-[#141414]/40">{data ? data.counts[l.id] : ''}</span>
              </div>
            ))}
            {canViewFleet && (
              <div className="flex items-center gap-2 text-xs pt-1 border-t border-[#141414]/10">
                <span className="w-6 h-6 rounded-full flex items-center justify-center text-white shrink-0" style={{ background: '#059669' }}>
                  <HardHat className="h-3.5 w-3.5" />
                </span>
                <span className="font-bold">Technicians</span>
                <span className="ml-auto text-[#141414]/40">{fleet ? fleet.members.length : ''}</span>
              </div>
            )}
          </div>
          <p className="text-[10px] font-mono uppercase tracking-wider text-[#141414]/40 mt-3 mb-1.5">Dot colour = status</p>
          <div className="space-y-1">
            {STATUS_KEY.map((s) => (
              <div key={s.label} className="flex items-center gap-2 text-[11px]">
                <span className="w-3 h-3 rounded-full border border-white shrink-0"
                      style={{ background: s.color, boxShadow: '0 0 0 1px #14141433' }} />
                {s.label}
              </div>
            ))}
          </div>
          <p className="text-[10px] text-[#141414]/45 mt-2.5 leading-relaxed">
            Hover a pin for details · click to open the record · tap <b>Locate me</b> to show
            where you&apos;re standing (a live blue dot that follows you).
          </p>
        </aside>
      </div>

      {/* The live "you are here" dot — a blue disc with a soft radar pulse. */}
      <style>{`
        .wifios-here-dot {
          width: 16px; height: 16px; border-radius: 50%;
          background: #2563EB; border: 3px solid #fff;
          box-shadow: 0 0 0 2px rgba(37,99,235,.45);
        }
        .wifios-here-dot::before {
          content: ''; position: absolute; left: 50%; top: 50%;
          width: 16px; height: 16px; border-radius: 50%;
          transform: translate(-50%, -50%); background: rgba(37,99,235,.35);
          animation: wifios-here-pulse 2s ease-out infinite;
        }
        @keyframes wifios-here-pulse {
          0% { width: 16px; height: 16px; opacity: .6; }
          100% { width: 60px; height: 60px; opacity: 0; }
        }
      `}</style>
    </div>
  );
}

function fitToData(map: MLMap, data: MapData, extra?: [number, number]) {
  const all: MapPoint[] = [
    ...data.layers.towers, ...data.layers.clients, ...data.layers.routers,
    ...data.layers.leads, ...data.layers.fibre,
  ];
  const coords: [number, number][] = all.map((p) => [p.lng, p.lat]);
  if (extra) coords.push(extra);
  if (coords.length === 0) return;
  if (coords.length === 1) {
    map.flyTo({ center: coords[0], zoom: 14, duration: 0 });
    return;
  }
  const b = new maplibregl.LngLatBounds();
  coords.forEach((c) => b.extend(c));
  map.fitBounds(b, { padding: 70, maxZoom: 15, duration: 0 });
}

/** A "Navigate" link for the popup — opens the tech's Google Maps to this coordinate (the app on a
 *  phone). The console record pages carry the full multi-app chooser; the popup keeps it to one tap. */
function navHtml(p: MapPoint): string {
  return `<a href="${navLinks(p.lat, p.lng, p.label).google}" target="_blank" rel="noreferrer" style="display:inline-block;margin-top:7px;font-size:11px;font-weight:700;color:#0E7490;text-decoration:none">Navigate &#9656;</a>`;
}

/** The hover detail card — richest for a client, so the ISP knows exactly who it is. */
function card(p: MapPoint, layer: { id: MapLayer; label: string }): HTMLElement {
  const el = document.createElement('div');
  el.style.cssText = 'font-family:sans-serif;min-width:160px';
  const chip = `<span style="display:inline-block;padding:1px 6px;border-radius:9px;font-size:10px;font-weight:700;text-transform:uppercase;color:#fff;background:${statusColor(p.status)}">${esc(p.status)}</span>`;
  const rows = (kv: [string, string | undefined][]) =>
    `<table style="font-size:11px;color:#333;border-collapse:collapse">${kv
      .map(([k, v]) => `<tr><td style="color:#888;padding-right:8px">${k}</td><td>${esc(v || '—')}</td></tr>`)
      .join('')}</table>`;
  if (layer.id === 'clients') {
    el.innerHTML = `
      <div style="font-weight:700;font-size:13px;margin-bottom:3px">${esc(p.label)}</div>
      <div style="margin-bottom:5px">${chip}</div>
      ${rows([['Account', p.account], ['Plan', p.plan], ['Phone', p.phone], ['Type', p.connection]])}
      <div style="font-size:10px;color:#999;margin-top:5px">Click to open this client</div>${navHtml(p)}`;
  } else if (layer.id === 'leads') {
    el.innerHTML = `
      <div style="font-weight:700;font-size:13px;margin-bottom:3px">${esc(p.label)}</div>
      <div style="margin-bottom:5px">${chip}</div>
      ${rows([['Phone', p.phone], ['Source', p.source]])}
      <div style="font-size:10px;color:#999;margin-top:5px">A prospect — click to open in Leads</div>${navHtml(p)}`;
  } else {
    el.innerHTML = `
      <div style="font-weight:700;font-size:13px;margin-bottom:3px">${esc(p.label)}</div>
      <div>${chip}</div>
      <div style="font-size:10px;color:#999;margin-top:5px">Click to open in ${layer.id === 'routers' ? 'MikroTik' : 'Network'}</div>${navHtml(p)}`;
  }
  return el;
}

/** The fibre-plant hover card — type, status, and live port capacity (used / total, free). */
function fibreCard(p: MapPoint): HTMLElement {
  const el = document.createElement('div');
  el.style.cssText = 'font-family:sans-serif;min-width:170px';
  const chip = `<span style="display:inline-block;padding:1px 6px;border-radius:9px;font-size:10px;font-weight:700;text-transform:uppercase;color:#fff;background:${statusColor(p.status)}">${esc(p.status)}</span>`;
  const typeLabel = FIBRE_TYPE_LABEL[(p.ptype ?? 'other') as FibreType] ?? esc(p.ptype || '');
  const cap = p.capacity
    ? `${p.used ?? 0} / ${p.capacity} ports${p.free != null ? ` · ${p.free} free` : ''}`
    : '—';
  el.innerHTML = `
    <div style="font-weight:700;font-size:13px;margin-bottom:3px">${esc(p.label)}</div>
    <div style="font-size:11px;color:#555;margin-bottom:5px">${esc(typeLabel)} · ${chip}</div>
    <table style="font-size:11px;color:#333;border-collapse:collapse">
      <tr><td style="color:#888;padding-right:8px">Capacity</td><td>${cap}</td></tr>
    </table>${navHtml(p)}`;
  return el;
}

function esc(s: string): string {
  return (s || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]!));
}

type FleetProps = { name: string; is_live: boolean; recorded_at: string };
function timeAgo(iso: string): string {
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return 'just now';
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  return `${Math.floor(mins / 60)}h ago`;
}
/** The hover card for a technician's live dot. */
function fleetCard(m: FleetProps): HTMLElement {
  const el = document.createElement('div');
  el.style.cssText = 'font-family:sans-serif;min-width:150px';
  const color = m.is_live ? '#059669' : '#94A3B8';
  el.innerHTML = `
    <div style="font-weight:700;font-size:13px;margin-bottom:3px">${esc(m.name || 'Technician')}</div>
    <div style="font-size:11px;color:#555"><span style="color:${color};font-weight:700">${m.is_live ? 'LIVE' : 'STALE'}</span> · seen ${esc(timeAgo(m.recorded_at))}</div>`;
  return el;
}

/**
 * Capture the ISP's business location. Opens pre-centred on the device's current position (an
 * ISP is usually AT its base when setting this up), so it's typically one tap of "Use my
 * location" and Save. Persists to the operator so the Map always opens here.
 */
function SetBusinessLocationModal({
  onClose, onSaved,
}: {
  onClose: () => void;
  onSaved: (lat: number, lng: number) => void;
}) {
  const [lat, setLat] = useState<number | null>(null);
  const [lng, setLng] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  // Pre-fill with wherever the device is right now — the common case.
  useEffect(() => {
    let alive = true;
    getPosition().then((c) => { if (alive && lat == null) { setLat(c.lat); setLng(c.lng); } }).catch(() => {});
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async () => {
    if (lat == null || lng == null || busy) return;
    setBusy(true);
    try {
      await api.map.setBusinessLocation(lat, lng);
      toast('success', 'Business location saved.');
      onSaved(lat, lng);
    } catch {
      toast('error', 'Could not save the location.');
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-[#141414]/50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white border border-[#141414] w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-[#141414]">
          <h3 className="font-bold font-mono uppercase text-sm flex items-center gap-2">
            <Building2 className="h-4 w-4" /> Your business location
          </h3>
          <button onClick={onClose} className="cursor-pointer"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-4">
          <p className="text-xs text-[#141414]/60 mb-3">
            Where your business is based — the map will always open here. It starts at your
            current location; drag the pin or click to adjust.
          </p>
          <MapPicker
            lat={lat} lng={lng}
            onChange={(la, ln) => {
              setLat(Number.isFinite(la) ? la : null);
              setLng(Number.isFinite(ln) ? ln : null);
            }}
          />
          <div className="flex justify-end gap-2 mt-4">
            <button onClick={onClose} className="text-xs font-mono font-bold uppercase border border-[#141414] px-3 py-2 cursor-pointer">Cancel</button>
            <button onClick={save} disabled={busy || lat == null}
              className="text-xs font-mono font-bold uppercase border border-[#228B22] bg-[#228B22] text-white px-3 py-2 cursor-pointer disabled:opacity-40">
              {busy ? 'Saving…' : 'Save location'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
