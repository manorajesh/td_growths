"""
Spores -- physarum (slime-mold) filaments growing over each LED side's silhouette.

Run in TouchDesigner's Textport:

    import os; exec(open(os.path.expanduser('~/code/td_silhouette/build_spores.py')).read())

Creates /project1/spores with side_L and side_R.  Each side runs a physarum simulation:
~590k agents (768x768) sense the trail ahead at three angles, turn toward the strongest,
step and deposit -- self-organising into flowing, hair-fine filament networks.  Agents live
only inside that side's silhouette, so the network reveals the form; they come alive
gradually after someone arrives (from the outline and the feet first), stream with a gentle
downward flow, and a second 'hair' species braids fine fuzz around the main veins.  When the
person leaves, agents drift off and die, and the last network lingers and fades.

Pipeline per side:  agents (GLSL, feedback) -> deposit (Render TOP: one instanced point per
agent, additive) -> trail (GLSL: diffuse/decay, feedback) -> look (violet strands, white-hot
cores, orange haze, sparks) -> bloom -> out_hi (4x) -> box-filter -> out_led (160x320).

If /project1/silhouette_wall exists, display_L / display_R show the result.  All controls
are on the spores COMP (shared by both sides).  Re-running rebuilds spores.
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
ROOT_DIR = next((d for d in _candidates if os.path.isfile(os.path.join(d, 'spores', 'agents.glsl'))), None)
if ROOT_DIR is None:
	raise FileNotFoundError('spores: cannot find spores/agents.glsl; set SILHOUETTE_DIR. Looked in: {}'.format(_candidates))
SPORE_DIR = os.path.join(ROOT_DIR, 'spores')
NAME = 'spores'
G = 'parent(2).par.'          # inside a side: the spores COMP's parameters


def try_set(o, **kw):
	for k, v in kw.items():
		try:
			setattr(o.par, k, v)
		except Exception as e:
			print('spores: could not set {}.{} ({})'.format(o.path, k, e))


def set_expr(par, v):
	if isinstance(v, str):
		par.expr = v
	else:
		par.val = v


def res(o, w, h):
	o.par.outputresolution = 'custom'
	set_expr(o.par.resolutionw, w)
	set_expr(o.par.resolutionh, h)


def load_shader(comp, name, path):
	d = comp.create(textDAT, name + '_frag')
	d.text = open(path).read()
	return d


def connect_inputs(g, srcs):
	"""Wire srcs into g's inputs in order.  A multi-input TOP only exposes one free input
	connector beyond those connected, and that list can lag behind, so refresh and fall back."""
	for i, s in enumerate(srcs):
		if i >= len(g.inputConnectors):
			try:
				g.cook(force=True)
			except Exception:
				pass
		if i < len(g.inputConnectors):
			s.outputConnectors[0].connect(g.inputConnectors[i])
		else:
			try:
				g.setInputs(list(g.inputs) + [s])
			except Exception:
				s.outputConnectors[0].connect(g)
	got = [o.name for o in g.inputs]
	want = [o.name for o in srcs]
	if got != want:
		print('spores: {} inputs are {} -- expected {} (wire the rest by hand)'.format(g.path, got, want))


def glsl(comp, name, shader, inputs=(), uniforms=(), w=None, h=None, fmt=None):
	g = comp.create(glslTOP, name)
	for d in list(g.docked):
		d.destroy()
	g.par.pixeldat = shader + '_frag'
	if fmt:
		g.par.format = fmt
	if w is not None:
		res(g, w, h)
	connect_inputs(g, inputs)
	try:
		g.seq.vec.numBlocks = max(len(uniforms), 1)
	except Exception:
		pass
	for i, (uname, vals) in enumerate(uniforms):
		getattr(g.par, 'vec{}name'.format(i)).val = uname
		for c, v in zip('xyzw', vals):
			set_expr(getattr(g.par, 'vec{}value{}'.format(i, c)), v)
	return g


def const(comp, name, w, h, rgba):
	c = comp.create(constantTOP, name)
	res(c, w, h)
	try_set(c, format='rgba32float', colorr=rgba[0], colorg=rgba[1], colorb=rgba[2], alpha=rgba[3])
	return c


def feedback(comp, name, init, target):
	fb = comp.create(feedbackTOP, name)
	init.outputConnectors[0].connect(fb)
	fb.par.top = target
	return fb


def place(o, x, y):
	o.nodeX, o.nodeY = x * 200, -y * 160


def add(page, kind, name, label, default, lo=None, hi=None):
	p = getattr(page, 'append' + kind)(name, label=label)[0]
	p.default = p.val = default
	if lo is not None:
		p.normMin, p.normMax = lo, hi
	return p


def add_rgb(page, name, label, rgb):
	for p, v in zip(page.appendRGB(name, label=label), rgb):
		p.default = p.val = v


def params(c):
	pg = c.appendCustomPage('Input')
	p = pg.appendMenu('Source', label='Silhouette Source')[0]
	p.menuNames, p.menuLabels = ['silhouette', 'test'], ['Silhouette wall (camera)', 'Test figure']
	p.default = p.val = 'silhouette' if op('/project1/silhouette_wall') else 'test'
	add(pg, 'Toggle', 'Testpresent', 'Test Figure Present', True)
	add(pg, 'Float', 'Guide', 'Follow Camera Image (0 = off)', 0.4, 0, 2)
	add(pg, 'Float', 'Coverthreshold', 'Someone Here Above (coverage)', 0.01, 0, 0.2)
	pg.appendPulse('Reset', label='Reset')

	pg = c.appendCustomPage('Growth')
	add(pg, 'Float', 'Spreadspeed', 'Mycelium Spread Speed', 1.8, 0.05, 8)
	add(pg, 'Float', 'Newcolonies', 'New Colonies (rate)', 2.0, 0, 10)
	add(pg, 'Float', 'Colonystart', 'New Colonies After (s present)', 6.0, 0, 120)
	p = pg.appendMenu('Seedmode', label='Starts From')[0]
	p.menuNames, p.menuLabels = ['height', 'random', 'fixed'], ['A point at Seed Height', 'A random point on the body', 'Fixed (side Seed U/V)']
	p.default = p.val = 'height'
	add(pg, 'Float', 'Seedheight', 'Seed Height (0 = feet, 1 = head)', 0.62, 0, 1)
	add(pg, 'Float', 'Radialflow', 'Grow Outward (follow each colony)', 0.6, 0, 1)
	add(pg, 'Float', 'Fade', 'Strand Fade In/Out (s)', 0.5, 0.01, 5)
	add(pg, 'Float', 'Growtime', 'Agent Ramp-In Time (s)', 20.0, 1, 300)
	add(pg, 'Float', 'Maskhold', 'Hold Silhouette Through Dropouts (s)', 1.5, 0, 10)
	add(pg, 'Float', 'Presencehold', 'Keep Growing If Tracking Lost (s)', 2.5, 0, 20)
	add(pg, 'Float', 'Withertime', 'Wither Time (s)', 5.0, 0.5, 30)
	add(pg, 'Float', 'Respawn', 'Agent Respawn Rate (/s)', 0.05, 0, 1)
	add(pg, 'Float', 'Edgebias', 'Start From Outline / Feet', 2.0, 0, 6)

	pg = c.appendCustomPage('Agents')
	add(pg, 'Float', 'Sensorangle', 'Sensor Angle (rad)', 0.45, 0, 1.6)
	add(pg, 'Float', 'Sensordist', 'Sensor Distance (px)', 8.0, 1, 40)
	add(pg, 'Float', 'Turnangle', 'Turn Angle (rad)', 0.35, 0, 1.6)
	add(pg, 'Float', 'Step', 'Step (px)', 1.0, 0.1, 4)
	add(pg, 'Float', 'Flowdir', 'Flow Direction (deg, -90 = down)', -90.0, -180, 180)
	add(pg, 'Float', 'Flow', 'Flow Strength', 0.12, 0, 0.6)
	add(pg, 'Float', 'Curl', 'Flow Meander', 1.0, 0, 4)
	add(pg, 'Float', 'Variety', 'Agent Variety (less uniform)', 0.4, 0, 1)
	add(pg, 'Float', 'Hairshare', 'Fine Hair Share', 0.5, 0, 1)
	add(pg, 'Float', 'Hairsensor', 'Hair Sensor Distance (px)', 3.0, 1, 20)
	add(pg, 'Float', 'Hairangle', 'Hair Sensor Angle (rad)', 0.7, 0, 1.6)
	add(pg, 'Float', 'Hairturn', 'Hair Turn Angle (rad)', 0.7, 0, 1.6)
	add(pg, 'Float', 'Hairstep', 'Hair Step (px)', 1.0, 0.1, 4)
	p = pg.appendMenu('Agentcount', label='Agents (per side)')[0]
	p.menuNames, p.menuLabels = ['512', '768', '1024'], ['262k (512x512)', '590k (768x768)', '1M (1024x1024)']
	p.default = p.val = '768'

	pg = c.appendCustomPage('Trail')
	add(pg, 'Float', 'Decay', 'Trail Decay (per frame)', 0.82, 0.5, 0.999)
	add(pg, 'Float', 'Diffuse', 'Trail Diffuse', 0.0, 0, 1)
	add(pg, 'Float', 'Deposit', 'Deposit', 0.01, 0, 0.2)

	pg = c.appendCustomPage('Look')
	add(pg, 'Float', 'Gain', 'Density Gain', 3.5, 0.1, 10)
	add(pg, 'Float', 'Crisp', 'Filament Crispness', 3.5, 0, 8)
	add(pg, 'Float', 'Haze', 'Warm Haze', 0.6, 0, 2)
	add(pg, 'Float', 'Sparks', 'Sparks', 1.0, 0, 3)
	add(pg, 'Float', 'Brightness', 'Brightness', 1.0, 0, 3)
	add(pg, 'Float', 'Shimmer', 'Shimmer', 1.0, 0, 3)
	add_rgb(pg, 'Thincolor', 'Thin Strands', (0.2, 0.9, 0.55))
	add_rgb(pg, 'Midcolor', 'Body', (0.7, 1.0, 0.75))
	add_rgb(pg, 'Hotcolor', 'Dense Cores', (0.98, 1.0, 0.85))
	add_rgb(pg, 'Hazecolor', 'Haze / Sparks', (1.0, 0.5, 0.12))

	pg = c.appendCustomPage('Flowers')
	add(pg, 'Float', 'Flowers', 'Flowers', 1.0, 0, 3)
	add(pg, 'Float', 'Flowerstart', 'First Flowers After (s present)', 40.0, 0, 300)
	add(pg, 'Float', 'Flowerspread', 'Flower Cycle (s): bloom, wither, rest', 40.0, 2, 300)
	add(pg, 'Float', 'Flowersize', 'Flower Size (LED px)', 8.5, 1, 30)
	add(pg, 'Float', 'Flowerdensity', 'Flower Density', 0.5, 0, 1)
	add(pg, 'Float', 'Flowergrow', 'Flower Unfurl / Fade Time (s)', 6.0, 0.5, 60)
	add(pg, 'Float', 'Flowermotes', 'Spore Motes', 1.0, 0, 3)

	pg = c.appendCustomPage('Spores')
	add(pg, 'Float', 'Sporerate', 'Spore Emission', 0.02, 0, 1)
	add(pg, 'Float', 'Sporelife', 'Spore Lifetime (s)', 6.0, 0.5, 30)
	add(pg, 'Float', 'Sporesize', 'Spore Size (LED px)', 2.5, 0.25, 10)
	add(pg, 'Float', 'Sporeout', 'Drift Outward (LED px/s)', 4.5, 0, 30)
	add(pg, 'Float', 'Sporerise', 'Rise (LED px/s)', 3.5, -10, 30)
	add(pg, 'Float', 'Sporeturb', 'Swirl (LED px/s)', 2.5, 0, 20)
	add(pg, 'Float', 'Sporemature', 'Emit From Growth Older Than (s)', 12.0, 0, 120)
	add_rgb(pg, 'Sporecolor', 'Spore Colour', (0.85, 1.0, 0.8))
	p = pg.appendMenu('Sporecount', label='Max Spores (per side)')[0]
	p.menuNames, p.menuLabels = ['128', '192', '256'], ['16k (128x128)', '37k (192x192)', '65k (256x256)']
	p.default = p.val = '128'

	pg = c.appendCustomPage('Post')
	add(pg, 'Float', 'Exposure', 'Exposure', 1.0, 0, 3)
	add(pg, 'Float', 'Bloom', 'Bloom', 0.35, 0, 2)
	add(pg, 'Float', 'Saturation', 'Saturation', 1.0, 0, 2)

	pg = c.appendCustomPage('Size')
	add(pg, 'Int', 'Ledw', 'LED Width', 160, 16, 1024)
	add(pg, 'Int', 'Ledh', 'LED Height', 320, 16, 1024)
	add(pg, 'Int', 'Trailscale', 'Trail Resolution (x LED)', 4, 1, 8)


RESET = '''
def onPulse(par):
	if par.name == 'Reset':
		for s in ('side_L', 'side_R'):
			side = par.owner.op(s)
			if side is None:
				continue
			for n in ('agents_fb', 'trail_fb', 'presence_fb', 'mask_guide_fb', 'front_fb', 'spores_fb'):
				o = side.op(n)
				if o is not None:
					o.par.resetpulse.pulse()
			side.par.Seedactive = False
	return
'''

# Picks where the mycelium starts each time someone arrives (reads a 64x128 copy of the mask).
SEEDPICKER = '''
import numpy as np

def _pick(side, comp):
	if comp.par.Seedmode.eval() == 'fixed':
		return True
	arr = side.op('seed_sample').numpyArray()            # row 0 = bottom
	if arr is None:
		return False
	m = arr[..., 0] > 0.5
	ys, xs = np.nonzero(m)
	if len(xs) < 4:
		return False
	h, w = m.shape
	u, v = (xs + 0.5) / w, (ys + 0.5) / h
	wts = np.ones(len(u))
	if comp.par.Seedmode.eval() == 'height':
		rel = (v - v.min()) / max(v.max() - v.min(), 1e-3)
		wts = np.exp(-((rel - comp.par.Seedheight.eval()) ** 2) / (2 * 0.07 ** 2))
		uc = float(np.sum(u * wts) / max(wts.sum(), 1e-9))          # middle of the body at that height
		wts = wts * np.exp(-((u - uc) ** 2) / (2 * 0.06 ** 2))
	i = np.random.choice(len(u), p=wts / wts.sum())
	side.par.Seedu, side.par.Seedv = float(u[i]), float(v[i])
	return True

def onFrameStart(frame):
	comp = me.parent()
	for s in ('side_L', 'side_R'):
		side = comp.op(s)
		if side is None:
			continue
		t = side.op('presence').sample(x=0, y=0)[0]
		if t < 0.05:
			if side.par.Seedactive.eval():
				side.par.Seedactive = False                 # next person gets a new seed
		elif not side.par.Seedactive.eval() and t > 0.3:
			if _pick(side, comp):
				side.par.Seedactive = True
	return
'''


def deposit_render(c, agents, tw, th, tw3, th3):
	"""Draw every agent as one tiny additive quad at its position (instancing from the agents TOP)."""
	geo = c.create(geometryCOMP, 'agent_points')
	for ch in list(geo.children):
		ch.destroy()
	rect = geo.create(rectangleSOP, 'pt')
	set_expr(rect.par.sizex, '1.0 / ({})'.format(tw3))        # inside the geo: spores COMP is parent(3)
	set_expr(rect.par.sizey, '1.0 / ({})'.format(th3))
	rect.render = rect.display = True
	geo.par.sy.expr = '({}) / ({})'.format(th, tw)              # uv y (0..1) -> world y (0..h/w)
	try_set(geo, instancing=True, instanceop=agents.path, instancetx='r', instancety='g',
	        instancesx='a', instancesy='a', instancesz='a')
	mat = c.create(constantMAT, 'deposit_mat')
	try_set(mat, colorr=1, colorg=0, colorb=0, blending=True, srcblend='one', destblend='one',
	        depthtest=False, depthwriting=False)
	geo.par.material.expr = "parent().op('deposit_mat')"        # explicit: COMP params resolve oddly
	cam = c.create(cameraCOMP, 'deposit_cam')
	try_set(cam, projection='ortho', orthowidth=1.0, tx=0.5, tz=5.0)
	cam.par.ty.expr = '0.5 * ({}) / ({})'.format(th, tw)
	ren = c.create(renderTOP, 'deposit')
	try_set(ren, camera=cam.name, geometry=geo.name, lights='', format='rgba32float',
	        bgcolorr=0, bgcolorg=0, bgcolorb=0, antialias='aa1')
	res(ren, tw, th)
	return geo, mat, cam, ren


def spore_render(c, spores, cam, tw, th):
	"""Draw each spore as a soft additive dot (instancing from the spores TOP), into its own layer."""
	sprite = glsl(c, 'sprite', 'sprite', w=64, h=64)
	geo = c.create(geometryCOMP, 'spore_points')
	for ch in list(geo.children):
		ch.destroy()
	rect = geo.create(rectangleSOP, 'dot')
	size = "parent(3).par.Sporesize * parent(3).par.Trailscale"
	set_expr(rect.par.sizex, '({}) / ({})'.format(size, tw.replace('parent(2)', 'parent(3)')))
	set_expr(rect.par.sizey, '({}) / ({})'.format(size, th.replace('parent(2)', 'parent(3)')))
	rect.render = rect.display = True
	geo.par.sy.expr = '({}) / ({})'.format(th, tw)
	try_set(geo, instancing=True, instanceop=spores.path, instancetx='r', instancety='g',
	        instancesx='a', instancesy='a', instancesz='a')            # size follows the fade envelope
	mat = c.create(constantMAT, 'spore_mat')
	try_set(mat, blending=True, srcblend='one', destblend='one', depthtest=False, depthwriting=False)
	mat.par.colormap.expr = "parent().op('sprite')"
	for ch, comp in zip('rgb', ('r', 'g', 'b')):
		getattr(mat.par, 'color' + ch).expr = '{}Sporecolor{}'.format(G, comp)
	geo.par.material.expr = "parent().op('spore_mat')"
	ren = c.create(renderTOP, 'spore_render')
	try_set(ren, camera=cam.name, geometry=geo.name, lights='', format='rgba16float',
	        bgcolorr=0, bgcolorg=0, bgcolorb=0, antialias='aa1')
	res(ren, tw, th)
	return geo, mat, sprite, ren


def build_side(parent_comp, tag, seed):
	c = parent_comp.create(baseCOMP, 'side_' + tag)
	pg = c.appendCustomPage('Side')
	p = pg.appendTOP('Masktop', label='Silhouette TOP')[0]
	p.val = '/project1/silhouette_wall/silhouette_hi_' + tag
	p = pg.appendTOP('Guidetop', label='Camera Image TOP (guide)')[0]
	p.val = '/project1/silhouette_wall/camera_' + tag
	for name, label, v in (('Seedu', 'Seed U (set automatically)', 0.5), ('Seedv', 'Seed V (set automatically)', 0.62)):
		q = pg.appendFloat(name, label=label)[0]
		q.default = q.val = v
	q = pg.appendToggle('Seedactive', label='Seed Placed')[0]
	q.default = q.val = False
	for n in ('presence', 'pack', 'front', 'agents', 'trail', 'particles', 'sprite', 'look', 'post', 'testfigure'):
		load_shader(c, n, os.path.join(SPORE_DIR, n + '.glsl'))
	load_shader(c, 'downsample', os.path.join(ROOT_DIR, 'shaders', 'downsample.glsl'))

	tw, th = '{0}Ledw*{0}Trailscale'.format(G), '{0}Ledh*{0}Trailscale'.format(G)
	asz = 'int({}Agentcount.eval())'.format(G)
	now, dt = 'absTime.seconds', '1.0/me.time.rate'

	# ---- inputs
	test = glsl(c, 'testfig', 'testfigure', w=tw, h=th,
	            uniforms=[('uFig', (now, G + 'Testpresent', -0.01 if tag == 'L' else 0.015, 1.0))])
	mask = c.create(selectTOP, 'mask_in')
	mask.par.top.expr = ("op('testfig') if {0}Source.eval() == 'test' "
	                     "else (parent().par.Masktop.eval() or op('testfig'))").format(G)
	guide_sel = c.create(selectTOP, 'guide_in')
	guide_sel.par.top.expr = ("op('mask_in') if ({0}Source.eval() == 'test' or {0}Guide.eval() <= 0) "
	                          "else (parent().par.Guidetop.eval() or op('mask_in'))").format(G)
	guide = c.create(monochromeTOP, 'guide')
	guide_sel.outputConnectors[0].connect(guide)

	# ---- presence timer (1x1) and seed point
	pinit = const(c, 'presence_init', 1, 1, (0, 0, 0, 1))
	pfb = feedback(c, 'presence_fb', pinit, 'presence')
	pres_x, pres_here = "op('presence').sample(x=0, y=0)[0]", "op('presence').sample(x=0, y=0)[2]"
	pres_prev = "op('presence_fb').sample(x=0, y=0)[0]"          # last frame (no cook loop)
	kinit = const(c, 'mask_guide_init', tw, th, (0, 0, 0, 1))
	kfb = feedback(c, 'mask_guide_fb', kinit, 'mask_guide')
	pack = glsl(c, 'mask_guide', 'pack', inputs=[mask, guide, kfb], w=tw, h=th, fmt='rgba16float',
	            uniforms=[('uH', (dt, G + 'Maskhold', 0, 0))])
	seed_sample = c.create(resolutionTOP, 'seed_sample')       # small copy the seed picker reads
	pack.outputConnectors[0].connect(seed_sample)
	res(seed_sample, 64, 128)

	# ---- mycelium growth front: from the seed point outward over the body
	fw, fh = 'int(({})/2)'.format(tw), 'int(({})/2)'.format(th)
	finit = const(c, 'front_init', fw, fh, (0, 0, 0, 0))
	ffb = feedback(c, 'front_fb', finit, 'front')
	front = glsl(c, 'front', 'front', inputs=[ffb, pack], w=fw, h=fh, fmt='rgba32float', uniforms=[
		('uF', (now, dt, G + 'Spreadspeed', 'parent().par.Seedactive')),
		('uF2', ('parent().par.Seedu', 'parent().par.Seedv', pres_prev, seed)),
		('uF3', (G + 'Newcolonies', G + 'Colonystart', 0, 0))])
	cover = c.create(analyzeTOP, 'coverage')                   # r = grown share, b = body share
	front.outputConnectors[0].connect(cover)
	try_set(cover, op='average')
	pres = glsl(c, 'presence', 'presence', inputs=[pfb, cover], w=1, h=1, fmt='rgba32float',
	            uniforms=[('uP', (dt, G + 'Coverthreshold', 3.0, G + 'Presencehold'))])
	grown_share = "op('coverage').sample(x=0, y=0)[0] / max(op('coverage').sample(x=0, y=0)[2], 1e-4)"

	# ---- agents + trail (feedback loops); agents live only where the front has grown
	ainit = const(c, 'agents_init', asz, asz, (0, 0, 0, 0))
	afb = feedback(c, 'agents_fb', ainit, 'agents')
	tinit = const(c, 'trail_init', tw, th, (0, 0, 0, 1))
	tfb = feedback(c, 'trail_fb', tinit, 'trail')
	agents = glsl(c, 'agents', 'agents', inputs=[afb, tfb, front], w=asz, h=asz, fmt='rgba32float',
	              uniforms=[('uS', (G + 'Sensorangle', G + 'Sensordist', G + 'Turnangle', G + 'Step')),
	                        ('uA', (now, G + 'Growtime', G + 'Respawn', dt)),
	                        ('uG', (0.5, G + 'Guide', G + 'Edgebias', seed)),
	                        ('uB', (G + 'Flowdir * 0.0174533', G + 'Flow', G + 'Curl', G + 'Hairshare')),
	                        ('uW', (G + 'Withertime', 0, 0, 0)),
	                        ('uP', (pres_x, pres_here, grown_share, 0)),
	                        ('uS2', (G + 'Hairangle', G + 'Hairsensor', G + 'Hairturn', G + 'Hairstep')),
	                        ('uSeed', (G + 'Variety', 0, G + 'Radialflow', '{0}Ledw / {0}Ledh'.format(G)))])
	try_set(agents, inputfiltertype='nearest')
	tw3, th3 = '{0}Ledw*{0}Trailscale'.format('parent(3).par.'), '{0}Ledh*{0}Trailscale'.format('parent(3).par.')
	geo, mat, cam, dep = deposit_render(c, agents, tw, th, tw3, th3)
	trail = glsl(c, 'trail', 'trail', inputs=[tfb, dep, front], w=tw, h=th, fmt='rgba32float',
	             uniforms=[('uTr', (G + 'Decay', G + 'Diffuse', G + 'Deposit', 50.0)),
	                       ('uTr2', (dt, G + 'Withertime', pres_here, now)),
	                       ('uTr3', (G + 'Fade', 0, 0, 0))])

	# ---- spores: particles rising off mature growth
	qsz = 'int({}Sporecount.eval())'.format(G)
	qinit = const(c, 'spores_init', qsz, qsz, (0, 0, -1, 0))     # b < 0 = dead
	qfb = feedback(c, 'spores_fb', qinit, 'spores')
	spores = glsl(c, 'spores', 'particles', inputs=[qfb, front], w=qsz, h=qsz, fmt='rgba32float', uniforms=[
		('uQ', (now, dt, G + 'Sporerate', G + 'Sporelife')),
		('uQ2', ('{0}Sporeout * {0}Trailscale'.format(G), '{0}Sporerise * {0}Trailscale'.format(G),
		         '{0}Sporeturb * {0}Trailscale'.format(G), G + 'Sporemature')),
		('uQ3', ('parent().par.Seedu', 'parent().par.Seedv', pres_here, th))])
	try_set(spores, inputfiltertype='nearest')
	sgeo, smat, sprite, sren = spore_render(c, spores, cam, tw, th)

	# ---- look
	bs, bl = c.create(blurTOP, 'trail_blur_small'), c.create(blurTOP, 'trail_blur_large')
	for b, sz in ((bs, 3), (bl, 18)):
		trail.outputConnectors[0].connect(b)
		try_set(b, size=sz, extend='zero')
	col = lambda n: (G + n + 'r', G + n + 'g', G + n + 'b', 1)
	look = glsl(c, 'look', 'look', inputs=[trail, bs, bl], w=tw, h=th, fmt='rgba16float', uniforms=[
		('uL', (G + 'Gain', G + 'Crisp', G + 'Haze', G + 'Sparks')),
		('uL2', (now, G + 'Brightness', G + 'Shimmer', 0)),
		('uF', (G + 'Flowers', G + 'Flowerstart', '{0}Flowersize * {0}Trailscale'.format(G), G + 'Flowerspread')),
		('uF2', (pres_x, G + 'Flowerdensity', G + 'Flowergrow', G + 'Flowermotes')),
		('cThin', col('Thincolor')), ('cMid', col('Midcolor')), ('cHot', col('Hotcolor')), ('cHaze', col('Hazecolor'))])
	with_spores = c.create(compositeTOP, 'look_spores')         # add the spore particles
	look.outputConnectors[0].connect(with_spores.inputConnectors[0])
	sren.outputConnectors[0].connect(with_spores.inputConnectors[1])
	try_set(with_spores, operand='add')
	bloom = c.create(blurTOP, 'bloom')
	with_spores.outputConnectors[0].connect(bloom)
	try_set(bloom, size=30, preshrink=1)
	post = glsl(c, 'post', 'post', inputs=[with_spores, bloom],
	            uniforms=[('uPost', (G + 'Exposure', G + 'Bloom', G + 'Saturation', 0))])
	hi = c.create(nullTOP, 'out_hi')
	post.outputConnectors[0].connect(hi)
	led = glsl(c, 'led', 'downsample', inputs=[post], w=G + 'Ledw', h=G + 'Ledh')
	out_led = c.create(nullTOP, 'out_led')
	led.outputConnectors[0].connect(out_led)
	o = c.create(outTOP, 'out1')
	out_led.outputConnectors[0].connect(o)

	for node, x, y in ((test, 0, 0), (mask, 1, 0), (guide_sel, 1, 2), (guide, 2, 2), (kinit, 2, 3), (kfb, 3, 3), (pack, 3, 2),
	                   (seed_sample, 4, 3), (finit, 3, 5), (ffb, 4, 5), (front, 5, 4), (cover, 6, 5), (pinit, 6, 7), (pfb, 7, 7),
	                   (pres, 7, 5), (ainit, 4, 0), (afb, 5, 0), (agents, 6, 1), (geo, 7, 0), (mat, 7, -1), (cam, 8, -1),
	                   (dep, 8, 1), (tinit, 7, 3), (tfb, 8, 3), (trail, 9, 2), (qinit, 7, 9), (qfb, 8, 9), (spores, 9, 8),
	                   (sgeo, 10, 9), (smat, 10, 10), (sprite, 9, 10), (sren, 11, 8), (bs, 10, 1), (bl, 10, 3), (look, 11, 2),
	                   (with_spores, 12, 4), (bloom, 13, 5), (post, 14, 4), (hi, 15, 3), (led, 15, 5), (out_led, 16, 5), (o, 17, 5)):
		place(node, x, y)
	for i, n in enumerate(('presence', 'pack', 'front', 'agents', 'trail', 'particles', 'sprite', 'look', 'post',
	                       'testfigure', 'downsample')):
		place(c.op(n + '_frag'), i, 12)
	return c


def wire_to_wall(c):
	wall = op('/project1/silhouette_wall')
	if wall is None:
		print('spores: no /project1/silhouette_wall -- use spores/side_L/out_led and side_R/out_led yourself')
		return
	for tag in ('L', 'R'):
		disp = wall.op('display_' + tag)
		if disp is None:
			continue
		sel = wall.op('spores_' + tag) or wall.create(selectTOP, 'spores_' + tag)
		sel.par.top = '{}/side_{}/out_led'.format(c.path, tag)
		sel.outputConnectors[0].connect(disp.inputConnectors[0])     # display_X input 0 = the effect
		sel.nodeX, sel.nodeY = disp.nodeX - 200, disp.nodeY + 100
	print('spores: wired into silhouette_wall display_L / display_R (input 0)')


def build():
	host = op('/project1') or root
	old = host.op(NAME)
	if old:
		old.destroy()
	c = host.create(baseCOMP, NAME)
	params(c)
	pe = c.create(parameterexecuteDAT, 'reset')
	pe.par.op.expr = 'parent()'
	try_set(pe, pars='Reset', custom=True, builtin=False, valuechange=False, onpulse=True)
	pe.text = RESET
	left = build_side(c, 'L', 3.0)
	right = build_side(c, 'R', 7.0)
	sp = c.create(executeDAT, 'seedpicker')
	sp.text = SEEDPICKER
	try_set(sp, framestart=True)
	place(sp, 1, 3)
	place(left, 0, 0)
	place(right, 0, 2)
	place(pe, 1, 1)
	wire_to_wall(c)
	print('spores: built {} (source: {})'.format(c.path, c.par.Source.eval()))
	return c


build()
