#!/usr/bin/env python3
"""
c922_max_exposure.py -- max out exposure on Logitech C920/C922 (any UVC webcam) on macOS.

No installs: plain python3 + macOS IOKit.  Settings go into the camera itself over USB, and
work while another app (browser / VDO.Ninja / TouchDesigner) is using the camera.

    python3 c922_max_exposure.py              # auto exposure off, exposure time to max
    python3 c922_max_exposure.py --gain max   # ... and gain to max (brighter, noisier)
    python3 c922_max_exposure.py --gain 120   # ... or a specific gain (0-255 on a C922)
    python3 c922_max_exposure.py --ms 20      # a specific exposure time instead of max
    python3 c922_max_exposure.py --auto       # back to automatic exposure
    python3 c922_max_exposure.py --show       # just print the current values
    python3 c922_max_exposure.py --keep-fps   # don't let the frame rate drop (exposure <= 1 frame)
    python3 c922_max_exposure.py --name C922  # only cameras whose name contains this

By default the camera may lower its frame rate so the long exposure really happens (C922 max is
204.7 ms -> about 5 fps).  Cameras keep these settings until unplugged.
"""
import argparse
import ctypes
import ctypes.util
import sys

iokit = ctypes.cdll.LoadLibrary(ctypes.util.find_library('IOKit'))
cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library('CoreFoundation'))
vp = ctypes.c_void_p
cf.CFUUIDGetConstantUUIDWithBytes.restype = vp
cf.CFUUIDGetConstantUUIDWithBytes.argtypes = [vp] + [ctypes.c_ubyte] * 16
cf.CFStringCreateWithCString.restype = vp
cf.CFStringCreateWithCString.argtypes = [vp, ctypes.c_char_p, ctypes.c_uint32]
cf.CFNumberGetValue.argtypes = [vp, ctypes.c_int, vp]
cf.CFStringGetCString.argtypes = [vp, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
cf.CFGetTypeID.argtypes = [vp]
cf.CFGetTypeID.restype = ctypes.c_ulong
cf.CFStringGetTypeID.restype = ctypes.c_ulong
iokit.IOServiceMatching.restype = vp
iokit.IOServiceMatching.argtypes = [ctypes.c_char_p]
iokit.IOServiceGetMatchingServices.argtypes = [ctypes.c_uint, vp, ctypes.POINTER(ctypes.c_uint)]
iokit.IOIteratorNext.restype = ctypes.c_uint
iokit.IOIteratorNext.argtypes = [ctypes.c_uint]
iokit.IORegistryEntryCreateCFProperty.restype = vp
iokit.IORegistryEntryCreateCFProperty.argtypes = [ctypes.c_uint, vp, vp, ctypes.c_uint]
iokit.IOCreatePlugInInterfaceForService.argtypes = [ctypes.c_uint, vp, vp, ctypes.POINTER(vp), ctypes.POINTER(ctypes.c_int32)]


class UUIDBytes(ctypes.Structure):
	_fields_ = [('b', ctypes.c_ubyte * 16)]


class Req(ctypes.Structure):
	_fields_ = [('bmRequestType', ctypes.c_uint8), ('bRequest', ctypes.c_uint8), ('wValue', ctypes.c_uint16),
	            ('wIndex', ctypes.c_uint16), ('wLength', ctypes.c_uint16), ('pData', vp), ('wLenDone', ctypes.c_uint32)]


def uuid(s):
	return cf.CFUUIDGetConstantUUIDWithBytes(None, *bytes.fromhex(s.replace('-', '')))


USER_CLIENT = uuid('9dc7b780-9ec0-11d4-a54f-000a27052861')
PLUGIN = uuid('C244E858-109C-11D4-91D4-0050E4C6426F')
DEVICE_IID = UUIDBytes((ctypes.c_ubyte * 16)(*bytes.fromhex('5c8187d09ef311d48b45000a27052861')))


def prop(svc, name):
	v = iokit.IORegistryEntryCreateCFProperty(svc, cf.CFStringCreateWithCString(None, name.encode(), 0x08000100), None, 0)
	if not v:
		return None
	if cf.CFGetTypeID(v) == cf.CFStringGetTypeID():
		buf = ctypes.create_string_buffer(256)
		cf.CFStringGetCString(v, buf, 256, 0x08000100)
		return buf.value.decode(errors='replace')
	out = ctypes.c_int64()
	cf.CFNumberGetValue(v, 4, ctypes.byref(out))
	return out.value


def vtable(obj):
	return ctypes.cast(ctypes.cast(obj, ctypes.POINTER(vp))[0], ctypes.POINTER(vp))


class Camera:
	def __init__(self, svc):
		self.name = prop(svc, 'USB Product Name') or prop(svc, 'kUSBProductString') or 'USB camera'
		self.location = prop(svc, 'locationID') or 0
		plug, score = vp(), ctypes.c_int32()
		if iokit.IOCreatePlugInInterfaceForService(svc, USER_CLIENT, PLUGIN, ctypes.byref(plug), ctypes.byref(score)):
			raise OSError('cannot open')
		qi = ctypes.CFUNCTYPE(ctypes.c_int32, vp, UUIDBytes, ctypes.POINTER(vp))(vtable(plug)[1])
		self.dev = vp()
		if qi(plug, DEVICE_IID, ctypes.byref(self.dev)) or not self.dev:
			raise OSError('no device interface')
		vt = vtable(self.dev)
		self.request = ctypes.CFUNCTYPE(ctypes.c_int32, vp, ctypes.POINTER(Req))(vt[26])
		get_cfg = ctypes.CFUNCTYPE(ctypes.c_int32, vp, ctypes.c_uint8, ctypes.POINTER(vp))(vt[21])
		desc = vp()
		self.vc = self.ct = self.pu = None
		if get_cfg(self.dev, 0, ctypes.byref(desc)) == 0 and desc:
			raw = ctypes.string_at(desc, ctypes.cast(desc, ctypes.POINTER(ctypes.c_uint16))[1])
			i, iface = 0, None
			while i + 2 < len(raw) and raw[i] > 0:
				ln, ty = raw[i], raw[i + 1]
				if ty == 0x04 and ln >= 9:
					iface = raw[i + 2] if (raw[i + 5] == 0x0E and raw[i + 6] == 0x01) else None
					if iface is not None and self.vc is None:
						self.vc = iface
				elif ty == 0x24 and iface is not None and ln >= 4:
					if raw[i + 2] == 0x02 and ln >= 6 and int.from_bytes(raw[i + 4:i + 6], 'little') == 0x0201:
						self.ct = raw[i + 3]
					elif raw[i + 2] == 0x05:
						self.pu = raw[i + 3]
				i += ln

	def _x(self, set_, req, unit, sel, size, value=0):
		buf = (ctypes.c_uint8 * size)(*int(value).to_bytes(size, 'little')) if set_ else (ctypes.c_uint8 * size)()
		r = Req(0x21 if set_ else 0xA1, req, sel << 8, (unit << 8) | self.vc, size, ctypes.cast(buf, vp), 0)
		if self.request(self.dev, ctypes.byref(r)):
			raise OSError('not supported')
		return int.from_bytes(bytes(buf), 'little')

	def get(self, unit, sel, size, which=0x81):          # 0x81 cur, 0x82 min, 0x83 max, 0x84 res
		return self._x(False, which, unit, sel, size)

	def set(self, unit, sel, size, value):
		self._x(True, 0x01, unit, sel, size, value)


def cameras(name):
	it = ctypes.c_uint()
	iokit.IOServiceGetMatchingServices(0, iokit.IOServiceMatching(b'IOUSBHostDevice'), ctypes.byref(it))
	found = []
	while True:
		s = iokit.IOIteratorNext(it.value)
		if not s:
			break
		try:
			c = Camera(s)
		except OSError:
			continue
		if c.vc is not None and c.ct is not None and (not name or name.lower() in c.name.lower()):
			found.append(c)
	return found


def show(c):
	ae = c.get(c.ct, 0x02, 1)
	exp = c.get(c.ct, 0x04, 4)
	gain = c.get(c.pu, 0x04, 2) if c.pu is not None else None
	try:
		drop = 'may drop' if c.get(c.ct, 0x03, 1) else 'fixed'
	except OSError:
		drop = '?'
	print('  auto exposure {}, exposure {:.1f} ms, gain {}, frame rate {}'.format(
		'on' if ae != 1 else 'off', exp / 10.0, gain, drop))


def main():
	ap = argparse.ArgumentParser(description='Max out exposure on C920/C922 (UVC) webcams.')
	ap.add_argument('--gain', help="also set gain: a number, or 'max'")
	ap.add_argument('--ms', type=float, help='exposure time in ms instead of max')
	ap.add_argument('--keep-fps', action='store_true', help="don't let the frame rate drop")
	ap.add_argument('--auto', action='store_true', help='back to automatic exposure')
	ap.add_argument('--show', action='store_true', help='only show current values')
	ap.add_argument('--name', default='', help='only cameras whose name contains this')
	a = ap.parse_args()
	cams = cameras(a.name)
	if not cams:
		sys.exit('no UVC webcams found' + (' matching "{}"'.format(a.name) if a.name else ''))
	for c in cams:
		print('{} (USB location 0x{:08x})'.format(c.name, c.location))
		try:
			if a.show:
				pass
			elif a.auto:
				res = c.get(c.ct, 0x02, 1, 0x84)                      # supported auto modes (bitmask)
				c.set(c.ct, 0x02, 1, 8 if (res & 8 or not res) else 2)
				try:
					c.set(c.ct, 0x03, 1, 0)                           # normal frame rate again
				except OSError:
					pass
			else:
				c.set(c.ct, 0x02, 1, 1)                               # manual exposure
				try:                                                  # 1 = frame rate may drop
					c.set(c.ct, 0x03, 1, 0 if a.keep_fps else 1)
				except OSError:
					pass
				lo, hi = c.get(c.ct, 0x04, 4, 0x82), c.get(c.ct, 0x04, 4, 0x83)
				target = hi if a.ms is None else max(lo, min(hi, round(a.ms * 10)))
				c.set(c.ct, 0x04, 4, target)
				if a.gain is not None and c.pu is not None:
					glo, ghi = c.get(c.pu, 0x04, 2, 0x82), c.get(c.pu, 0x04, 2, 0x83)
					g = ghi if a.gain.lower() == 'max' else max(glo, min(ghi, int(float(a.gain))))
					c.set(c.pu, 0x04, 2, g)
			show(c)
		except OSError as e:
			print('  could not change this camera: {}'.format(e))


if __name__ == '__main__':
	main()
