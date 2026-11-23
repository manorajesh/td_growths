# Floor Tracker (TouchDesigner)

This tracks up to 5 audience members from a high, angled webcam and reports where their **feet** are on the floor,
in perspective-corrected floor coordinates, plus **step events**. It's a separate module from the silhouette wall,
and its outputs are meant to replace the mouse input your floor effects use now.

## Build

In TouchDesigner's Textport:

```python
import os; exec(open(os.path.expanduser('~/code/td_silhouette/build_floor_tracker.py')).read())
```

This creates `/project1/floor_tracker` and starts its helper (`helper/floor_track.py`, Apple Vision) on the camera
chosen on the **Camera** page. The helper runs alongside the silhouette helpers and uses the same `helper/.venv`.
Re-running the script rebuilds `floor_tracker` and resets its parameters.

## Outputs (inside `floor_tracker`)

| Op | Type | What |
|---|---|---|
| `people` | CHOP | Per slot `i` = 0–4: `p{i}_active`, `p{i}_id`, `p{i}_u`, `p{i}_v`, `p{i}_tx`, `p{i}_ty`, `p{i}_speed` (m/s), feet `p{i}_lu/lv/lfoot`, `p{i}_ru/rv/rfoot`, `p{i}_step` (1 for the frame a step lands), `p{i}_stepu/stepv` (where it landed). Also `count`, `steps_total`, `helper_ok`. |
| `mouse` | CHOP | `u`, `v`, `tx`, `ty`, `active`, `slot` for the person who has been in view longest. A drop-in replacement for your mouse-debug input. `fx`, `fy` (= u−0.5, v−0.5) can go straight into a Transform TOP's translate. |
| `step_trigger` | CHOP | `gate` (1 for *Step Trigger Gate* seconds after a step; ignores further steps for *Step Trigger Cooldown*), plus `u`, `v`, `fx`, `fy` of that step. Use it like a key press that also says where. |
| `steps` | DAT | The last 32 step events: `n, slot, id, foot, u, v, time`. |
| `feet_map` | TOP | Floor-space texture. Red = feet / presence blobs, green = step flashes that fade out. |
| `floor_view` | TOP | Debug: camera rectified to the floor, with the feet map and grid on top. |
| `calib_pattern` | TOP | Grid with coloured corner dots to show on the floor while calibrating. |

`out_people`, `out_mouse`, `out_steps` and `out_feet_map` are the same data on the COMP's output connectors,
so you can wire `floor_tracker` straight into an effects network.

**Coordinates:** `u`, `v` run 0–1 across the calibrated floor area. `u` goes left to right and `v` goes from the
bottom to the top of your floor texture. `tx`, `ty` are the same values in −1 to 1. When a person leaves, their
slot's `active` drops to 0 but the last position is held, so effects don't jump. A slot keeps the same person
while they're tracked (`id` increases for each new person).

**Hooking up your effects:**
- **Single cursor:** wherever the effect reads the Mouse In CHOP (or panel `u`/`v`), point it at `floor_tracker/mouse`.
- **Multi-person:** use `people`, for example a Select CHOP on `p*_u p*_v p*_active`, or instance on the slots.
- **Steps:** use a CHOP Execute DAT on `p*_step` (fires on 0→1), or watch the `steps` DAT.
- **Texture-based effects:** read `feet_map`.

## Auto calibration (recommended): projector + camera only

There's nothing to print and no Kantan Mapper. Send `/container1/out2` straight to the projector.

1. Press **Auto Calibrate** on the tracker's Floor page.
   - For about 3 seconds, `/container1/out2` shows a white frame with 24 square markers.
   - The camera finds them and measures exactly how the projector's image lands on the floor.
   - The tracker is set from that measurement, so the circles land under people's feet.
   - **Calibration Status** reports the result, e.g. `OK: 24 of 24 markers, fit error 2.3 px`.
2. **Square up the image** (Projector page, with **Output Warp** = *Auto*):
   - `output_warp`, just before `out2`, fits the largest undistorted 16:9 image inside the projected area on the floor.
   - To judge "square on the floor", it needs roughly how the camera is angled.
   - **Camera FOV:** about 70 for the iPhone 15 Pro main camera in landscape, about 105 for the ultra-wide.
   - **Camera Tilt:** drag it while watching the floor until the projection looks rectangular. It updates live, with
     no need to recalibrate, and the tracking stays aligned at any tilt.
   - **Output Warp** = *Off* uses the full projector image unwarped. Tracking still lines up.
   - **Constant Circle Size** (on by default): each person's circle is scaled by `p{i}_scale` so it covers the same
     floor area wherever they stand, even with Output Warp off. This also uses **Camera Tilt**, so tune the tilt
     (temporarily with Output Warp on Auto, until the image looks rectangular) for the sizes to be right.

Press **Auto Calibrate** again whenever the camera or projector moves. Keep the phone in landscape: a portrait stream
arrives with black bars, which throws off the FOV maths.

