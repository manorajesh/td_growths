"""
camctl -- hardware controls for UVC webcams (Logitech C920 / C922 ...) on macOS.

Sends standard UVC control requests straight to the camera over USB (through IOKit, no root, no
drivers), so exposure etc. are set IN THE CAMERA -- not a post effect.  Works while the camera
is in use (TouchDesigner / the helpers keep running).

    helper/.venv/bin/python helper/camctl.py list
    helper/.venv/bin/python helper/camctl.py show                       # all cameras
    helper/.venv/bin/python helper/camctl.py set exposure_ms=8 gain=60 wb=4500 focus=0
    helper/.venv/bin/python helper/camctl.py set -c 1 auto_exposure=on   # camera 1 only
    helper/.venv/bin/python helper/camctl.py reset                      # factory defaults, autos on
    helper/.venv/bin/python helper/camctl.py save show.json             # remember the look
    helper/.venv/bin/python helper/camctl.py load show.json             # re-apply (e.g. after replug)

-c / --camera: list index, macOS camera ID (as in the TouchDesigner camera menu), or name text.
Default: all UVC cameras.  Setting exposure / wb / focus turns that control's auto mode off.

Controls: auto_exposure (on/off), exposure_ms (or exposure in 100us units), low_light (frame-rate
drop on/off), gain, brightness, contrast, saturation, sharpness, wb_auto (on/off), wb (Kelvin),
focus_auto (on/off), focus, zoom, backlight, powerline (off/50/60).
"""
import argparse
import ctypes
import ctypes.util
import json
import sys

