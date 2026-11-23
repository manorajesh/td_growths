"""
Logogram -- ink-in-fog lookdev patch (separate from the silhouette wall and floor tracker).

Run once inside TouchDesigner (Dialogs > Textport and DATs):

    import os; exec(open(os.path.expanduser('~/code/td_silhouette/build_logogram.py')).read())

Creates /project1/logogram.  On a trigger, a ring of ink materialises out of the fog,
spreading organically around the circle from a random start angle, then keeps morphing
(wobbling radius, clumps, gaps, tendrils thrown outward) until triggered again, when it
disperses like an exhale.

Triggers (each toggles: materialise <-> disperse):
  * click on logogram/stage (open it with right-click > View...) -- the ring appears where you click
  * space bar or T while TouchDesigner has focus (C clears)
  * the Trigger pulse on the logogram COMP
  * any CHOP wired into the COMP's input (first channel, rising edge), e.g. a floor-tracker step

Output: logogram/out (TOP, 1920x1080 by default) and the COMP's output connector.
Re-running the script rebuilds logogram (parameters reset).
"""
import os

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
ROOT_DIR = next((d for d in _candidates if os.path.isfile(os.path.join(d, 'logogram', 'ink_sim.glsl'))), None)
if ROOT_DIR is None:
	raise FileNotFoundError('logogram: cannot find logogram/ink_sim.glsl; set SILHOUETTE_DIR. Looked in: {}'
	                        .format(_candidates))
SHADER_DIR = os.path.join(ROOT_DIR, 'logogram')
SHADERS = ['ink_sim', 'ink_render', 'ink_post']
NAME = 'logogram'


def E(name):
	return 'parent().par.{}'.format(name)


def try_set(o, **kw):
	for k, v in kw.items():
		try:
			setattr(o.par, k, v)
		except Exception as e:
			print('logogram: could not set {}.{} ({})'.format(o.path, k, e))


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
	noise = open(os.path.join(SHADER_DIR, 'noise.glslinc')).read()
	d = comp.create(textDAT, name + '_frag')
	d.text = open(os.path.join(SHADER_DIR, name + '.glsl')).read().replace('#include noise', noise)
	return d


def connect(srcs, dst):
	for i, s in enumerate(srcs):
		s.outputConnectors[0].connect(dst.inputConnectors[i])


def glsl(comp, name, shader, inputs=(), uniforms=(), w=None, h=None, fmt=None):
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


def add_toggle(page, name, label, default=False):
	p = page.appendToggle(name, label=label)[0]
	p.default = p.val = default
	return p


def add_int(page, name, label, default, lo=0, hi=100):
	p = page.appendInt(name, label=label)[0]
	p.default = p.val = default
	p.normMin, p.normMax = lo, hi
	return p


def add_rgb(page, name, label, rgb):
	for p, v in zip(page.appendRGB(name, label=label), rgb):
		p.default = p.val = v


# --------------------------------------------------------------------------- scripts
CONTROL = '''
import math, random

def trigger(c, u=None, v=None):
	"""Toggle: materialise a new logogram, or disperse the current one."""
	if c.par.Emitting.eval():
		release(c)
		return
	if u is not None and c.par.Clickposition.eval():
		c.par.Centerx = u
		c.par.Centery = v
	c.par.Ttrigger = absTime.seconds
	c.par.Startangle = random.uniform(0.0, 2.0 * math.pi)
	c.par.Seed = random.uniform(0.0, 100.0)
	c.par.Emitting = True

def release(c):
	if c.par.Emitting.eval():
		c.par.Emitting = False
		c.par.Trelease = absTime.seconds

def clear(c):
	c.par.Emitting = False
	c.par.Trelease = absTime.seconds - 1000.0
	c.op('sim_fb').par.resetpulse.pulse()

def onPulse(par):
	c = par.owner
	if par.name == 'Trigger':
		trigger(c)
	elif par.name == 'Release':
		release(c)
	elif par.name == 'Clear':
		clear(c)
	return
'''

