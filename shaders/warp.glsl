// warp.glsl -- removes the camera's steep viewing angle: perspective (keystone) warp,
// plus lens correction, mirror and channel select.
// Maps OUTPUT uv -> CAMERA uv using a square->quad homography (Heckbert).
// in0: camera image or segmentation mask
uniform vec4 uC0;   // xy = camera uv for output bottom-left, zw = bottom-right
uniform vec4 uC1;   // xy = camera uv for output top-right,   zw = top-left
uniform vec4 uOpt;  // x mirror(0/1)  y lens k1  z channel(-1 rgba,0 r,1 g,2 b,3 a,4 luma)  w invert(0/1)

layout(location = 0) out vec4 fragColor;

vec2 squareToQuad(vec2 uv, vec2 p0, vec2 p1, vec2 p2, vec2 p3) {
	// p0=(0,0) p1=(1,0) p2=(1,1) p3=(0,1)
	float sx = p0.x - p1.x + p2.x - p3.x;
	float sy = p0.y - p1.y + p2.y - p3.y;
	float dx1 = p1.x - p2.x, dx2 = p3.x - p2.x;
	float dy1 = p1.y - p2.y, dy2 = p3.y - p2.y;
	float den = dx1 * dy2 - dx2 * dy1;
	den = abs(den) < 1e-8 ? 1e-8 : den;
	float g = (sx * dy2 - dx2 * sy) / den;
	float h = (dx1 * sy - sx * dy1) / den;
	float a = p1.x - p0.x + g * p1.x, b = p3.x - p0.x + h * p3.x, c = p0.x;
	float d = p1.y - p0.y + g * p1.y, e = p3.y - p0.y + h * p3.y, f = p0.y;
	float w = g * uv.x + h * uv.y + 1.0;
	return vec2(a * uv.x + b * uv.y + c, d * uv.x + e * uv.y + f) / w;
}

void main() {
	vec2 q = squareToQuad(vUV.st, uC0.xy, uC0.zw, uC1.xy, uC1.zw);
	vec2 c = q - 0.5;
	q = 0.5 + c * (1.0 + uOpt.y * dot(c, c));          // apply lens (barrel) distortion
	if (uOpt.x > 0.5) q.x = 1.0 - q.x;                   // corners are given in the mirrored image
	vec4 src = texture(sTD2DInputs[0], q);
	float inside = step(0.0, q.x) * step(q.x, 1.0) * step(0.0, q.y) * step(q.y, 1.0);
	int ch = int(uOpt.z + 0.5 * sign(uOpt.z));
	vec4 outc;
	if (ch < 0) {
		outc = vec4(src.rgb * inside, 1.0);
	} else {
		float m = ch == 0 ? src.r : ch == 1 ? src.g : ch == 2 ? src.b : ch == 3 ? src.a : dot(src.rgb, vec3(0.299, 0.587, 0.114));
		if (uOpt.w > 0.5) m = 1.0 - m;
		m *= inside;
		outc = vec4(m, m, m, 1.0);
	}
	fragColor = TDOutputSwizzle(outc);
}
