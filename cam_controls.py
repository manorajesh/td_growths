"""
Camera exposure / contrast controls (used by the build scripts and update_patch.py).

add_cam_controls(comp, page) adds 'Camera Exposure (stops)' and 'Camera Contrast' to a COMP
that runs a segmentation/tracking helper.  The helper applies them to every camera frame
BEFORE segmenting/tracking (so they help detection, not just the look), live.
Safe to call again.
"""


def add_cam_controls(comp, page):
	if not hasattr(comp.par, 'Camexposure'):
		p = page.appendFloat('Camexposure', label='Camera Exposure (stops)')[0]
		p.default = p.val = 0.0
		p.normMin, p.normMax = -3, 3
		p = page.appendFloat('Camcontrast', label='Camera Contrast')[0]
		p.default = p.val = 1.0
		p.normMin, p.normMax = 0.3, 3