STAGE_CLICK = '''
def onOffToOn(panelValue):
	if panelValue.name == 'lselect':
		ui = panelValue.owner
		c = ui.parent()
		c.op('control').module.trigger(c, ui.panel.u.val, ui.panel.v.val)
	return
'''

KEYS = '''
def onKey(dat, key, character, *args, **kwargs):
	state = kwargs.get('state', args[9] if len(args) > 9 else True)
	if not state:
		return
	c = dat.parent()
	k = (key or '').lower()
	ctl = c.op('control').module
	if k in ('space', 't') or character in (' ', 't', 'T'):
		ctl.trigger(c)
	elif k == 'c' or character in ('c', 'C'):
		ctl.clear(c)
	return
'''

CHOP_TRIGGER = '''
def onOffToOn(channel, sampleIndex, val, prev):
	c = me.parent()
	c.op('control').module.trigger(c)
	return
'''

EXEC = '''
def onFrameStart(frame):
	c = me.parent()
	if not c.par.Autocycle.eval():
		return
	now = absTime.seconds
	ctl = c.op('control').module
	if c.par.Emitting.eval() and now - c.par.Ttrigger.eval() > c.par.Holdtime.eval():
		ctl.release(c)
	elif not c.par.Emitting.eval() and now - c.par.Trelease.eval() > c.par.Restime.eval():
		ctl.trigger(c)
	return
'''


# --------------------------------------------------------------------------- build
def params(c):
	pg = c.appendCustomPage('Control')
	pg.appendPulse('Trigger', label='Trigger (toggle)')
	pg.appendPulse('Release', label='Disperse')
	pg.appendPulse('Clear', label='Clear')
	add_toggle(pg, 'Clickposition', 'Appear Where Clicked', True)
	add_float(pg, 'Centerx', 'Centre X', 0.5)
	add_float(pg, 'Centery', 'Centre Y', 0.52)
	add_toggle(pg, 'Autocycle', 'Auto Cycle (lookdev)')
	add_float(pg, 'Holdtime', 'Auto: Hold (s)', 14.0, 1, 60)
	add_float(pg, 'Restime', 'Auto: Rest (s)', 4.0, 0, 30)
	add_toggle(pg, 'Emitting', 'Emitting (state)')
	add_float(pg, 'Ttrigger', 'Trigger Time (state)', -1000.0, -1000, 1000)
	add_float(pg, 'Trelease', 'Release Time (state)', -1000.0, -1000, 1000)
	add_float(pg, 'Startangle', 'Start Angle (state)', 2.4, 0, 6.3)
	add_float(pg, 'Seed', 'Seed (state)', 3.0, 0, 100)

	pg = c.appendCustomPage('Shape')
	add_float(pg, 'Radius', 'Radius', 0.27, 0.05, 0.5)
	add_float(pg, 'Thickness', 'Thickness', 0.028, 0.005, 0.1)
	add_float(pg, 'Wobble', 'Radius Wobble', 0.12, 0, 0.5)
	add_float(pg, 'Thickvar', 'Clumpiness', 1.0, 0, 1)
	add_float(pg, 'Gaps', 'Gaps', 0.38, 0, 0.9)
	add_float(pg, 'Morphspeed', 'Morph Speed', 0.12, 0, 1)
	add_float(pg, 'Growtime', 'Materialise Time (s)', 4.0, 0.2, 20)

	pg = c.appendCustomPage('Flow')
	add_float(pg, 'Curl', 'Turbulence', 0.045, 0, 0.2)
	add_float(pg, 'Curlscale', 'Turbulence Scale', 3.0, 0.5, 10)
	add_float(pg, 'Swirl', 'Swirl Along Ring', 0.015, -0.1, 0.1)
	add_float(pg, 'Buoyancy', 'Buoyancy', 0.008, -0.05, 0.05)
	add_float(pg, 'Jets', 'Tendrils', 0.25, 0, 0.6)
	add_float(pg, 'Emission', 'Ink Emission', 2.2, 0, 8)
	add_float(pg, 'Lifetime', 'Ink Lifetime (s)', 3.0, 0.3, 15)

	pg = c.appendCustomPage('Look')
	add_float(pg, 'Inkdensity', 'Ink Opacity', 3.6, 0.5, 10)
	add_float(pg, 'Wisps', 'Fine Wisps', 0.7, 0, 2)
	add_float(pg, 'Detail', 'Fibre Detail', 1.0, 0, 2)
	add_float(pg, 'Haze', 'Haze In Front', 0.22, 0, 1)
	add_float(pg, 'Fog', 'Fog Variation', 1.0, 0, 2)
	add_float(pg, 'Shafts', 'Light Shafts', 0.6, 0, 2)
	add_float(pg, 'Shadow', 'Ink Shadow', 0.35, 0, 1)
	add_float(pg, 'Refraction', 'Refraction', 1.0, 0, 3)
	add_rgb(pg, 'Fogcolor', 'Fog (lit)', (0.40, 0.52, 0.57))
	add_rgb(pg, 'Deepcolor', 'Fog (deep)', (0.03, 0.06, 0.08))
	add_rgb(pg, 'Inkcolor', 'Ink', (0.015, 0.02, 0.025))

	pg = c.appendCustomPage('Post')
	add_float(pg, 'Exposure', 'Exposure', 1.0, 0, 3)
	add_float(pg, 'Bloom', 'Bloom', 0.25, 0, 1)
	add_float(pg, 'Grain', 'Film Grain', 0.05, 0, 0.3)
	add_float(pg, 'Vignette', 'Vignette', 0.55, 0, 1)
	add_float(pg, 'Chroma', 'Chromatic Aberration', 0.004, 0, 0.03)
	add_float(pg, 'Contrast', 'Contrast', 1.05, 0.5, 2)
	add_float(pg, 'Saturation', 'Saturation', 0.85, 0, 2)

	pg = c.appendCustomPage('Size')
	add_int(pg, 'Outw', 'Output Width', 1920, 256, 7680)
	add_int(pg, 'Outh', 'Output Height', 1080, 256, 4320)
	add_float(pg, 'Simscale', 'Sim Resolution Scale', 0.5, 0.25, 1)


