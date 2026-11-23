"""
Connect the floor tracker to the ROOTS scene (/container1) of the burst patch.

Open the burst .toe in TouchDesigner on the show Mac, then in the Textport:

    import os; exec(open(os.path.expanduser('~/code/td_silhouette/integrate_roots.py')).read())

then File > Save As to keep the result.  What it does:

  1. Undoes the earlier burst integration (integrate_burst.py) if it was run: restores
     /project1's keyboard wiring and burst position, removes /project1/floor_tracker and the
     /container1/pointer node.  Footsteps no longer trigger anything.
  2. Builds the floor tracker inside /container1 (/container1/floor_tracker).
  3. One reveal circle per tracked person: person_mask0..4 are copies of the existing circle
     mask (circle5 -> blur7, same pulsing look) placed at each person's floor position; they
     grow in when someone arrives and shrink away when they leave.  people_mask combines them
     and replaces the mouse circle (transform4) as the mask going into comp12 / comp13.
  4. Auto calibration (projector + camera only, nothing to print or drag):
     Auto Calibrate shows a marker pattern on /container1/out2; the helper measures how the
     projector lands on the floor, sets the tracker, and an output_warp stage squares the image
     up on the floor (Projector page: Output Warp, Camera Tilt -- replaces Kantan Mapper).
  5. Links the Movie File In images to ~/Downloads/assets, relative to the .toe.

floor_tracker > Output > Drive Visuals off = the original single mouse circle.
Safe to run again.
"""
import os

ROOT_DIR = os.path.expanduser('~/code/td_silhouette')
try:
	ROOT_DIR = SILHOUETTE_DIR
except NameError:
	pass
ASSETS_DIR = os.path.expanduser('~/Downloads/assets')
NET = '/container1'
FT = NET + '/floor_tracker'
SLOTS = 5
BURST_NETS = ['/project1', '/project1/base1', '/project1/base2', '/project1/base3', '/project1/base4']


def log(*a):
	print('integrate_roots:', *a)


def try_set(o, **kw):
	for k, v in kw.items():
		try:
			setattr(o.par, k, v)
		except Exception as e:
			log('could not set {}.{} ({})'.format(o.path, k, e))


def replace_in_exprs(net, old, new):
	n = 0
	for o in net.children:
		for p in o.pars():
			try:
				e = p.expr
			except Exception:
				continue
			if e and old in e:
				p.expr = e.replace(old, new)
				n += 1
	return n


def destroy(o):
	if o is not None:
		cb = o.parent().op(o.name + '_callbacks')
		o.destroy()
		if cb is not None:
			cb.destroy()


# ----------------------------------------------------------------------------- 1. undo burst wiring
def undo_burst_integration():
	for path in BURST_NETS:
		net = op(path)
		if net is None:
			continue
		kos, kb = net.op('key_or_step'), net.op('keyboardin1')
		if kos is None or kb is None:
			continue
		for conn in list(kos.outputConnectors[0].connections):
			kb.outputConnectors[0].connect(conn)
		replace_in_exprs(net, "op('key_or_step')", "op('keyboardin1')")
		destroy(kos)
		log('restored', path, 'keyboard wiring')
	t3 = op('/project1/transform3')
	if t3 is not None:
		for par, orig in ((t3.par.tx, "op('switch1')['resX']"), (t3.par.ty, "op('switch1')['resY']")):
			if 'step_trigger' in (par.expr or ''):
				par.expr = orig
				log('restored /project1/transform3', par.name)
	destroy(op('/project1/integrate_cook'))
	old_ft = op('/project1/floor_tracker')
	if old_ft is not None:
		try:
			old_ft.op('pulses').module.stop_helper(old_ft)
		except Exception:
			pass
		old_ft.destroy()
		log('removed /project1/floor_tracker')
	net = op(NET)
	if net is not None and net.op('pointer') is not None:
		replace_in_exprs(net, "op('pointer')", "op('mousein1')")
		destroy(net.op('pointer'))
		log('orb is back on the mouse (pointer removed)')


# ----------------------------------------------------------------------------- 2. tracker
def build_tracker():
	ft = op(FT)
	if ft is None:
		log('building', FT, '...')
		g = dict(globals())
		g['FLOOR_TRACKER_PARENT'] = NET
		exec(open(os.path.join(ROOT_DIR, 'build_floor_tracker.py')).read(), g)
		ft = op(FT)
	pg = next((p for p in ft.customPages if p.name == 'Output'), None) or ft.appendCustomPage('Output')
	if not hasattr(ft.par, 'Drivevisuals'):
		p = pg.appendToggle('Drivevisuals', label='Drive Visuals (off = mouse circle)')[0]
		p.default = p.val = True
	if not hasattr(ft.par, 'Circlefadein'):
		p = pg.appendFloat('Circlefadein', label='Circle Grow In (s)')[0]
		p.default = p.val = 0.6
		p = pg.appendFloat('Circlefadeout', label='Circle Shrink Out (s)')[0]
		p.default = p.val = 1.2
	ft.nodeX, ft.nodeY = op(NET).op('mousein1').nodeX, op(NET).op('mousein1').nodeY - 300
	return ft


