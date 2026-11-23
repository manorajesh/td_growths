"""
NDI output for /project1/silhouette_wall -- sends only the part of the canvas the LEDs use.

The LED controller only shows the top-left of the 1024x768 canvas (both 2x4 panel sides =
320x320 by default), so ndi_out sends just that region (~7.7x less data than the full canvas).
Its size follows the wall's side offsets and LED size.  On the receiving Mac, run
receiver_setup.py to place it back in the top-left of a 1024x768 output.

Run in the Textport on the SENDING Mac (keeps calibration; safe to run again):

    import os; exec(open(os.path.expanduser('~/code/td_silhouette/add_ndi.py')).read())

build_silhouette.py uses the same add_ndi() for new builds.
"""
import os

try:
	_NDI_ROOT = SILHOUETTE_DIR
except NameError:
	_NDI_ROOT = os.path.expanduser('~/code/td_silhouette')


def add_ndi(wall):
	def try_set(o, **kw):
		for k, v in kw.items():
			try:
				setattr(o.par, k, v)
			except Exception as e:
				print('silhouette_wall: could not set {}.{} ({})'.format(o.path, k, e))

	pg = next((p for p in wall.customPages if p.name == 'Output'), None) or wall.appendCustomPage('Output')
	if not hasattr(wall.par, 'Ndienable'):
		p = pg.appendToggle('Ndienable', label='NDI Output')[0]
		p.default = p.val = True
	if not hasattr(wall.par, 'Ndiname'):
		p = pg.appendStr('Ndiname', label='NDI Source Name')[0]
		p.default = p.val = 'Silhouette Wall'
	if not hasattr(wall.par, 'Ndicrop'):
		p = pg.appendToggle('Ndicrop', label='NDI: Send Only The LED Area')[0]
		p.default = p.val = True

	out = wall.op('out_canvas')
	for n in ('ndi_out', 'ndi_crop', 'ndi_crop_frag', 'ndi_select'):
		if wall.op(n) is not None:
			wall.op(n).destroy()

	# the used region: from the top-left to the far edge of whichever side reaches furthest
	frag = wall.create(textDAT, 'ndi_crop_frag')
	frag.text = open(os.path.join(_NDI_ROOT, 'shaders', 'crop_topleft.glsl')).read()
	crop = wall.create(glslTOP, 'ndi_crop')
	for d in list(crop.docked):
		d.destroy()
	crop.par.pixeldat = frag.name
	out.outputConnectors[0].connect(crop.inputConnectors[0])
	crop.par.outputresolution = 'custom'
	crop.par.resolutionw.expr = ("int(max(parent().par.Leftx + op('side_L').par.Ledw, "
	                             "parent().par.Rightx + op('side_R').par.Ledw))")
	crop.par.resolutionh.expr = ("int(max(parent().par.Lefty + op('side_L').par.Ledh, "
	                             "parent().par.Righty + op('side_R').par.Ledh))")
	try_set(crop, format='rgba8fixed')

	sel = wall.create(switchTOP, 'ndi_select')
	out.outputConnectors[0].connect(sel.inputConnectors[0])
	crop.outputConnectors[0].connect(sel.inputConnectors[1])
	sel.par.index.expr = 'int(parent().par.Ndicrop)'

	ndi = wall.create(ndioutTOP, 'ndi_out')
	sel.outputConnectors[0].connect(ndi)
	ndi.par.active.expr = 'parent().par.Ndienable'
	try:
		ndi.par.name.expr = 'parent().par.Ndiname'
	except Exception as e:
		print('silhouette_wall: could not set ndi_out.name ({})'.format(e))
	try_set(ndi, includealpha=False)

	frag.nodeX, frag.nodeY = out.nodeX, out.nodeY - 480
	crop.nodeX, crop.nodeY = out.nodeX + 150, out.nodeY - 320
	sel.nodeX, sel.nodeY = out.nodeX + 300, out.nodeY - 200
	ndi.nodeX, ndi.nodeY = out.nodeX + 450, out.nodeY - 200
	print('silhouette_wall: NDI "{}" sends {} ({}x{}) -- run receiver_setup.py on the receiving Mac'.format(
		wall.par.Ndiname.eval(), 'the LED area only' if wall.par.Ndicrop.eval() else 'the full canvas',
		crop.par.resolutionw.eval(), crop.par.resolutionh.eval()))
	return ndi


if __name__ != 'silhouette_build':
	_wall = (op('/project1') or root).op('silhouette_wall')
	if _wall is None:
		print('silhouette_wall not found -- run build_silhouette.py first')
	else:
		add_ndi(_wall)
