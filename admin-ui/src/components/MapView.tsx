import { createElement, useEffect, useRef, useState, type ComponentType } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import {
  MapPin, RadioTower, Router as RouterIcon, Home, UserPlus, Loader2, AlertTriangle,
  Satellite, Map as MapGlyph, Flame, Building2, X,
} from 'lucide-react';
import { api, type MapData, type MapLayer, type MapPoint } from '../api/client';
import { getPosition } from '../utils/geolocate';
import MapPicker from './MapPicker';
import { toast } from './ui';

type MLMap = maplibregl.Map;
type StyleSpecification = maplibregl.StyleSpecification;
type IconType = ComponentType<{ className?: string; size?: number; color?: string; strokeWidth?: number }>;

const WORLD_CENTER: [number, number] = [37.9, 0.2];
const TAB_FOR: Record<MapLayer, string> = {
  towers: 'network', clients: 'pppoe_clients', routers: 'mikrotik', leads: 'leads',
};
// `heat` layers plot as a demand HEATMAP as well as pins (leads → where to expand next).
const LAYERS: { id: MapLayer; label: string; color: string; Icon: IconType; heat?: boolean }[] = [
  { id: 'towers', label: 'Towers', color: '#6D28D9', Icon: RadioTower },
  { id: 'clients', label: 'Clients', color: '#2563EB', Icon: Home },
  { id: 'routers', label: 'Routers', color: '#0F766E', Icon: RouterIcon },
  { id: 'leads', label: 'Leads', color: '#DB2777', Icon: UserPlus, heat: true },
];

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

export default function MapView({ onNavigate }: { onNavigate: (tab: string) => void }) {
  const holder = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const [data, setData] = useState<MapData | null>(null);
  const [error, setError] = useState('');
  const [basemap, setBasemap] = useState<'streets' | 'satellite'>('streets');
  const [visible, setVisible] = useState<Record<MapLayer, boolean>>({
    towers: true, clients: true, routers: true, leads: true,
  });
  const [heatmap, setHeatmap] = useState(false); // leads: heatmap vs pins
  const [showBiz, setShowBiz] = useState(false); // "set business location" modal
  const [bizSet, setBizSet] = useState(false);   // hide the prompt after saving

  const navRef = useRef(onNavigate);
  navRef.current = onNavigate;
  const [mapReady, setMapReady] = useState(false);
  const addedRef = useRef(false);

  useEffect(() => {
    api.map.points().then(setData).catch(() => setError('Could not load the map data.'));
  }, []);

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
    // "You are here" — a live blue dot that FOLLOWS the viewer as they move (watchPosition
    // under the hood), with a heading arrow. This is the technician seeing where they stand
    // in the field, relative to the towers/clients/ADSS around them. Client-side only; needs
    // HTTPS (staging :8443 / localhost) and the one-time browser location prompt.
    map.addControl(new maplibregl.GeolocateControl({
      // A timeout + maximumAge so a device without a quick GPS fix doesn't hang or hard-fail;
      // a recent cached position answers instantly on repeated taps.
      positionOptions: { enableHighAccuracy: true, timeout: 8000, maximumAge: 30000 },
      trackUserLocation: true,
      showAccuracyCircle: true,
    }), 'top-right');
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
    // Where to open. If the ISP has SET a business location, that's home. Otherwise open at the
    // DEVICE's current location — an ISP is physically at its operating area, so "where am I" is
    // the natural first view (and we prompt them to save it as their business location). If the
    // device won't share, fall back to the spread of their placed assets, else Kenya.
    if (data.business_location) {
      map.flyTo({ center: [data.business_location.lng, data.business_location.lat], zoom: 13, duration: 0 });
    } else {
      getPosition()
        .then((c) => map.flyTo({ center: [c.lng, c.lat], zoom: 14, duration: 0 }))
        .catch(() => { if (data.center) fitToData(map, data); });
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
  }, [visible, heatmap, mapReady]);

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
            Hover a pin for details · click to open the record · tap the ◎ locate button to
            show where you&apos;re standing.
          </p>
        </aside>
      </div>
    </div>
  );
}

function fitToData(map: MLMap, data: MapData) {
  const all: MapPoint[] = [...data.layers.towers, ...data.layers.clients, ...data.layers.routers];
  if (all.length < 2) return;
  const b = new maplibregl.LngLatBounds();
  all.forEach((p) => b.extend([p.lng, p.lat]));
  map.fitBounds(b, { padding: 70, maxZoom: 15, duration: 0 });
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
      <div style="font-size:10px;color:#999;margin-top:5px">Click to open this client</div>`;
  } else if (layer.id === 'leads') {
    el.innerHTML = `
      <div style="font-weight:700;font-size:13px;margin-bottom:3px">${esc(p.label)}</div>
      <div style="margin-bottom:5px">${chip}</div>
      ${rows([['Phone', p.phone], ['Source', p.source]])}
      <div style="font-size:10px;color:#999;margin-top:5px">A prospect — click to open in Leads</div>`;
  } else {
    el.innerHTML = `
      <div style="font-weight:700;font-size:13px;margin-bottom:3px">${esc(p.label)}</div>
      <div>${chip}</div>
      <div style="font-size:10px;color:#999;margin-top:5px">Click to open in ${layer.id === 'routers' ? 'MikroTik' : 'Network'}</div>`;
  }
  return el;
}

function esc(s: string): string {
  return (s || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]!));
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
