"""
Silhouette Wall -- TouchDesigner network builder.

Run once inside TouchDesigner (Dialogs > Textport and DATs):

    import os; exec(open(os.path.expanduser('~/code/td_silhouette/build_silhouette.py')).read())

Creates /project1/silhouette_wall with two independent sides (side_L, side_R).
Each side: webcam -> person segmentation (Apple Vision helper by default, or a MediaPipe
mask TOP, or background subtraction) -> perspective warp that removes the floor camera's
steep angle -> clean, smoothed silhouette.  Outputs per side:

    silhouette_L / _R       mask at LED resolution (160x320: 2x4 panels of 80x80), white on black
    silhouette_hi_L / _R    mask at high resolution (LED x Supersample, 640x1280)
    camera_L / _R           angle-corrected camera image (high resolution)

These Null TOPs in silhouette_wall are what your vine effect should read.  Wire your
effect's 160x320 result into input 0 of display_L / display_R; the compositor places
both on the 1024x768 canvas the Absen controller crops from (with a panel test pattern).

Re-running the script deletes and rebuilds silhouette_wall (parameter values are reset).
"""
import os
import subprocess

# Where the shaders/ folder lives.  When run via exec() in the Textport, __file__ is
# TouchDesigner's own, so it is only trusted if a shaders/ folder actually exists there.
# Set SILHOUETTE_DIR before exec() to override, e.g. SILHOUETTE_DIR = '/path/to/td_silhouette'
_candidates = []
try:
	_candidates.append(SILHOUETTE_DIR)
except NameError:
	pass
try:
	_candidates.append(os.path.dirname(os.path.abspath(__file__)))
except NameError:
	pass
_candidates.append(os.path.expanduser('~/code/td_silhouette'))
ROOT_DIR = next((d for d in _candidates if os.path.isfile(os.path.join(d, 'shaders', 'warp.glsl'))), None)
if ROOT_DIR is None:
	raise FileNotFoundError('silhouette_wall: cannot find shaders/ -- set SILHOUETTE_DIR to the project folder '
	                        'before exec(). Looked in: {}'.format(_candidates))
SHADER_DIR = os.path.join(ROOT_DIR, 'shaders')


def portable(path):
	"""Store paths under the user's home as ~/... so a saved .toe works for another user."""
	home = os.path.expanduser('~')
	return '~' + path[len(home):] if path.startswith(home + os.sep) else path
SIDE_SHADERS = ['warp', 'calibview', 'calibout', 'bgsub', 'bgplate', 'maskproc', 'downsample']
HELPER_PY = os.path.join(ROOT_DIR, 'helper', '.venv', 'bin', 'python')
HELPER = os.path.join(ROOT_DIR, 'helper', 'vision_segment.py')


def E(name):
	"""Expression reading a custom parameter on the owning COMP."""
	return 'parent().par.{}'.format(name)


def try_set(o, **kw):
	for k, v in kw.items():
		try:
			setattr(o.par, k, v)
		except Exception as e:
			print('silhouette_wall: could not set {}.{} ({})'.format(o.path, k, e))


def set_expr(par, v):
	if isinstance(v, str):
		par.expr = v
	else:
		par.val = v


def res(o, w, h):
	o.par.outputresolution = 'custom'
	set_expr(o.par.resolutionw, w)
	set_expr(o.par.resolutionh, h)


def load_shader(comp, name):
	d = comp.create(textDAT, name + '_frag')
	with open(os.path.join(SHADER_DIR, name + '.glsl')) as f:
		d.text = f.read()
	return d


def connect(srcs, dst):
	for i, s in enumerate(srcs):
		s.outputConnectors[0].connect(dst.inputConnectors[i])


def glsl(comp, name, shader, inputs=(), uniforms=(), fmt=None, w=None, h=None):
	g = comp.create(glslTOP, name)
	for d in list(g.docked):
		d.destroy()
	g.par.pixeldat = shader + '_frag'
	if fmt:
		g.par.format = fmt
	if w is not None:
		res(g, w, h)
	connect(inputs, g)
	try:
		g.seq.vec.numBlocks = max(len(uniforms), 1)
	except Exception:
		pass
	for i, (uname, vals) in enumerate(uniforms):
		getattr(g.par, 'vec{}name'.format(i)).val = uname
		for c, v in zip('xyzw', vals):
			set_expr(getattr(g.par, 'vec{}value{}'.format(i, c)), v)
	return g


