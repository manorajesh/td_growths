"""
Build ONE side of the installation on this MacBook (each side has its own MacBook + camera).

In TouchDesigner's Textport on the LEFT side's MacBook:

    SIDE = 'L'; import os; exec(open(os.path.expanduser('~/code/td_silhouette/build_side.py')).read())

and on the RIGHT side's MacBook:

    SIDE = 'R'; import os; exec(open(os.path.expanduser('~/code/td_silhouette/build_side.py')).read())

Builds, for that side only:
  /project1/silhouette_wall   camera -> segmentation -> perspective warp -> silhouette, plus
                              ndi_out: that side's LED image (160x320) as NDI source
                              'Growth Side L' / 'Growth Side R'
  /project1/spores            the mycelium growth (with the OSC on/off switch), shown on that side

The receiving MacBook (cabled to the LED controller) composites both sources onto the panels:
run receiver_setup.py there.  Rebuilding resets that side's settings (use update_patch.py to
update an existing build instead).
"""
import os

_side = str(globals().get('SIDE', '')).upper()[:1]
if _side not in ('L', 'R'):
	raise SystemExit("build_side: set SIDE first, e.g.  SIDE = 'L'; exec(open(...build_side.py).read())")

_root = os.path.expanduser('~/code/td_silhouette')
try:
	_root = SILHOUETTE_DIR
except NameError:
	pass

SIDES = (_side,)
try:
	exec(open(os.path.join(_root, 'build_silhouette.py')).read(), globals())
	exec(open(os.path.join(_root, 'build_spores.py')).read(), globals())
finally:
	del SIDES                      # don't leave single-side mode on for later full builds
print('build_side: side {} built. NDI source "Growth Side {}" -> run receiver_setup.py on the LED MacBook.'.format(
	_side, _side))
