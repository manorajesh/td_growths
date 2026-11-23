// presence.glsl -- 1x1: r = seconds someone has been here, g = coverage, b = here now (0/1),
// a = seconds since the silhouette was last seen.  'Here' holds for a while after the
// silhouette is lost, so short tracking dropouts don't trigger the wither.
// in0: previous (feedback)  in1: growth-front average (1x1: r = grown share of frame, b = silhouette share)
uniform vec4 uP;   // x dt  y coverage threshold  z decay speed (x faster than build-up)  w hold (s)
layout(location = 0) out vec4 fragColor;
void main() {
	vec4 prev = texelFetch(sTD2DInputs[0], ivec2(0), 0);
	float cov = texture(sTD2DInputs[1], vec2(0.5)).b;           // silhouette coverage (front.b average)
	float lost = cov > uP.y ? 0.0 : prev.a + uP.x;
	bool here = lost < uP.w;
	float t = here ? prev.r + uP.x : max(prev.r - uP.x * uP.z, 0.0);
	fragColor = TDOutputSwizzle(vec4(t, cov, here ? 1.0 : 0.0, lost));
}
