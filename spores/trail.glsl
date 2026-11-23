// trail.glsl -- diffuse + decay the trail, add this frame's deposits.
// in0: trail (feedback)  in1: deposits (agents drawn as points, additive)  in2: growth front
// r = live trail;  g = what is shown: the live trail, or after the person leaves a lingering
// afterglow of the last network that fades over the wither time;  b = freshly grown edge (glow)
uniform vec4 uTr;   // x decay (per frame, 0..1)  y diffuse (0..1)  z deposit amount  w max
uniform vec4 uTr2;  // x dt  y wither seconds  z someone is here (0/1)  w time
uniform vec4 uTr3;  // x fade time (s): how gently strands appear and disappear
layout(location = 0) out vec4 fragColor;
void main() {
	ivec2 ip = ivec2(gl_FragCoord.xy);
	ivec2 res = ivec2(uTD2DInfos[0].res.zw);
	float c = texelFetch(sTD2DInputs[0], ip, 0).r, sum = 0.0;
	for (int j = -1; j <= 1; j++)
		for (int i = -1; i <= 1; i++)
			sum += texelFetch(sTD2DInputs[0], clamp(ip + ivec2(i, j), ivec2(0), res - 1), 0).r;
	float v = mix(c, sum / 9.0, uTr.y) * uTr.x + texelFetch(sTD2DInputs[1], ip, 0).r * uTr.z;
	v = min(v, uTr.w);
	bool here = uTr2.z > 0.5;
	float prevShown = texelFetch(sTD2DInputs[0], ip, 0).g;
	// strands ease in and out instead of switching with the agents; after the person leaves the
	// last network lingers and fades over the wither time
	float k = 1.0 - exp(-uTr2.x / max(uTr3.x, 0.01));
	float shown = here ? mix(prevShown, v, k) : max(prevShown * exp(-uTr2.x / max(uTr2.y * 0.35, 0.05)), mix(prevShown, v, k));
	vec4 fr = texture(sTD2DInputs[2], vUV.st);
	float fresh = fr.r * min(fr.b * 2.0, 1.0) * exp(-max(uTr2.w - fr.g, 0.0) / 3.0) * (here ? 1.0 : 0.0);
	fragColor = TDOutputSwizzle(vec4(v, shown, fresh, 1.0));
}