# ----------------------------------------------------------------------------- IOKit plumbing
_iokit = ctypes.cdll.LoadLibrary(ctypes.util.find_library('IOKit'))
_cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library('CoreFoundation'))
_vp = ctypes.c_void_p
_cf.CFUUIDGetConstantUUIDWithBytes.restype = _vp
_cf.CFUUIDGetConstantUUIDWithBytes.argtypes = [_vp] + [ctypes.c_ubyte] * 16
_cf.CFStringCreateWithCString.restype = _vp
_cf.CFStringCreateWithCString.argtypes = [_vp, ctypes.c_char_p, ctypes.c_uint32]
_cf.CFNumberGetValue.argtypes = [_vp, ctypes.c_int, _vp]
_cf.CFStringGetCString.argtypes = [_vp, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
_cf.CFGetTypeID.argtypes = [_vp]
_cf.CFGetTypeID.restype = ctypes.c_ulong
_cf.CFStringGetTypeID.restype = ctypes.c_ulong
_cf.CFRelease.argtypes = [_vp]
_iokit.IOServiceMatching.restype = _vp
_iokit.IOServiceMatching.argtypes = [ctypes.c_char_p]
_iokit.IOServiceGetMatchingServices.argtypes = [ctypes.c_uint, _vp, ctypes.POINTER(ctypes.c_uint)]
_iokit.IOIteratorNext.restype = ctypes.c_uint
_iokit.IOIteratorNext.argtypes = [ctypes.c_uint]
_iokit.IORegistryEntryCreateCFProperty.restype = _vp
_iokit.IORegistryEntryCreateCFProperty.argtypes = [ctypes.c_uint, _vp, _vp, ctypes.c_uint]
_iokit.IOCreatePlugInInterfaceForService.argtypes = [ctypes.c_uint, _vp, _vp, ctypes.POINTER(_vp), ctypes.POINTER(ctypes.c_int32)]


def _uuid(s):
	return _cf.CFUUIDGetConstantUUIDWithBytes(None, *bytes.fromhex(s.replace('-', '')))


class _CFUUIDBytes(ctypes.Structure):
	_fields_ = [('b', ctypes.c_ubyte * 16)]


class _Req(ctypes.Structure):
	_fields_ = [('bmRequestType', ctypes.c_uint8), ('bRequest', ctypes.c_uint8), ('wValue', ctypes.c_uint16),
	            ('wIndex', ctypes.c_uint16), ('wLength', ctypes.c_uint16), ('pData', _vp), ('wLenDone', ctypes.c_uint32)]


_USER_CLIENT = _uuid('9dc7b780-9ec0-11d4-a54f-000a27052861')       # kIOUSBDeviceUserClientTypeID
_PLUGIN = _uuid('C244E858-109C-11D4-91D4-0050E4C6426F')            # kIOCFPlugInInterfaceID
_DEV_IID = _CFUUIDBytes((ctypes.c_ubyte * 16)(*bytes.fromhex('5c8187d09ef311d48b45000a27052861')))  # kIOUSBDeviceInterfaceID
_STALL = 0xE000404F


def _cfstr(s):
	return _cf.CFStringCreateWithCString(None, s.encode(), 0x08000100)


def _prop(svc, name):
	v = _iokit.IORegistryEntryCreateCFProperty(svc, _cfstr(name), None, 0)
	if not v:
		return None
	if _cf.CFGetTypeID(v) == _cf.CFStringGetTypeID():
		buf = ctypes.create_string_buffer(256)
		_cf.CFStringGetCString(v, buf, 256, 0x08000100)
		return buf.value.decode(errors='replace')
	out = ctypes.c_int64()
	_cf.CFNumberGetValue(v, 4, ctypes.byref(out))
	return out.value


def _vtable(obj):
	return ctypes.cast(ctypes.cast(obj, ctypes.POINTER(_vp))[0], ctypes.POINTER(_vp))


class Camera:
	"""One UVC camera: finds its control units from the USB descriptors, sends GET/SET requests."""

	def __init__(self, svc):
		self.vid, self.pid = _prop(svc, 'idVendor'), _prop(svc, 'idProduct')
		self.location = _prop(svc, 'locationID') or 0
		self.name = _prop(svc, 'USB Product Name') or _prop(svc, 'kUSBProductString') or 'USB camera'
		self.unique_id = '{}{:04x}{:04x}'.format(hex(self.location), self.vid, self.pid)   # = macOS camera ID
		plug, score = _vp(), ctypes.c_int32()
		if _iokit.IOCreatePlugInInterfaceForService(svc, _USER_CLIENT, _PLUGIN, ctypes.byref(plug), ctypes.byref(score)):
			raise OSError('cannot open USB device')
		qi = ctypes.CFUNCTYPE(ctypes.c_int32, _vp, _CFUUIDBytes, ctypes.POINTER(_vp))(_vtable(plug)[1])
		self.dev = _vp()
		if qi(plug, _DEV_IID, ctypes.byref(self.dev)) or not self.dev:
			raise OSError('cannot get USB device interface')
		vt = _vtable(self.dev)
		self._request = ctypes.CFUNCTYPE(ctypes.c_int32, _vp, ctypes.POINTER(_Req))(vt[26])        # DeviceRequest
		get_cfg = ctypes.CFUNCTYPE(ctypes.c_int32, _vp, ctypes.c_uint8, ctypes.POINTER(_vp))(vt[21])  # GetConfigurationDescriptorPtr
		desc = _vp()
		self.vc = self.ct = self.pu = None
		if get_cfg(self.dev, 0, ctypes.byref(desc)) == 0 and desc:
			total = ctypes.cast(desc, ctypes.POINTER(ctypes.c_uint16))[1]
			raw = ctypes.string_at(desc, total)
			i, iface = 0, None
			while i + 2 < len(raw) and raw[i] > 0:
				ln, ty = raw[i], raw[i + 1]
				if ty == 0x04 and ln >= 9:                                   # interface
					iface = raw[i + 2] if (raw[i + 5] == 0x0E and raw[i + 6] == 0x01) else None
					if iface is not None and self.vc is None:
						self.vc = iface
				elif ty == 0x24 and iface is not None and ln >= 4:         # class-specific video control
					sub = raw[i + 2]
					if sub == 0x02 and ln >= 6 and int.from_bytes(raw[i + 4:i + 6], 'little') == 0x0201:
						self.ct = raw[i + 3]                                  # camera terminal
					elif sub == 0x05:
						self.pu = raw[i + 3]                                  # processing unit
				i += ln

	@property
	def is_uvc(self):
		return self.vc is not None and (self.ct is not None or self.pu is not None)

	def _xfer(self, set_, req, unit, sel, size, data=0):
		buf = (ctypes.c_uint8 * size)(*data.to_bytes(size, 'little', signed=data < 0)) if set_ else (ctypes.c_uint8 * size)()
		r = _Req(0x21 if set_ else 0xA1, req, sel << 8, (unit << 8) | self.vc, size, ctypes.cast(buf, _vp), 0)
		kr = self._request(self.dev, ctypes.byref(r)) & 0xFFFFFFFF
		if kr:
			raise OSError('stalled (not supported)' if kr == _STALL else 'USB error 0x{:08x}'.format(kr))
		return bytes(buf)

	def get(self, ctrl, which='cur'):
		unit = self.ct if ctrl[0] == 'ct' else self.pu
		if unit is None:
			raise OSError('no such unit')
		b = self._xfer(False, {'cur': 0x81, 'min': 0x82, 'max': 0x83, 'res': 0x84, 'def': 0x87}[which], unit, ctrl[1], ctrl[2])
		return int.from_bytes(b, 'little', signed=ctrl[3])

	def set(self, ctrl, value):
		unit = self.ct if ctrl[0] == 'ct' else self.pu
		self._xfer(True, 0x01, unit, ctrl[1], ctrl[2], int(value))


# ----------------------------------------------------------------------------- controls
#            unit, selector, bytes, signed
CONTROLS = {
	'auto_exposure': ('ct', 0x02, 1, False),     # 1 manual, 2 auto, 4 shutter prio, 8 aperture prio
	'low_light':     ('ct', 0x03, 1, False),     # exposure priority: 1 = may drop frame rate
	'exposure':      ('ct', 0x04, 4, False),     # 100 microsecond units
	'focus':         ('ct', 0x06, 2, False),
	'focus_auto':    ('ct', 0x08, 1, False),
	'zoom':          ('ct', 0x0B, 2, False),
	'backlight':     ('pu', 0x01, 2, False),
	'brightness':    ('pu', 0x02, 2, True),
	'contrast':      ('pu', 0x03, 2, False),
	'gain':          ('pu', 0x04, 2, False),
	'powerline':     ('pu', 0x05, 1, False),     # 0 off, 1 50 Hz, 2 60 Hz
	'saturation':    ('pu', 0x07, 2, False),
	'sharpness':     ('pu', 0x08, 2, False),
	'wb':            ('pu', 0x0A, 2, False),     # Kelvin
	'wb_auto':       ('pu', 0x0B, 1, False),
}
ORDER = ['auto_exposure', 'low_light', 'exposure', 'gain', 'brightness', 'contrast', 'saturation', 'sharpness',
         'wb_auto', 'wb', 'focus_auto', 'focus', 'zoom', 'backlight', 'powerline']
AUTO_OF = {'exposure': ('auto_exposure', 'off'), 'wb': ('wb_auto', 'off'), 'focus': ('focus_auto', 'off')}
ONOFF = {'on': 1, 'off': 0, 'true': 1, 'false': 0, '1': 1, '0': 0, 'yes': 1, 'no': 0}


def _auto_exposure_value(cam, on):
	"""UVC auto-exposure is a bitmask of modes; pick 'manual' or the camera's automatic mode."""
	if not on:
		return 1
	try:
		supported = cam.get(CONTROLS['auto_exposure'], 'res')
	except OSError:
		supported = 0
	return 8 if supported & 8 or not supported else (2 if supported & 2 else 8)


def find_cameras():
	it = ctypes.c_uint()
	_iokit.IOServiceGetMatchingServices(0, _iokit.IOServiceMatching(b'IOUSBHostDevice'), ctypes.byref(it))
	cams = []
	while True:
		s = _iokit.IOIteratorNext(it.value)
		if not s:
			break
		try:
			c = Camera(s)
		except OSError:
			continue
		if c.is_uvc:
			cams.append(c)
	return sorted(cams, key=lambda c: c.location)


def select(cams, spec):
	if spec in (None, '', 'all'):
		return cams
	if spec.isdigit() and int(spec) < len(cams):
		return [cams[int(spec)]]
	hit = [c for c in cams if spec.lower() in (c.unique_id.lower(), hex(c.location)) or spec.lower() in c.name.lower()]
	if not hit:
		raise SystemExit('no camera matches "{}" (see: camctl.py list)'.format(spec))
	return hit


def describe(cam, name):
	ctrl = CONTROLS[name]
	try:
		cur = cam.get(ctrl)
	except OSError:
		return None
	extra = ''
	if name == 'auto_exposure':
		return 'on' if cur != 1 else 'off (manual)'
	if name in ('wb_auto', 'focus_auto', 'low_light'):
		return 'on' if cur else 'off'
	if name == 'powerline':
		return {0: 'off', 1: '50 Hz', 2: '60 Hz'}.get(cur, cur)
	try:
		extra = '  (range {} .. {}, default {})'.format(cam.get(ctrl, 'min'), cam.get(ctrl, 'max'), cam.get(ctrl, 'def'))
	except OSError:
		pass
	if name == 'exposure':
		return '{} = {:.1f} ms{}'.format(cur, cur / 10.0, extra)
	return '{}{}'.format(cur, extra)


def apply(cam, assignments):
	"""assignments: list of (name, value-string).  Auto modes are applied first."""
	todo = []
	for name, val in assignments:
		if name == 'exposure_ms':
			name, val = 'exposure', str(round(float(val) * 10))
		if name not in CONTROLS:
			raise SystemExit('unknown control "{}"; known: {}'.format(name, ', '.join(ORDER + ['exposure_ms'])))
		todo.append((name, val))
	names = [n for n, _ in todo]
	for n in list(names):                       # setting a manual value switches its auto off
		if n in AUTO_OF and AUTO_OF[n][0] not in names:
			todo.insert(0, AUTO_OF[n])
			names.insert(0, AUTO_OF[n][0])
	todo.sort(key=lambda nv: 0 if nv[0] in ('auto_exposure', 'wb_auto', 'focus_auto') else 1)
	for name, val in todo:
		v = val.lower() if isinstance(val, str) else val
		if name == 'auto_exposure':
			value = _auto_exposure_value(cam, ONOFF.get(str(v), 1) == 1)
		elif name in ('wb_auto', 'focus_auto', 'low_light'):
			value = ONOFF.get(str(v), int(float(v)))
		elif name == 'powerline':
			value = {'off': 0, '50': 1, '50hz': 1, '60': 2, '60hz': 2}.get(str(v), int(float(v)))
		else:
			value = int(round(float(v)))
			ctrl = CONTROLS[name]
			try:
				value = max(cam.get(ctrl, 'min'), min(cam.get(ctrl, 'max'), value))
			except OSError:
				pass
		try:
			cam.set(CONTROLS[name], value)
			print('  {:<14} -> {}'.format(name, describe(cam, name)))
		except OSError as e:
			print('  {:<14} not set: {}'.format(name, e))


def main(argv=None):
	ap = argparse.ArgumentParser(description='Hardware controls for UVC webcams (C920/C922...).')
	ap.add_argument('command', choices=['list', 'show', 'set', 'reset', 'save', 'load'])
	ap.add_argument('args', nargs='*', help='set: name=value ...   save/load: file.json')
	ap.add_argument('-c', '--camera', default='all', help='index, macOS camera ID, or name (default: all)')
	a = ap.parse_args(argv)
	cams = find_cameras()
	if not cams:
		raise SystemExit('no UVC cameras found')
	if a.command == 'list':
		for i, c in enumerate(cams):
			print('{}  {:<26} camera ID {}'.format(i, c.name, c.unique_id))
		return
	chosen = select(cams, a.camera)
	if a.command == 'show':
		for c in chosen:
			print('{}  [{}]'.format(c.name, c.unique_id))
			for n in ORDER:
				d = describe(c, n)
				if d is not None:
					print('  {:<14} {}'.format(n, d))
	elif a.command == 'set':
		pairs = [x.split('=', 1) for x in a.args]
		if not pairs or any(len(p) != 2 for p in pairs):
			raise SystemExit('usage: camctl.py set name=value [name=value ...]')
		for c in chosen:
			print('{}  [{}]'.format(c.name, c.unique_id))
			apply(c, pairs)
	elif a.command == 'reset':
		for c in chosen:
			print('{}  [{}]  -> defaults'.format(c.name, c.unique_id))
			pairs = [('auto_exposure', 'on'), ('wb_auto', 'on'), ('focus_auto', 'on')]
			for n in ('gain', 'brightness', 'contrast', 'saturation', 'sharpness', 'zoom', 'backlight', 'low_light'):
				try:
					pairs.append((n, str(c.get(CONTROLS[n], 'def'))))
				except OSError:
					pass
			apply(c, pairs)
	elif a.command == 'save':
		if len(a.args) != 1:
			raise SystemExit('usage: camctl.py save file.json')
		data = {}
		for c in chosen:
			vals = {}
			for n in ORDER:
				try:
					v = c.get(CONTROLS[n])
				except OSError:
					continue
				vals[n] = ('on' if v != 1 else 'off') if n == 'auto_exposure' else v
			data[c.unique_id] = {'name': c.name, 'controls': vals}
		with open(a.args[0], 'w') as f:
			json.dump(data, f, indent=1)
		print('saved {} camera(s) to {}'.format(len(data), a.args[0]))
	elif a.command == 'load':
		if len(a.args) != 1:
			raise SystemExit('usage: camctl.py load file.json')
		with open(a.args[0]) as f:
			data = json.load(f)
		for c in chosen:
			entry = data.get(c.unique_id) or next((e for e in data.values() if e.get('name') == c.name), None)
			if entry is None:
				print('{}  [{}]: not in {}'.format(c.name, c.unique_id, a.args[0]))
				continue
			print('{}  [{}]'.format(c.name, c.unique_id))
			ctrls = entry['controls']
			apply(c, [(n, str(ctrls[n])) for n in ORDER if n in ctrls and not (
				(n == 'exposure' and ctrls.get('auto_exposure') == 'on') or
				(n == 'wb' and ctrls.get('wb_auto')) or (n == 'focus' and ctrls.get('focus_auto')))])


if __name__ == '__main__':
	sys.exit(main())
