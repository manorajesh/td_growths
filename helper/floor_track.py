"""
Floor tracker helper (macOS, Apple Vision) -- tracks up to N people from a high, angled
webcam and reports where their feet are on the floor, plus step events.

Pipeline per frame:
  camera -> Vision body pose (ankles) + human rectangles (fallback) -> lens undistort ->
  perspective homography (camera -> floor 0..1) -> tracking with stable slots -> smoothing ->
  step detection (a foot that moved and then planted).

Calibration comes from a JSON file that TouchDesigner writes (re-read whenever it changes):
  {"corners": {"bl": [x, y], "br": [...], "tr": [...], "tl": [...]},   # camera uv, origin bottom-left
   "lens_k1": 0.0, "floor_w": 6.0, "floor_d": 4.0, "max_people": 5, ...thresholds...}

Output is a memory-mapped file read by TouchDesigner:
  header (64 bytes): b'FLT1', version, seq (odd while writing), width, height, json_len
  RGBA camera image (bottom row first) with debug drawing, at offset 64
  JSON state (people + recent steps) at offset JSON_OFFSET

Manual use:
  helper/.venv/bin/python helper/floor_track.py --list
  helper/.venv/bin/python helper/floor_track.py --camera C922 --config /tmp/floor_track_config.json
"""
import argparse
import json
import math
import mmap
import os
import signal
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2
import numpy as np
import objc
import Quartz
import Vision
from vision_segment import CameraAdjust, devices, open_camera, parent_alive, rss_mb

HEADER = struct.Struct('<4sIQIII')
HEADER_SIZE = 64
MAX_W, MAX_H = 1920, 1080
JSON_OFFSET = HEADER_SIZE + MAX_W * MAX_H * 4
JSON_MAX = 256 * 1024
FILE_SIZE = JSON_OFFSET + JSON_MAX

J = Vision  # joint name constants
ANKLES = (J.VNHumanBodyPoseObservationJointNameLeftAnkle, J.VNHumanBodyPoseObservationJointNameRightAnkle)
KNEES = (J.VNHumanBodyPoseObservationJointNameLeftKnee, J.VNHumanBodyPoseObservationJointNameRightKnee)

DEFAULT_CONFIG = {
	'corners': {'bl': [0.0, 0.0], 'br': [1.0, 0.0], 'tr': [1.0, 1.0], 'tl': [0.0, 1.0]},
	'lens_k1': 0.0,
	'floor_w': 6.0,            # metres the 0..1 floor u range spans (for speeds / thresholds)
	'floor_d': 4.0,            # metres the 0..1 floor v range spans
	'max_people': 5,
	'margin': 0.15,            # ignore people further than this (in 0..1 units) outside the floor area
	'joint_conf': 0.2,         # minimum ankle confidence
	'match_dist': 0.9,         # m: max jump to still be the same person between frames
	'lost_time': 0.7,          # s: keep a track this long after it was last seen
	'smooth_min_cutoff': 1.2,  # One-Euro filter (lower = smoother, laggier)
	'smooth_beta': 0.6,        # One-Euro filter (higher = less lag when moving fast)
	'step_move_speed': 0.35,   # m/s: a foot faster than this is "lifted"
	'step_plant_speed': 0.15,  # m/s: a lifted foot slower than this for step_plant_time is "planted"
	'step_plant_time': 0.08,   # s
	'step_min_dist': 0.12,     # m: a step must land at least this far from the previous one
}


# ----------------------------------------------------------------------------- geometry
def undistort(p, k1):
	"""Inverse of the lens model in shaders/warp.glsl (observed camera uv -> ideal uv)."""
	if not k1:
		return p
	c = np.asarray(p, float) - 0.5
	u = c.copy()
	for _ in range(6):
		u = c / (1.0 + k1 * float(u @ u))
	return u + 0.5


class FloorMap:
	"""Camera uv -> floor uv (0..1) using the same corner convention as warp.glsl:
	the camera point at corner 'bl' maps to floor (0,0), 'br' to (1,0), 'tr' to (1,1), 'tl' to (0,1)."""

	def __init__(self, cfg):
		c = cfg['corners']
		src = np.float32([c['bl'], c['br'], c['tr'], c['tl']])
		dst = np.float32([[0, 0], [1, 0], [1, 1], [0, 1]])
		self.H = cv2.getPerspectiveTransform(src, dst)
		self.k1 = cfg['lens_k1']

	def __call__(self, cam_uv):
		x, y = undistort(cam_uv, self.k1)
		v = self.H @ np.array([x, y, 1.0])
		return np.array([v[0] / v[2], v[1] / v[2]])


