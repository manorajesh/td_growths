// bgsub.glsl -- fallback segmentation: difference against a captured empty-scene plate.
// in0: live camera   in1: background plate
uniform vec4 uBg;   // x threshold  y softness
layout(location = 0) out vec4 fragColor;
void main() {
	vec3 a = texture(sTD2DInputs[0], vUV.st).rgb;
	vec3 b = texture(sTD2DInputs[1], vUV.st).rgb;
	// compare chroma more than brightness so soft shadows leak less
	float la = dot(a, vec3(0.333)), lb = dot(b, vec3(0.333));
	vec3 ca = a / max(la, 0.03), cb = b / max(lb, 0.03);
	float diff = 0.6 * length(ca - cb) * 0.5 + 0.4 * abs(la - lb) * 2.0;
	float m = smoothstep(uBg.x, uBg.x + uBg.y, diff);
	fragColor = TDOutputSwizzle(vec4(m, m, m, 1.0));
}