# ----------------------------------------------------------------------------- 3. circles
def person_masks():
	net = op(NET)
	src, t4 = net.op('blur7'), net.op('transform4')
	if src is None or t4 is None:
		log('skip masks: {}/blur7 or transform4 not found'.format(NET))
		return
	x0, y0 = t4.nodeX, t4.nodeY - 200

	sel = net.op('people_active') or net.create(selectCHOP, 'people_active')
	sel.par.chops = 'floor_tracker/people'
	try_set(sel, channames='p*_active')
	fade = net.op('people_fade') or net.create(lagCHOP, 'people_fade')
	if not fade.inputs:
		sel.outputConnectors[0].connect(fade)
	try:
		fade.par.lag1.expr = "op('floor_tracker').par.Circlefadein"
		fade.par.lag2.expr = "op('floor_tracker').par.Circlefadeout"
	except Exception as e:
		log('could not set people_fade lag times ({})'.format(e))
	sel.nodeX, sel.nodeY = x0 - 400, y0
	fade.nodeX, fade.nodeY = x0 - 200, y0

	masks = []
	for i in range(SLOTS):
		t = net.op('person_mask{}'.format(i)) or net.create(transformTOP, 'person_mask{}'.format(i))
		if not t.inputs:
			src.outputConnectors[0].connect(t)
		ch = "op('floor_tracker/people')['p{}_{{}}']".format(i)
		t.par.tx.expr = ch.format('u') + ' - 0.5'          # floor u,v (0..1) -> Transform offset
		t.par.ty.expr = ch.format('v') + ' - 0.5'
		# fade in/out x per-person scale, so the circle covers the same floor area everywhere
		size = "op('people_fade')['p{0}_active'] * op('floor_tracker/people')['p{0}_scale']".format(i)
		t.par.sx.expr = size
		t.par.sy.expr = size
		t.nodeX, t.nodeY = x0, y0 - 130 * i
		masks.append(t)

	comb = net.op('people_mask') or net.create(compositeTOP, 'people_mask')
	if len(comb.inputs) < SLOTS:
		for i, t in enumerate(masks):
			t.outputConnectors[0].connect(comb.inputConnectors[i])
	try:
		comb.par.operand = 'maximum'          # overlapping circles don't over-brighten
	except Exception:
		comb.par.operand = 'add'
	comb.nodeX, comb.nodeY = x0 + 200, y0 - 260

	sw = net.op('mask_select')
	if sw is None:
		sw = net.create(switchTOP, 'mask_select')
		consumers = [c for c in t4.outputConnectors[0].connections]
		t4.outputConnectors[0].connect(sw.inputConnectors[0])
		comb.outputConnectors[0].connect(sw.inputConnectors[1])
		for conn in consumers:
			sw.outputConnectors[0].connect(conn)       # comp12 / comp13 now get the switch
		log('mask now feeds', [c.owner.name for c in consumers])
	sw.par.index.expr = "1 if op('floor_tracker').par.Drivevisuals else 0"
	sw.nodeX, sw.nodeY = t4.nodeX + 200, t4.nodeY - 100
	log('{} person circles -> people_mask -> mask_select (replaces the mouse circle)'.format(SLOTS))