If it fails:
- **Too few markers seen:** the camera must see the projected floor, so dim the room lights.
- **"reaches the horizon":** lower **Camera Tilt**.

Tested on simulated rooms with a keystoned projector and a camera tilted 40°:
- With the right tilt, the image lands as an exact rectangle (90° corners, 16:9).
- Circles land within about 1 cm of a person's position.

## Calibration (manual, Floor page)

The camera sees the floor at an angle. Four corners tell the tracker where the floor area's corners are in the camera
image, and every foot position is mapped through that perspective, the same way as the silhouette wall's warp.

1. Send `calib_pattern` to the floor output (projector or LEDs) temporarily. It shows a grid with corner dots:
   yellow bottom-left, blue bottom-right, green top-right, red top-left.
2. Open `floor_tracker/calibrate_ui` in a viewer (right-click › View…) and drag each coloured corner onto the
   matching dot as the camera sees it. The pink grid drawn on the camera image should land on the projected grid.
3. Set **Floor Width / Depth** to the real size of that area in metres. Speeds and step thresholds use metres.
4. Check `floor_view`. Walking around should move the green blobs with your feet on a straight-on floor view.

**Lens Correction k1** straightens a wide-angle lens (try −0.1 to −0.3). Changes apply live: TouchDesigner writes
`/tmp/floor_track_config.json` and the helper re-reads it.

## Tuning (Tracking page)

- **Max People (slots)**: 5 by default. Extra people beyond that are ignored until a slot frees up.
- **Outside-Floor Margin**: people more than this far (0–1 units) outside the floor area are ignored.
- **Same-Person Max Jump / Keep Lost Person**: raise these if IDs swap or tracks drop out when people cross.
- **Smoothing / Smoothing Speed Response**: a One-Euro filter. Lower *Smoothing* means steadier but laggier;
  higher *Speed Response* means less lag when people move fast.
- **Step settings**: a step fires when a foot that was moving faster than *Lifted Above* slows below
  *Planted Below* for *Planted For* seconds, at least *Min Distance* from that foot's previous step.

## Camera placement tips

- Ankle detection (and so steps) needs people to look reasonably large and the camera to see legs, not just the tops
  of heads. A high corner or wall mount looking down at about 30–60° works best.
- A camera pointing straight down sees mostly heads and shoulders, so Vision can't find ankles. The tracker then falls
  back to body outlines (positions only, no steps).
- In testing, people about 60 px tall were mostly tracked by body outline only. At 150–200 px tall, ankles were found
  reliably and steps were detected.
- Even, bright lighting helps.

Logs are in `/tmp/floor_track.log`. The helper also exits (and TouchDesigner restarts it) if its memory ever goes
above 1.5 GB.

## Roots scene integration (`integrate_roots.py`)

With the burst `.toe` open on the show Mac, run:

```python
import os; exec(open(os.path.expanduser('~/code/td_silhouette/integrate_roots.py')).read())
```

Then **Save As** a new version. It:

- **Undoes the earlier burst wiring**, if you ran the old script: `/project1`'s keyboard triggers and burst
  position are restored, and footsteps no longer trigger anything.
- **Builds the tracker in `/container1`** (`/container1/floor_tracker`).
- **Adds one reveal circle per person:** `person_mask0`–`person_mask4` are copies of your `circle5` → `blur7` mask,
  each placed at a tracked person's floor position. They grow in and shrink out (**Circle Grow In / Shrink Out** on the
  tracker's Output page). `people_mask` combines them, and `mask_select` feeds `comp12`/`comp13` in place of the mouse
  circle (`transform4`).
- **Links the images** in `~/Downloads/assets`, relative to the `.toe`.

**Drive Visuals** off goes back to the single mouse circle.

**Calibration with Kantan Mapper:** keep using Kantan Mapper to fit the projector output to the floor. Then show
`/container1/floor_tracker/calib_pattern` *through that same mapped output* and drag the tracker's four corners onto
the projected corner dots in `calibrate_ui`. That way the camera, the content and the projection all agree.

## Phone camera via VDO.Ninja

Any camera menu can use a phone instead of a webcam: **Vision Camera** on each silhouette side, and **Camera** on the
floor tracker.

1. On the phone, open VDO.Ninja and start sending its camera. Copy the **view link** it gives you
   (`https://vdo.ninja/?view=...`).
2. Set the camera menu to **Phone (VDO.Ninja URL)** and paste the link into **Phone URL**.
   - `&cleanoutput&noaudio` is added automatically, so the page shows only the video and can autoplay.
3. `phone_in` (a Web Render TOP) plays the stream. `phone_send` hands each frame to the helper, which then segments or
   tracks it like a webcam. **Phone Frame Width/Height** (960×540 by default) sets the size sent; larger costs more.

Every patch has its own **Phone Frame File** in `/tmp`, so you can use several phones at once. Only the patch that has
Phone selected runs its web page. If the image stays black, open `phone_in`'s viewer to check the stream is playing.
The helper waits up to 60 s for the first frame before TouchDesigner restarts it.
