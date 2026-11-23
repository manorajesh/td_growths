"""
Floor Tracker -- TouchDesigner network builder (separate from the silhouette wall).

Run once inside TouchDesigner (Dialogs > Textport and DATs):

    import os; exec(open(os.path.expanduser('~/code/td_silhouette/build_floor_tracker.py')).read())

Creates /project1/floor_tracker (or inside FLOOR_TRACKER_PARENT if you set it first, e.g.
FLOOR_TRACKER_PARENT = '/container1').  A high, angled webcam watches the audience; the helper
(helper/floor_track.py, Apple Vision) finds up to 5 people's feet, maps them through the
perspective calibration onto the floor (0..1 floor coordinates), tracks them with stable
slots and detects steps.  Outputs inside floor_tracker, ready to plug into your effects:

    people    CHOP  per slot i (0..4): p{i}_active, p{i}_id, p{i}_u, p{i}_v, p{i}_tx, p{i}_ty,
                    p{i}_speed, p{i}_lu, p{i}_lv, p{i}_lfoot, p{i}_ru, p{i}_rv, p{i}_rfoot,
                    p{i}_step (1 for the frame a step lands), p{i}_stepu, p{i}_stepv,
                    p{i}_scale (multiply a circle's size by this to keep it the same size on the floor);
                    plus count, steps_total
    mouse     CHOP  u, v, tx, ty, fx, fy, active, slot -- the primary person, a drop-in for mouse debugging
                    (fx, fy = u-0.5, v-0.5: ready to use as Transform TOP translate)
    step_trigger CHOP gate (1 for Gate Time after a step, with cooldown), u, v, fx, fy of that step
    steps     DAT   recent step events: n, slot, id, foot, u, v, time
    feet_map  TOP   r = feet / presence blobs, g = step flashes (fading), in floor space
    floor_view TOP  debug: camera rectified to the floor + feet map + grid
    calib_pattern TOP  grid with coloured corner dots (manual calibration)
    calib_markers TOP  ArUco marker pattern shown while Auto Calibrate runs (route into your output)

u, v are 0..1 across the calibrated floor area (u right, v up the floor texture);
tx, ty are the same in -1..1.  Re-running the script rebuilds floor_tracker (resets params).
"""
import os
import subprocess

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
ROOT_DIR = next((d for d in _candidates if os.path.isfile(os.path.join(d, 'helper', 'floor_track.py'))), None)
if ROOT_DIR is None:
	raise FileNotFoundError('floor_tracker: cannot find helper/floor_track.py; set SILHOUETTE_DIR. '
	                        'Looked in: {}'.format(_candidates))
SHADER_DIR = os.path.join(ROOT_DIR, 'shaders')


def portable(path):
	"""Store paths under the user's home as ~/... so a saved .toe works for another user."""
	home = os.path.expanduser('~')
	return '~' + path[len(home):] if path.startswith(home + os.sep) else path
HELPER_PY = os.path.join(ROOT_DIR, 'helper', '.venv', 'bin', 'python')
HELPER = os.path.join(ROOT_DIR, 'helper', 'floor_track.py')
SHADERS = ['warp', 'calibview', 'floorview', 'floorgrid']
NAME = 'floor_tracker'


# --------------------------------------------------------------------------- helpers
def E(name):
	return 'parent().par.{}'.format(name)


def try_set(o, **kw):
	for k, v in kw.items():
		try:
			setattr(o.par, k, v)
		except Exception as e:
			print('floor_tracker: could not set {}.{} ({})'.format(o.path, k, e))


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


def glsl(comp, name, shader, inputs=(), uniforms=(), w=None, h=None):
	g = comp.create(glslTOP, name)
	for d in list(g.docked):
		d.destroy()
	g.par.pixeldat = shader + '_frag'
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


def script_op(comp, optype, name, text):
	o = comp.create(optype, name)
	for d in list(o.docked):
		d.destroy()
	cb = comp.create(textDAT, name + '_callbacks')
	cb.text = text
	o.par.callbacks = cb.name
	return o, cb


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


def add_xy(page, name, label, x, y):
	for p, v in zip(page.appendXY(name, label=label), (x, y)):
		p.default = p.val = v
		p.normMin, p.normMax = 0, 1


def add_str(page, name, label, default):
	p = page.appendStr(name, label=label)[0]
	p.default = p.val = default
	return p


def list_cameras():
	try:
		out = subprocess.run([HELPER_PY, '-I', HELPER, '--list'], capture_output=True, text=True,
		                     timeout=30).stdout
		cams = [tuple(ln.split('\t')[1:3]) for ln in out.splitlines() if ln.count('\t') == 2]
		if cams:
			return cams
	except Exception as e:
		print('floor_tracker: could not list cameras via helper ({})'.format(e))
	return [('0', 'Camera 0'), ('1', 'Camera 1'), ('2', 'Camera 2')]


