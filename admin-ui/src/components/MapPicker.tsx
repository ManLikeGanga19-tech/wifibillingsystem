import { useEffect, useRef, useState } from 'react';
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Crosshair, Loader2, X } from 'lucide-react';

type MLMap = maplibregl.Map;
type StyleSpecification = maplibregl.StyleSpecification;

const KENYA_CENTER: [number, number] = [37.9, 0.2];

// A plain OSM streets base — same key-free tiles as the Map page, so a pin sits where the tech
// actually is. No satellite here; picking a spot is clearer on a street map.
function streetsStyle(): StyleSpecification {
  return {
    version: 8,
    sources: {
      streets: {
        type: 'raster', tileSize: 256,
        tiles: ['https://a.tile.openstreetmap.org/{z}/{x}/{y}.png'],
        attribution: '© OpenStreetMap contributors',
      },
    },
    layers: [{ id: 'streets', type: 'raster', source: 'streets' }],
  };
}

/**
 * Drop-a-pin location picker, reused on the tower / client / router / lead forms. Click or drag
 * the pin to set the coordinates; "Use my current location" reads the device GPS (a field tech
 * standing at the site). Fully inbuilt — no geocoder, no keys. Emits (lat, lng) up to the form.
 */
export default function MapPicker({
  lat, lng, onChange, height = 260,
}: {
  lat: number | null;
  lng: number | null;
  onChange: (lat: number, lng: number) => void;
  height?: number;
}) {
  const holder = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const [ready, setReady] = useState(false);
  const [locating, setLocating] = useState(false);
  const [geoError, setGeoError] = useState('');

  const place = (la: number, ln: number) => {
    const map = mapRef.current;
    if (!map) return;
    if (!markerRef.current) {
      markerRef.current = new maplibregl.Marker({ color: '#B22222', draggable: true })
        .setLngLat([ln, la]).addTo(map);
      markerRef.current.on('dragend', () => {
        const p = markerRef.current!.getLngLat();
        onChangeRef.current(round(p.lat), round(p.lng));
      });
    } else {
      markerRef.current.setLngLat([ln, la]);
    }
    onChangeRef.current(round(la), round(ln));
  };

  // Create the map ONCE (StrictMode-safe: [] deps, guard, explicit size).
  useEffect(() => {
    if (!holder.current || mapRef.current) return;
    const start: [number, number] = lat != null && lng != null ? [lng, lat] : KENYA_CENTER;
    const map = new maplibregl.Map({
      container: holder.current, style: streetsStyle(),
      center: start, zoom: lat != null ? 14 : 6,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    const ro = new ResizeObserver(() => map.resize());
    ro.observe(holder.current);
    map.on('load', () => {
      map.resize();
      setReady(true);
      if (lat != null && lng != null) {
        markerRef.current = new maplibregl.Marker({ color: '#B22222', draggable: true })
          .setLngLat([lng, lat]).addTo(map);
        markerRef.current.on('dragend', () => {
          const p = markerRef.current!.getLngLat();
          onChangeRef.current(round(p.lat), round(p.lng));
        });
      }
    });
    map.on('click', (e) => place(e.lngLat.lat, e.lngLat.lng));
    return () => { ro.disconnect(); map.remove(); mapRef.current = null; markerRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const useMyLocation = () => {
    setGeoError('');
    if (!navigator.geolocation) { setGeoError('This device has no location service.'); return; }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        const { latitude, longitude } = pos.coords;
        mapRef.current?.flyTo({ center: [longitude, latitude], zoom: 16, duration: 0 });
        place(latitude, longitude);
      },
      () => { setLocating(false); setGeoError('Could not get your location — allow location access, or click the map.'); },
      { enableHighAccuracy: true, timeout: 10000 },
    );
  };

  const clear = () => {
    markerRef.current?.remove();
    markerRef.current = null;
    onChangeRef.current(NaN, NaN); // caller treats NaN as "cleared"
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[11px] font-mono text-[#141414]/50">
          {lat != null && lng != null
            ? <>Pinned at <b>{lat.toFixed(5)}, {lng.toFixed(5)}</b></>
            : 'Click the map to drop a pin, or use your location.'}
        </span>
        <div className="flex items-center gap-1.5">
          <button type="button" onClick={useMyLocation} disabled={locating}
            className="flex items-center gap-1 text-[11px] font-mono font-bold uppercase border border-[#141414] px-2 py-1 cursor-pointer hover:bg-[#141414] hover:text-white disabled:opacity-40">
            {locating ? <Loader2 className="h-3 w-3 animate-spin" /> : <Crosshair className="h-3 w-3" />}
            Use my location
          </button>
          {lat != null && lng != null && (
            <button type="button" onClick={clear}
              className="flex items-center gap-1 text-[11px] font-mono font-bold uppercase border border-[#141414]/40 px-2 py-1 cursor-pointer hover:bg-[#141414]/5">
              <X className="h-3 w-3" /> Clear
            </button>
          )}
        </div>
      </div>
      <div className="relative border border-[#141414]/30" style={{ height }}>
        {!ready && (
          <div className="absolute inset-0 z-10 flex items-center justify-center text-xs text-[#141414]/50 bg-[#e7edf2]">
            <Loader2 className="h-4 w-4 animate-spin mr-2" /> Loading…
          </div>
        )}
        <div ref={holder} style={{ height: '100%', width: '100%' }} />
      </div>
      {geoError && <p className="text-[11px] text-[#B22222] mt-1">{geoError}</p>}
    </div>
  );
}

const round = (n: number) => Math.round(n * 1e6) / 1e6;
