# Marketing media — what to capture, and how

The marketing site's proof is screenshots and screen recordings of the real product.
This is the brief for capturing them.

**The slots are declared in code**, in `marketing/src/lib/media.ts`. That file — not
this one — is the source of truth. Any slot without a file renders a labelled
placeholder on the page showing its filename and brief, so the site is never broken and
the outstanding shot list is always visible on the page itself.

## How to add one

1. Capture it (see below).
2. Save it into `marketing/public/media/` with the **exact filename** from the manifest.
3. Reload. The placeholder is replaced by the real thing. Nothing else to change.

## The shot list

| Slot | File | Kind | What it must show |
|---|---|---|---|
| `hero` | `console-dashboard.png` | screenshot | The ISP dashboard, eye toggle OPEN so revenue is visible |
| `payments` | `stk-push.mp4` (+ `stk-push.png` poster) | recording | Portal → pick plan → phone → STK prompt → connected |
| `wallet` | `wallet-ledger.png` | screenshot | Balance, sales, commission line, ledger below |
| `pppoe` | `pppoe-clients.png` | screenshot | Client list, mix of active/suspended, account numbers |
| `routers` | `router-health.png` | screenshot | Routers page, at least one ONLINE with RouterOS version |
| `onboarding` | `go-live.mp4` (+ `go-live.png` poster) | recording | Go-live checklist → add settlement account → payments ON |

## Rules that are not negotiable

**Never publish a real customer's data.** Screenshots of the console contain phone
numbers, names, MAC addresses and payment history of real people. Publishing them is a
Data Protection Act breach, and it is also just wrong. Capture against **seeded demo
data**:

```bash
docker compose exec api python manage.py seed_dev
```

If you must shoot against live data, every phone number, name and account number has to
be edited out before the file goes anywhere near `public/`. Blurring is not enough at
this resolution — cover them.

**Shoot a clean window.** No bookmarks bar, no other tabs, no notifications, no
extensions. Use a private window at a fixed size.

## Screenshots

- **Width: 2560px** (retina for a 1440-wide layout). Use browser zoom at 100% and a
  2× device pixel ratio, or capture on a retina display.
- **PNG.** These are UI, not photographs — PNG stays sharp where JPEG smears the mono
  type.
- Crop to the browser viewport. No OS chrome, no desktop wallpaper.

## Screen recordings

- **MP4 (H.264)**, no audio track. They autoplay muted and loop, so they are moving
  screenshots, not videos anybody watches with sound.
- **15–30 seconds.** If it takes longer than that to show, the product is the problem,
  not the recording.
- **Keep them small — target under 3 MB.** This page loads on mobile data in Kenya, on
  a phone belonging to someone deciding whether to trust us. A 40 MB hero video is a
  lost customer.

  ```bash
  ffmpeg -i raw.mov -vcodec libx264 -crf 28 -preset slow -an -movflags +faststart stk-push.mp4
  ```

- **Always ship a poster frame** (`*.png`, same filename stem). It is what shows before
  the video loads and on a slow connection, and without one the slot is a black box.

  ```bash
  ffmpeg -i stk-push.mp4 -vframes 1 -q:v 2 stk-push.png
  ```

- Move the cursor deliberately and slowly. A recording where the pointer darts around
  reads as chaos, not competence.

## Social preview

`marketing/public/og.png` — 1200×630, the card that renders when the link is pasted into
a WhatsApp group of WISP operators. That preview does as much selling as the page. It is
referenced by every page's `og:image`.