def place(o, x, y):
	o.nodeX, o.nodeY = x * 200, -y * 160


def add_float(page, name, label, default, lo=0.0, hi=1.0):
	p = page.appendFloat(name, label=label)[0]
	p.default = p.val = default
	p.normMin, p.normMax = lo, hi
	return p


def add_int(page, name, label, default, lo=0, hi=100):
	p = page.appendInt(name, label=label)[0]
	p.default = p.val = default
	p.normMin, p.normMax = lo, hi
	return p


def add_toggle(page, name, label, default=False):
	p = page.appendToggle(name, label=label)[0]
	p.default = p.val = default
	return p


def add_xy(page, name, label, x, y):
	for p, v in zip(page.appendXY(name, label=label), (x, y)):
		p.default = p.val = v
		p.normMin, p.normMax = 0, 1


def add_menu(page, name, label, names, labels, default):
	p = page.appendMenu(name, label=label)[0]
	p.menuNames, p.menuLabels = names, labels
	p.default = p.val = default
	return p


# --------------------------------------------------------------------------- callbacks
SIDE_PULSE = '''
import os, signal, subprocess

CORNERS = {'Cornerbl': (0.0, 0.0), 'Cornerbr': (1.0, 0.0), 'Cornertr': (1.0, 1.0), 'Cornertl': (0.0, 1.0)}
HELPER_PARS = ('Source', 'Visioncamera', 'Visionquality', 'Gateframes', 'Helperfile', 'Phonefile')
CAM_PARS = ('Camexposure', 'Camcontrast')
_procs = {}

def _is_helper(pid):
	try:
		out = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True).stdout
	except Exception:
		return False
	return 'vision_segment.py' in out

def _camera_args(c, par):
	# phone (VDO.Ninja via phone_in / phone_send) or a real camera by ID with a name fallback
	if par.eval() == 'phone':
		return ['--camera', 'td:' + c.par.Phonefile.eval()]
	names = list(par.menuNames)
	label = par.menuLabels[names.index(par.eval())] if par.eval() in names else ''
	return ['--camera', par.eval(), '--camera-name', label]

def stop_helper(c):
	p = _procs.pop(c.path, None)
	if p is not None and p.poll() is None:
		debug('silhouette: stopping helper for', c.name, 'pid', p.pid)
		p.terminate()
	pid = c.fetch('helper_pid', 0, search=False)
	if pid and (p is None or p.pid != pid) and _is_helper(pid):
		try:
			os.kill(pid, signal.SIGTERM)
		except OSError:
			pass
	c.unstore('helper_pid')

def cam_config_path(c):
	return os.path.splitext(c.par.Helperfile.eval())[0] + '_cam.json'

def write_cam_config(c):
	# exposure/contrast the helper applies before segmenting; it re-reads this file live
	import json
	if not hasattr(c.par, 'Camexposure'):
		return
	path = cam_config_path(c)
	with open(path + '.tmp', 'w') as f:
		json.dump({'exposure': c.par.Camexposure.eval(), 'contrast': c.par.Camcontrast.eval()}, f)
	os.replace(path + '.tmp', path)

def start_helper(c):
	stop_helper(c)
	write_cam_config(c)
	root = os.path.expanduser(c.parent().par.Projectfolder.eval())
	py = os.path.join(root, 'helper', '.venv', 'bin', 'python')
	script = os.path.join(root, 'helper', 'vision_segment.py')
	if not os.path.exists(py):
		debug('silhouette: helper venv missing at', py, '- see README (helper setup)')
		return
	f = c.par.Helperfile.eval()
	log = open(os.path.splitext(f)[0] + '.log', 'a')
	log.write('\\n--- started by TouchDesigner for {} (camera {})\\n'.format(c.path, c.par.Visioncamera.eval()))
	log.flush()
	cmd = [py, '-I', script] + _camera_args(c, c.par.Visioncamera) + ['--cam-config', cam_config_path(c), '--file', f,
	       '--quality', c.par.Visionquality.eval(), '--gate', str(int(c.par.Gateframes.eval())),
	       '--parent-pid', str(os.getpid())]
	_procs[c.path] = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
	c.store('helper_pid', _procs[c.path].pid)
	debug('silhouette: started helper for', c.name, 'camera', c.par.Visioncamera.eval(), 'pid', _procs[c.path].pid)

def helper_alive(c):
	p = _procs.get(c.path)
	return p is not None and p.poll() is None

def helper_status(c):
	p = _procs.get(c.path)
	if p is None:
		return 'not running'
	return 'running (pid {})'.format(p.pid) if p.poll() is None else 'exited ({}) - see log'.format(p.returncode)

def sync_helper(c):
	if c.par.Source.eval() == 'vision':
		start_helper(c)
	else:
		stop_helper(c)

def onValueChange(par, prev):
	if par.name in HELPER_PARS:
		sync_helper(par.owner)
	elif par.name in CAM_PARS:
		write_cam_config(par.owner)
	return

def refresh_cameras(c):
	# re-list cameras (e.g. one was plugged in after building) and keep the current choice
	root = os.path.expanduser(c.parent().par.Projectfolder.eval())
	py = os.path.join(root, 'helper', '.venv', 'bin', 'python')
	out = subprocess.run([py, '-I', os.path.join(root, 'helper', 'vision_segment.py'), '--list'],
	                     capture_output=True, text=True, timeout=30).stdout
	cams = [tuple(ln.split('\\t')[1:3]) for ln in out.splitlines() if ln.count('\\t') == 2]
	if not cams:
		debug('silhouette: no cameras found')
		return
	p = c.par.Visioncamera
	cur = p.eval()
	p.menuNames = [u for u, n in cams] + ['phone']
	p.menuLabels = [n for u, n in cams] + ['Phone (VDO.Ninja URL)']
	if cur in p.menuNames:
		p.val = cur
	debug('silhouette:', c.name, 'cameras', [n for u, n in cams])

def onPulse(par):
	c = par.owner
	if par.name == 'Refreshcameras':
		refresh_cameras(c)
	elif par.name == 'Capturebg':
		c.par.Capturing = True
		run("args[0].par.Capturing = False", c, delayFrames=10)
	elif par.name == 'Restarthelper':
		sync_helper(c)
	elif par.name == 'Resetcorners':
		for n, (x, y) in CORNERS.items():
			getattr(c.par, n + 'x').val = x
			getattr(c.par, n + 'y').val = y
	return
'''

