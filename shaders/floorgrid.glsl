// floorgrid.glsl -- calibration pattern to send to the FLOOR visuals output (projector/LEDs).
// Point the tracker's corners at these corner dots as seen by the camera.
// Corner dots match the calibration view: bottom-left yellow, bottom-right blue,
// top-right green, top-left red.
uniform vec4 uGrid;  // x columns  y rows
layout(location = 0) out vec4 fragColor;
void main() {
	vec2 uv = vUV.st;
	vec2 res = uTDOutputInfo.res.zw;
	vec3 c = vec3(0.0);
	vec2 g = uv * max(uGrid.xy, vec2(1.0));
	vec2 d = abs(fract(g + 0.5) - 0.5) / max(fwidth(g), vec2(1e-6));
	c = mix(c, vec3(0.8), 1.0 - smoothstep(1.0, 2.5, min(d.x, d.y)));
	vec2 e = min(uv, 1.0 - uv) * res;                    // border, in pixels
	c = mix(c, vec3(1.0), step(min(e.x, e.y), 4.0));
	float r = 0.06 * min(res.x, res.y);
	vec2 p = uv * res;
	if (length(p - vec2(0.0, 0.0)) < r) c = vec3(1.0, 0.9, 0.0);
	if (length(p - vec2(res.x, 0.0)) < r) c = vec3(0.1, 0.4, 1.0);
	if (length(p - res) < r) c = vec3(0.1, 1.0, 0.2);
	if (length(p - vec2(0.0, res.y)) < r) c = vec3(1.0, 0.1, 0.1);
	vec2 q = abs(p - res * 0.5);
	if (min(q.x, q.y) < 3.0 && max(q.x, q.y) < r) c = vec3(1.0);   // centre cross
	fragColor = TDOutputSwizzle(vec4(c, 1.0));
}