# ----------------------------------------------------------------------------- detection
class Detector:
	"""Vision body pose (ankles) + human rectangles (fallback for people whose ankles are hidden)."""

	def __init__(self):
		self.pose = Vision.VNDetectHumanBodyPoseRequest.alloc().initWithCompletionHandler_(None)
		self.rects = Vision.VNDetectHumanRectanglesRequest.alloc().initWithCompletionHandler_(None)
		self.rects.setUpperBodyOnly_(False)
		self.pb, self.pb_size = None, None

	def _buffer(self, w, h):
		# one reusable CoreVideo buffer (per-frame CGImages leak; see vision_segment.py)
		if self.pb is None or self.pb_size != (w, h):
			err, self.pb = Quartz.CVPixelBufferCreate(
				None, w, h, Quartz.kCVPixelFormatType_32BGRA,
				{Quartz.kCVPixelBufferIOSurfacePropertiesKey: {}}, None)
			if err != 0:
				raise RuntimeError('CVPixelBufferCreate failed ({})'.format(err))
			self.pb_size = (w, h)
		return self.pb

	def __call__(self, bgra, joint_conf):
		with objc.autorelease_pool():
			return self._detect(bgra, joint_conf)

	def _detect(self, bgra, joint_conf):
		h, w = bgra.shape[:2]
		pb = self._buffer(w, h)
		Quartz.CVPixelBufferLockBaseAddress(pb, 0)
		try:
			bpr = Quartz.CVPixelBufferGetBytesPerRow(pb)
			dst = np.frombuffer(Quartz.CVPixelBufferGetBaseAddress(pb).as_buffer(bpr * h), np.uint8)
			dst.reshape(h, bpr // 4, 4)[:, :w] = bgra
		finally:
			Quartz.CVPixelBufferUnlockBaseAddress(pb, 0)
		handler = Vision.VNImageRequestHandler.alloc().initWithCVPixelBuffer_options_(pb, None)
		handler.performRequests_error_([self.pose, self.rects], None)

		people = []   # each: {'feet': [uv|None, uv|None], 'base': uv, 'bbox': [x,y,w,h] or None}
		for obs in (self.pose.results() or []):
			feet = []
			for name in ANKLES:
				pt, err = obs.recognizedPointForJointName_error_(name, None)
				if pt is not None and pt.confidence() >= joint_conf:
					loc = pt.location()
					feet.append([float(loc.x), float(loc.y)])
				else:
					feet.append(None)
			if not any(feet):
				continue
			got = [f for f in feet if f]
			base = [sum(f[0] for f in got) / len(got), min(f[1] for f in got)]
			people.append({'feet': feet, 'base': base, 'bbox': None, 'source': 'pose'})

		for r in (self.rects.results() or []):
			if r.confidence() < 0.3:
				continue
			bb = r.boundingBox()
			x, y, bw, bh = float(bb.origin.x), float(bb.origin.y), float(bb.size.width), float(bb.size.height)
			# skip rectangles that already contain a pose person's feet
			if any(x <= p['base'][0] <= x + bw and y - 0.05 <= p['base'][1] <= y + bh for p in people):
				for p in people:
					if x <= p['base'][0] <= x + bw and y - 0.05 <= p['base'][1] <= y + bh:
						p['bbox'] = [x, y, bw, bh]
				continue
			people.append({'feet': [None, None], 'base': [x + bw / 2, y], 'bbox': [x, y, bw, bh],
			               'source': 'rect'})
		return people


# ----------------------------------------------------------------------------- tracking
class OneEuro:
	def __init__(self, min_cutoff, beta, d_cutoff=1.0):
		self.mc, self.beta, self.dc = min_cutoff, beta, d_cutoff
		self.x = self.dx = None

	@staticmethod
	def _a(cutoff, dt):
		tau = 1.0 / (2 * math.pi * cutoff)
		return 1.0 / (1.0 + tau / dt)

	def __call__(self, x, dt):
		x = np.asarray(x, float)
		if self.x is None:
			self.x, self.dx = x, np.zeros_like(x)
			return x
		dx = (x - self.x) / dt
		self.dx = self.dx + self._a(self.dc, dt) * (dx - self.dx)
		cutoff = self.mc + self.beta * float(np.linalg.norm(self.dx))
		self.x = self.x + self._a(cutoff, dt) * (x - self.x)
		return self.x


class Foot:
	def __init__(self, cfg):
		self.f = OneEuro(cfg['smooth_min_cutoff'] * 2, cfg['smooth_beta'])
		self.pos = None          # smoothed floor uv
		self.prev = None
		self.speed = 0.0         # m/s
		self.lifted = False
		self.slow_time = 0.0
		self.last_step = None    # floor uv of last planted step

	def update(self, uv, dt, cfg, scale):
		"""Returns a step position (floor uv) when this foot just planted, else None."""
		if uv is None:
			return None
		self.prev = self.pos
		self.pos = self.f(uv, dt)
		if self.prev is None:
			self.last_step = self.pos.copy()
			return None
		self.speed = float(np.linalg.norm((self.pos - self.prev) * scale)) / dt
		if self.speed > cfg['step_move_speed']:
			self.lifted, self.slow_time = True, 0.0
		elif self.lifted and self.speed < cfg['step_plant_speed']:
			self.slow_time += dt
			if self.slow_time >= cfg['step_plant_time']:
				self.lifted = False
				if self.last_step is None or np.linalg.norm((self.pos - self.last_step) * scale) >= cfg['step_min_dist']:
					self.last_step = self.pos.copy()
					return self.pos.copy()
		return None


class Track:
	_next_id = 1

	def __init__(self, slot, pos, now, cfg):
		self.id = Track._next_id
		Track._next_id += 1
		self.slot = slot
		self.first_seen = self.last_seen = now
		self.center = OneEuro(cfg['smooth_min_cutoff'], cfg['smooth_beta'])
		self.pos = self.center(pos, 1 / 30)
		self.prev = self.pos.copy()
		self.speed = 0.0
		self.feet = [Foot(cfg), Foot(cfg)]
		self.raw = None


class Tracker:
	def __init__(self):
		self.tracks = {}       # slot -> Track
		self.steps = []        # recent step events
		self.step_count = 0

	def update(self, dets, now, dt, cfg):
		scale = np.array([cfg['floor_w'], cfg['floor_d']])
		max_people = int(cfg['max_people'])
		# greedy nearest-neighbour matching in metres
		pairs = sorted(
			(float(np.linalg.norm((t.pos - d['floor']) * scale)), s, i)
			for s, t in self.tracks.items() for i, d in enumerate(dets))
		used_t, used_d = set(), set()
		for dist, s, i in pairs:
			if dist > cfg['match_dist'] or s in used_t or i in used_d:
				continue
			used_t.add(s)
			used_d.add(i)
			self._apply(self.tracks[s], dets[i], now, dt, cfg, scale)
		for i, d in enumerate(dets):
			if i in used_d:
				continue
			free = [s for s in range(max_people) if s not in self.tracks]
			if not free:
				break
			t = Track(free[0], d['floor'], now, cfg)
			self.tracks[free[0]] = t
			self._apply(t, d, now, dt, cfg, scale)
		for s in [s for s, t in self.tracks.items() if now - t.last_seen > cfg['lost_time'] or s >= max_people]:
			del self.tracks[s]
		cutoff = now - 5.0
		self.steps = [e for e in self.steps if e['time'] >= cutoff]

	def _apply(self, t, d, now, dt, cfg, scale):
		t.last_seen = now
		t.raw = d
		t.prev = t.pos.copy()
		t.pos = t.center(d['floor'], dt)
		t.speed = float(np.linalg.norm((t.pos - t.prev) * scale)) / dt
		for k, foot in enumerate(t.feet):
			hit = foot.update(d['floor_feet'][k], dt, cfg, scale)
			if hit is not None:
				self.step_count += 1
				self.steps.append({'n': self.step_count, 'id': t.id, 'slot': t.slot, 'foot': 'LR'[k],
				                   'u': round(float(hit[0]), 4), 'v': round(float(hit[1]), 4),
				                   'time': round(now, 3)})

	def state(self, now, sizer=None):
		people = []
		for s in sorted(self.tracks):
			t = self.tracks[s]
			feet = [f.pos.round(4).tolist() if (f.pos is not None and t.raw['floor_feet'][k] is not None) else None
			        for k, f in enumerate(t.feet)]
			sc = sizer.scale(float(t.pos[0]), float(t.pos[1])) if sizer is not None else 1.0
			people.append({'slot': s, 'id': t.id, 'u': round(float(t.pos[0]), 4), 'v': round(float(t.pos[1]), 4),
			               'scale': round(sc, 4),
			               'speed': round(t.speed, 3), 'feet': feet, 'age': round(now - t.first_seen, 2),
			               'seen': round(now - t.last_seen, 2), 'source': t.raw['source']})
		return {'time': round(now, 3), 'count': len(people), 'people': people,
		        'steps': self.steps[-32:], 'step_count': self.step_count}


# ----------------------------------------------------------------------------- auto calibration
ARUCO_DICT = cv2.aruco.DICT_5X5_100


def marker_layout(W, H, cols=6, rows=4):
	"""Marker grid for a W x H content frame.  Returns [(id, x0, y0, size)] in pixels (y down)."""
	size = int(min(W / cols, H / rows) * 0.62)
	out = []
	for r in range(rows):
		for c in range(cols):
			cx = (c + 0.5) * W / cols
			cy = (r + 0.5) * H / rows
			out.append((r * cols + c, int(cx - size / 2), int(cy - size / 2), size))
	return out


def make_markers(path, W, H):
	"""White frame with black ArUco markers (projected through the real output while calibrating)."""
	d = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
	img = np.full((H, W), 255, np.uint8)
	for mid, x0, y0, size in marker_layout(W, H):
		img[y0:y0 + size, x0:x0 + size] = cv2.aruco.generateImageMarker(d, mid, size)
	cv2.imwrite(path, img)
	return path


def content_corners(W, H):
	"""marker id -> its 4 corners in content uv (origin bottom-left), in ArUco's corner order."""
	out = {}
	for mid, x0, y0, s in marker_layout(W, H):
		px = [(x0, y0), (x0 + s, y0), (x0 + s, y0 + s), (x0, y0 + s)]
		out[mid] = np.array([[x / W, 1.0 - y / H] for x, y in px], np.float64)
	return out


def ground_point(uv, tilt_deg, hfov_deg, aspect):
	"""Camera uv (origin bottom-left) -> point on the floor plane (arbitrary scale), assuming a
	pinhole camera with this horizontal FOV, tilted tilt_deg away from pointing straight down,
	no roll.  Used to judge what is 'square on the floor' without anything placed there."""
	fx = 0.5 / np.tan(np.radians(hfov_deg) / 2)            # focal length in units of image width
	x = (uv[0] - 0.5)                                       # camera space: x right, y down, z forward
	y = (0.5 - uv[1]) / aspect                              # (image height = 1/aspect widths)
	d = np.array([x, y, fx])
	t = np.radians(tilt_deg)
	# world: X right, Y away from the camera, Z up.  Straight down: forward=-Z, image-down=-Y.
	fwd = np.array([0.0, np.sin(t), -np.cos(t)])
	down = np.array([0.0, -np.cos(t), -np.sin(t)])
	right = np.array([1.0, 0.0, 0.0])
	w = right * d[0] + down * d[1] + fwd * d[2]
	if w[2] >= -1e-6:
		return None                                         # at or above the horizon
	k = 1.0 / -w[2]                                         # camera at height 1
	return np.array([w[0] * k, w[1] * k])


def _inside(poly, p):
	"""p inside the convex polygon poly (counter-clockwise or clockwise)."""
	sign = 0
	for i in range(len(poly)):
		a, b = poly[i], poly[(i + 1) % len(poly)]
		c = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
		if abs(c) < 1e-12:
			continue
		if sign == 0:
			sign = np.sign(c)
		elif np.sign(c) != sign:
			return False
	return True


def largest_rect(quad, aspect):
	"""Largest rectangle of the given aspect (w/h) inside a convex quad (bl, br, tr, tl),
	aligned with the quad's bottom edge.  Returns its corners bl, br, tr, tl."""
	ex = quad[1] - quad[0]
	ex = ex / np.linalg.norm(ex)
	ey = np.array([-ex[1], ex[0]])
	if np.dot(quad[3] - quad[0], ey) < 0:
		ey = -ey
	loc = np.array([[np.dot(p - quad[0], ex), np.dot(p - quad[0], ey)] for p in quad])
	lo, hi = loc.min(axis=0), loc.max(axis=0)
	best = None
	for _ in range(2):                                      # coarse, then refine around the best
		cxs = np.linspace(lo[0], hi[0], 41) if best is None else best[0][0] + np.linspace(-1, 1, 21) * (hi[0] - lo[0]) / 40
		cys = np.linspace(lo[1], hi[1], 41) if best is None else best[0][1] + np.linspace(-1, 1, 21) * (hi[1] - lo[1]) / 40
		for cx in cxs:
			for cy in cys:
				h_lo, h_hi = 0.0, (hi[1] - lo[1])
				for _ in range(22):                         # biggest height that fits at this centre
					h = 0.5 * (h_lo + h_hi)
					w = h * aspect
					corners = [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]
					if all(_inside(loc, c) for c in corners):
						h_lo = h
					else:
						h_hi = h
				if best is None or h_lo > best[1]:
					best = ((cx, cy), h_lo)
	(cx, cy), h = best
	w = h * aspect
	rect = [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]
	return np.array([quad[0] + ex * x + ey * y for x, y in rect])


class SizeCompensation:
	"""How much bigger/smaller one unit of content looks on the floor at a given content uv,
	relative to the centre.  A projector aimed down at an angle stretches its far side; multiply
	a circle's size by scale(u, v) to keep it the same size on the floor everywhere."""

	def __init__(self, fmap, cfg, cam_aspect):
		self.Hinv = np.linalg.inv(fmap.H)              # content uv -> (undistorted) camera uv
		self.tilt = float(cfg.get('camera_tilt', 0.0))
		self.fov = float(cfg.get('camera_fov', 70.0))
		self.aspect = cam_aspect
		self.ref = self._mag(0.5, 0.5)

	def _floor(self, u, v):
		c = cv2.perspectiveTransform(np.array([[[u, v]]], np.float64), self.Hinv)[0, 0]
		return ground_point(c, self.tilt, self.fov, self.aspect)

	def _mag(self, u, v, e=0.01):
		p0, pu, pv = self._floor(u, v), self._floor(u + e, v), self._floor(u, v + e)
		if p0 is None or pu is None or pv is None:
			return None
		J = np.column_stack([(pu - p0) / e, (pv - p0) / e])
		return float(np.sqrt(abs(np.linalg.det(J))))

	def scale(self, u, v):
		m = self._mag(u, v)
		if m is None or not self.ref:
			return 1.0
		return float(np.clip(self.ref / m, 0.25, 4.0))


class Calibrator:
	"""Auto calibration using only the projector and the camera.
	The projector shows a marker pattern (through the real output path); the camera finds it.
	  * tracking: camera uv -> content uv, so circles land under people's feet;
	  * output warp (warp_mode 'auto'): using the camera tilt / FOV estimate, the largest
	    undistorted rectangle (content aspect) inside the projected area is found on the floor,
	    and the content is pre-warped to fill it."""
	SETTLE, COLLECT = 0.8, 2.0

	def __init__(self):
		self.det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(ARUCO_DICT),
		                                   cv2.aruco.DetectorParameters())
		self.seen_request = None
		self.active = None

	def start(self, request, W, H, now, cfg=None):
		self.active = {'request': request, 't0': now, 'cam': [], 'content': [], 'ids': set(), 'frames': 0,
		               'ref': content_corners(W, H), 'W': W, 'H': H, 'cfg': dict(cfg or {}), 'shape': None}

	def detect(self, bgra):
		gray = cv2.cvtColor(bgra, cv2.COLOR_BGRA2GRAY)
		h, w = gray.shape
		corners, ids, _ = self.det.detectMarkers(gray)
		out = []
		if ids is not None:
			for c, i in zip(corners, ids.flatten()):
				q = c.reshape(4, 2).astype(np.float64)
				out.append((int(i), np.column_stack([q[:, 0] / w, 1.0 - q[:, 1] / h])))
		return out

	def update(self, bgra, now):
		a = self.active
		if a is None:
			return None
		a['shape'] = bgra.shape[:2]
		t = now - a['t0']
		if self.SETTLE <= t < self.SETTLE + self.COLLECT:
			a['frames'] += 1
			for mid, cam in self.detect(bgra):
				if mid in a['ref']:
					a['cam'].append(cam)
					a['content'].append(a['ref'][mid])
					a['ids'].add(mid)
			return None
		if t < self.SETTLE:
			return None
		self.active = None
		return self.solve(a)

	@staticmethod
	def solve(a):
		res = {'request': a['request'], 'ok': False, 'markers': len(a['ids']), 'frames': a['frames'],
		       'of': len(a['ref'])}
		if len(a['ids']) < 4:
			res['message'] = 'only {} of {} markers seen -- is the pattern projected and in the camera view?'.format(
				len(a['ids']), len(a['ref']))
			return res
		cam = np.concatenate(a['cam']).astype(np.float64)
		con = np.concatenate(a['content']).astype(np.float64)
		H, inl = cv2.findHomography(cam, con, cv2.RANSAC, 0.01)       # camera uv -> projector uv
		if H is None:
			res['message'] = 'could not solve the mapping'
			return res
		inl = inl.ravel().astype(bool)
		proj = cv2.perspectiveTransform(cam[inl].reshape(-1, 1, 2), H).reshape(-1, 2)
		err = np.sqrt(np.mean(np.sum(((proj - con[inl]) * [a['W'], a['H']]) ** 2, axis=1)))
		keys = ('bl', 'br', 'tr', 'tl')
		unit = np.array([[[0, 0]], [[1, 0]], [[1, 1]], [[0, 1]]], np.float64)
		rnd = lambda q: {k: [round(float(x), 5), round(float(y), 5)] for k, (x, y) in zip(keys, q)}
		res.update(ok=True, error_px=round(float(err), 2), inliers=int(inl.sum()), points=int(len(cam)))
		measured = {'H': H, 'shape': a['shape'] or (720, 1280), 'W': a['W'], 'Hc': a['H'],
		            'base': '{} of {} markers, fit error {:.1f} px'.format(len(a['ids']), len(a['ref']), err)}
		return Calibrator.geometry(res, measured, a['cfg'])

	@staticmethod
	def geometry(res, m, cfg):
		"""Tracker corners + output warp from a measured camera->projector mapping.  Cheap: it is
		re-run whenever Camera Tilt / FOV / warp mode change, without projecting markers again."""
		res = dict(res, measured=None)
		H = m['H']
		keys = ('bl', 'br', 'tr', 'tl')
		unit = np.array([[[0, 0]], [[1, 0]], [[1, 1]], [[0, 1]]], np.float64)
		rnd = lambda q: {k: [round(float(x), 5), round(float(y), 5)] for k, (x, y) in zip(keys, q)}
		proj_quad_cam = cv2.perspectiveTransform(unit, np.linalg.inv(H)).reshape(4, 2)  # projector corners, camera uv
		msg = m['base']
		res.pop('proj_corners', None)
		if cfg.get('warp_mode', 'off') == 'auto':
			ch, cw = m['shape']
			tilt, fov = float(cfg.get('camera_tilt', 0.0)), float(cfg.get('camera_fov', 70.0))
			floor = [ground_point(p, tilt, fov, cw / ch) for p in proj_quad_cam]
			if any(f is None for f in floor):
				res['corners'] = rnd(proj_quad_cam)
				res['message'] = msg + '; projected area reaches the horizon for this camera tilt -- lower Camera Tilt'
				return res
			rect = largest_rect(np.array(floor), m['W'] / m['Hc'])
			# floor rectangle -> camera uv (numerically invert ground_point through a homography fit)
			grid = np.array([[u, v] for u in np.linspace(0, 1, 9) for v in np.linspace(0, 1, 9)])
			gp = [ground_point(p, tilt, fov, cw / ch) for p in grid]
			ok = [g is not None for g in gp]
			Hg, _ = cv2.findHomography(np.array([g for g in gp if g is not None]), grid[ok])
			rect_cam = cv2.perspectiveTransform(rect.reshape(-1, 1, 2), Hg).reshape(4, 2)
			pc = cv2.perspectiveTransform(rect_cam.reshape(-1, 1, 2), H).reshape(4, 2)   # in projector uv
			Hout = cv2.getPerspectiveTransform(unit.reshape(4, 2).astype(np.float32), pc.astype(np.float32))
			res['proj_corners'] = rnd(cv2.perspectiveTransform(unit, np.linalg.inv(Hout)).reshape(4, 2))
			res['corners'] = rnd(rect_cam)
			msg += '; output squared up for camera tilt {:.0f} deg'.format(tilt)
		else:
			res['corners'] = rnd(proj_quad_cam)
		res['message'] = msg
		res['measured'] = m
		return res