def build():
	host = op('/project1') or root
	old = host.op(NAME)
	if old:
		old.destroy()
	c = host.create(baseCOMP, NAME)
	params(c)
	for s in SHADERS:
		load_shader(c, s)

	simw = 'int({} * {})'.format(E('Outw'), E('Simscale'))
	simh = 'int({} * {})'.format(E('Outh'), E('Simscale'))
	aspect = '{} / {}'.format(E('Outw'), E('Outh'))
	now = 'absTime.seconds'

	init = c.create(constantTOP, 'sim_init')
	res(init, simw, simh)
	try_set(init, format='rgba16float', colorr=0, colorg=0, colorb=0, alpha=1)
	fb = c.create(feedbackTOP, 'sim_fb')
	init.outputConnectors[0].connect(fb)
	fb.par.top = 'ink_sim'
	sim = glsl(c, 'ink_sim', 'ink_sim', inputs=[fb], w=simw, h=simh, fmt='rgba16float', uniforms=[
		('uTime', (now, '1.0/me.time.rate', aspect, E('Seed'))),
		('uState', ('max({} - {}, 0)'.format(now, E('Ttrigger')), E('Emitting'),
		            'max({} - {}, 0)'.format(now, E('Trelease')), E('Startangle'))),
		('uRing', (E('Centerx'), E('Centery'), E('Radius'), E('Thickness'))),
		('uFlow', (E('Curl'), E('Curlscale'), E('Swirl'), E('Buoyancy'))),
		('uInk', (E('Emission'), E('Lifetime'), E('Jets'), E('Growtime'))),
		('uMorph', (E('Morphspeed'), E('Wobble'), E('Thickvar'), E('Gaps')))])

	blur_s = c.create(blurTOP, 'ink_blur_small')
	blur_l = c.create(blurTOP, 'ink_blur_large')
	for b, sz in ((blur_s, 4), (blur_l, 24)):
		sim.outputConnectors[0].connect(b)
		try_set(b, size=sz, extend='zero')

	render = glsl(c, 'render', 'ink_render', inputs=[sim, blur_s, blur_l], w=E('Outw'), h=E('Outh'),
	              fmt='rgba16float', uniforms=[
		('uTime', (now, aspect, E('Seed'), 0)),
		('uLook', (E('Inkdensity'), E('Haze'), E('Fog'), E('Shafts'))),
		('uLook2', (E('Shadow'), E('Refraction'), E('Wisps'), E('Detail'))),
		('cFog', (E('Fogcolorr'), E('Fogcolorg'), E('Fogcolorb'), 1)),
		('cDeep', (E('Deepcolorr'), E('Deepcolorg'), E('Deepcolorb'), 1)),
		('cInk', (E('Inkcolorr'), E('Inkcolorg'), E('Inkcolorb'), 1))])
	bloom = c.create(blurTOP, 'bloom')
	render.outputConnectors[0].connect(bloom)
	try_set(bloom, size=40, preshrink=1)
	post = glsl(c, 'post', 'ink_post', inputs=[render, bloom], uniforms=[
		('uPost', (E('Exposure'), E('Bloom'), E('Grain'), E('Vignette'))),
		('uPost2', (E('Chroma'), now, E('Contrast'), E('Saturation')))])
	out = c.create(nullTOP, 'out')
	post.outputConnectors[0].connect(out)
	out_top = c.create(outTOP, 'out1')
	out.outputConnectors[0].connect(out_top)

	# controls
	ctl = c.create(parameterexecuteDAT, 'control')
	ctl.par.op.expr = 'parent()'
	try_set(ctl, pars='Trigger Release Clear', custom=True, builtin=False, valuechange=False, onpulse=True)
	ctl.text = CONTROL

	stage = c.create(containerCOMP, 'stage')
	stage.par.w.expr = 'int({} / 2)'.format(E('Outw'))
	stage.par.h.expr = 'int({} / 2)'.format(E('Outh'))
	stage.par.top.expr = "parent().op('out')"      # the logogram's output
	click = c.create(panelexecuteDAT, 'stage_click')
	try_set(click, panels='stage', panelvalue='lselect', offtoon=True)
	click.text = STAGE_CLICK

	kb = c.create(keyboardinDAT, 'keys')
	kcb = c.create(textDAT, 'keys_callbacks')
	kcb.text = KEYS
	try_set(kb, callbacks=kcb.name)

	trig_in = c.create(inCHOP, 'trigger_in')
	trig_exec = c.create(chopexecuteDAT, 'trigger_exec')
	trig_exec.par.chop = trig_in.name
	try_set(trig_exec, offtoon=True, ontooff=False, valuechange=False, whileon=False, whileoff=False)
	trig_exec.text = CHOP_TRIGGER

	ex = c.create(executeDAT, 'autocycle')
	ex.text = EXEC
	try_set(ex, framestart=True)

	layout = [(init, 0, 1), (fb, 1, 1), (sim, 2, 1), (blur_s, 3, 0), (blur_l, 3, 2), (render, 4, 1),
	          (bloom, 5, 2), (post, 6, 1), (out, 7, 1), (out_top, 8, 1), (ctl, 0, 4), (stage, 7, 3),
	          (click, 8, 3), (kb, 0, 6), (kcb, 1, 6), (trig_in, 2, 6), (trig_exec, 3, 6), (ex, 0, 8)]
	for o, x, y in layout:
		place(o, x, y)
	for i, s in enumerate(SHADERS):
		place(c.op(s + '_frag'), 2 + i, -1)
	print('logogram: built {} -- click logogram/stage, press space, or pulse Trigger'.format(c.path))
	return c


build()
