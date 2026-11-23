"""
Refresh the camera menus (after plugging in a camera) without rebuilding.  In the Textport:

    import os; exec(open(os.path.expanduser('~/code/td_silhouette/refresh_cameras.py')).read())

Updates floor_tracker > Camera and silhouette_wall/side_L, side_R > Vision Camera, keeping the
current selections.  Newer builds also have a "Refresh Cameras" button that does the same.
"""
import os
import subprocess

_ROOT = os.path.expanduser('~/code/td_silhouette')
try:
	_ROOT = SILHOUETTE_DIR
except NameError:
	pass


def refresh_cameras(root=_ROOT):
	py = os.path.join(root, 'helper', '.venv', 'bin', 'python')
	out = subprocess.run([py, '-I', os.path.join(root, 'helper', 'vision_segment.py'), '--list'],
	                     capture_output=True, text=True, timeout=30).stdout
	cams = [tuple(ln.split('\t')[1:3]) for ln in out.splitlines() if ln.count('\t') == 2]
	if not cams:
		print('refresh_cameras: no cameras found (helper output: {!r})'.format(out))
		return cams
	host = op('/project1') or root_op()
	targets = [('/project1/floor_tracker', 'Camera'), ('/container1/floor_tracker', 'Camera'),
	           ('/project1/silhouette_wall/side_L', 'Visioncamera'), ('/project1/silhouette_wall/side_R', 'Visioncamera')]
	for path, pname in targets:
		c = op(path)
		if c is None or not hasattr(c.par, pname):
			continue
		p = getattr(c.par, pname)
		current = p.eval()
		p.menuNames = [u for u, n in cams] + (['phone'] if 'phone' in list(p.menuNames) else [])
		p.menuLabels = [n for u, n in cams] + (['Phone (VDO.Ninja URL)'] if 'phone' in list(p.menuNames) else [])
		if current in p.menuNames:
			p.val = current            # keep the selection (no helper restart)
		print('refresh_cameras: {}.{} -> {}'.format(c.path, pname, [n for u, n in cams]))
	return cams


def root_op():
	return op('/')


if __name__ != 'refresh_module':
	refresh_cameras()