# ----------------------------------------------------------------------------- 4. auto calibration
def auto_calibration_output():
	"""While Auto Calibrate runs, container1's output (out2) shows the marker pattern, so it goes
	through Kantan Mapper / the projector exactly like the roots visuals do."""
	net, ft = op(NET), op(FT)
	exec(open(os.path.join(ROOT_DIR, 'autocal.py')).read(), globals())
	add_autocalibration(ft)
	const = net.op('constant1')
	if const is not None:                    # pattern = the roots output resolution
		# parent() = /container1 (a relative '../' path does not resolve from a COMP's own parameter)
		ft.par.Patternw.expr = "int(parent().op('constant1')['resX'])"
		ft.par.Patternh.expr = "int(parent().op('constant1')['resY'])"
	out = net.op('out2')
	if out is None or not out.inputs:
		log('no {}/out2 -- route floor_tracker/calib_markers into your output yourself while calibrating'.format(NET))
		return
	sw = net.op('calib_override')
	if sw is None:
		src = out.inputs[0]
		sw = net.create(switchTOP, 'calib_override')
		src.outputConnectors[0].connect(sw.inputConnectors[0])
		sel = net.create(selectTOP, 'calib_markers_in')
		sel.par.top = 'floor_tracker/calib_markers'
		sel.outputConnectors[0].connect(sw.inputConnectors[1])
		sw.outputConnectors[0].connect(out.inputConnectors[0])
		sw.nodeX, sw.nodeY = out.nodeX - 150, out.nodeY - 120
		sel.nodeX, sel.nodeY = out.nodeX - 350, out.nodeY - 240
		log('{}/out2 shows the markers while calibrating (calib_override)'.format(NET))
	sw.par.index.expr = "1 if op('floor_tracker').par.Calibrating else 0"
	output_warp(net, ft, out, sw)
	try:
		ft.op('pulses').module.make_markers(ft)
	except Exception as e:
		log('marker pattern not generated yet ({})'.format(e))


def output_warp(net, ft, out, src):
	"""output_warp: pre-distorts the roots image so it lands square on the floor (replaces Kantan
	Mapper).  Bypassed while calibrating so the markers measure the raw projector."""
	if net.op('output_warp') is None:
		dat = net.create(textDAT, 'output_warp_frag')
		dat.text = open(os.path.join(ROOT_DIR, 'shaders', 'warp.glsl')).read()
		g = net.create(glslTOP, 'output_warp')
		for d in list(g.docked):
			d.destroy()
		g.par.pixeldat = 'output_warp_frag'
		src.outputConnectors[0].connect(g.inputConnectors[0])
		sel = net.create(switchTOP, 'warp_select')
		src.outputConnectors[0].connect(sel.inputConnectors[0])
		g.outputConnectors[0].connect(sel.inputConnectors[1])
		sel.outputConnectors[0].connect(out.inputConnectors[0])
		g.nodeX, g.nodeY = out.nodeX - 150, out.nodeY - 240
		sel.nodeX, sel.nodeY = out.nodeX - 75, out.nodeY - 120
		dat.nodeX, dat.nodeY = out.nodeX - 300, out.nodeY - 360
		log('output_warp added before {} (Auto output warp replaces Kantan Mapper)'.format(out.path))
	g, sel = net.op('output_warp'), net.op('warp_select')
	try:
		g.par.outputresolution = 'custom'
		g.par.resolutionw.expr = "int(op('floor_tracker').par.Patternw)"
		g.par.resolutionh.expr = "int(op('floor_tracker').par.Patternh)"
	except Exception as e:
		log('could not set output_warp resolution ({})'.format(e))
	P = "op('floor_tracker').par.Projcorner"
	uniforms = [('uC0', (P + 'blx', P + 'bly', P + 'brx', P + 'bry')),
	            ('uC1', (P + 'trx', P + 'try', P + 'tlx', P + 'tly')),
	            ('uOpt', (0, 0, -1, 0))]
	try:
		g.seq.vec.numBlocks = len(uniforms)
	except Exception:
		pass
	for i, (name, vals) in enumerate(uniforms):
		getattr(g.par, 'vec{}name'.format(i)).val = name
		for c, v in zip('xyzw', vals):
			par = getattr(g.par, 'vec{}value{}'.format(i, c))
			if isinstance(v, str):
				par.expr = v
			else:
				par.val = v
	sel.par.index.expr = "1 if (op('floor_tracker').par.Warpmode == 'auto' and not op('floor_tracker').par.Calibrating) else 0"


# ----------------------------------------------------------------------------- 5. assets
def link_assets():
	have = set(os.listdir(ASSETS_DIR)) if os.path.isdir(ASSETS_DIR) else set()
	if not have:
		log('assets folder not found:', ASSETS_DIR)
		return
	linked = 0
	for m in root.findChildren(type=moviefileinTOP):
		p = m.par.file
		src = p.val or ''
		name = src.replace('\\', '/').split('/')[-1]
		if name in have:
			p.mode = ParMode.CONSTANT
			p.val = os.path.relpath(os.path.join(ASSETS_DIR, name), project.folder).replace(os.sep, '/')
			linked += 1
	log('linked {} images to {} (relative to the .toe)'.format(linked, ASSETS_DIR))


undo_burst_integration()
build_tracker()
person_masks()
auto_calibration_output()
link_assets()
log('done. Press', FT, '> Floor > Auto Calibrate (camera must see the projected floor).')
