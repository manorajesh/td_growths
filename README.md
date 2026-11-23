# Silhouette Wall (TouchDesigner)

> A separate module, the audience **floor tracker**, is documented in [FLOOR_TRACKER.md](FLOOR_TRACKER.md).
>
> **Logogram lookdev** (`build_logogram.py`, shaders in `logogram/`): a ring of ink materialises out of fog and keeps
> morphing. Build it with `import os; exec(open(os.path.expanduser('~/code/td_silhouette/build_logogram.py')).read())`, then click on
> `logogram/stage` (right-click › View…) or press space to materialise or disperse it. Output: `logogram/out`.
> All look controls are on the COMP's Shape / Flow / Look / Post pages. Wire any CHOP into the COMP's input to trigger
> it on a rising edge, for example a floor-tracker `p0_step`.

This tool gets a clean, perspective-corrected silhouette for each half of the LED wall and hands it to your own
TouchDesigner effects network, such as the vine growth. It does not draw the silhouette itself. You get a plain
white-on-black mask.

## Hardware model

| | |
|---|---|
| Panels | 12 × 80×80 px |
| Each side | 2 cols × 4 rows = **160×320 px**, own webcam |
| Controller canvas | One display at **1024×768**. The Absen shows a crop of the top-left. |
| Default placement | Left side at x 160–319, right side at x 0–159, y 0–319 (the controller maps canvas x 0–159 to the right-hand panels) |

## Build

In TouchDesigner, open Dialogs › Textport and DATs and run:

```python
import os; exec(open(os.path.expanduser('~/code/td_silhouette/build_silhouette.py')).read())
```

This creates `/project1/silhouette_wall`. Shaders are copied into the file, so save the .toe and it's self-contained.
Re-running the script rebuilds everything and resets parameters.

## Outputs for your effect

These are inside `silhouette_wall`:

| TOP | What |
|---|---|
| `silhouette_L`, `silhouette_R` | Silhouette mask at LED resolution, **160×320**, white = person, soft anti-aliased edge |
| `silhouette_hi_L`, `silhouette_hi_R` | Same mask at **640×1280** (LED × *High-Res Multiplier*) for finer effects |
| `camera_L`, `camera_R` | The angle-corrected camera image (640×960), if you want the colour feed |

Reference them from anywhere, e.g. `op('/project1/silhouette_wall/silhouette_L')`, or with a Select TOP.

To get your effect onto the wall, wire its 160×320 result into **input 0 of `display_L` / `display_R`**.
By default that input is the plain silhouette. The compositor places both sides on the 1024×768 canvas
(`out_canvas`), and the output window sends it to the controller.

## Sending to the LED controller over NDI

**Sending Mac:** `silhouette_wall/ndi_out` sends only the LED area of the canvas. That's the top-left 320×320 for two
2×4 panel sides, about 7.7× less data than 1024×768. The size follows the side offsets and LED size.
- *NDI: Send Only The LED Area* (`silhouette_wall` › Output) switches back to the full canvas.
- To update an existing patch, keeping calibration:
  `import os; exec(open(os.path.expanduser('~/code/td_silhouette/add_ndi.py')).read())`

**Receiving Mac** (cabled to the Absen): copy `receiver_setup.py` over (or the whole folder) and run
`import os; exec(open(os.path.expanduser('~/code/td_silhouette/receiver_setup.py')).read())`. It builds
`/project1/led_receiver`, which puts the stream back in the top-left of a black 1024×768 canvas at 1:1 pixels.
1. In `led_receiver/ndi_in`, pick the **Silhouette Wall** source.
2. Set **Monitor Index** to the Absen display.
3. Press **Open Window**.

On that Mac, set the Absen display to exactly 1024×768 with no scaling, and keep the menu bar off it.

## 1. Silhouette source (per side: `side_L`, `side_R` › Input)

**Apple Vision (default, built in).** `helper/vision_segment.py` captures that side's webcam, runs macOS's own
person segmentation (Neural Engine, about 50 fps for 1280×720 on this Mac), and hands camera + mask to
TouchDesigner through a shared file (`/tmp/silhouette_L.bin` / `_R.bin`). TouchDesigner starts and stops the
helper itself: when the project opens, when you change these settings, and when it exits.

- **Vision Camera**: pick that side's webcam (the list is filled from your Mac's cameras when you build).
- **Vision Quality**: *Balanced* is the right default; *Accurate* gives cleaner edges but is slower.
- **Person Gate Hold**: the segmenter can mistake textures for a person in an empty scene. A human
  detector must have seen someone within this many frames, or the mask stays black. Set to 0 to disable.
