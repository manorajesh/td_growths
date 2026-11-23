// calibout.glsl -- what the LEDs show while calibrating: warped camera, mask tint, panel grid.
// in0: warped camera   in1: processed mask
uniform vec4 uGrid;  // x columns  y rows
layout(location = 0) out vec4 fragColor;
void main() {
	vec3 c = texture(sTD2DInputs[0], vUV.st).rgb * 0.85;
	c += vec3(0.0, 0.35, 0.1) * texture(sTD2DInputs[1], vUV.st).r;
	vec2 g = vUV.st * uGrid.xy;
	vec2 d = abs(fract(g + 0.5) - 0.5) / max(fwidth(g), vec2(1e-6));
	c = mix(c, vec3(1.0, 0.2, 0.7), 1.0 - smoothstep(0.5, 1.5, min(d.x, d.y)));
	fragColor = TDOutputSwizzle(vec4(c, 1.0));
}
