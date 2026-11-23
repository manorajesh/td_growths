"""
Phone camera via VDO.Ninja as an input option (used by the build scripts and update_patch.py).

add_phone_input(comp, cam_par_name, tag) adds to a COMP that runs a helper (silhouette side,
floor tracker):
  * a "Phone (VDO.Ninja URL)" entry in its camera menu, and Phone URL / size settings;
  * phone_in  -- Web Render TOP playing the VDO.Ninja view link (only active while selected);
  * phone_send -- Execute DAT that writes each frame to a shared file the helper reads
    (the helper is started with --camera td:<file> when the phone is selected).
Safe to call again on a COMP that already has it.
"""

PHONE_NAME = 'phone'
PHONE_LABEL = 'Phone (VDO.Ninja URL)'

PHONE_WRITER = '''
# Sends phone_in (the VDO.Ninja stream) to the helper: RGBA uint8, bottom row first.
import mmap, os, struct
import numpy as np

HDR = struct.Struct('<4sIQII')
HS = 64
SIZE = HS + 1920 * 1080 * 4
_st = {}

def _map(path):
	m = _st.get(path)
	if m is None:
		if not os.path.exists(path) or os.path.getsize(path) != SIZE:
			with open(path, 'wb') as f:
				f.truncate(SIZE)
		f = open(path, 'r+b')
		mm = mmap.mmap(f.fileno(), SIZE)
		m = _st[path] = {'f': f, 'mm': mm, 'seq': HDR.unpack_from(mm, 0)[2] & ~1}
	return m

def onFrameEnd(frame):
	c = me.parent()
	if c.par.%(cam)s.eval() != 'phone':
		return
	arr = c.op('phone_in').numpyArray(delayed=True)
	if arr is None or arr.ndim != 3:
		return
	h, w = arr.shape[:2]
	if w * h * 4 > SIZE - HS:
		return
	rgba = np.clip(arr[..., :4] * 255.0 + 0.5, 0, 255).astype(np.uint8)   # numpyArray is 0..1 float
	m = _map(c.par.Phonefile.eval())
	mm = m['mm']
	m['seq'] += 1
	mm[:HDR.size] = HDR.pack(b'CAM1', 1, m['seq'], w, h)
	mm[HS:HS + rgba.nbytes] = rgba.tobytes()
	m['seq'] += 1
	mm[:HDR.size] = HDR.pack(b'CAM1', 1, m['seq'], w, h)
	return
'''

# the URL as typed + flags so the page shows only the video and can autoplay
URL_EXPR = ("(lambda u: u if (not u or 'cleanoutput' in u) else u + ('&' if '?' in u else '?') + "
            "'cleanoutput&noaudio')(parent().par.Phoneurl.eval().strip())")


def _try(o, **kw):
	for k, v in kw.items():
		try:
			setattr(o.par, k, v)
		except Exception as e:
			print('phone_input: could not set {}.{} ({})'.format(o.path, k, e))


def add_phone_input(comp, cam_par_name, tag):
	cam = getattr(comp.par, cam_par_name)
	names = list(cam.menuNames)
	if PHONE_NAME not in names:
		cam.menuNames = names + [PHONE_NAME]
		cam.menuLabels = list(cam.menuLabels) + [PHONE_LABEL]
	page = cam.page
	if not hasattr(comp.par, 'Phoneurl'):
		p = page.appendStr('Phoneurl', label='Phone URL (VDO.Ninja view link)')[0]
		p.default = p.val = ''
	if not hasattr(comp.par, 'Phonefile'):
		p = page.appendStr('Phonefile', label='Phone Frame File')[0]
		p.default = p.val = '/tmp/{}_phone.bin'.format(tag)
	if not hasattr(comp.par, 'Phonew'):
		pw = page.appendInt('Phonew', label='Phone Frame Width')[0]
		pw.default = pw.val = 960
		ph = page.appendInt('Phoneh', label='Phone Frame Height')[0]
		ph.default = ph.val = 540

	web = comp.op('phone_in')
	if web is None:
		web = comp.create(webrenderTOP, 'phone_in')
		web.nodeX, web.nodeY = -400, 300
	try:
		web.par.url.expr = URL_EXPR
	except Exception as e:
		print('phone_input: could not set phone_in url ({})'.format(e))
	for wn, hn in (('resolutionw', 'resolutionh'), ('w', 'h')):
		try:
			getattr(web.par, wn).expr = 'parent().par.Phonew'
			getattr(web.par, hn).expr = 'parent().par.Phoneh'
			break
		except Exception:
			continue
	try:
		web.par.outputresolution = 'custom'
	except Exception:
		pass
	try:
		web.par.active.expr = "parent().par.{}.eval() == 'phone'".format(cam_par_name)
	except Exception as e:
		print('phone_input: could not set phone_in active ({})'.format(e))
	_try(web, audio=False)

	send = comp.op('phone_send')
	if send is None:
		send = comp.create(executeDAT, 'phone_send')
		send.nodeX, send.nodeY = -200, 300
	send.text = PHONE_WRITER % {'cam': cam_par_name}
	_try(send, frameend=True)
	return web
