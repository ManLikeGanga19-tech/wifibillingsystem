import { Hammer } from 'lucide-react';

/**
 * A settings section that is designed but not yet built. Deliberately honest — we ship
 * the settings shell whole and fill each panel step by step, so an empty section says so
 * plainly instead of pretending or 404ing.
 */
export default function Placeholder({ title, blurb }: { title: string; blurb: string }) {
  return (
    <div className="border border-[#141414] bg-white p-8 text-center">
      <div className="mx-auto grid h-11 w-11 place-items-center border border-[#141414] bg-[#f0efec]">
        <Hammer className="h-5 w-5 text-[#141414]/60" />
      </div>
      <h3 className="mt-4 font-mono text-sm font-bold uppercase">{title}</h3>
      <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-[#141414]/60">{blurb}</p>
      <p className="mt-3 font-mono text-[10px] uppercase tracking-widest text-[#141414]/40">
        Coming in a later step
      </p>
    </div>
  );
}
