// pack.glsl -- r = silhouette mask HELD through short dropouts, g = guide (camera luminance).
// The held mask releases slowly, so brief segmentation flicker doesn't kill the agents.
// in0: mask   in1: guide (monochrome)   in2: previous output (feedback)
uniform vec4 uH;   // x dt  y hold seconds
layout(location = 0) out vec4 fragColor;
void main() {
	float m = texture(sTD2DInputs[0], vUV.st).r;
	float g = texture(sTD2DInputs[1], vUV.st).r;
	float prev = texture(sTD2DInputs[2], vUV.st).r;
	float held = max(m, prev - uH.x / max(uH.y, 0.01));
	fragColor = TDOutputSwizzle(vec4(held, g, 0.0, 1.0));
}
