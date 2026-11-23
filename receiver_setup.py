"""
RECEIVING MacBook (the one cabled to the Absen LED controller).

Each side of the installation runs on its own MacBook and sends its LED image over NDI
('Growth Side L', 'Growth Side R', 160x320 each).  This composites both onto the 1024x768
canvas the controller crops from -- each side at its offset, 1:1 pixels -- with the panel test
pattern, and shows it in a window on the controller's display.  Self-contained: needs only
this file.

In TouchDesigner's Textport on the receiving MacBook:

    import os; exec(open(os.path.expanduser('~/code/td_silhouette/receiver_setup.py')).read())

Then on /project1/led_receiver:
  1. check that ndi_L / ndi_R found 'Growth Side L' / 'Growth Side R' (picked automatically when
     they appear; or choose them in each NDI In TOP's source menu),
  2. Panel Test Pattern on -> adjust Left / Right X/Y until the panels show the right numbers,
  3. Monitor Index = the Absen display -> Open Window.
"""

COMPOSE = '''
// Places the two sides on the canvas.  Offsets are from the TOP-LEFT of the canvas, in pixels.
// in0: left side (NDI)   in1: right side (NDI)
uniform vec4 uOffL;   // xy offset of the left side,  z enabled
uniform vec4 uOffR;   // xy offset of the right side, z enabled
uniform vec4 uSize;   // xy LED size of each side (px)  z panel size (px)  w test pattern (0/1)
layout(location = 0) out vec4 fragColor;

vec3 testPattern(ivec2 lp, ivec2 size, int side) {
	int ps = int(uSize.z);
	ivec2 pc = lp / ps;                                  // panel col / row (row 0 = top)
	ivec2 q = lp - pc * ps;
	int idx = pc.y * max(size.x / ps, 1) + pc.x;
	vec3 base = side == 0 ? vec3(0.55, 0.12, 0.05) : vec3(0.05, 0.15, 0.55);
	vec3 c = base * (((pc.x + pc.y) % 2 == 0) ? 1.0 : 0.55);
	if (q.x == 0 || q.y == 0 || q.x == ps - 1 || q.y == ps - 1) c = vec3(1.0);
	for (int k = 0; k <= idx && k < 12; k++) {         // idx+1 dots: 1 = top-left panel of that side
		ivec2 d = q - ivec2(6 + k * 9, ps / 2 - 3);
		if (d.x >= 0 && d.x < 6 && d.y >= 0 && d.y < 6) c = vec3(1.0, 1.0, 0.3);
	}
	if (lp.x < 6 && lp.y < 6) c = vec3(0.0, 1.0, 0.0);    // green = that side's top-left corner
	return c;
}

vec3 sampleSide(int s, ivec2 lp, ivec2 size) {
	ivec2 inRes = ivec2(s == 0 ? uTD2DInfos[0].res.zw : uTD2DInfos[1].res.zw);
	if (inRes == size) {                                 // the normal case: exact pixels
		ivec2 sp = ivec2(lp.x, size.y - 1 - lp.y);
		return s == 0 ? texelFetch(sTD2DInputs[0], sp, 0).rgb : texelFetch(sTD2DInputs[1], sp, 0).rgb;
	}
	vec2 uv = (vec2(lp) + 0.5) / vec2(size);             // different size (e.g. no source yet): fit
	uv.y = 1.0 - uv.y;
	return s == 0 ? texture(sTD2DInputs[0], uv).rgb : texture(sTD2DInputs[1], uv).rgb;
}

void main() {
	ivec2 res = ivec2(uTDOutputInfo.res.zw);
	ivec2 px = ivec2(gl_FragCoord.xy);
	ivec2 tl = ivec2(px.x, res.y - 1 - px.y);            // pixel from the top-left
	ivec2 size = ivec2(uSize.xy);
	vec3 col = vec3(0.0);
	for (int s = 0; s < 2; s++) {
		vec4 off = s == 0 ? uOffL : uOffR;
		if (off.z < 0.5) continue;
		ivec2 lp = tl - ivec2(off.xy + 0.5);
		if (lp.x < 0 || lp.y < 0 || lp.x >= size.x || lp.y >= size.y) continue;
		col = uSize.w > 0.5 ? testPattern(lp, size, s) : sampleSide(s, lp, size);
	}
	fragColor = TDOutputSwizzle(vec4(col, 1.0));
}
'''

PULSES = '''
def onPulse(par):
	w = par.owner.op('window')
	if par.name == 'Openwindow':
		w.par.winopen.pulse()
	elif par.name == 'Closewindow':
		w.par.winclose.pulse()
	return
'''

# Picks 'Growth Side L' / 'Growth Side R' in the NDI In TOPs as soon as they show up on the network.
AUTOPICK = '''
def _pick(ndi, want):
	if not want:
		return
	try:
		cur = ndi.par.name.eval()
		if want.lower() in str(cur).lower():
			return
		for n in ndi.par.name.menuNames:
			if want.lower() in str(n).lower():
				ndi.par.name = n
				debug('led_receiver: {} -> {}'.format(ndi.name, n))
				return
	except Exception:
		pass

def onFrameStart(frame):
	if frame % 60:
		return
	c = me.parent()
	_pick(c.op('ndi_L'), c.par.Leftsource.eval())
	_pick(c.op('ndi_R'), c.par.Rightsource.eval())
	return
'''


