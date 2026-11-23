// bgplate.glsl -- holds the empty-scene background plate for background subtraction.
// in0: previous plate (feedback)   in1: live camera
uniform vec4 uCap;  // x capturing (1 = copy the live camera into the plate)
layout(location = 0) out vec4 fragColor;
void main() {
	vec4 prev = texture(sTD2DInputs[0], vUV.st);
	vec4 cam = texture(sTD2DInputs[1], vUV.st);
	fragColor = TDOutputSwizzle(uCap.x > 0.5 ? cam : prev);
}
