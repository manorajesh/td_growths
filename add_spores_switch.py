"""
On/off switch for the spores (mycelium) displays, driven by OSC.  Update script: run it in the
.toe that has /project1/spores -- your settings are kept (safe to run again).

    import os; exec(open(os.path.expanduser('~/code/td_silhouette/add_spores_switch.py')).read())

Adds to /project1/spores (new 'Enable' page):
  Enabled           the switch.  On: growth starts fresh on whoever is there and the output fades
                    up.  Off: the silhouette is ignored so the mold withers, and the output fades
                    to black (Fade Time).
  OSC Port          OSC In listens here (UDP, default 7000).
  OSC Address       default /growth/enable
  OSC Mode          how messages at that address act:
     auto     a pulse (short 1 then 0, or a message with no value) turns it ON and it stays on;
              a value held at 1 keeps it on, and going back to 0 after being held turns it off
     follow   on while the last value is > 0
     toggle   every pulse / rising edge flips it
     on       any message turns it on (use <address>/off to turn it off)
  Pulse Length      'auto': a 1 shorter than this counts as a pulse (s)
  Always available: <address>/on, <address>/off, <address>/toggle

Test from Terminal:  helper/.venv/bin/python helper/osc_send.py /growth/enable 1
"""


def add_spores_switch(sp):
	def try_set(o, **kw):
		for k, v in kw.items():
			try:
				setattr(o.par, k, v)
			except Exception as e:
				print('spores switch: could not set {}.{} ({})'.format(o.path, k, e))

	# ---- parameters
	if not hasattr(sp.par, 'Enabled'):
		pg = sp.appendCustomPage('Enable')
		p = pg.appendToggle('Enabled', label='Enabled (displays on)')[0]
		p.default = p.val = True
		p = pg.appendFloat('Fadetime', label='Fade Time (s)')[0]
		p.default = p.val = 2.0
		p.normMin, p.normMax = 0, 10
		p = pg.appendInt('Oscport', label='OSC Port')[0]
		p.default = p.val = 7000
		p = pg.appendStr('Oscaddress', label='OSC Address')[0]
		p.default = p.val = '/growth/enable'
		p = pg.appendMenu('Oscmode', label='OSC Mode')[0]
		p.menuNames = ['auto', 'follow', 'toggle', 'on']
		p.menuLabels = ['Pulse or hold turns on', 'Follow the value', 'Each pulse toggles', 'Any message turns on']
		p.default = p.val = 'auto'
		p = pg.appendFloat('Pulseseconds', label='Pulse Length (s)')[0]
		p.default = p.val = 0.5
		p.normMin, p.normMax = 0.05, 3

	# ---- OSC In + callbacks
	for n in ('osc_enable', 'osc_enable_callbacks', 'enable_state', 'enable_fade'):
		if sp.op(n) is not None:
			sp.op(n).destroy()
	cb = sp.create(textDAT, 'osc_enable_callbacks')
	cb.text = OSC_CALLBACKS
	osc = sp.create(oscinDAT, 'osc_enable')
	osc.par.port.expr = 'parent().par.Oscport'
	try_set(osc, callbacks=cb.name, active=True)

	# ---- smooth master fade (0..1) from the switch
	state = sp.create(constantCHOP, 'enable_state')
	try_set(state, const0name='on')
	state.par.const0value.expr = '1 if parent().par.Enabled else 0'
	fade = sp.create(lagCHOP, 'enable_fade')
	state.outputConnectors[0].connect(fade)
	try:
		fade.par.lag1.expr = 'parent().par.Fadetime'
		fade.par.lag2.expr = 'parent().par.Fadetime'
	except Exception as e:
		print('spores switch: could not set enable_fade lag ({})'.format(e))
	for o, x, y in ((cb, 2, 4), (osc, 3, 4), (state, 2, 5), (fade, 3, 5)):
		o.nodeX, o.nodeY = x * 200, -y * 160

	# ---- per side: gate the silhouette, fade the output
	for tag in ('L', 'R'):
		side = sp.op('side_' + tag)
		if side is None:
			continue
		mask, pack, post = side.op('mask_in'), side.op('mask_guide'), side.op('post')
		if side.op('mask_gate') is None and mask is not None and pack is not None:
			gate = side.create(levelTOP, 'mask_gate')                    # off = nobody here -> withers
			mask.outputConnectors[0].connect(gate)
			gate.outputConnectors[0].connect(pack.inputConnectors[0])
			gate.nodeX, gate.nodeY = mask.nodeX + 100, mask.nodeY - 120
		if side.op('mask_gate') is not None:
			side.op('mask_gate').par.brightness1.expr = '1 if parent(2).par.Enabled else 0'
		if side.op('master') is None and post is not None:
			consumers = [c for c in post.outputConnectors[0].connections]
			master = side.create(levelTOP, 'master')                     # fades the whole output
			post.outputConnectors[0].connect(master)
			for conn in consumers:
				master.outputConnectors[0].connect(conn)
			master.nodeX, master.nodeY = post.nodeX + 100, post.nodeY - 120
		if side.op('master') is not None:
			side.op('master').par.brightness1.expr = "parent(2).op('enable_fade')['on']"
	print('spores switch: OSC {} on port {} (mode: {}); Enabled = {}'.format(
		sp.par.Oscaddress.eval(), sp.par.Oscport.eval(), sp.par.Oscmode.eval(), sp.par.Enabled.eval()))


OSC_CALLBACKS = '''
# OSC -> spores Enabled.  See add_spores_switch.py for the modes.
_st = {'last': 0.0, 'high_since': None}

def _set(on):
	parent().par.Enabled = bool(on)

def handle(address, args, now):
	c = parent()
	base = c.par.Oscaddress.eval().rstrip('/')
	if address == base + '/on':
		_set(True)
		return
	if address == base + '/off':
		_set(False)
		return
	if address == base + '/toggle':
		_set(not c.par.Enabled.eval())
		return
	if address != base:
		return
	bang = len(args) == 0
	try:
		v = 1.0 if bang else float(args[0])
	except (TypeError, ValueError):
		v = 1.0
	mode = c.par.Oscmode.eval()
	rising = v > 0 and (bang or _st['last'] <= 0)
	if mode == 'follow':
		_set(v > 0)
	elif mode == 'toggle':
		if rising:
			_set(not c.par.Enabled.eval())
	elif mode == 'on':
		_set(True)
	else:                                                   # auto: pulse latches on, hold follows
		if rising:
			_set(True)
			_st['high_since'] = None if bang else now
		elif v <= 0 and _st['high_since'] is not None:
			if now - _st['high_since'] >= c.par.Pulseseconds.eval():
				_set(False)                                 # it was held, not pulsed
			_st['high_since'] = None
	_st['last'] = 0.0 if bang else v

def onReceiveOSC(dat, rowIndex, message, byteData, timeStamp, address, args, peer=None, *rest):
	handle(address, list(args or []), absTime.seconds)
	return
'''


if __name__ != 'spores_build':
	_sp = (op('/project1') or root).op('spores')
	if _sp is None:
		print('spores not found -- run build_spores.py first')
	else:
		add_spores_switch(_sp)