- **Restart Helper** if a camera was unplugged. The helper's log is `/tmp/silhouette_L.log` / `_R.log`.
- If the image is upside down, turn on **Flip Vision Image Vertically**.

One-time helper setup (already done on this Mac; on a new Mac see "Moving to another Mac" below):

```sh
bash ~/code/td_silhouette/setup_mac.sh      # creates helper/.venv and lists the cameras
```

The helper uses TouchDesigner's camera permission because TouchDesigner launches it.

**MediaPipe mask TOP**: if you prefer the [MediaPipe plugin](https://github.com/torinmb/mediapipe-touchdesigner),
drag its segmentation-mask TOP onto **MediaPipe Mask TOP** and its camera TOP onto **Camera TOP**. Use **Mask Channel**
/ **Invert Mask** if the person comes out black.

**Background subtraction**: no AI. Pick the webcam in `side_X/cam`. With nobody in view, press
**Capture Empty Background**, then tune **BG Sub Threshold**. It needs steady lighting.

**Mask** page: *Threshold*, *Edge Softness*, *Edge Blur*, and *Temporal Smoothing* (steadies flicker at the cost of a
slight lag; 0 = off).

## 2. Remove the camera angle (per side › Warp)

The floor camera looks up at the person, so the image is keystoned: wide at the bottom, narrow at the top. The warp
picks a four-cornered region of the camera image and stretches it so it fills that side's 2×4 panel block
square-on. This is a true perspective (homography) warp, not a simple stretch.

1. Open `side_X/calibrate_ui` in a viewer. Right-click › *View…* gives a floating window, or turn on its node viewer.
   It shows the camera with:
   - four corner dots: red = top-left, green = top-right, yellow = bottom-left, blue = bottom-right
   - the warp outline
   - the **2×4 panel grid drawn through the warp**, which shows exactly which part of the camera image will land
     on which panel. Everything outside the region is dimmed.
2. **Click and drag** near a corner to move it. You can also type values into the **Corner** parameters
   (0–1 camera coordinates, 0,0 = bottom-left).
3. Turn on **Show Camera on LEDs**. The wall then shows the corrected camera with the panel grid and the mask tinted
   green, so you can check alignment on the real panels with someone standing on the mark. This only changes the
   wall preview. The silhouette outputs your effect reads are never affected.
4. **Mirror Camera** (default on) makes the wall act like a mirror. **Lens Correction k1** straightens wide-angle
   barrel distortion (try −0.1 to −0.3) and is applied before the perspective warp.
5. **Reset Corners** returns to the full, unwarped frame.

A tip for setting the corners: tape marks on the floor and wall where the panel edges would be at the person's
standing distance, or have someone hold a pole at each edge. Then drag the dots onto those marks.

## 3. Map the panels (`silhouette_wall` › Output)

Turn on **Panel Test Pattern** and press **Open Output Window** (set **Monitor Index** first).
- Each 80×80 panel shows white borders and 1–8 yellow dots: 1 = top-left of that side, counting left→right,
  top→bottom.
- Red = left side, blue = right side, and a green square marks each side's top-left corner.

Adjust **Left/Right X/Y** until the physical panels show the right numbers.

## Pipeline (per side)

```
Vision helper (vision_in) | MediaPipe mask | bg subtraction ─► warp_mask (lens + perspective + mirror, 640x960) ─► mask_blur ─► silhouette_hi (threshold + temporal smoothing)
                                                                                                      ├─► out2  silhouette_hi_X
                                                                                                      └─► silhouette_led (box downsample) ─► out1  silhouette_X
camera ─► cam_warp (same warp) ─► out3 camera_X;   calib_led ─► out4 (wall preview while calibrating)
calib_view + calibrate_ui + calibrate_drag: the drag-to-calibrate panel
```

The perspective warp was checked offscreen against a synthetic keystoned camera frame. The corrected output matched
the flat original to within 0.43/255 on average, and the projected grid landed on the true panel edges.

## Moving to another Mac

This works for any user name, as long as the folder layout is the same: this project in `~/code/td_silhouette`, and
for the burst patch, the `.toe` in `~/Downloads` with its images in `~/Downloads/assets`.

1. **Copy** the `~/code/td_silhouette` folder, *without* `helper/.venv` (it only works on the Mac that created it).
   For example: `rsync -a --exclude .venv ~/code/td_silhouette/ newmac:~/code/td_silhouette/`. Also copy your `.toe` files
   and `~/Downloads/assets`.
2. On the new Mac, run once: `bash ~/code/td_silhouette/setup_mac.sh`. It needs [uv](https://docs.astral.sh/uv/) or
   Python 3, recreates the helper environment, and lists that Mac's cameras.
3. Open each `.toe` in TouchDesigner and run this in the Textport, then save:
   `import os; exec(open(os.path.expanduser('~/code/td_silhouette/update_patch.py')).read())`
   - It updates the embedded scripts, stores the project folder as `~/code/td_silhouette`, restarts the helpers, and
     for the burst patch links the images as `assets/...` relative to the `.toe`.
   - Calibration and settings are kept.
4. Allow camera access for TouchDesigner when macOS asks. The helpers use TouchDesigner's permission.
5. **Cameras:** each patch remembers its camera by ID and falls back to the camera's name if the ID differs on the new
   Mac. If a camera menu shows the wrong device, press **Refresh Cameras** and pick it again.

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

## Spores lookdev (`build_spores.py`)

`import os; exec(open(os.path.expanduser('~/code/td_silhouette/build_spores.py')).read())` builds `/project1/spores`.

**What it is:** a real physarum (slime-mold) simulation over each LED side's silhouette, on black.
- **The agents:** about 590k per side. Each senses the trail ahead at three angles, turns toward the strongest, steps
  and deposits, so they self-organise into flowing, hair-fine filament networks.
- **The silhouette guides them:** agents only live inside it, so the network reveals the form. With **Follow Camera
  Image** they also follow the camera's brightness, so faces and clothing get structure.
- **Growing in:** agents come alive over **Grow-In Time** after someone arrives, from the outline and the feet.
- **Flow and fibre:** a gentle downward flow makes streams drip and meander, and a second "hair" species braids fine
  fuzz around the main veins.
- **When the person leaves:** agents drift off and die, and the last network lingers, then fades over **Wither Time**.

**Mycelium growth:** each time someone arrives, a seed point is picked on the body (by default around chest height,
see **Starts From** / **Seed Height**).
- A growth front creeps outward from it over the body at an uneven, organic pace (**Mycelium Spread Speed**).
- Agents live only inside the grown region and radiate out from the seed, so fine branching hyphae fan out across the
  body. The advancing edge glows with fresh tips.

**Spores:** glowing particles rise off the mature growth, drift outward and upward with a swirl, leave the body into
the dark, and fade (Spores page: emission, lifetime, size, drift, rise, swirl, colour, count).

**The look:** green-teal strands, mint-white dense cores, a warm orange haze and sparks, with bloom. It's rendered
at 4× resolution and box-filtered down to the 160×320 LEDs.

**Wiring:**
- **Inputs:** `silhouette_wall/silhouette_hi_L` / `_R`, plus `camera_L` / `_R` as the guide. For lookdev without a
  person, set **Silhouette Source** = *Test figure*.
- **Outputs:** `spores/side_L/out_led`, `spores/side_R/out_led`, and the `out_hi` previews. They're wired into the wall's
  `display_L` / `display_R`.

**Controls** are on the `spores` COMP: Growth, Agents (sensor angle/distance, turn, step, flow, hair species, agent
count), Trail (decay, diffuse, deposit), Look (gain, crispness, haze, sparks, colours), Post, Size.
- Shorter **Sensor Distance** with faster **Decay** gives a finer network.
- More **Flow** gives dripping streams.
- Use **Agents** = 512×512 if the frame rate drops.

## Webcam hardware controls (`helper/camctl.py`)

**Control page:** `helper/.venv/bin/python helper/camctl_web.py` opens `http://127.0.0.1:8765` in the browser. It has
a camera picker, a live preview, switches for the auto modes, sliders for exposure (ms, log scale), gain, white
balance, focus and so on, and Save / Load preset and Reset buttons. Presets go to `camera_presets.json`. The page is
served on this Mac only. Double-click a slider to return it to the default.

The command-line equivalent:

This sets exposure and similar controls inside the C920/C922 (or any UVC webcam) over USB. It's a real camera setting,
not a post effect, and it works while TouchDesigner is using the camera, with no root or drivers.

```sh
cd ~/code/td_silhouette
helper/.venv/bin/python helper/camctl.py list                     # cameras + their macOS camera IDs
helper/.venv/bin/python helper/camctl.py show                     # every control: current, range, default
helper/.venv/bin/python helper/camctl.py set exposure_ms=10 gain=40 wb=4500 focus=0
helper/.venv/bin/python helper/camctl.py set -c 1 auto_exposure=on  # one camera (index, camera ID or name)
helper/.venv/bin/python helper/camctl.py save show.json             # store the tuned settings
helper/.venv/bin/python helper/camctl.py load show.json             # re-apply after a replug / reboot
helper/.venv/bin/python helper/camctl.py reset                      # factory defaults, auto modes on
```

**Controls:** `auto_exposure`, `exposure_ms` (C922: 0.3–204.7 ms), `low_light`, `gain` (0–255), `brightness`,
`contrast`, `saturation`, `sharpness`, `wb_auto`, `wb` (2000–6500 K), `focus_auto`, `focus` (0–250), `zoom`,
`backlight`, `powerline`.
- Setting `exposure_ms`, `wb` or `focus` switches that control's auto mode off.
- For the installation, lock exposure and white balance so the image doesn't pump as people move: set `exposure_ms` to
  about 8–16, raise `gain` until bright enough, then save.
- Keep `low_light=off` so the frame rate never drops.
- Each camera is listed with the same camera ID the TouchDesigner camera menus use, so two C922s can be told apart.
- Cameras keep these settings until they lose power. Run `load` after replugging or at boot.

## Spores on/off over OSC (`add_spores_switch.py`)

`import os; exec(open(os.path.expanduser('~/code/td_silhouette/add_spores_switch.py')).read())` adds an **Enable**
page to `/project1/spores`, keeping your settings. New builds include it.
- **Enabled on:** growth starts fresh on whoever is there and the output fades up.
- **Enabled off:** the silhouette is ignored, so the mold withers, and the output fades to black over **Fade Time**.
- **OSC:** listens on **OSC Port** (7000) at **OSC Address** (`/growth/enable`). `<address>/on`, `/off` and `/toggle`
  always work.

| OSC Mode | Behaviour |
|---|---|
| Pulse or hold turns on (default) | A pulse (a short 1 then 0, or a message with no value) turns it on and it stays on. A 1 held longer than **Pulse Length** keeps it on, and returning to 0 turns it off. |
| Follow the value | On while the last value is above 0. |
| Each pulse toggles | Every pulse flips it. |
| Any message turns on | Any message turns it on; use `/off` to turn it off. |

**Test:** `python3 helper/osc_send.py /growth/enable 1 --pulse 0.2`. Add `--host <ip>` from another machine.

## Three-MacBook setup: one MacBook per side + one driving the LEDs

**Each side's MacBook** (with that side's camera):
```python
SIDE = 'L'; import os; exec(open(os.path.expanduser('~/code/td_silhouette/build_side.py')).read())   # left MacBook
SIDE = 'R'; import os; exec(open(os.path.expanduser('~/code/td_silhouette/build_side.py')).read())   # right MacBook
```
This builds only that side:
- **`silhouette_wall`:** camera, segmentation and warp, with `calibrate_ui` for that side.
- **`spores`:** the growth, with the OSC on/off switch.
- **NDI:** `silhouette_wall/ndi_out` sends that side's 160×320 LED image as **Growth Side L** / **Growth Side R**.

**Calibration View** on the side shows its calibration through the same stream.

**LED MacBook** (cabled to the Absen):
`import os; exec(open(os.path.expanduser('~/code/td_silhouette/receiver_setup.py')).read())` builds
`/project1/led_receiver`. `ndi_L` + `ndi_R` feed `canvas`: a black 1024×768 canvas with each side placed at its offset
from the top-left, at 1:1 pixels. The defaults are left at x 160, right at x 0, both at y 0.
- The NDI sources are picked automatically once they appear. You can also choose them in each NDI In TOP.
- **Panel Test Pattern** (red = left, blue = right, 1–8 dots per panel, green = top-left of each side). Use it with
  **Left/Right X/Y** to match the physical panels.
- Set **Monitor Index** to the Absen display, then **Open Window**. The display must be exactly 1024×768, unscaled, with
  no menu bar on it.

**NDI over campus Wi-Fi:** in `~/.ndi/ndi-config.v1.json` on the LED MacBook, list both senders' IPs:
`{ "ndi": { "networks": { "ips": "<left-ip>,<right-ip>", "discovery": "" }, "tcp": { "recv": { "enable": true } },
"rudp": { "recv": { "enable": false } }, "unicast": { "recv": { "enable": false } }, "multicast": { "recv": { "enable": false } } } }`
Then fully restart TouchDesigner. A wired network (one small switch) is more reliable.
