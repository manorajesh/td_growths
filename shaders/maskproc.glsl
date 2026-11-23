// maskproc.glsl -- threshold + temporal smoothing of the warped mask.
// in0: previous output (feedback)   in1: warped (and lightly blurred) mask
// out: white silhouette on black
uniform vec4 uMask;  // x threshold  y softness  z smoothing rate (1/s, 0 = off)  w dt
layout(location = 0) out vec4 fragColor;
void main() {
	float prev = texture(sTD2DInputs[0], vUV.st).r;
	float raw = texture(sTD2DInputs[1], vUV.st).r;
	float cur = smoothstep(uMask.x - uMask.y, uMask.x + uMask.y, raw);
	float m = uMask.z > 0.0 ? mix(prev, cur, 1.0 - exp(-uMask.z * uMask.w)) : cur;
	fragColor = TDOutputSwizzle(vec4(m, m, m, 1.0));
}
