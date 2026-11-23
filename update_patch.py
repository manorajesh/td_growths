"""
Bring an already-built .toe up to date WITHOUT rebuilding (calibration and settings are kept).
Use it after moving to another Mac / user, or after updating this folder.  In the Textport:

    import os; exec(open(os.path.expanduser('~/code/td_silhouette/update_patch.py')).read())

then save the .toe.  For each of silhouette_wall / floor_tracker / logogram found in /project1:
  * stops its helpers, replaces its embedded scripts with the current versions from the
    build_*.py files, stores Project Folder as ~/code/td_silhouette, restarts the helpers;
  * adds the 'Phone (VDO.Ninja URL)' camera option where it is missing;
  * for the burst/roots patch, re-runs integrate_roots.py (person circles, relative image links).
"""
import os
import re

ROOT = os.path.expanduser('~/code/td_silhouette')
try:
	ROOT = SILHOUETTE_DIR
except NameError:
	pass


def _consts(build_file, names):
	src = open(os.path.join(ROOT, build_file)).read()
	out = {}
	for n in names:
		m = re.search(n + r" = '''(.*?)'''", src, re.S)
		out[n] = eval("'''" + m.group(1) + "'''")
	return out


def _portable(path):
	home = os.path.expanduser('~')
	return '~' + path[len(home):] if path.startswith(home + os.sep) else path


def _set_text(comp, dat_name, text, report):
	d = comp.op(dat_name)
	if d is None:
		report.append('{}/{} missing (rebuild to get it)'.format(comp.path, dat_name))
		return
	if d.text != text:
		d.text = text
		report.append('updated ' + d.path)


def _module(comp, name='pulses'):
	try:
		return comp.op(name).module
	except Exception:
		return None


def _phone(comp, cam_par, tag, report):
	exec(open(os.path.join(ROOT, 'phone_input.py')).read(), globals())
	had = 'phone' in list(getattr(comp.par, cam_par).menuNames)
	add_phone_input(comp, cam_par, tag)
	if not had:
		report.append('{}: added the Phone (VDO.Ninja URL) camera option'.format(comp.path))


def _cam(comp, page_par, report):
	exec(open(os.path.join(ROOT, 'cam_controls.py')).read(), globals())
	if not hasattr(comp.par, 'Camexposure'):
		add_cam_controls(comp, getattr(comp.par, page_par).page)
		report.append('{}: added Camera Exposure / Contrast'.format(comp.path))


def update_silhouette(wall, report):
	k = _consts('build_silhouette.py', ['SIDE_PULSE', 'VISION_READER', 'WALL_EXEC', 'WALL_PULSE', 'PANEL_DRAG'])
	sides = [wall.op(s) for s in ('side_L', 'side_R') if wall.op(s)]
	for s in sides:
		m = _module(s)
		if m and hasattr(m, 'stop_helper'):
			m.stop_helper(s)
	if hasattr(wall.par, 'Projectfolder'):
		wall.par.Projectfolder = _portable(os.path.expanduser(wall.par.Projectfolder.eval()))
		if not os.path.isdir(os.path.expanduser(wall.par.Projectfolder.eval())):
			wall.par.Projectfolder = _portable(ROOT)
	_set_text(wall, 'helpers', k['WALL_EXEC'], report)
	_set_text(wall, 'pulses', k['WALL_PULSE'], report)
	for s in sides:
		_phone(s, 'Visioncamera', 'silhouette_' + s.name[-1], report)
		_cam(s, 'Visioncamera', report)
		_set_text(s, 'pulses', k['SIDE_PULSE'], report)
		_set_text(s, 'vision_in_callbacks', k['VISION_READER'], report)
		_set_text(s, 'calibrate_drag', k['PANEL_DRAG'], report)
		s.op('calibrate_ui').par.top.expr = "parent().op('calib_view')"
		m = _module(s)
		if m and hasattr(m, 'sync_helper'):
			m.sync_helper(s)
	report.append('{}: Project Folder = {}'.format(wall.path, wall.par.Projectfolder.eval()))


def update_floor(ft, report):
	k = _consts('build_floor_tracker.py', ['READER', 'CAMERA_TOP', 'PEOPLE_CHOP', 'MOUSE_CHOP', 'STEPS_DAT',
	                                       'FEETMAP_TOP', 'STEP_TRIGGER', 'PULSES', 'EXEC', 'PANEL_DRAG'])
	m = _module(ft)
	if m and hasattr(m, 'stop_helper'):
		m.stop_helper(ft)
	ft.par.Projectfolder = _portable(os.path.expanduser(ft.par.Projectfolder.eval()))
	if not os.path.isdir(os.path.expanduser(ft.par.Projectfolder.eval())):
		ft.par.Projectfolder = _portable(ROOT)
	_phone(ft, 'Camera', 'floor_track', report)
	_cam(ft, 'Camera', report)
	for dat, key in (('reader', 'READER'), ('camera_in_callbacks', 'CAMERA_TOP'),
	                 ('people_script_callbacks', 'PEOPLE_CHOP'), ('mouse_script_callbacks', 'MOUSE_CHOP'),
	                 ('steps_script_callbacks', 'STEPS_DAT'), ('feet_map_script_callbacks', 'FEETMAP_TOP'),
	                 ('pulses', 'PULSES'), ('helpers', 'EXEC'), ('calibrate_drag', 'PANEL_DRAG')):
		_set_text(ft, dat, k[key], report)
	if ft.op('step_trigger_script_callbacks') is not None and hasattr(ft.par, 'Stepcooldown'):
		_set_text(ft, 'step_trigger_script_callbacks', k['STEP_TRIGGER'], report)
	exec(open(os.path.join(ROOT, 'autocal.py')).read(), globals())
	had = hasattr(ft.par, 'Autocalibrate')
	add_autocalibration(ft)
	if not had:
		report.append('{}: added Auto Calibrate'.format(ft.path))
	ft.op('calibrate_ui').par.top.expr = "parent().op('calib_view')"
	m = _module(ft)
	if m and hasattr(m, 'start_helper'):
		m.start_helper(ft)
	report.append('{}: Project Folder = {}'.format(ft.path, ft.par.Projectfolder.eval()))


def main():
	if not os.path.isfile(os.path.join(ROOT, 'helper', '.venv', 'bin', 'python')):
		print('update_patch: helper environment missing -- run  bash ~/code/td_silhouette/setup_mac.sh  first')
	host = op('/project1') or root
	report = []
	if host.op('silhouette_wall'):
		update_silhouette(host.op('silhouette_wall'), report)
	for ft in (op('/project1/floor_tracker'), op('/container1/floor_tracker')):
		if ft is not None:
			update_floor(ft, report)
	if host.op('logogram'):
		report.append('logogram has no machine-specific paths -- nothing to update')
	if op('/container1/floor_tracker') or host.op('key_or_step') or op('/container1/pointer'):
		exec(open(os.path.join(ROOT, 'integrate_roots.py')).read(), globals())   # burst/roots patch
	for line in report:
		print('update_patch:', line)
	print('update_patch: done -- save the .toe. If a camera menu looks wrong, press Refresh Cameras.')


main()
