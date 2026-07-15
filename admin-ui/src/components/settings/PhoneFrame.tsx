import { ReactNode } from 'react';

/**
 * A phone chrome for previewing the captive portal exactly as a subscriber meets it — the
 * same mobile framing the marketing site uses, rebuilt in CSS so the live preview scales.
 * `scale` shrinks the whole device for the card grid; the full-screen modal renders it at 1.
 */
export default function PhoneFrame({
  children,
  scale = 1,
}: {
  children: ReactNode;
  scale?: number;
}) {
  // A fixed device size, scaled as a whole — so the screen's contents keep their real
  // proportions rather than being squashed.
  const W = 300;
  const H = 620;
  return (
    <div
      style={{
        width: W * scale,
        height: H * scale,
        // Keep layout size in step with the visual scale.
        position: 'relative',
      }}
    >
      <div
        style={{
          width: W,
          height: H,
          transform: `scale(${scale})`,
          transformOrigin: 'top left',
          borderRadius: 42,
          background: '#0b0b0d',
          padding: 11,
          boxShadow: '0 24px 60px rgba(0,0,0,0.35), inset 0 0 0 2px #26262b',
          position: 'absolute',
          top: 0,
          left: 0,
        }}
      >
        {/* the screen */}
        <div
          style={{
            width: '100%',
            height: '100%',
            borderRadius: 32,
            overflow: 'hidden',
            position: 'relative',
            background: '#fff',
          }}
        >
          {/* notch */}
          <div
            style={{
              position: 'absolute',
              top: 0,
              left: '50%',
              transform: 'translateX(-50%)',
              width: 128,
              height: 24,
              background: '#0b0b0d',
              borderBottomLeftRadius: 14,
              borderBottomRightRadius: 14,
              zIndex: 5,
            }}
          />
          <div style={{ width: '100%', height: '100%', overflowY: 'auto' }}>{children}</div>
        </div>
      </div>
    </div>
  );
}