# --------------------------------------------------------------------------- DAT scripts
# Shared reader: maps the helper's output file once per frame (all script ops call update()).
READER = '''
import json, mmap, os, struct
import numpy as np

HEADER = struct.Struct('<4sIQIII')
HS = 64
JSON_OFFSET = HS + 1920 * 1080 * 4
FILE_SIZE = JSON_OFFSET + 256 * 1024
EMPTY = {'people': [], 'steps': [], 'count': 0, 'step_count': 0}

_st = {'path': None, 'f': None, 'mm': None, 'seq': -1, 'img': None, 'state': EMPTY, 'frame': -1,
       'last_n': 0, 'new_steps': [], 'step_log': [], 'updated': -1.0}

def _open(path):
	if _st['path'] == path and _st['mm'] is not None:
		return True
	if not os.path.exists(path) or os.path.getsize(path) != FILE_SIZE:
		return False
	f = open(path, 'rb')
	_st.update(path=path, f=f, mm=mmap.mmap(f.fileno(), FILE_SIZE, access=mmap.ACCESS_READ), seq=-1)
	return True

def update():
	"""Read the newest helper frame (once per TouchDesigner frame) and return the shared state."""
	if _st['frame'] == absTime.frame:
		return _st
	_st['frame'] = absTime.frame
	_st['new_steps'] = []
	try:
		if not _open(me.parent().par.Datafile.eval()):
			return _st
		mm = _st['mm']
		magic, ver, seq, w, h, jl = HEADER.unpack_from(mm, 0)
		if magic != b'FLT1' or seq % 2 or seq == _st['seq'] or not (0 < w * h * 4 <= JSON_OFFSET - HS):
			return _st
		img = np.frombuffer(mm, np.uint8, w * h * 4, HS).reshape(h, w, 4).copy()
		js = bytes(mm[JSON_OFFSET:JSON_OFFSET + jl])
		if HEADER.unpack_from(mm, 0)[2] != seq:
			return _st
		state = json.loads(js)
		_st.update(seq=seq, img=img, state=state, updated=absTime.seconds)
		if state.get('step_count', 0) < _st['last_n']:      # helper restarted
			_st['last_n'] = 0
		new = [s for s in state.get('steps', []) if s['n'] > _st['last_n']]
		if new:
			_st['last_n'] = max(s['n'] for s in new)
			for s in new:
				s['td_time'] = absTime.seconds
			_st['new_steps'] = new
			_st['step_log'] = (_st['step_log'] + new)[-64:]
	except Exception as e:
		debug('floor_tracker reader:', e)
	return _st

def stale():
	"""True if the helper has not delivered a frame for over a second."""
	return absTime.seconds - _st['updated'] > 1.0
'''

CAMERA_TOP = '''
import numpy as np

def onSetupParameters(scriptOp):
	return

def onCook(scriptOp):
	st = op('reader').module.update()
	img = st['img'] if st['img'] is not None else np.zeros((16, 16, 4), np.uint8)
	scriptOp.copyNumpyArray(img)
'''

PEOPLE_CHOP = '''
_last = {}

def onSetupParameters(scriptOp):
	return

def onCook(scriptOp):
	rd = op('reader').module
	st = rd.update()
	c = scriptOp.parent()
	n_slots = int(c.par.Maxpeople.eval())
	people = {} if rd.stale() else {p['slot']: p for p in st['state'].get('people', [])}
	stepped = {}
	for s in st['new_steps']:
		stepped[s['slot']] = s
	scriptOp.clear()
	scriptOp.numSamples = 1
	vals = []
	for i in range(n_slots):
		p = people.get(i)
		last = _last.setdefault(i, {'u': 0.5, 'v': 0.5, 'lu': 0.5, 'lv': 0.5, 'ru': 0.5, 'rv': 0.5,
		                            'stepu': 0.5, 'stepv': 0.5, 'id': 0, 'scale': 1.0})
		if p:
			last.update(u=p['u'], v=p['v'], id=p['id'], scale=p.get('scale', 1.0))
			for k, f in zip('lr', p['feet']):
				if f:
					last[k + 'u'], last[k + 'v'] = f
		s = stepped.get(i)
		if s:
			last['stepu'], last['stepv'] = s['u'], s['v']
		pre = 'p{}_'.format(i)
		vals += [(pre + 'active', 1 if p else 0), (pre + 'id', last['id']),
		         (pre + 'u', last['u']), (pre + 'v', last['v']),
		         (pre + 'tx', last['u'] * 2 - 1), (pre + 'ty', last['v'] * 2 - 1),
		         (pre + 'speed', p['speed'] if p else 0.0),
		         (pre + 'lu', last['lu']), (pre + 'lv', last['lv']), (pre + 'lfoot', 1 if p and p['feet'][0] else 0),
		         (pre + 'ru', last['ru']), (pre + 'rv', last['rv']), (pre + 'rfoot', 1 if p and p['feet'][1] else 0),
		         (pre + 'step', 1 if s else 0), (pre + 'stepu', last['stepu']), (pre + 'stepv', last['stepv']),
		         (pre + 'scale', last['scale'])]
	vals += [('count', len(people)), ('steps_total', st['state'].get('step_count', 0)),
	         ('helper_ok', 0 if rd.stale() else 1)]
	for name, v in vals:
		scriptOp.appendChan(name)[0] = v
'''