def _try(o, **kw):
	for k, v in kw.items():
		try:
			setattr(o.par, k, v)
		except Exception as e:
			print('led_receiver: could not set {}.{} ({})'.format(o.path, k, e))


def _connect(srcs, g):
	for i, s in enumerate(srcs):
		if i >= len(g.inputConnectors):
			try:
				g.cook(force=True)
			except Exception:
				pass
		s.outputConnectors[0].connect(g.inputConnectors[min(i, len(g.inputConnectors) - 1)])


def build_receiver():
	host = op('/project1') or root
	old = host.op('led_receiver')
	if old:
		try:
			old.op('window').par.winclose.pulse()
		except Exception:
			pass
		old.destroy()
	c = host.create(baseCOMP, 'led_receiver')
	pg = c.appendCustomPage('Panels')

	def add(kind, name, label, v):
		p = getattr(pg, 'append' + kind)(name, label=label)[0]
		p.default = p.val = v
		return p
	add('Toggle', 'Testpattern', 'Panel Test Pattern', False)
	add('Str', 'Leftsource', 'Left NDI Source (name contains)', 'Growth Side L')
	add('Toggle', 'Leftenable', 'Left Side Enabled', True)
	add('Int', 'Leftx', 'Left Side X (from top-left)', 160)
	add('Int', 'Lefty', 'Left Side Y (from top-left)', 0)
	add('Str', 'Rightsource', 'Right NDI Source (name contains)', 'Growth Side R')
	add('Toggle', 'Rightenable', 'Right Side Enabled', True)
	add('Int', 'Rightx', 'Right Side X (from top-left)', 0)
	add('Int', 'Righty', 'Right Side Y (from top-left)', 0)
	add('Int', 'Ledw', 'Side Width (px)', 160)
	add('Int', 'Ledh', 'Side Height (px)', 320)
	add('Int', 'Panelsize', 'Panel Size (px)', 80)
	add('Int', 'Canvasw', 'Canvas Width', 1024)
	add('Int', 'Canvash', 'Canvas Height', 768)
	add('Int', 'Monitor', 'Monitor Index', 1)
	pg.appendPulse('Openwindow', label='Open Window')
	pg.appendPulse('Closewindow', label='Close Window')

	ndi_l = c.create(ndiinTOP, 'ndi_L')
	ndi_r = c.create(ndiinTOP, 'ndi_R')
	frag = c.create(textDAT, 'compose_frag')
	frag.text = COMPOSE
	comp = c.create(glslTOP, 'canvas')
	for d in list(comp.docked):
		d.destroy()
	comp.par.pixeldat = frag.name
	_connect([ndi_l, ndi_r], comp)
	comp.par.outputresolution = 'custom'
	comp.par.resolutionw.expr = 'parent().par.Canvasw'
	comp.par.resolutionh.expr = 'parent().par.Canvash'
	_try(comp, format='rgba8fixed')
	uniforms = [('uOffL', ('parent().par.Leftx', 'parent().par.Lefty', 'parent().par.Leftenable', 0)),
	            ('uOffR', ('parent().par.Rightx', 'parent().par.Righty', 'parent().par.Rightenable', 0)),
	            ('uSize', ('parent().par.Ledw', 'parent().par.Ledh', 'parent().par.Panelsize', 'parent().par.Testpattern'))]
	try:
		comp.seq.vec.numBlocks = len(uniforms)
	except Exception:
		pass
	for i, (name, vals) in enumerate(uniforms):
		getattr(comp.par, 'vec{}name'.format(i)).val = name
		for ch, v in zip('xyzw', vals):
			par = getattr(comp.par, 'vec{}value{}'.format(i, ch))
			if isinstance(v, str):
				par.expr = v
			else:
				par.val = v
	out = c.create(nullTOP, 'out_canvas')
	comp.outputConnectors[0].connect(out)

	win = c.create(windowCOMP, 'window')
	_try(win, winop=out.path, borders=False, winoffsetx=0, winoffsety=0)
	win.par.monitor.expr = 'parent().par.Monitor'
	win.par.winw.expr = 'parent().par.Canvasw'
	win.par.winh.expr = 'parent().par.Canvash'
	pe = c.create(parameterexecuteDAT, 'pulses')
	pe.par.op.expr = 'parent()'
	_try(pe, pars='Openwindow Closewindow', custom=True, builtin=False, valuechange=False, onpulse=True)
	pe.text = PULSES
	ap = c.create(executeDAT, 'autopick')
	ap.text = AUTOPICK
	_try(ap, framestart=True)

	for o, x, y in ((ndi_l, 0, 0), (ndi_r, 0, 1), (frag, 1, -1), (comp, 1, 0), (out, 2, 0), (win, 3, 0),
	                (pe, 3, 1), (ap, 2, 2)):
		o.nodeX, o.nodeY = x * 200, -y * 160
	got = [o.name for o in comp.inputs]
	if got != ['ndi_L', 'ndi_R']:
		print('led_receiver: canvas inputs are {} -- wire ndi_L into input 0 and ndi_R into input 1'.format(got))
	print('led_receiver: built {}. Sources are picked when "Growth Side L/R" appear; '
	      'set Monitor Index and press Open Window.'.format(c.path))
	return c


build_receiver()
