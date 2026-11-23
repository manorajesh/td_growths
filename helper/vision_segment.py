"""
Person segmentation helper for the Silhouette Wall (macOS, Apple Vision).

Captures one webcam, runs Apple's VNGeneratePersonSegmentationRequest (Neural Engine),
and publishes each frame to a memory-mapped file that TouchDesigner reads with a Script TOP:

    header (64 bytes): magic b'SIL1', version, seq (uint64, odd while writing), width, height
    pixels: width*height*4 uint8 RGBA, bottom row first (TouchDesigner order),
            RGB = camera, A = person mask (255 = person)

TouchDesigner normally launches this itself (side_X > Input > Start Helper).  Manual use:

    helper/.venv/bin/python helper/vision_segment.py --list          # index, unique ID, name
    helper/.venv/bin/python helper/vision_segment.py --camera C922 --file /tmp/silhouette_L.bin

Cameras are opened through AVFoundation by unique ID, so the device you pick is the device
you get (OpenCV's device numbering does not match macOS's camera list).
    helper/.venv/bin/python helper/vision_segment.py --test-image photo.jpg   # writes photo_mask.png
"""
import argparse
import json
import mmap
import os
import signal
import struct
import sys
import threading
import time

import cv2
import numpy as np
import AVFoundation as AV
import CoreMedia
import objc
import Quartz
import Vision
from dispatch import dispatch_queue_create
from Foundation import NSObject

HEADER = struct.Struct('<4sIQII')
HEADER_SIZE = 64
MAX_W, MAX_H = 1920, 1080
FILE_SIZE = HEADER_SIZE + MAX_W * MAX_H * 4   # fixed, so a reader's mapping never becomes invalid
QUALITY = {
	'fast': Vision.VNGeneratePersonSegmentationRequestQualityLevelFast,
	'balanced': Vision.VNGeneratePersonSegmentationRequestQualityLevelBalanced,
	'accurate': Vision.VNGeneratePersonSegmentationRequestQualityLevelAccurate,
}


def devices():
	return list(AV.AVCaptureDevice.devicesWithMediaType_(AV.AVMediaTypeVideo))


def resolve_camera(spec, name=None):
	"""Unique ID (exact), index ('0'), or case-insensitive name substring ('C922').
	If a saved unique ID is not present (e.g. the patch moved to another Mac, or a USB camera
	moved to another port), fall back to the camera's name."""
	devs = devices()
	for d in devs:
		if d.uniqueID() == spec:
			return d
	if name:
		for d in devs:
			if d.localizedName() == name:
				print('camera ID {} not found; using "{}" by name [{}]'.format(spec, name, d.uniqueID()), flush=True)
				return d
	if spec.isdigit() and int(spec) < len(devs):
		return devs[int(spec)]
	for d in devs:
		if spec.lower() in d.localizedName().lower():
			return d
	raise SystemExit('camera "{}" not found; available: {}'.format(
		spec, [(d.uniqueID(), d.localizedName()) for d in devs]))


SampleDelegate = objc.protocolNamed('AVCaptureVideoDataOutputSampleBufferDelegate')