MOUSE_CHOP = '''
_last = {'u': 0.5, 'v': 0.5, 'slot': -1}

def onSetupParameters(scriptOp):
	return

def onCook(scriptOp):
	rd = op('reader').module
	st = rd.update()
	people = [] if rd.stale() else st['state'].get('people', [])
	active = 0
	if people:
		# primary = the person who has been here longest (stable while people come and go)
		p = max(people, key=lambda q: q.get('age', 0))
		_last.update(u=p['u'], v=p['v'], slot=p['slot'])
		active = 1
	scriptOp.clear()
	scriptOp.numSamples = 1
	for name, v in (('u', _last['u']), ('v', _last['v']), ('tx', _last['u'] * 2 - 1),
	                ('ty', _last['v'] * 2 - 1), ('fx', _last['u'] - 0.5), ('fy', _last['v'] - 0.5),
	                ('active', active), ('slot', _last['slot'])):
		scriptOp.appendChan(name)[0] = v
'''

STEPS_DAT = '''
def onSetupParameters(scriptOp):
	return

def onCook(scriptOp):
	st = op('reader').module.update()
	scriptOp.clear()
	scriptOp.appendRow(['n', 'slot', 'id', 'foot', 'u', 'v', 'time'])
	for s in st['step_log'][-int(parent().par.Steplog.eval()):]:
		scriptOp.appendRow([s['n'], s['slot'], s['id'], s['foot'], s['u'], s['v'], round(s['td_time'], 3)])
'''

FEETMAP_TOP = '''
import numpy as np
_grid = {}

def onSetupParameters(scriptOp):
	return

def onCook(scriptOp):
	rd = op('reader').module
	st = rd.update()
	c = scriptOp.parent()
	w = int(c.par.Feetmapw.eval())
	h = int(c.par.Feetmaph.eval())
	if _grid.get('size') != (w, h):
		yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
		_grid.update(size=(w, h), u=(xx + 0.5) / w, v=(yy + 0.5) / h)
	u, v = _grid['u'], _grid['v']
	aspect = c.par.Floorw.eval() / max(c.par.Floord.eval(), 1e-3)
	r = max(c.par.Feetradius.eval(), 1e-4)
	img = np.zeros((h, w, 4), np.float32)
	img[..., 3] = 1.0
	def splat(ch, pu, pv, amp):
		d2 = ((u - pu) * aspect) ** 2 + (v - pv) ** 2
		img[..., ch] = np.maximum(img[..., ch], amp * np.exp(-d2 / (2 * r * r)))
	if not rd.stale():
		for p in st['state'].get('people', []):
			feet = [f for f in p['feet'] if f]
			for f in (feet or [[p['u'], p['v']]]):
				splat(0, f[0], f[1], 1.0)
	fade = max(c.par.Stepflash.eval(), 1e-3)
	now = absTime.seconds
	for s in st['step_log']:
		age = now - s['td_time']
		if age < fade * 4:
			splat(1, s['u'], s['v'], float(np.exp(-age / fade)))
	scriptOp.copyNumpyArray(img)   # row 0 = bottom = floor v 0
'''

