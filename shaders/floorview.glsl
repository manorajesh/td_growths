// floorview.glsl -- debug view of the floor as if seen straight from above.
// in0: perspective-corrected camera (warp.glsl)   in1: feet map (r = feet/presence, g = step flashes)
uniform vec4 uGrid;  // x columns  y rows
layout(location = 0) out vec4 fragColor;
void main() {
	vec3 c = texture(sTD2DInputs[0], vUV.st).rgb * 0.7;
	vec4 fm = texture(sTD2DInputs[1], vUV.st);
	c = mix(c, vec3(0.1, 1.0, 0.4), clamp(fm.r, 0.0, 1.0) * 0.8);
	c += vec3(1.0, 0.8, 0.1) * fm.g;
	vec2 g = vUV.st * max(uGrid.xy, vec2(1.0));
	vec2 d = abs(fract(g + 0.5) - 0.5) / max(fwidth(g), vec2(1e-6));
	c = mix(c, vec3(1.0, 0.2, 0.7), 0.6 * (1.0 - smoothstep(0.5, 1.5, min(d.x, d.y))));
	fragColor = TDOutputSwizzle(vec4(c, 1.0));
}