# Script TOP that reads frames published by helper/vision_segment.py (RGB = camera, A = mask).
VISION_READER = '''
import mmap, os, struct
import numpy as np

HEADER = struct.Struct('<4sIQII')
HS = 64
FILE_SIZE = HS + 1920 * 1080 * 4
_maps = {}

def onSetupParameters(scriptOp):
	return

def _out(scriptOp, ent):
	img = ent.get('img') if ent else None
	if img is None:
		img = np.zeros((16, 16, 4), np.uint8)
	elif scriptOp.parent().par.Visionflip.eval():
		img = np.ascontiguousarray(img[::-1])
	scriptOp.copyNumpyArray(img)

def onCook(scriptOp):
	path = scriptOp.parent().par.Helperfile.eval()
	ent = _maps.get(scriptOp.path)
	try:
		if ent is None or ent['path'] != path:
			if not os.path.exists(path) or os.path.getsize(path) != FILE_SIZE:
				return _out(scriptOp, ent)
			f = open(path, 'rb')
			ent = {'path': path, 'f': f, 'mm': mmap.mmap(f.fileno(), FILE_SIZE, access=mmap.ACCESS_READ),
			       'seq': -1, 'img': None}
			_maps[scriptOp.path] = ent
		mm = ent['mm']
		magic, ver, seq, w, h = HEADER.unpack_from(mm, 0)
		if magic == b'SIL1' and seq % 2 == 0 and seq != ent['seq'] and 0 < w * h * 4 <= FILE_SIZE - HS:
			img = np.frombuffer(mm, np.uint8, w * h * 4, HS).reshape(h, w, 4).copy()
			if HEADER.unpack_from(mm, 0)[2] == seq:      # not overwritten while copying
				ent['img'], ent['seq'] = img, seq
	except Exception as e:
		debug('vision_in:', e)
	_out(scriptOp, ent)
'''

