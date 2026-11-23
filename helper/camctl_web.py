"""
camctl web -- a small local control page for UVC webcam hardware settings (C920 / C922 ...).

    helper/.venv/bin/python helper/camctl_web.py          # opens http://127.0.0.1:8765

Sliders and switches for exposure, gain, white balance, focus, etc. (set in the camera over USB,
via camctl.py), a live preview, presets (save / load / reset).  Serves on localhost only.
"""
import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import camctl  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, 'camctl_web.html')
PRESET = os.path.join(os.path.dirname(HERE), 'camera_presets.json')
PORT = int(os.environ.get('CAMCTL_PORT', 8765))
_lock = threading.Lock()
_cams = []


def _refresh():
	global _cams
	_cams = camctl.find_cameras()
	return _cams


def _cam(cid):
	for c in _cams:
		if c.unique_id == cid:
			return c
	for c in _refresh():
		if c.unique_id == cid:
			return c
	raise KeyError('camera {} not found'.format(cid))


def _state(c):
	ctrls = {}
	for n in camctl.ORDER:
		ctrl = camctl.CONTROLS[n]
		try:
			cur = c.get(ctrl)
		except OSError:
			continue
		info = {'cur': cur}
		if n == 'auto_exposure':
			info['cur'] = cur != 1
		elif n in ('wb_auto', 'focus_auto', 'low_light'):
			info['cur'] = bool(cur)
		else:
			for k in ('min', 'max', 'def'):
				try:
					info[k] = c.get(ctrl, k)
				except OSError:
					pass
		ctrls[n] = info
	return {'id': c.unique_id, 'name': c.name, 'controls': ctrls}


class Handler(BaseHTTPRequestHandler):
	def log_message(self, *a):
		pass

	def _send(self, code, body, ctype='application/json'):
		data = body if isinstance(body, bytes) else json.dumps(body).encode()
		self.send_response(code)
		self.send_header('Content-Type', ctype)
		self.send_header('Content-Length', str(len(data)))
		self.send_header('Cache-Control', 'no-store')
		self.end_headers()
		self.wfile.write(data)

	def do_GET(self):
		if self.path in ('/', '/index.html'):
			with open(PAGE, 'rb') as f:
				return self._send(200, f.read(), 'text/html; charset=utf-8')
		if self.path == '/api/cameras':
			with _lock:
				return self._send(200, {'cameras': [_state(c) for c in _refresh()], 'preset': PRESET,
				                        'has_preset': os.path.exists(PRESET)})
		self._send(404, {'error': 'not found'})

	def do_POST(self):
		try:
			n = int(self.headers.get('Content-Length', 0))
			req = json.loads(self.rfile.read(n) or b'{}')
			with _lock:
				if self.path == '/api/set':
					c = _cam(req['id'])
					name, value = req['name'], req['value']
					if isinstance(value, bool):
						value = 'on' if value else 'off'
					camctl.apply(c, [(name, str(value))])
					return self._send(200, _state(c))
				if self.path == '/api/reset':
					c = _cam(req['id'])
					camctl.main(['reset', '-c', c.unique_id])
					return self._send(200, _state(c))
				if self.path == '/api/save':
					camctl.main(['save', PRESET])
					return self._send(200, {'saved': PRESET})
				if self.path == '/api/load':
					if not os.path.exists(PRESET):
						return self._send(400, {'error': 'no preset saved yet'})
					camctl.main(['load', PRESET])
					return self._send(200, {'cameras': [_state(c) for c in _refresh()]})
			self._send(404, {'error': 'not found'})
		except (KeyError, OSError, ValueError, SystemExit) as e:
			self._send(400, {'error': str(e)})


def main():
	_refresh()
	srv = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
	url = 'http://127.0.0.1:{}/'.format(PORT)
	print('camera controls at', url, '(Ctrl+C to stop)')
	if '--no-browser' not in sys.argv:
		threading.Timer(0.5, lambda: webbrowser.open(url)).start()
	try:
		srv.serve_forever()
	except KeyboardInterrupt:
		pass


if __name__ == '__main__':
	main()
