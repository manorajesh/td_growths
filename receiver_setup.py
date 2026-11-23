"""
RECEIVING Mac (the one cabled to the Absen controller).

The sending Mac's NDI stream is only the LED area (e.g. 320x320).  This puts it back, pixel for
pixel, in the top-left corner of a black 1024x768 canvas and shows that full-screen-style on the
controller's display.  Self-contained: needs only this file.

In TouchDesigner's Textport on the receiving Mac:

    import os; exec(open(os.path.expanduser('~/code/td_silhouette/receiver_setup.py')).read())

(or paste this whole file into a Text DAT and run it).  Then in /project1/led_receiver:
  1. ndi_in > pick the sending Mac's 'Silhouette Wall' source,
  2. set Monitor Index to the Absen display and press Open Window.
"""

W, H = 1024, 768

PLACE = '''
// places the input at the TOP-LEFT of the output at 1:1 pixels; everything else black
layout(location = 0) out vec4 fragColor;
void main() {
	ivec2 o = ivec2(gl_FragCoord.xy);                   // origin bottom-left
	ivec2 outRes = ivec2(uTDOutputInfo.res.zw);
	ivec2 inRes = ivec2(uTD2DInfos[0].res.zw);
	int yTop = outRes.y - 1 - o.y;                      // row counted from the top
	vec4 c = vec4(0.0, 0.0, 0.0, 1.0);
	if (o.x < inRes.x && yTop < inRes.y)
		c = vec4(texelFetch(sTD2DInputs[0], ivec2(o.x, inRes.y - 1 - yTop), 0).rgb, 1.0);
	fragColor = TDOutputSwizzle(c);
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


def _try(o, **kw):
	for k, v in kw.items():
		try:
			setattr(o.par, k, v)
		except Exception as e:
			print('led_receiver: could not set {}.{} ({})'.format(o.path, k, e))


def build_receiver():
	host = op('/project1') or root
	old = host.op('led_receiver')
	if old:
		old.destroy()
	c = host.create(baseCOMP, 'led_receiver')
	pg = c.appendCustomPage('Output')
	for name, label, v in (('Canvasw', 'Canvas Width', W), ('Canvash', 'Canvas Height', H), ('Monitor', 'Monitor Index', 1)):
		p = pg.appendInt(name, label=label)[0]
		p.default = p.val = v
	pg.appendPulse('Openwindow', label='Open Window')
	pg.appendPulse('Closewindow', label='Close Window')

	ndi = c.create(ndiinTOP, 'ndi_in')
	frag = c.create(textDAT, 'place_frag')
	frag.text = PLACE
	place = c.create(glslTOP, 'canvas')
	for d in list(place.docked):
		d.destroy()
	place.par.pixeldat = frag.name
	ndi.outputConnectors[0].connect(place.inputConnectors[0])
	place.par.outputresolution = 'custom'
	place.par.resolutionw.expr = 'parent().par.Canvasw'
	place.par.resolutionh.expr = 'parent().par.Canvash'
	_try(place, format='rgba8fixed')
	out = c.create(nullTOP, 'out_canvas')
	place.outputConnectors[0].connect(out)

	win = c.create(windowCOMP, 'window')
	_try(win, winop=out.path, borders=False, winoffsetx=0, winoffsety=0)
	win.par.monitor.expr = 'parent().par.Monitor'
	win.par.winw.expr = 'parent().par.Canvasw'
	win.par.winh.expr = 'parent().par.Canvash'
	pe = c.create(parameterexecuteDAT, 'pulses')
	pe.par.op.expr = 'parent()'
	_try(pe, pars='Openwindow Closewindow', custom=True, builtin=False, valuechange=False, onpulse=True)
	pe.text = PULSES

	for o, x, y in ((ndi, 0, 0), (frag, 1, -1), (place, 1, 0), (out, 2, 0), (win, 3, 0), (pe, 3, 1)):
		o.nodeX, o.nodeY = x * 200, -y * 160
	print('led_receiver: built {}.  Pick the NDI source in ndi_in, set Monitor Index, press Open Window.'.format(c.path))
	return c


build_receiver()
