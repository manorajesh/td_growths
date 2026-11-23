"""
Toggle the spores displays with a key press -- locally, or from another TouchDesigner over the
network (Touch In CHOP).  Each press flips spores > Enable > Enabled (same switch as the OSC one,
with the same smooth fade).  Update script: keeps your settings; safe to run again.

On each side's MacBook (needs the Enable page -- run add_spores_switch.py first if missing):

    import os; exec(open(os.path.expanduser('~/code/td_silhouette/add_spores_keytoggle.py')).read())

Adds to spores > Enable:
  Local Key           a key on THIS machine that toggles (default 'e'; empty = off).  Works while
                      TouchDesigner is the focused app (e.g. in Perform Mode).
  Touch In            on/off, plus the sending machine's address and port.  Any channel of the
                      incoming CHOP going from 0 to 1 toggles.

On the CONTROLLER machine (the one whose key presses should switch the sides):
  Keyboard In CHOP (Keys: e)  ->  Touch Out CHOP (Port: 9000)
then on each side set Touch In Address to the controller's IP and Touch In Port to 9000.
"""


def add_spores_keytoggle(sp):
	def try_set(o, **kw):
		for k, v in kw.items():
			try:
				setattr(o.par, k, v)
			except Exception as e:
				print('spores key toggle: could not set {}.{} ({})'.format(o.path, k, e))

	if not hasattr(sp.par, 'Enabled'):
		raise SystemExit('spores has no Enable page yet -- run add_spores_switch.py first')
	pg = sp.par.Enabled.page
	if not hasattr(sp.par, 'Localkey'):
		p = pg.appendStr('Localkey', label='Local Key (toggles; empty = off)')[0]
		p.default = p.val = 'e'
		p = pg.appendToggle('Touchin', label='Touch In (key from another machine)')[0]
		p.default = p.val = False
		p = pg.appendStr('Touchinaddress', label='Touch In Address (sender IP)')[0]
		p.default = p.val = '127.0.0.1'
		p = pg.appendInt('Touchinport', label='Touch In Port')[0]
		p.default = p.val = 9000

	for n in ('key_in', 'touch_in', 'key_toggle', 'touch_toggle', 'toggle_callbacks'):
		if sp.op(n) is not None:
			sp.op(n).destroy()
	cb = sp.create(textDAT, 'toggle_callbacks')
	cb.text = TOGGLE

	key = sp.create(keyboardinCHOP, 'key_in')
	key.par.keys.expr = 'parent().par.Localkey'
	key.par.active.expr = "bool(parent().par.Localkey.eval().strip())"

	touch = sp.create(touchinCHOP, 'touch_in')
	touch.par.active.expr = 'parent().par.Touchin'
	for pname, expr in (('address', 'parent().par.Touchinaddress'), ('port', 'parent().par.Touchinport')):
		try:
			getattr(touch.par, pname).expr = expr
		except Exception as e:
			print('spores key toggle: could not set touch_in.{} ({})'.format(pname, e))

	for name, chop in (('key_toggle', key), ('touch_toggle', touch)):
		ex = sp.create(chopexecuteDAT, name)
		ex.par.chop = chop.name
		try_set(ex, channel='*', offtoon=True, ontooff=False, whileon=False, whileoff=False, valuechange=False)
		ex.text = cb.text

	for o, x, y in ((key, 4, 4), (touch, 4, 5), (sp.op('key_toggle'), 5, 4), (sp.op('touch_toggle'), 5, 5), (cb, 5, 6)):
		o.nodeX, o.nodeY = x * 200, -y * 160
	print('spores key toggle: local key "{}", Touch In {} ({}:{})'.format(
		sp.par.Localkey.eval(), 'on' if sp.par.Touchin.eval() else 'off',
		sp.par.Touchinaddress.eval(), sp.par.Touchinport.eval()))


TOGGLE = '''
# a channel going 0 -> 1 (key down) flips spores > Enabled
def onOffToOn(channel, sampleIndex, val, prev):
	c = me.parent()
	c.par.Enabled = not c.par.Enabled.eval()
	debug('spores: Enabled ->', c.par.Enabled.eval(), '(from', channel.owner.name + ')')
	return
'''


if __name__ != 'spores_build':
	_sp = (op('/project1') or root).op('spores')
	if _sp is None:
		print('spores not found -- build it first')
	else:
		add_spores_keytoggle(_sp)