STEP_TRIGGER = '''
# One trigger for "a step happened", with a cooldown so walking does not re-fire constantly.
# gate: 1 for Gate Time after an accepted step (use it like a key press)
# u, v: where that step landed (held until the next accepted step)
# fx, fy: the same as Transform TOP translate offsets (u - 0.5, v - 0.5, fraction units)
_s = {'fired': -1e9, 'u': 0.5, 'v': 0.5, 'n': 0}

def onSetupParameters(scriptOp):
	return

def onCook(scriptOp):
	c = scriptOp.parent()
	st = op('reader').module.update()
	now = absTime.seconds
	for s in st['new_steps']:
		if now - _s['fired'] >= c.par.Stepcooldown.eval():
			_s.update(fired=now, u=s['u'], v=s['v'], n=_s['n'] + 1)
	gate = 1 if now - _s['fired'] < c.par.Gatetime.eval() else 0
	scriptOp.clear()
	scriptOp.numSamples = 1
	for name, v in (('gate', gate), ('u', _s['u']), ('v', _s['v']), ('fx', _s['u'] - 0.5),
	                ('fy', _s['v'] - 0.5), ('count', _s['n'])):
		scriptOp.appendChan(name)[0] = v
'''

PULSES = '''
import json, os, signal, subprocess

CORNERS = {'Cornerbl': (0.0, 0.0), 'Cornerbr': (1.0, 0.0), 'Cornertr': (1.0, 1.0), 'Cornertl': (0.0, 1.0)}
HELPER_PARS = ('Camera', 'Datafile', 'Configfile', 'Phonefile')
_procs = {}

def write_config(c):
	p = c.par
	cfg = {
		'corners': {k: [getattr(p, 'Corner' + k + 'x').eval(), getattr(p, 'Corner' + k + 'y').eval()]
		            for k in ('bl', 'br', 'tr', 'tl')},
		'lens_k1': p.Lensk1.eval(), 'floor_w': p.Floorw.eval(), 'floor_d': p.Floord.eval(),
		'max_people': int(p.Maxpeople.eval()), 'margin': p.Margin.eval(), 'joint_conf': p.Jointconf.eval(),
		'match_dist': p.Matchdist.eval(), 'lost_time': p.Losttime.eval(),
		'smooth_min_cutoff': p.Smoothing.eval(), 'smooth_beta': p.Smoothingbeta.eval(),
		'step_move_speed': p.Stepmovespeed.eval(), 'step_plant_speed': p.Stepplantspeed.eval(),
		'step_plant_time': p.Stepplanttime.eval(), 'step_min_dist': p.Stepmindist.eval(),
		'calib_request': int(p.Calibrequest.eval()) if hasattr(p, 'Calibrequest') else 0,
		'calib_result_file': p.Calibfile.eval() if hasattr(p, 'Calibfile') else '/tmp/floor_track_calib.json',
		'pattern_w': int(p.Patternw.eval()), 'pattern_h': int(p.Patternh.eval()),
		'warp_mode': p.Warpmode.eval() if hasattr(p, 'Warpmode') else 'off',
		'camera_tilt': p.Cameratilt.eval() if hasattr(p, 'Cameratilt') else 0.0,
		'camera_fov': p.Camerafov.eval() if hasattr(p, 'Camerafov') else 70.0,
		'constant_size': bool(p.Constantsize.eval()) if hasattr(p, 'Constantsize') else True,
		'cam_exposure': p.Camexposure.eval() if hasattr(p, 'Camexposure') else 0.0,
		'cam_contrast': p.Camcontrast.eval() if hasattr(p, 'Camcontrast') else 1.0,
	}
	path = p.Configfile.eval()
	tmp = path + '.tmp'
	with open(tmp, 'w') as f:
		json.dump(cfg, f, indent=1)
	os.replace(tmp, path)          # atomic: the helper never reads a half-written file

def _camera_args(c, par):
	# phone (VDO.Ninja via phone_in / phone_send) or a real camera by ID with a name fallback
	if par.eval() == 'phone':
		return ['--camera', 'td:' + c.par.Phonefile.eval()]
	names = list(par.menuNames)
	label = par.menuLabels[names.index(par.eval())] if par.eval() in names else ''
	return ['--camera', par.eval(), '--camera-name', label]

def _is_helper(pid):
	try:
		out = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True).stdout
	except Exception:
		return False
	return 'floor_track.py' in out

def stop_helper(c):
	p = _procs.pop(c.path, None)
	if p is not None and p.poll() is None:
		debug('floor_tracker: stopping helper pid', p.pid)
		p.terminate()
	pid = c.fetch('helper_pid', 0, search=False)
	if pid and (p is None or p.pid != pid) and _is_helper(pid):
		try:
			os.kill(pid, signal.SIGTERM)
		except OSError:
			pass
	c.unstore('helper_pid')

def start_helper(c):
	stop_helper(c)
	write_config(c)
	root = os.path.expanduser(c.par.Projectfolder.eval())
	py = os.path.join(root, 'helper', '.venv', 'bin', 'python')
	script = os.path.join(root, 'helper', 'floor_track.py')
	if not os.path.exists(py):
		debug('floor_tracker: helper venv missing at', py)
		return
	f = c.par.Datafile.eval()
	log = open(os.path.splitext(f)[0] + '.log', 'a')
	log.write('\\n--- started by TouchDesigner (camera {})\\n'.format(c.par.Camera.eval()))
	log.flush()
	cmd = [py, '-I', script] + _camera_args(c, c.par.Camera) + ['--file', f,
	       '--config', c.par.Configfile.eval(), '--parent-pid', str(os.getpid())]
	_procs[c.path] = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
	c.store('helper_pid', _procs[c.path].pid)
	debug('floor_tracker: started helper pid', _procs[c.path].pid, 'camera', c.par.Camera.eval())

def helper_alive(c):
	p = _procs.get(c.path)
	return p is not None and p.poll() is None

def helper_status(c):
	p = _procs.get(c.path)
	if p is None:
		return 'not running'
	return 'running (pid {})'.format(p.pid) if p.poll() is None else 'exited ({})'.format(p.returncode)

def make_markers(c):
	# the ArUco pattern at the content resolution, drawn by the helper (TouchDesigner has no ArUco)
	root = os.path.expanduser(c.par.Projectfolder.eval())
	py = os.path.join(root, 'helper', '.venv', 'bin', 'python')
	script = os.path.join(root, 'helper', 'floor_track.py')
	subprocess.run([py, '-I', script, '--make-markers', c.par.Markerfile.eval(),
	                '--mw', str(int(c.par.Patternw.eval())), '--mh', str(int(c.par.Patternh.eval()))],
	               capture_output=True, timeout=60)
	m = c.op('calib_markers')
	if m is not None:
		m.par.reloadpulse.pulse()

def auto_calibrate(c):
	if not helper_alive(c):
		c.par.Calibstatus = 'FAILED: helper not running (check the camera / log)'
		return
	make_markers(c)
	c.par.Calibrequest = int(c.par.Calibrequest.eval()) + 1
	c.par.Calibrating = True
	c.store('calib_started', absTime.seconds)
	c.par.Calibstatus = 'calibrating: showing markers...'
	write_config(c)
	debug('floor_tracker: auto-calibration', int(c.par.Calibrequest.eval()), 'started')

IDENTITY = {'bl': (0, 0), 'br': (1, 0), 'tr': (1, 1), 'tl': (0, 1)}

def apply_result(c, res):
	c.par.Calibrating = False
	if not res.get('ok'):
		c.par.Calibstatus = 'FAILED: ' + res.get('message', '?')
		return
	for k in ('bl', 'br', 'tr', 'tl'):
		x, y = res['corners'][k]
		getattr(c.par, 'Corner' + k + 'x').val = x
		getattr(c.par, 'Corner' + k + 'y').val = y
	c.par.Lensk1 = 0.0
	if hasattr(c.par, 'Projcornerblx'):
		proj = res.get('proj_corners') or IDENTITY
		for k in ('bl', 'br', 'tr', 'tl'):
			getattr(c.par, 'Projcorner' + k + 'x').val = proj[k][0]
			getattr(c.par, 'Projcorner' + k + 'y').val = proj[k][1]
	c.par.Calibstatus = 'OK: ' + res['message']

def poll_calibration(c):
	# results arrive after Auto Calibrate, and again whenever Camera Tilt / FOV / Output Warp change
	path = c.par.Calibfile.eval()
	try:
		mt = os.path.getmtime(path)
	except OSError:
		mt = None
	if mt is not None and mt != c.fetch('calib_mtime', None, search=False):
		c.store('calib_mtime', mt)
		try:
			with open(path) as f:
				res = json.load(f)
		except (OSError, ValueError):
			res = None
		if res and res.get('request') == int(c.par.Calibrequest.eval()):
			apply_result(c, res)
			debug('floor_tracker calibration:', c.par.Calibstatus.eval())
			return
	if c.par.Calibrating.eval() and absTime.seconds - c.fetch('calib_started', 0, search=False) > 15:
		c.par.Calibrating = False
		c.par.Calibstatus = 'FAILED: no answer from the helper (see /tmp/floor_track.log)'

def onValueChange(par, prev):
	c = par.owner
	if par.name in HELPER_PARS:
		start_helper(c)
	elif par.name not in ('Projectfolder', 'Calibstatus', 'Calibrating'):
		write_config(c)
	return

def refresh_cameras(c):
	# re-list cameras (e.g. one was plugged in after building) and keep the current choice
	root = os.path.expanduser(c.par.Projectfolder.eval())
	py = os.path.join(root, 'helper', '.venv', 'bin', 'python')
	out = subprocess.run([py, '-I', os.path.join(root, 'helper', 'floor_track.py'), '--list'],
	                     capture_output=True, text=True, timeout=30).stdout
	cams = [tuple(ln.split('\\t')[1:3]) for ln in out.splitlines() if ln.count('\\t') == 2]
	if not cams:
		debug('floor_tracker: no cameras found')
		return
	cur = c.par.Camera.eval()
	c.par.Camera.menuNames = [u for u, n in cams] + ['phone']
	c.par.Camera.menuLabels = [n for u, n in cams] + ['Phone (VDO.Ninja URL)']
	if cur in c.par.Camera.menuNames:
		c.par.Camera.val = cur
	debug('floor_tracker: cameras', [n for u, n in cams])

def onPulse(par):
	c = par.owner
	if par.name == 'Refreshcameras':
		refresh_cameras(c)
	elif par.name == 'Autocalibrate':
		auto_calibrate(c)
	elif par.name == 'Restarthelper':
		start_helper(c)
	elif par.name == 'Resetcorners':
		for n, (x, y) in CORNERS.items():
			getattr(c.par, n + 'x').val = x
			getattr(c.par, n + 'y').val = y
		write_config(c)
	return
'''