# Wall-level Execute DAT: start helpers when the project opens, cook the readers every frame,
# stop helpers on exit.
WALL_EXEC = '''
SIDES = ('side_L', 'side_R')

def _sides():
	return [me.parent().op(s) for s in SIDES if me.parent().op(s)]

def onStart():
	for c in _sides():
		c.op('pulses').module.sync_helper(c)
	return

_last_restart = {}

def onFrameStart(frame):
	for c in _sides():
		if c.par.Source.eval() != 'vision':
			continue
		c.op('vision_in').cook(force=True)
		# watchdog: restart a helper that died (camera unplugged, crash), at most every 5 s
		if frame % 30 == 0:
			pulses = c.op('pulses').module
			if not pulses.helper_alive(c) and absTime.seconds - _last_restart.get(c.path, -99) > 5:
				_last_restart[c.path] = absTime.seconds
				debug('silhouette: helper for', c.name, 'is', pulses.helper_status(c), '- restarting')
				pulses.start_helper(c)
	return

def onExit():
	for c in _sides():
		c.op('pulses').module.stop_helper(c)
	return
'''

# Drag the warp corners directly on the camera image (calibrate_ui panel).
PANEL_DRAG = '''
CORNERS = ['Cornerbl', 'Cornerbr', 'Cornertr', 'Cornertl']

def _undistort(side, u, v):
	# inverse of the lens model in warp.glsl, so clicks land where the dots are drawn
	k = side.par.Lensk1.eval()
	cx, cy = u - 0.5, v - 0.5
	x, y = cx, cy
	for _ in range(6):
		s = 1.0 + k * (x * x + y * y)
		x, y = cx / s, cy / s
	return x + 0.5, y + 0.5

def _uv(ui):
	return _undistort(ui.parent(), ui.panel.u.val, ui.panel.v.val)

def _set(side, name, u, v):
	getattr(side.par, name + 'x').val = round(min(max(u, -0.5), 1.5), 4)
	getattr(side.par, name + 'y').val = round(min(max(v, -0.5), 1.5), 4)

def onOffToOn(panelValue):
	if panelValue.name != 'lselect':
		return
	ui = panelValue.owner
	side = ui.parent()
	u, v = _uv(ui)
	best = min(CORNERS, key=lambda n: (getattr(side.par, n + 'x').eval() - u) ** 2 +
	                                  (getattr(side.par, n + 'y').eval() - v) ** 2)
	ui.store('drag', best)
	_set(side, best, u, v)
	return

def onValueChange(panelValue, prev):
	if panelValue.name not in ('u', 'v'):
		return
	ui = panelValue.owner
	name = ui.fetch('drag', None, search=False)
	if name and ui.panel.lselect.val:
		u, v = _uv(ui)
		_set(ui.parent(), name, u, v)
	return

def onOnToOff(panelValue):
	if panelValue.name == 'lselect':
		panelValue.owner.unstore('drag')
	return
'''

WALL_PULSE = '''
def onPulse(par):
	w = par.owner.op('window')
	if par.name == 'Openwindow':
		w.par.winopen.pulse()
	elif par.name == 'Closewindow':
		w.par.winclose.pulse()
	return
'''


def par_exec(comp, text, valuechange=False):
	pe = comp.create(parameterexecuteDAT, 'pulses')
	pe.par.op.expr = 'parent()'
	try_set(pe, pars='*', custom=True, builtin=False, valuechange=valuechange, onpulse=True)
	pe.text = text
	return pe


# --------------------------------------------------------------------------- side
def list_cameras():
	"""[(unique_id, name)] from the helper (AVFoundation order)."""
	try:
		out = subprocess.run([HELPER_PY, '-I', HELPER, '--list'], capture_output=True, text=True,
		                     timeout=20).stdout
		cams = [tuple(ln.split('\t')[1:3]) for ln in out.splitlines() if ln.count('\t') == 2]
		if cams:
			return cams
	except Exception as e:
		print('silhouette_wall: could not list cameras via helper ({})'.format(e))
	return [('0', 'Camera 0'), ('1', 'Camera 1'), ('2', 'Camera 2')]