def write_json_atomic(path, obj):
	tmp = path + '.tmp'
	with open(tmp, 'w') as f:
		json.dump(obj, f)
	os.replace(tmp, path)


# ----------------------------------------------------------------------------- output
class Publisher:
	def __init__(self, path):
		if not os.path.exists(path) or os.path.getsize(path) != FILE_SIZE:
			with open(path, 'wb') as f:
				f.truncate(FILE_SIZE)
		self.f = open(path, 'r+b')            # never truncate: TouchDesigner may have it mapped
		self.mm = mmap.mmap(self.f.fileno(), FILE_SIZE)
		self.seq = HEADER.unpack_from(self.mm, 0)[2] & ~1

	def publish(self, rgba_bottom_up, state):
		h, w = rgba_bottom_up.shape[:2]
		js = json.dumps(state, separators=(',', ':')).encode()[:JSON_MAX]
		self.seq += 1
		self.mm[:HEADER.size] = HEADER.pack(b'FLT1', 1, self.seq, w, h, len(js))
		self.mm[HEADER_SIZE:HEADER_SIZE + rgba_bottom_up.nbytes] = rgba_bottom_up.tobytes()
		self.mm[JSON_OFFSET:JSON_OFFSET + len(js)] = js
		self.seq += 1
		self.mm[:HEADER.size] = HEADER.pack(b'FLT1', 1, self.seq, w, h, len(js))