EXEC = '''
_last_restart = [-99.0]
COOK = ('camera_in', 'people_script', 'mouse_script', 'steps_script', 'feet_map_script', 'step_trigger_script')

def onStart():
	me.parent().op('pulses').module.start_helper(me.parent())
	return

def onFrameStart(frame):
	c = me.parent()
	for n in COOK:
		o = c.op(n)
		if o is not None:
			o.cook(force=True)
	if hasattr(c.par, 'Calibfile') and (frame % 6 == 0 or c.par.Calibrating.eval()):
		c.op('pulses').module.poll_calibration(c)
	if frame % 30 == 0:
		pulses = c.op('pulses').module
		if not pulses.helper_alive(c) and absTime.seconds - _last_restart[0] > 5:
			_last_restart[0] = absTime.seconds
			debug('floor_tracker: helper is', pulses.helper_status(c), '- restarting')
			pulses.start_helper(c)
	return

def onExit():
	me.parent().op('pulses').module.stop_helper(me.parent())
	return
'''

# Drag the floor corners on the camera image (same tool as the silhouette wall).
PANEL_DRAG = '''
CORNERS = ['Cornerbl', 'Cornerbr', 'Cornertr', 'Cornertl']

def _undistort(c, u, v):
	k = c.par.Lensk1.eval()
	cx, cy = u - 0.5, v - 0.5
	x, y = cx, cy
	for _ in range(6):
		s = 1.0 + k * (x * x + y * y)
		x, y = cx / s, cy / s
	return x + 0.5, y + 0.5

def _uv(ui):
	return _undistort(ui.parent(), ui.panel.u.val, ui.panel.v.val)

def _set(c, name, u, v):
	getattr(c.par, name + 'x').val = round(min(max(u, -0.5), 1.5), 4)
	getattr(c.par, name + 'y').val = round(min(max(v, -0.5), 1.5), 4)

def onOffToOn(panelValue):
	if panelValue.name != 'lselect':
		return
	ui = panelValue.owner
	c = ui.parent()
	u, v = _uv(ui)
	best = min(CORNERS, key=lambda n: (getattr(c.par, n + 'x').eval() - u) ** 2 +
	                                  (getattr(c.par, n + 'y').eval() - v) ** 2)
	ui.store('drag', best)
	_set(c, best, u, v)
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


# --------------------------------------------------------------------------- build
def params(c, cameras):
	pg = c.appendCustomPage('Camera')
	p = pg.appendMenu('Camera', label='Camera')[0]
	p.menuNames, p.menuLabels = [u for u, n in cameras], [n for u, n in cameras]
	p.default = p.val = cameras[0][0]
	pg.appendPulse('Refreshcameras', label='Refresh Cameras')
	pg.appendPulse('Restarthelper', label='Restart Helper')
	exec(open(os.path.join(ROOT_DIR, 'cam_controls.py')).read(), globals())
	add_cam_controls(c, pg)                       # Camera Exposure / Contrast (applied before tracking)
	add_str(pg, 'Datafile', 'Helper Data File', '/tmp/floor_track.bin')
	add_str(pg, 'Configfile', 'Helper Config File', '/tmp/floor_track_config.json')
	p = pg.appendFolder('Projectfolder', label='Project Folder (helper/)')[0]
	p.default = p.val = portable(ROOT_DIR)

	pg = c.appendCustomPage('Floor')
	add_xy(pg, 'Cornertl', 'Top-Left (red)', 0.0, 1.0)
	add_xy(pg, 'Cornertr', 'Top-Right (green)', 1.0, 1.0)
	add_xy(pg, 'Cornerbl', 'Bottom-Left (yellow)', 0.0, 0.0)
	add_xy(pg, 'Cornerbr', 'Bottom-Right (blue)', 1.0, 0.0)
	pg.appendPulse('Resetcorners', label='Reset Corners')
	add_float(pg, 'Lensk1', 'Lens Correction k1', 0.0, -0.6, 0.6)
	add_float(pg, 'Floorw', 'Floor Width (m, along u)', 6.0, 1, 30)
	add_float(pg, 'Floord', 'Floor Depth (m, along v)', 4.0, 1, 30)
	add_int(pg, 'Gridcols', 'Grid Columns', 4, 1, 16)
	add_int(pg, 'Gridrows', 'Grid Rows', 4, 1, 16)
	add_int(pg, 'Patternw', 'Calib Pattern Width', 1920, 64, 8192)
	add_int(pg, 'Patternh', 'Calib Pattern Height', 1080, 64, 8192)

	pg = c.appendCustomPage('Tracking')
	add_int(pg, 'Maxpeople', 'Max People (slots)', 5, 1, 12)
	add_float(pg, 'Margin', 'Outside-Floor Margin', 0.15, 0, 1)
	add_float(pg, 'Jointconf', 'Ankle Confidence Min', 0.2)
	add_float(pg, 'Matchdist', 'Same-Person Max Jump (m)', 0.9, 0.1, 3)
	add_float(pg, 'Losttime', 'Keep Lost Person (s)', 0.7, 0, 5)
	add_float(pg, 'Smoothing', 'Smoothing (lower = smoother)', 1.2, 0.1, 10)
	add_float(pg, 'Smoothingbeta', 'Smoothing Speed Response', 0.6, 0, 5)
	add_float(pg, 'Stepmovespeed', 'Step: Lifted Above (m/s)', 0.35, 0, 3)
	add_float(pg, 'Stepplantspeed', 'Step: Planted Below (m/s)', 0.15, 0, 3)
	add_float(pg, 'Stepplanttime', 'Step: Planted For (s)', 0.08, 0, 1)
	add_float(pg, 'Stepmindist', 'Step: Min Distance (m)', 0.12, 0, 1)

	pg = c.appendCustomPage('Output')
	add_int(pg, 'Feetmapw', 'Feet Map Width', 256, 16, 2048)
	add_int(pg, 'Feetmaph', 'Feet Map Height', 256, 16, 2048)
	add_float(pg, 'Feetradius', 'Feet Blob Radius (0..1)', 0.025, 0.002, 0.2)
	add_float(pg, 'Stepflash', 'Step Flash Fade (s)', 0.4, 0.05, 3)
	add_int(pg, 'Steplog', 'Steps DAT Rows', 32, 1, 64)
	add_float(pg, 'Stepcooldown', 'Step Trigger Cooldown (s)', 2.5, 0, 10)
	add_float(pg, 'Gatetime', 'Step Trigger Gate (s)', 0.25, 0.02, 2)


def build():
	# where to build: set FLOOR_TRACKER_PARENT before exec() (e.g. '/container1'); default /project1
	host = op(globals().get('FLOOR_TRACKER_PARENT', '/project1')) or op('/project1') or root
	old = host.op(NAME)
	if old:
		try:
			old.op('pulses').module.stop_helper(old)
		except Exception:
			pass
		old.destroy()
	subprocess.run(['pkill', '-f', 'floor_track.py .*--file '], capture_output=True)

	c = host.create(baseCOMP, NAME)
	cameras = list_cameras()
	params(c, cameras)
	for s in SHADERS:
		load_shader(c, s)
	reader = c.create(textDAT, 'reader')
	reader.text = READER

	cam, cam_cb = script_op(c, scriptTOP, 'camera_in', CAMERA_TOP)
	people_s, people_cb = script_op(c, scriptCHOP, 'people_script', PEOPLE_CHOP)
	mouse_s, mouse_cb = script_op(c, scriptCHOP, 'mouse_script', MOUSE_CHOP)
	steps_s, steps_cb = script_op(c, scriptDAT, 'steps_script', STEPS_DAT)
	feet_s, feet_cb = script_op(c, scriptTOP, 'feet_map_script', FEETMAP_TOP)
	trig_s, trig_cb = script_op(c, scriptCHOP, 'step_trigger_script', STEP_TRIGGER)

	outs = {}
	for src, fam, nm in ((people_s, nullCHOP, 'people'), (mouse_s, nullCHOP, 'mouse'),
	                     (steps_s, nullDAT, 'steps'), (feet_s, nullTOP, 'feet_map'),
	                     (trig_s, nullCHOP, 'step_trigger')):
		n = c.create(fam, nm)
		src.outputConnectors[0].connect(n)
		outs[nm] = n

	corners = [('uC0', (E('Cornerblx'), E('Cornerbly'), E('Cornerbrx'), E('Cornerbry'))),
	           ('uC1', (E('Cornertrx'), E('Cornertry'), E('Cornertlx'), E('Cornertly')))]
	vw = 800
	vh = 'int(800 * {} / max({}, 0.001))'.format(E('Floord'), E('Floorw'))
	cam_warp = glsl(c, 'cam_warp', 'warp', inputs=[cam], w=vw, h=vh,
	                uniforms=corners + [('uOpt', (0, E('Lensk1'), -1, 0))])
	floor_view = glsl(c, 'floor_view', 'floorview', inputs=[cam_warp, outs['feet_map']],
	                  uniforms=[('uGrid', (E('Gridcols'), E('Gridrows'), 0, 0))])
	calib = glsl(c, 'calib_view', 'calibview', inputs=[cam, cam],
	             uniforms=corners + [('uOpt', (0, E('Lensk1'), E('Gridcols'), E('Gridrows'))),
	                                 ('uMaskCh', (3, 1, 0, 0))])
	pattern = glsl(c, 'calib_pattern', 'floorgrid', w=E('Patternw'), h=E('Patternh'),
	               uniforms=[('uGrid', (E('Gridcols'), E('Gridrows'), 0, 0))])

	# Out ops so the COMP can be wired directly into an effects network
	wired = []
	for nm, fam, src in (('out_people', outCHOP, outs['people']), ('out_mouse', outCHOP, outs['mouse']),
	                     ('out_steps', outDAT, outs['steps']), ('out_feet_map', outTOP, outs['feet_map'])):
		o = c.create(fam, nm)
		src.outputConnectors[0].connect(o)
		wired.append(o)

	ui = c.create(containerCOMP, 'calibrate_ui')
	ui.par.w = 800
	ui.par.h.expr = "int(800 * op('camera_in').height / max(op('camera_in').width, 1))"
	ui.par.top.expr = "parent().op('calib_view')"
	drag = c.create(panelexecuteDAT, 'calibrate_drag')
	try_set(drag, panels='calibrate_ui', panelvalue='lselect u v', offtoon=True, ontooff=True, valuechange=True)
	drag.text = PANEL_DRAG

	pe = c.create(parameterexecuteDAT, 'pulses')
	pe.par.op.expr = 'parent()'
	try_set(pe, pars='*', custom=True, builtin=False, valuechange=True, onpulse=True)
	pe.text = PULSES
	ex = c.create(executeDAT, 'helpers')
	ex.text = EXEC
	try_set(ex, start=True, framestart=True, exit=True)

	layout = [(reader, 0, 0), (cam, 1, 0), (cam_cb, 1, -1), (people_s, 2, 1), (people_cb, 2, 0),
	          (mouse_s, 2, 3), (mouse_cb, 2, 2), (steps_s, 2, 5), (steps_cb, 2, 4), (feet_s, 2, 7),
	          (feet_cb, 2, 6), (outs['people'], 3, 1), (outs['mouse'], 3, 3), (outs['steps'], 3, 5),
	          (outs['feet_map'], 3, 7), (wired[0], 4, 1), (wired[1], 4, 3), (wired[2], 4, 5), (wired[3], 4, 7),
	          (cam_warp, 5, 0), (floor_view, 6, 0), (calib, 5, -2), (ui, 6, -2), (drag, 7, -2),
	          (pattern, 5, 9), (pe, 0, 3), (ex, 0, 5), (trig_s, 2, 9), (trig_cb, 2, 8), (outs['step_trigger'], 3, 9)]
	for o, x, y in layout:
		place(o, x, y)
	for i, s in enumerate(SHADERS):
		place(c.op(s + '_frag'), i, 11)

	exec(open(os.path.join(ROOT_DIR, 'phone_input.py')).read(), globals())
	add_phone_input(c, 'Camera', 'floor_track')        # 'Phone (VDO.Ninja URL)' camera option
	exec(open(os.path.join(ROOT_DIR, 'autocal.py')).read(), globals())
	add_autocalibration(c)                              # Auto Calibrate (projected ArUco markers)
	c.op('pulses').module.start_helper(c)
	print('floor_tracker: built {}  (cameras: {})'.format(c.path, [n for u, n in cameras]))
	return c


build()