def side_params(c, cameras, cam_default, tag):
	pg = c.appendCustomPage('Input')
	add_menu(pg, 'Source', 'Silhouette Source', ['vision', 'mediapipe', 'bgsub'],
	         ['Apple Vision (built-in helper)', 'MediaPipe mask TOP', 'Background subtraction'], 'vision')
	add_menu(pg, 'Visioncamera', 'Vision Camera', [u for u, n in cameras], [n for u, n in cameras], cam_default)
	add_menu(pg, 'Visionquality', 'Vision Quality', ['fast', 'balanced', 'accurate'],
	         ['Fast', 'Balanced', 'Accurate (slow)'], 'balanced')
	add_int(pg, 'Gateframes', 'Person Gate Hold (frames, 0=off)', 20, 0, 120)
	add_toggle(pg, 'Visionflip', 'Flip Vision Image Vertically')
	p = pg.appendStr('Helperfile', label='Helper Frame File')[0]
	p.default = p.val = '/tmp/silhouette_{}.bin'.format(tag)
	pg.appendPulse('Refreshcameras', label='Refresh Cameras')
	pg.appendPulse('Restarthelper', label='Restart Helper')
	exec(open(os.path.join(ROOT_DIR, 'cam_controls.py')).read(), globals())
	add_cam_controls(c, pg)                       # Camera Exposure / Contrast (applied before segmenting)
	pg.appendTOP('Masktop', label='MediaPipe Mask TOP')
	pg.appendTOP('Cameratop', label='Camera TOP (optional)')
	add_menu(pg, 'Maskchannel', 'Mask Channel', ['r', 'g', 'b', 'a', 'luma'],
	         ['Red', 'Green', 'Blue', 'Alpha', 'Luminance'], 'r')
	add_toggle(pg, 'Maskinvert', 'Invert Mask')
	add_float(pg, 'Bgthreshold', 'BG Sub Threshold', 0.15)
	add_float(pg, 'Bgsoftness', 'BG Sub Softness', 0.1)
	pg.appendPulse('Capturebg', label='Capture Empty Background')
	add_toggle(pg, 'Capturing', 'Capturing (automatic)')

	pg = c.appendCustomPage('Mask')
	add_float(pg, 'Maskthreshold', 'Threshold', 0.5)
	add_float(pg, 'Masksoftness', 'Edge Softness', 0.1, 0, 0.5)
	add_float(pg, 'Maskblur', 'Edge Blur (px)', 3, 0, 20)
	add_float(pg, 'Masksmoothing', 'Temporal Smoothing (1/s, 0=off)', 15, 0, 60)

	pg = c.appendCustomPage('Warp')
	add_toggle(pg, 'Calibrate', 'Show Camera on LEDs (wall preview only)')
	add_toggle(pg, 'Mirror', 'Mirror Camera', True)
	add_float(pg, 'Lensk1', 'Lens Correction k1', 0.0, -0.6, 0.6)
	add_xy(pg, 'Cornertl', 'Top-Left (red)', 0.0, 1.0)
	add_xy(pg, 'Cornertr', 'Top-Right (green)', 1.0, 1.0)
	add_xy(pg, 'Cornerbl', 'Bottom-Left (yellow)', 0.0, 0.0)
	add_xy(pg, 'Cornerbr', 'Bottom-Right (blue)', 1.0, 0.0)
	pg.appendPulse('Resetcorners', label='Reset Corners')

	pg = c.appendCustomPage('Size')
	add_int(pg, 'Ledw', 'LED Width', 160, 16, 1024)
	add_int(pg, 'Ledh', 'LED Height', 320, 16, 1024)
	add_int(pg, 'Gridcols', 'Panel Columns', 2, 1, 8)
	add_int(pg, 'Gridrows', 'Panel Rows', 4, 1, 8)
	add_int(pg, 'Supersample', 'High-Res Multiplier', 4, 1, 8)