class FrameGrabber(NSObject, protocols=[SampleDelegate]):
	"""Receives camera frames on a dispatch queue and keeps only the newest one (BGRA)."""

	def init(self):
		self = objc.super(FrameGrabber, self).init()
		if self is None:
			return None
		self.lock = threading.Lock()
		self.event = threading.Event()
		self.frame = None
		self.count = 0
		return self

	def captureOutput_didOutputSampleBuffer_fromConnection_(self, output, sbuf, conn):
		pb = CoreMedia.CMSampleBufferGetImageBuffer(sbuf)
		if pb is None:
			return
		Quartz.CVPixelBufferLockBaseAddress(pb, Quartz.kCVPixelBufferLock_ReadOnly)
		try:
			w, h = Quartz.CVPixelBufferGetWidth(pb), Quartz.CVPixelBufferGetHeight(pb)
			bpr = Quartz.CVPixelBufferGetBytesPerRow(pb)
			base = Quartz.CVPixelBufferGetBaseAddress(pb)
			img = np.frombuffer(base.as_buffer(bpr * h), np.uint8).reshape(h, bpr // 4, 4)[:, :w].copy()
		finally:
			Quartz.CVPixelBufferUnlockBaseAddress(pb, Quartz.kCVPixelBufferLock_ReadOnly)
		with self.lock:
			self.frame = img
			self.count += 1
		self.event.set()

	@objc.python_method
	def latest(self, timeout):
		if not self.event.wait(timeout):
			return None
		with self.lock:
			self.event.clear()
			return self.frame


class AVCamera:
	def __init__(self, device, width, height):
		self.device = device
		inp, err = AV.AVCaptureDeviceInput.deviceInputWithDevice_error_(device, None)
		if inp is None:
			raise SystemExit('cannot open camera "{}": {}'.format(device.localizedName(), err))
		self.session = AV.AVCaptureSession.alloc().init()
		for preset in ({(1920, 1080): AV.AVCaptureSessionPreset1920x1080,
		                (1280, 720): AV.AVCaptureSessionPreset1280x720,
		                (640, 480): AV.AVCaptureSessionPreset640x480}.get((width, height)),
		               AV.AVCaptureSessionPreset1280x720, AV.AVCaptureSessionPresetHigh):
			if preset and self.session.canSetSessionPreset_(preset):
				self.session.setSessionPreset_(preset)
				break
		self.session.addInput_(inp)
		out = AV.AVCaptureVideoDataOutput.alloc().init()
		out.setVideoSettings_({Quartz.kCVPixelBufferPixelFormatTypeKey: Quartz.kCVPixelFormatType_32BGRA})
		out.setAlwaysDiscardsLateVideoFrames_(True)
		self.grabber = FrameGrabber.alloc().init()
		self.queue = dispatch_queue_create(b'silhouette.camera', None)
		out.setSampleBufferDelegate_queue_(self.grabber, self.queue)
		if not self.session.canAddOutput_(out):
			raise SystemExit('cannot add video output for "{}"'.format(device.localizedName()))
		self.session.addOutput_(out)
		self.out = out
		self.session.startRunning()

	def read(self, timeout=2.0):
		return self.grabber.latest(timeout)   # BGRA or None


CAM_HEADER = struct.Struct('<4sIQII')     # b'CAM1', version, seq (odd while writing), width, height
CAM_FILE_SIZE = HEADER_SIZE + MAX_W * MAX_H * 4


class SharedFrameCamera:
	"""Frames written by TouchDesigner (e.g. a VDO.Ninja phone stream in a Web Render TOP).
	File: 64-byte header + RGBA uint8 rows, bottom row first (TouchDesigner's numpyArray order)."""

	def __init__(self, path):
		self.path, self.mm, self.f, self.seq = path, None, None, -1

	def _open(self):
		if self.mm is None and os.path.exists(self.path) and os.path.getsize(self.path) == CAM_FILE_SIZE:
			self.f = open(self.path, 'rb')
			self.mm = mmap.mmap(self.f.fileno(), CAM_FILE_SIZE, access=mmap.ACCESS_READ)

	def read(self, timeout=2.0):
		t0 = time.time()
		while time.time() - t0 < timeout:
			self._open()
			if self.mm is not None:
				magic, ver, seq, w, h = CAM_HEADER.unpack_from(self.mm, 0)
				if magic == b'CAM1' and seq % 2 == 0 and seq != self.seq and 0 < w * h * 4 <= CAM_FILE_SIZE - HEADER_SIZE:
					a = np.frombuffer(self.mm, np.uint8, w * h * 4, HEADER_SIZE).reshape(h, w, 4).copy()
					if CAM_HEADER.unpack_from(self.mm, 0)[2] == seq:
						self.seq = seq
						return cv2.cvtColor(np.ascontiguousarray(a[::-1]), cv2.COLOR_RGBA2BGRA)
			time.sleep(0.004)
		return None


class CameraAdjust:
	"""Exposure (stops) and contrast applied to every camera frame BEFORE segmentation/tracking,
	via a 256-entry lookup table.  Values come from a small JSON file TouchDesigner writes
	({"exposure": stops, "contrast": x}); it is re-read whenever it changes."""

	def __init__(self, path=None, exposure=0.0, contrast=1.0):
		self.path, self.mtime, self.lut = path, None, None
		self.set(exposure, contrast)

	def set(self, exposure, contrast):
		x = np.arange(256, dtype=np.float32) / 255.0
		y = (x * (2.0 ** float(exposure)) - 0.5) * float(contrast) + 0.5
		lut = np.clip(y * 255.0 + 0.5, 0, 255).astype(np.uint8)
		self.lut = None if (exposure == 0 and contrast == 1) else lut

	def poll(self):
		if not self.path:
			return
		try:
			m = os.path.getmtime(self.path)
		except OSError:
			return
		if m != self.mtime:
			self.mtime = m
			try:
				with open(self.path) as f:
					c = json.load(f)
				self.set(c.get('exposure', 0.0), c.get('contrast', 1.0))
				print('camera adjust: exposure {:+.2f} stops, contrast {:.2f}'.format(
					c.get('exposure', 0.0), c.get('contrast', 1.0)), flush=True)
			except (OSError, ValueError):
				pass

	def __call__(self, bgra):
		if self.lut is None:
			return bgra
		out = bgra.copy()
		out[..., :3] = cv2.LUT(bgra[..., :3], self.lut)
		return out


def open_camera(spec, name, width, height):
	"""-> (camera, label, first-frame timeout).  spec: unique ID / index / name, a video file,
	or 'td:/path/file.bin' for frames sent by TouchDesigner (phone via VDO.Ninja)."""
	if spec.startswith('td:'):
		return SharedFrameCamera(spec[3:]), 'TouchDesigner stream ' + spec[3:], 60.0
	if os.path.isfile(spec):
		return FileCamera(spec), os.path.basename(spec), 10.0
	dev = resolve_camera(spec, name)
	return AVCamera(dev, width, height), '{} [{}]'.format(dev.localizedName(), dev.uniqueID()), 10.0


class FileCamera:
	"""A video file in place of a camera (for testing)."""

	def __init__(self, path):
		self.cap = cv2.VideoCapture(path)

	def read(self, timeout=2.0):
		ok, f = self.cap.read()
		if not ok:
			self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
			ok, f = self.cap.read()
		time.sleep(1 / 30)
		return cv2.cvtColor(f, cv2.COLOR_BGR2BGRA) if ok else None


class Segmenter:
	def __init__(self, quality):
		self.req = Vision.VNGeneratePersonSegmentationRequest.alloc().initWithCompletionHandler_(None)
		self.req.setQualityLevel_(QUALITY[quality])
		self.req.setOutputPixelFormat_(Quartz.kCVPixelFormatType_OneComponent8)
		self.pb, self.pb_size = None, None
		self.handler = Vision.VNSequenceRequestHandler.alloc().init()   # keeps temporal state
		# Gate: the segmenter can hallucinate a "person" in an empty scene, so only pass the
		# mask through if a human detector has seen someone recently.
		# (upper-body rectangles OR body pose: in testing the full-body detector missed clear
		# people, while these two caught them and stayed silent on empty scenes.)
		self.det = [Vision.VNDetectHumanRectanglesRequest.alloc().initWithCompletionHandler_(None),
		            Vision.VNDetectHumanBodyPoseRequest.alloc().initWithCompletionHandler_(None)]
		self.det[0].setUpperBodyOnly_(True)
		self.det_every = 3
		self.gate_frames = 0
		self.last_seen = -10 ** 9
		self.frame = 0
		self.humans = 0

	def __call__(self, bgra):
		# Drain the autorelease pool every frame so per-frame Vision objects are freed.
		with objc.autorelease_pool():
			return self._segment(bgra)

	def _buffer(self, w, h):
		"""One reusable, CoreVideo-owned BGRA pixel buffer.  (Wrapping each frame in a new
		CGImage leaked the whole frame every time: ~110 MB/s per camera.)"""
		if self.pb is None or self.pb_size != (w, h):
			err, self.pb = Quartz.CVPixelBufferCreate(
				None, w, h, Quartz.kCVPixelFormatType_32BGRA,
				{Quartz.kCVPixelBufferIOSurfacePropertiesKey: {}}, None)
			if err != 0:
				raise RuntimeError('CVPixelBufferCreate failed ({})'.format(err))
			self.pb_size = (w, h)
		return self.pb

	def _segment(self, bgra):
		h, w = bgra.shape[:2]
		pb = self._buffer(w, h)
		Quartz.CVPixelBufferLockBaseAddress(pb, 0)
		try:
			bpr = Quartz.CVPixelBufferGetBytesPerRow(pb)
			dst = np.frombuffer(Quartz.CVPixelBufferGetBaseAddress(pb).as_buffer(bpr * h), np.uint8)
			dst.reshape(h, bpr // 4, 4)[:, :w] = bgra
		finally:
			Quartz.CVPixelBufferUnlockBaseAddress(pb, 0)
		detect = self.gate_frames > 0 and self.frame % self.det_every == 0
		reqs = [self.req] + (self.det if detect else [])
		ok, err = self.handler.performRequests_onCVPixelBuffer_error_(reqs, pb, None)
		self.frame += 1
		if detect:
			self.humans = max(sum(1 for r in (d.results() or []) if r.confidence() > 0.3) for d in self.det)
			if self.humans:
				self.last_seen = self.frame
		if self.gate_frames > 0:
			if self.frame - self.last_seen > self.gate_frames:
				return np.zeros((h, w), np.uint8)
		res = self.req.results()
		if not ok or not res:
			return np.zeros((h, w), np.uint8)
		mb = res[0].pixelBuffer()
		Quartz.CVPixelBufferLockBaseAddress(mb, Quartz.kCVPixelBufferLock_ReadOnly)
		try:
			mw, mh = Quartz.CVPixelBufferGetWidth(mb), Quartz.CVPixelBufferGetHeight(mb)
			bpr = Quartz.CVPixelBufferGetBytesPerRow(mb)
			base = Quartz.CVPixelBufferGetBaseAddress(mb)
			m = np.frombuffer(base.as_buffer(bpr * mh), np.uint8).reshape(mh, bpr)[:, :mw].copy()
		finally:
			Quartz.CVPixelBufferUnlockBaseAddress(mb, Quartz.kCVPixelBufferLock_ReadOnly)
		return cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR)


class Publisher:
	def __init__(self, path, w, h):
		self.w, self.h = w, h
		if not os.path.exists(path) or os.path.getsize(path) != FILE_SIZE:
			with open(path, 'wb') as f:
				f.truncate(FILE_SIZE)
		self.f = open(path, 'r+b')            # never truncate an existing file: TD may have it mapped
		self.mm = mmap.mmap(self.f.fileno(), FILE_SIZE)
		self.seq = HEADER.unpack_from(self.mm, 0)[2] & ~1   # continue the sequence so TD sees new frames
		self._header()

	def _header(self):
		self.mm[:HEADER.size] = HEADER.pack(b'SIL1', 1, self.seq, self.w, self.h)

	def publish(self, rgba_bottom_up):
		self.seq += 1                       # odd: writing
		self._header()
		self.mm[HEADER_SIZE:HEADER_SIZE + rgba_bottom_up.nbytes] = rgba_bottom_up.tobytes()
		self.seq += 1                       # even: complete
		self._header()


def parent_alive(pid):
	if not pid:
		return True
	try:
		os.kill(pid, 0)
		return True
	except OSError:
		return False


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument('--camera', default='0', help='unique ID, index, name substring, a video file, or td:/path.bin')
	ap.add_argument('--camera-name', default='', help='fallback: exact camera name if the ID is not found')
	ap.add_argument('--file', default='/tmp/silhouette_L.bin')
	ap.add_argument('--width', type=int, default=1280)
	ap.add_argument('--height', type=int, default=720)
	ap.add_argument('--quality', choices=QUALITY, default='balanced')
	ap.add_argument('--gate', type=int, default=20,
	                help='frames the mask stays on after the human detector last saw someone (0 = no gate)')
	ap.add_argument('--cam-config', default='', help='JSON with camera exposure/contrast (re-read live)')
	ap.add_argument('--parent-pid', type=int, default=0, help='exit when this process ends')
	ap.add_argument('--max-mb', type=int, default=1500, help='exit if memory exceeds this (0 = no limit)')
	ap.add_argument('--list', action='store_true')
	ap.add_argument('--test-image')
	a = ap.parse_args()

	if a.list:
		for i, d in enumerate(devices()):
			print('{}\t{}\t{}'.format(i, d.uniqueID(), d.localizedName()))
		return
	seg = Segmenter(a.quality)
	seg.gate_frames = a.gate
	if a.test_image:
		bgra = cv2.cvtColor(cv2.imread(a.test_image), cv2.COLOR_BGR2BGRA)
		t = time.time()
		m = seg(bgra)
		out = os.path.splitext(a.test_image)[0] + '_mask.png'
		cv2.imwrite(out, m)
		print('mask {} in {:.0f} ms, humans detected {}, person pixels {:.1%} -> {}'.format(
			m.shape, (time.time() - t) * 1000, seg.humans, (m > 127).mean(), out))
		return

	def on_term(signum, _frame):
		print('stopped by signal {}'.format(signum), flush=True)
		os._exit(0)
	signal.signal(signal.SIGTERM, on_term)

	cam, label, first_timeout = open_camera(a.camera, a.camera_name, a.width, a.height)
	frame = cam.read(timeout=first_timeout)
	if frame is None:
		raise SystemExit('no frames from camera {} within {:.0f} s (in use by another app, no camera '
		                 'permission, or the phone stream is not playing?)'.format(label, first_timeout))
	h, w = frame.shape[:2]
	scale = min(1.0, MAX_W / w, MAX_H / h)
	if scale < 1.0:
		w, h = int(w * scale), int(h * scale)
	pub = Publisher(a.file, w, h)
	print('segmenting camera "{}" at {}x{} -> {}'.format(label, w, h, a.file), flush=True)
	rgba = np.empty((h, w, 4), np.uint8)
	adjust = CameraAdjust(a.cam_config)
	adjust.poll()
	n, t0, last_check, last_poll, stalls = 0, time.time(), time.time(), 0.0, 0
	while True:
		with objc.autorelease_pool():
			step = _step(cam, seg, pub, rgba, w, h, adjust)
		if step == 'stop':
			break
		n += step == 'ok'
		now = time.time()
		if now - t0 >= 10.0:
			print('{:.1f} fps, peak memory {} MB'.format(n / (now - t0), rss_mb()), flush=True)
			n, t0 = 0, now
		if now - last_poll > 0.5:                          # pick up exposure/contrast changes
			last_poll = now
			adjust.poll()
		if now - last_check > 2.0:
			last_check = now
			if not parent_alive(a.parent_pid):
				print('TouchDesigner (pid {}) has exited; stopping'.format(a.parent_pid), flush=True)
				break
			if a.max_mb and rss_mb() > a.max_mb:     # safety net for unattended running
				print('memory above {} MB; exiting so TouchDesigner restarts a fresh helper'.format(a.max_mb),
				      flush=True)
				break


def rss_mb():
	import resource
	return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // (1024 * 1024)   # bytes on macOS


_stalls = [0]


def _step(cam, seg, pub, rgba, w, h, adjust=None):
	frame = cam.read(timeout=2.0)
	if frame is None:
		_stalls[0] += 1
		print('no frame from camera for {} s'.format(2 * _stalls[0]), flush=True)
		return 'stall'
	_stalls[0] = 0
	if frame.shape[1] != w:
		frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
	if adjust is not None:
		frame = adjust(frame)
	mask = seg(frame)
	rgba[..., :3] = frame[..., 2::-1]
	rgba[..., 3] = mask
	pub.publish(rgba[::-1])
	return 'ok'


if __name__ == '__main__':
	sys.exit(main())
