// testfigure.glsl -- a swaying stand-in person (white on black) for lookdev without a camera.
uniform vec4 uFig;  // x time  y present (0/1)  z x offset  w scale
layout(location = 0) out vec4 fragColor;
float cap(vec2 p, vec2 a, vec2 b, float r) {
	vec2 pa = p - a, ba = b - a;
	float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
	return length(pa - ba * h) - r;
}
void main() {
	vec2 res = uTDOutputInfo.res.zw;
	float t = uFig.x;
	vec2 p = (vUV.st - vec2(0.5, 0.0)) * vec2(res.x / res.y, 1.0);
	p.x -= uFig.z + 0.012 * sin(t * 0.45);
	p /= max(uFig.w, 0.01);
	float sway = 0.01 * sin(t * 0.7);
	float d = length(p - vec2(sway * 1.3, 0.86)) - 0.062;
	d = min(d, cap(p, vec2(sway, 0.76), vec2(0.0, 0.48), 0.088));
	d = min(d, cap(p, vec2(0.0, 0.50), vec2(0.0, 0.44), 0.1));
	for (int s = -1; s <= 1; s += 2) {
		float fs = float(s);
		vec2 sh = vec2(fs * 0.095 + sway, 0.73);
		vec2 el = sh + vec2(fs * 0.05, -0.15 + 0.02 * sin(t * 0.6 + fs));
		vec2 ha = el + vec2(fs * 0.025, -0.14);
		d = min(d, cap(p, sh, el, 0.034));
		d = min(d, cap(p, el, ha, 0.028));
		vec2 hip = vec2(fs * 0.05, 0.46), kn = vec2(fs * 0.065, 0.24), ft = vec2(fs * 0.075, 0.035);
		d = min(d, cap(p, hip, kn, 0.048));
		d = min(d, cap(p, kn, ft, 0.038));
	}
	float px = 1.5 / res.y / max(uFig.w, 0.01);
	float m = (1.0 - smoothstep(-px, px, d)) * step(0.5, uFig.y);
	fragColor = TDOutputSwizzle(vec4(m, m, m, 1.0));
}