def build_side(wall, name, cameras, cam_default):
	c = wall.create(baseCOMP, name)
	side_params(c, cameras, cam_default, name[-1])
	for s in SIDE_SHADERS:
		load_shader(c, s)

	hiw = '{}*{}'.format(E('Ledw'), E('Supersample'))
	hih = '{}*{}'.format(E('Ledh'), E('Supersample'))
	mp = "{}.eval() == 'mediapipe'".format(E('Source'))
	vis = "{}.eval() == 'vision'".format(E('Source'))

	# ---- sources
	vision = c.create(scriptTOP, 'vision_in')
	for d in list(vision.docked):
		d.destroy()
	vcb = c.create(textDAT, 'vision_in_callbacks')
	vcb.text = VISION_READER
	vision.par.callbacks = vcb.name
	cam = c.create(videodeviceinTOP, 'cam')
	cam.par.active.expr = "not ({}) and not {}.eval()".format(vis, E('Cameratop'))
	cam_src = c.create(selectTOP, 'cam_src')
	cam_src.par.top.expr = "op('vision_in') if {} else ({}.eval() or op('cam'))".format(vis, E('Cameratop'))
	blank = c.create(constantTOP, 'no_mask')
	res(blank, 64, 64)
	try_set(blank, colorr=0, colorg=0, colorb=0, alpha=1)
	mp_mask = c.create(selectTOP, 'mediapipe_mask')
	mp_mask.par.top.expr = "{}.eval() or op('no_mask')".format(E('Masktop'))
	bg_fb = c.create(feedbackTOP, 'bg_fb')
	cam_src.outputConnectors[0].connect(bg_fb)
	bg_fb.par.top = 'bg_plate'
	bg_plate = glsl(c, 'bg_plate', 'bgplate', inputs=[bg_fb, cam_src],
	                uniforms=[('uCap', (E('Capturing'), 0, 0, 0))])
	bgsub = glsl(c, 'bgsub', 'bgsub', inputs=[cam_src, bg_plate],
	             uniforms=[('uBg', (E('Bgthreshold'), E('Bgsoftness'), 0, 0))])
	sw = c.create(switchTOP, 'mask_select')
	connect([vision, mp_mask, bgsub], sw)
	sw.par.index.expr = '{}.menuIndex'.format(E('Source'))
	chan = "(3 if {} else {}.menuIndex if {} else 0)".format(vis, E('Maskchannel'), mp)
	inv = "(int({}.eval()) if {} else 0)".format(E('Maskinvert'), mp)

	corners = [('uC0', (E('Cornerblx'), E('Cornerbly'), E('Cornerbrx'), E('Cornerbry'))),
	           ('uC1', (E('Cornertrx'), E('Cornertry'), E('Cornertlx'), E('Cornertly')))]

	# ---- silhouette chain (high res, then box-filtered down to LEDs)
	warp = glsl(c, 'warp_mask', 'warp', inputs=[sw], w=hiw, h=hih, fmt='rgba16float',
	            uniforms=corners + [('uOpt', (E('Mirror'), E('Lensk1'), chan, inv))])
	blur = c.create(blurTOP, 'mask_blur')
	warp.outputConnectors[0].connect(blur)
	blur.par.size.expr = E('Maskblur')
	try_set(blur, extend='zero')
	init = c.create(constantTOP, 'mask_init')
	res(init, hiw, hih)
	try_set(init, format='rgba16float', colorr=0, colorg=0, colorb=0, alpha=1)
	fb = c.create(feedbackTOP, 'mask_fb')
	init.outputConnectors[0].connect(fb)
	fb.par.top = 'silhouette_hi'
	sil_hi = glsl(c, 'silhouette_hi', 'maskproc', inputs=[fb, blur], w=hiw, h=hih, fmt='rgba16float',
	              uniforms=[('uMask', (E('Maskthreshold'), E('Masksoftness'), E('Masksmoothing'),
	                                   '1.0/me.time.rate'))])

	# ---- angle-corrected camera + calibration views
	cam_warp = glsl(c, 'cam_warp', 'warp', inputs=[cam_src], w=hiw, h=hih,
	                uniforms=corners + [('uOpt', (E('Mirror'), E('Lensk1'), -1, 0))])
	calib_led = glsl(c, 'calib_led', 'calibout', inputs=[cam_warp, sil_hi],
	                 uniforms=[('uGrid', (E('Gridcols'), E('Gridrows'), 0, 0))])
	calib = glsl(c, 'calib_view', 'calibview', inputs=[cam_src, sw],
	             uniforms=corners + [('uOpt', (E('Mirror'), E('Lensk1'), E('Gridcols'), E('Gridrows'))),
	                                 ('uMaskCh', (chan, inv, 0, 0))])
	sil_led = glsl(c, 'silhouette_led', 'downsample', inputs=[sil_hi], w=E('Ledw'), h=E('Ledh'))
	calib_small = glsl(c, 'calib_led_small', 'downsample', inputs=[calib_led], w=E('Ledw'), h=E('Ledh'))

	outs = []
	for i, src in enumerate([sil_led, sil_hi, cam_warp, calib_small]):
		o = c.create(outTOP, 'out{}'.format(i + 1))
		src.outputConnectors[0].connect(o)
		outs.append(o)

	# ---- drag-to-calibrate panel
	ui = c.create(containerCOMP, 'calibrate_ui')
	ui.par.w = 800
	ui.par.h.expr = "int(800 * op('cam_src').height / max(op('cam_src').width, 1))"
	ui.par.top.expr = "parent().op('calib_view')"
	drag = c.create(panelexecuteDAT, 'calibrate_drag')
	try_set(drag, panels='calibrate_ui', panelvalue='lselect u v',
	        offtoon=True, ontooff=True, valuechange=True)
	drag.text = PANEL_DRAG

	par_exec(c, SIDE_PULSE, valuechange=True)

	layout = [(vision, 0, -1), (vcb, 1, -1), (cam, 0, 0), (cam_src, 1, 0), (bg_fb, 2, -1), (bg_plate, 2, 0),
	          (bgsub, 3, 0), (blank, 2, 1),
	          (mp_mask, 3, 1), (sw, 4, 1), (warp, 5, 1), (blur, 6, 1), (init, 6, 2), (fb, 7, 2),
	          (sil_hi, 8, 1), (cam_warp, 5, 3), (calib_led, 8, 3), (sil_led, 10, 1), (calib_small, 10, 3),
	          (outs[0], 11, 0), (outs[1], 11, 1), (outs[2], 11, 2), (outs[3], 11, 3), (calib, 5, 5), (ui, 6, 5),
	          (drag, 7, 5), (c.op('pulses'), 0, 3)]
	for o, x, y in layout:
		place(o, x, y)
	for i, s in enumerate(SIDE_SHADERS):
		place(c.op(s + '_frag'), i, 7)
	return c


