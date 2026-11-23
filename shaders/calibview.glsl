// calibview.glsl -- operator view for keystone calibration.
// Shows the (mirrored) camera with the warp quad, and the 2x3 panel grid projected
// through the warp, so you can see exactly which part of the camera lands on which panel.
// Corner dots: top-left = red, top-right = green, bottom-left = yellow, bottom-right = blue.
// in0: camera image    in1: raw mask source (tinted green)
uniform vec4 uC0;   // xy = camera uv for output bottom-left, zw = bottom-right
uniform vec4 uC1;   // xy = camera uv for output top-right,   zw = top-left
uniform vec4 uOpt;  // x mirror  y lens k1  z grid columns  w grid rows
uniform vec4 uMaskCh;  // x mask channel (0 r,1 g,2 b,3 a,4 luma)  y invert

layout(location = 0) out vec4 fragColor;

mat3 squareToQuad(vec2 p0, vec2 p1, vec2 p2, vec2 p3) {
	float sx = p0.x - p1.x + p2.x - p3.x;
	float sy = p0.y - p1.y + p2.y - p3.y;
	float dx1 = p1.x - p2.x, dx2 = p3.x - p2.x;
	float dy1 = p1.y - p2.y, dy2 = p3.y - p2.y;
	float den = dx1 * dy2 - dx2 * dy1;
	den = abs(den) < 1e-8 ? 1e-8 : den;
	float g = (sx * dy2 - dx2 * sy) / den;
	float h = (dx1 * sy - sx * dy1) / den;
	return mat3(p1.x - p0.x + g * p1.x, p1.y - p0.y + g * p1.y, g,
	            p3.x - p0.x + h * p3.x, p3.y - p0.y + h * p3.y, h,
	            p0.x, p0.y, 1.0);
}

float segDist(vec2 p, vec2 a, vec2 b) {
	vec2 pa = p - a, ba = b - a;
	float h = clamp(dot(pa, ba) / max(dot(ba, ba), 1e-9), 0.0, 1.0);
	return length(pa - ba * h);
}

void main() {
	vec2 uv = vUV.st;
	vec2 su = uv;
	if (uOpt.x > 0.5) su.x = 1.0 - su.x;
	vec3 col = texture(sTD2DInputs[0], su).rgb;
	vec4 ms = texture(sTD2DInputs[1], su);
	int ch = int(uMaskCh.x + 0.5);
	float m = ch == 0 ? ms.r : ch == 1 ? ms.g : ch == 2 ? ms.b : ch == 3 ? ms.a : dot(ms.rgb, vec3(0.299, 0.587, 0.114));
	if (uMaskCh.y > 0.5) m = 1.0 - m;
	col = mix(col, col * 0.5 + vec3(0.0, 0.5, 0.2), 0.35 * m);

	// undistort this pixel (inverse of the lens model in warp.glsl)
	vec2 c = uv - 0.5, u = c;
	for (int i = 0; i < 6; i++) u = c / (1.0 + uOpt.y * dot(u, u));
	vec2 p = u + 0.5;

	vec2 p0 = uC0.xy, p1 = uC0.zw, p2 = uC1.xy, p3 = uC1.zw;
	vec2 px = uTDOutputInfo.res.xy;
	float lw = 1.5 * max(px.x, px.y);

	// panel grid: map camera point back into output (square) space
	vec3 s3 = inverse(squareToQuad(p0, p1, p2, p3)) * vec3(p, 1.0);
	vec2 s = s3.xy / s3.z;
	if (s3.z > 0.0 && all(greaterThanEqual(s, vec2(0.0))) && all(lessThanEqual(s, vec2(1.0)))) {
		vec2 g = s * max(uOpt.zw, vec2(1.0));
		vec2 d = abs(fract(g + 0.5) - 0.5) / max(fwidth(g), vec2(1e-6));
		float line = 1.0 - smoothstep(0.5, 1.5, min(d.x, d.y));
		col = mix(col, vec3(1.0, 0.2, 0.7), 0.8 * line);
	} else {
		col *= 0.45;   // dim everything that will not reach the panels
	}

	float e = min(min(segDist(p, p0, p1), segDist(p, p1, p2)), min(segDist(p, p2, p3), segDist(p, p3, p0)));
	col = mix(col, vec3(1.0), 1.0 - smoothstep(lw * 0.5, lw, e));
	float r = 7.0 * max(px.x, px.y);
	if (length(p - p0) < r) col = vec3(1.0, 0.9, 0.0);
	if (length(p - p1) < r) col = vec3(0.1, 0.4, 1.0);
	if (length(p - p2) < r) col = vec3(0.1, 1.0, 0.2);
	if (length(p - p3) < r) col = vec3(1.0, 0.1, 0.1);
	fragColor = TDOutputSwizzle(vec4(col, 1.0));
}