COLORS = [(255, 80, 80), (80, 220, 80), (80, 140, 255), (255, 210, 60), (220, 80, 255), (80, 230, 230)]


def draw_debug(rgb, dets, tracker):
	"""Draw detections (camera image space, top-down rows) for the calibration view."""
	h, w = rgb.shape[:2]
	px = lambda uv: (int(uv[0] * w), int((1 - uv[1]) * h))
	slot_of = {id(t.raw): s for s, t in tracker.tracks.items() if t.raw is not None}
	for d in dets:
		s = slot_of.get(id(d))
		col = COLORS[s % len(COLORS)] if s is not None else (160, 160, 160)
		if d['bbox']:
			x, y, bw, bh = d['bbox']
			cv2.rectangle(rgb, px((x, y + bh)), px((x + bw, y)), col, 2)
		for f in d['feet']:
			if f:
				cv2.circle(rgb, px(f), 7, col, -1)
		cv2.circle(rgb, px(d['base']), 4, (255, 255, 255), -1)
		if s is not None:
			cv2.putText(rgb, 'P{}'.format(s), px((d['base'][0], d['base'][1] + 0.02)),
			            cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, 2)


# ----------------------------------------------------------------------------- main
def load_config(path, cache):
	try:
		m = os.path.getmtime(path)
	except OSError:
		return cache.get('cfg') or dict(DEFAULT_CONFIG)
	if cache.get('mtime') != m:
		cfg = dict(DEFAULT_CONFIG)
		try:
			with open(path) as f:
				cfg.update(json.load(f))
			print('config loaded from {}'.format(path), flush=True)
		except (OSError, ValueError) as e:
			print('config error ({}), keeping previous'.format(e), flush=True)
			return cache.get('cfg') or cfg
		cache.update(mtime=m, cfg=cfg, map=FloorMap(cfg))
	return cache['cfg']