# --------------------------------------------------------------------------- NDI
def add_ndi(wall, out, pg):
	"""NDI output (only the LED area of the canvas) -- see add_ndi.py."""
	ns = {'__name__': 'silhouette_build', 'SILHOUETTE_DIR': ROOT_DIR}
	ns.update({k: globals()[k] for k in ('op', 'root', 'textDAT', 'glslTOP', 'switchTOP', 'ndioutTOP') if k in globals()})
	exec(open(os.path.join(ROOT_DIR, 'add_ndi.py')).read(), ns)
	return ns['add_ndi'](wall)


# --------------------------------------------------------------------------- wall
def build():
	host = op('/project1') or root
	old = host.op('silhouette_wall')
	if old:
		for sname in ('side_L', 'side_R'):          # stop the old network's helpers first
			try:
				old.op(sname).op('pulses').module.stop_helper(old.op(sname))
			except Exception:
				pass
		old.destroy()
	# also stop any helper left over from an earlier session (they hold the cameras)
	subprocess.run(['pkill', '-f', 'vision_segment.py .*--file /tmp/silhouette_'], capture_output=True)
	wall = host.create(baseCOMP, 'silhouette_wall')

	pg = wall.appendCustomPage('Output')
	add_toggle(pg, 'Testpattern', 'Panel Test Pattern')
	add_toggle(pg, 'Leftenable', 'Left Side Enabled', True)
	add_int(pg, 'Leftx', 'Left Side X (from top-left)', 160, 0, 1024)
	add_int(pg, 'Lefty', 'Left Side Y (from top-left)', 0, 0, 768)
	add_toggle(pg, 'Rightenable', 'Right Side Enabled', True)
	add_int(pg, 'Rightx', 'Right Side X (from top-left)', 0, 0, 1024)
	add_int(pg, 'Righty', 'Right Side Y (from top-left)', 0, 0, 768)
	add_int(pg, 'Panelsize', 'Panel Size (px)', 80, 8, 256)
	add_int(pg, 'Canvasw', 'Canvas Width', 1024, 64, 4096)
	add_int(pg, 'Canvash', 'Canvas Height', 768, 64, 4096)
	add_int(pg, 'Monitor', 'Monitor Index', 1, 0, 4)
	pg.appendPulse('Openwindow', label='Open Output Window')
	pg.appendPulse('Closewindow', label='Close Output Window')
	p = pg.appendFolder('Projectfolder', label='Project Folder (helper/)')[0]
	p.default = p.val = portable(ROOT_DIR)

	cameras = list_cameras()
	left = build_side(wall, 'side_L', cameras, cameras[0][0])
	right = build_side(wall, 'side_R', cameras, cameras[1 % len(cameras)][0])
	exec(open(os.path.join(ROOT_DIR, 'phone_input.py')).read(), globals())
	for side, tag in ((left, 'silhouette_L'), (right, 'silhouette_R')):
		add_phone_input(side, 'Visioncamera', tag)       # 'Phone (VDO.Ninja URL)' camera option

	# Clean, named outputs for your effects network (reference these, e.g. op('.../silhouette_L')).
	nulls = {}
	for side, tag in ((left, 'L'), (right, 'R')):
		for idx, nm in ((1, 'silhouette_' + tag), (2, 'silhouette_hi_' + tag), (3, 'camera_' + tag),
		                (4, 'calib_' + tag)):
			n = wall.create(selectTOP, nm)       # selects side_X/outN by name (robust to wiring order)
			n.par.top = '{}/out{}'.format(side.name, idx)
			nulls[nm] = n
	# What each side shows on the wall.  Input 0 = what normally goes to the LEDs: wire your
	# vine effect in here (defaults to the plain silhouette).  Input 1 = calibration view.
	displays = []
	for side, tag in ((left, 'L'), (right, 'R')):
		d = wall.create(switchTOP, 'display_' + tag)
		nulls['silhouette_' + tag].outputConnectors[0].connect(d.inputConnectors[0])
		nulls['calib_' + tag].outputConnectors[0].connect(d.inputConnectors[1])
		d.par.index.expr = "int(op('{}').par.Calibrate.eval())".format(side.name)
		displays.append(d)

	load_shader(wall, 'compose')
	comp = glsl(wall, 'compose', 'compose', inputs=displays, w=E('Canvasw'), h=E('Canvash'),
	            fmt='rgba8fixed',
	            uniforms=[('uOffL', (E('Leftx'), E('Lefty'), E('Leftenable'), 0)),
	                      ('uOffR', (E('Rightx'), E('Righty'), E('Rightenable'), 0)),
	                      ('uMode', (E('Testpattern'), E('Panelsize'), 0, 0))])
	out = wall.create(nullTOP, 'out_canvas')
	comp.outputConnectors[0].connect(out)

	win = wall.create(windowCOMP, 'window')
	try_set(win, winop=out.path, borders=False, winoffsetx=0, winoffsety=0)
	win.par.monitor.expr = E('Monitor')
	win.par.winw.expr = E('Canvasw')
	win.par.winh.expr = E('Canvash')

	par_exec(wall, WALL_PULSE)

	add_ndi(wall, out, pg)
	ex = wall.create(executeDAT, 'helpers')
	ex.text = WALL_EXEC
	try_set(ex, start=True, framestart=True, exit=True)
	place(ex, 4, 5)

	for i, tag in enumerate(('L', 'R')):
		for j, nm in enumerate(('silhouette_', 'silhouette_hi_', 'camera_', 'calib_')):
			place(nulls[nm + tag], 1, i * 4 + j)
		place(displays[i], 3, i * 4)
	for o, x, y in ((left, 0, 0), (right, 0, 4), (wall.op('compose_frag'), 3, 2), (comp, 4, 2),
	                (out, 5, 2), (win, 6, 2), (wall.op('ndi_out'), 6, 3), (wall.op('pulses'), 4, 4)):
		place(o, x, y)
	for c in (left, right):
		c.op('pulses').module.sync_helper(c)
	print('silhouette_wall: built {}  (cameras: {}, NDI source "{}")'.format(
		wall.path, [n for u, n in cameras], wall.par.Ndiname.eval()))
	return wall


build()
