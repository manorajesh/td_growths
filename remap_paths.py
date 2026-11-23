"""
Remap file paths in an open .toe so a patch made on Windows (or another Mac / user) runs here.

Open the patch in TouchDesigner, then in the Textport:

    import os; exec(open(os.path.expanduser('~/code/td_silhouette/remap_paths.py')).read())

then File > Save As.  For every operator in the project it looks at file parameters (images,
movies, audio, .tox, ...).  A path that doesn't exist on this Mac -- a Windows path like
D:/expanded theater/.../burst.1.png, or a Mac path from another user -- is relinked to a file
with the same name found in the search folders, stored RELATIVE to the .toe (e.g.
assets/burst.1.png) so it also works on other Macs with the same folder layout.  Paths that
already work, URLs and TouchDesigner's own components are left alone.  Prints what it did and
what it could not find.

Options (set before exec):
    REMAP_DIRS = ['~/Downloads/assets']   extra folders to search (project/assets, project folder,
                                          ~/Downloads/assets are always searched)
    RELINK_TOX = True                     point external .tox references at the local .tox files.
                                          Default False: the external-.tox link is cleared and the
                                          network saved INSIDE the .toe is kept (a linked .tox is
                                          reloaded on open and would replace those contents).
    REMAP_DRY_RUN = True                  only report, change nothing
"""
import os
import re

_g = globals()
_extra = [os.path.expanduser(d) for d in _g.get('REMAP_DIRS', [])]
_relink_tox = bool(_g.get('RELINK_TOX', False))
_dry = bool(_g.get('REMAP_DRY_RUN', False))

SEARCH = []
for d in [os.path.join(project.folder, 'assets'), project.folder, os.path.expanduser('~/Downloads/assets')] + _extra:
	if os.path.isdir(d) and d not in SEARCH:
		SEARCH.append(d)

_WIN = re.compile(r'^[A-Za-z]:[\\/]')
_SKIP_OPS = ('/sys', '/local', '/ui')                   # TouchDesigner internals
_FILE_PARS = {'file', 'externaltox', 'filename', 'syncfile', 'audiofile', 'moviefile'}


def _index():
	idx = {}
	for d in SEARCH:
		for dirpath, dirs, files in os.walk(d):
			dirs[:] = [x for x in dirs if not x.startswith('.') and x != 'psd']
			for f in files:
				idx.setdefault(f.lower(), os.path.join(dirpath, f))
	return idx


def _resolve(path):
	"""Does this path work on this Mac as it is?"""
	if not path or '://' in path or path.startswith('app.') or path.startswith('$'):
		return True
	if _WIN.match(path) or '\\' in path:
		return False
	p = path if os.path.isabs(path) else os.path.join(project.folder, path)
	return os.path.exists(p)


def _is_file_par(p):
	try:
		if p.style in ('File', 'Folder', 'FileSave'):
			return True
	except Exception:
		pass
	return p.name in _FILE_PARS


def remap():
	idx = _index()
	fixed, missing, tox = [], [], []
	for o in [root] + list(root.findChildren()):
		if any(o.path == s or o.path.startswith(s + '/') for s in _SKIP_OPS):
			continue
		for p in o.pars():
			if not _is_file_par(p):
				continue
			try:
				mode = p.mode
			except Exception:
				continue
			if mode != ParMode.CONSTANT:
				continue
			val = str(p.val or '')
			if _resolve(val):
				continue
			name = re.split(r'[\\/]', val)[-1]
			hit = idx.get(name.lower())
			if p.name == 'externaltox':
				if _relink_tox and hit:
					new = os.path.relpath(hit, project.folder).replace(os.sep, '/')
					tox.append('{} -> {}'.format(o.path, new))
					if not _dry:
						p.val = new
				else:
					tox.append('{}: cleared {} (keeping the network saved in the .toe)'.format(o.path, val))
					if not _dry:
						p.val = ''
				continue
			if hit:
				new = os.path.relpath(hit, project.folder).replace(os.sep, '/')
				fixed.append('{}.{}: {} -> {}'.format(o.path, p.name, name, new))
				if not _dry:
					p.val = new
			else:
				missing.append('{}.{}: {}'.format(o.path, p.name, val))
	tag = 'would relink' if _dry else 'relinked'
	print('remap_paths: searched {}'.format(SEARCH))
	print('remap_paths: {} {} file path(s)'.format(tag, len(fixed)))
	for line in fixed:
		print('   ', line)
	if tox:
		print('remap_paths: external .tox ({}):'.format('relinked' if _relink_tox else 'cleared'))
		for line in tox:
			print('   ', line)
	if missing:
		print('remap_paths: NOT FOUND (left as is) -- copy these files into an assets folder and run again:')
		for line in missing:
			print('   ', line)
	print('remap_paths: done{} -- File > Save As to keep it.'.format(' (dry run, nothing changed)' if _dry else ''))


remap()