def process(frame_bgra, detector, tracker, cfg, fmap, now, dt):
	dets = detector(frame_bgra, cfg['joint_conf'])
	keep = []
	m = cfg['margin']
	for d in dets:
		d['floor'] = fmap(d['base'])
		d['floor_feet'] = [fmap(f) if f else None for f in d['feet']]
		if -m <= d['floor'][0] <= 1 + m and -m <= d['floor'][1] <= 1 + m:
			keep.append(d)
	tracker.update(keep, now, dt, cfg)
	return dets


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument('--camera', default='0', help='unique ID, index, name substring, a video file, or td:/path.bin')
	ap.add_argument('--camera-name', default='', help='fallback: exact camera name if the ID is not found')
	ap.add_argument('--file', default='/tmp/floor_track.bin')
	ap.add_argument('--config', default='/tmp/floor_track_config.json')
	ap.add_argument('--width', type=int, default=1280)
	ap.add_argument('--height', type=int, default=720)
	ap.add_argument('--parent-pid', type=int, default=0)
	ap.add_argument('--max-mb', type=int, default=1500)
	ap.add_argument('--list', action='store_true')
	ap.add_argument('--make-markers', help='write the auto-calibration marker pattern PNG and exit')
	ap.add_argument('--mw', type=int, default=1920)
	ap.add_argument('--mh', type=int, default=1080)
	a = ap.parse_args()
	if a.make_markers:
		print('markers written to', make_markers(a.make_markers, a.mw, a.mh))
		return
	if a.list:
		for i, d in enumerate(devices()):
			print('{}\t{}\t{}'.format(i, d.uniqueID(), d.localizedName()))
		return

	def on_term(signum, _frame):
		print('stopped by signal {}'.format(signum), flush=True)
		os._exit(0)
	signal.signal(signal.SIGTERM, on_term)

	cam, label, first_timeout = open_camera(a.camera, a.camera_name, a.width, a.height)
	frame = cam.read(timeout=first_timeout)
	if frame is None:
		raise SystemExit('no frames from camera {} within {:.0f} s'.format(label, first_timeout))
	h, w = frame.shape[:2]
	scale = min(1.0, MAX_W / w, MAX_H / h)
	w, h = int(w * scale), int(h * scale)
	pub = Publisher(a.file)
	detector, tracker, cache, calib = Detector(), Tracker(), {}, Calibrator()
	adjust = CameraAdjust()
	last_result, last_geo, revision = None, None, 0
	print('tracking camera "{}" at {}x{} -> {}'.format(label, w, h, a.file), flush=True)
	rgba = np.empty((h, w, 4), np.uint8)
	t_prev = time.time()
	n, t0, last_check = 0, time.time(), time.time()
	while True:
		with objc.autorelease_pool():
			frame = cam.read(timeout=2.0)
			now = time.time()
			if frame is not None:
				if frame.shape[1] != w:
					frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
				cfg = load_config(a.config, cache)
				ckey = (cfg.get('cam_exposure', 0.0), cfg.get('cam_contrast', 1.0))
				if cache.get('cam_key') != ckey:
					adjust.set(*ckey)
					cache['cam_key'] = ckey
				frame = adjust(frame)                          # exposure / contrast before tracking
				req = cfg.get('calib_request')
				if calib.seen_request is None:
					calib.seen_request = req                 # don't re-run an old request at startup
				elif req != calib.seen_request:
					calib.seen_request = req
					calib.start(req, int(cfg.get('pattern_w', 1920)), int(cfg.get('pattern_h', 1080)), now, cfg)
					print('auto-calibration {} started'.format(req), flush=True)
				result = calib.update(frame, now)
				geo_key = (cfg.get('warp_mode'), cfg.get('camera_tilt'), cfg.get('camera_fov'))
				if result is None and last_result is not None and geo_key != last_geo:
					result = Calibrator.geometry(last_result, last_result['measured'], cfg)   # slider moved
				if result is not None:
					last_geo = geo_key
					if result.get('ok'):
						last_result = result
					revision += 1
					out = {k: v for k, v in result.items() if k != 'measured'}
					out['revision'] = revision
					write_json_atomic(cfg.get('calib_result_file', '/tmp/floor_track_calib.json'), out)
					print('auto-calibration:', result.get('message'), flush=True)
				dt = max(1e-3, min(0.2, now - t_prev))
				t_prev = now
				dets = process(frame, detector, tracker, cfg, cache['map'] if 'map' in cache else FloorMap(cfg),
				               now, dt)
				rgb = np.ascontiguousarray(frame[..., 2::-1])
				draw_debug(rgb, dets, tracker)
				rgba[..., :3] = rgb
				rgba[..., 3] = 255
				sizer = None
				if cfg.get('constant_size', True) and 'map' in cache:
					key = (id(cache['map']), cfg.get('camera_tilt'), cfg.get('camera_fov'), w, h)
					if cache.get('sizer_key') != key:
						cache['sizer'], cache['sizer_key'] = SizeCompensation(cache['map'], cfg, w / h), key
					sizer = cache['sizer']
				pub.publish(rgba[::-1], tracker.state(now, sizer))
				n += 1
		if now - t0 >= 10.0:
			print('{:.1f} fps, {} people, {} steps, peak memory {} MB'.format(
				n / (now - t0), len(tracker.tracks), tracker.step_count, rss_mb()), flush=True)
			n, t0 = 0, now
		if now - last_check > 2.0:
			last_check = now
			if not parent_alive(a.parent_pid):
				print('TouchDesigner (pid {}) has exited; stopping'.format(a.parent_pid), flush=True)
				break
			if a.max_mb and rss_mb() > a.max_mb:
				print('memory above {} MB; exiting so TouchDesigner restarts a fresh helper'.format(a.max_mb),
				      flush=True)
				break


if __name__ == '__main__':
	sys.exit(main())
