// ink_sim.glsl -- ink advected by layered curl noise, emitted along a living ring.
// in0: previous state (feedback).  state: r = ink density, g = fine wisps, b = freshness, a = 1
uniform vec4 uTime;   // x time  y dt  z aspect (w/h)  w seed
uniform vec4 uState;  // x seconds since trigger  y emitting (0/1)  z seconds since release  w start angle (rad)
uniform vec4 uRing;   // x centre u  y centre v  z radius (fraction of height)  w thickness
uniform vec4 uFlow;   // x curl strength  y curl scale  z swirl  w buoyancy
uniform vec4 uInk;    // x emission  y lifetime (s)  z jets  w grow time (s)
uniform vec4 uMorph;  // x morph speed  y radius wobble  z thickness variation  w gaps (0..1)
layout(location = 0) out vec4 fragColor;

#include noise

float psi(vec2 w, float t, float s) {
	return 0.6 * gnoise(vec3(w * s, t * 0.11)) + 0.3 * gnoise(vec3(w * s * 2.1 + 7.3, t * 0.19))
	     + 0.15 * gnoise(vec3(w * s * 4.3 + 3.1, t * 0.31));
}
vec2 curl(vec2 w, float t, float s) {
	float e = 0.02 / s;
	float dy = psi(w + vec2(0.0, e), t, s) - psi(w - vec2(0.0, e), t, s);
	float dx = psi(w + vec2(e, 0.0), t, s) - psi(w - vec2(e, 0.0), t, s);
	return vec2(dy, -dx) / (2.0 * e) / s;
}
// ring geometry at angle th (seamless around the circle: noise sampled on a circle)
vec3 ringAt(float th, float t) {
	vec2 cs = vec2(cos(th), sin(th));
	float ph = t * uMorph.x + uTime.w * 13.7;
	float R = uRing.z * (1.0 + uMorph.y * fbm3(vec3(cs * 1.1, ph)));
	float tv = smoothstep(-0.35, 0.55, fbm3(vec3(cs * 2.6 + 9.0, ph * 1.4)));
	float W = uRing.w * mix(1.0, 0.15 + 2.2 * tv * tv, uMorph.z);
	float gap = smoothstep(uMorph.w - 0.12, uMorph.w + 0.12, 0.5 + 0.9 * fbm3(vec3(cs * 1.7 + 4.0, ph * 0.8)));
	return vec3(R, W, gap);
}
vec2 velocity(vec2 w, float t, vec2 c) {
	// once released, the flow gets livelier so the ink disperses like an exhale
	float rel = (1.0 - uState.y) * smoothstep(0.0, 2.0, uState.z);
	vec2 v = curl(w, t, uFlow.y) * uFlow.x * (1.0 + 1.5 * rel);
	vec2 d = w - c;
	float r = length(d) + 1e-5;
	vec2 n = d / r;
	float th = atan(d.y, d.x);
	vec3 rg = ringAt(th, t);
	float near = exp(-pow((r - rg.x) / (rg.y * 3.0 + 0.02), 2.0));
	vec2 cs = vec2(cos(th), sin(th));
	float jet = pow(max(gnoise(vec3(cs * 3.1 + 21.0, t * 0.23 + uTime.w)) * 1.9, 0.0), 3.0);
	v += n * uInk.z * jet * near;                           // tendrils thrown outward
	v += vec2(-n.y, n.x) * uFlow.z * near;                  // slow swirl along the ring
	v.y += uFlow.w;                                         // buoyancy
	v += n * 0.035 * rel * exp(-pow((r - rg.x) / 0.25, 2.0)); // released ink drifts outward
	return v;
}

void main() {
	vec2 res = uTD2DInfos[0].res.zw;
	vec2 uv = vUV.st;
	float aspect = uTime.z, t = uTime.x, dt = uTime.y;
	vec2 toW = vec2(aspect, 1.0);
	vec2 w = uv * toW;
	vec2 c = uRing.xy * toW;

	// --- advect (RK2), with an extra fine-scale curl for the wisps channel
	vec2 v1 = velocity(w, t, c);
	vec2 v2 = velocity(w - 0.5 * dt * v1, t, c);
	vec2 src = (w - dt * v2) / toW;
	vec4 s = texture(sTD2DInputs[0], src);
	vec2 vf = curl(w * 1.0, t * 1.7, uFlow.y * 3.5) * uFlow.x * 0.6;
	s.g = texture(sTD2DInputs[0], (w - dt * (v2 + vf)) / toW).g;
	// gentle sharpening against numerical diffusion
	vec2 px = 1.0 / res;
	vec4 nb = 0.25 * (texture(sTD2DInputs[0], src + vec2(px.x, 0)) + texture(sTD2DInputs[0], src - vec2(px.x, 0)) +
	                  texture(sTD2DInputs[0], src + vec2(0, px.y)) + texture(sTD2DInputs[0], src - vec2(0, px.y)));
	// limited (no overshoot -> no ringing artifacts): stay within the local min/max
	vec4 a0 = texture(sTD2DInputs[0], src + vec2(px.x, 0)), a1 = texture(sTD2DInputs[0], src - vec2(px.x, 0));
	vec4 a2 = texture(sTD2DInputs[0], src + vec2(0, px.y)), a3 = texture(sTD2DInputs[0], src - vec2(0, px.y));
	float lo = min(min(a0.r, a1.r), min(a2.r, a3.r)), hi = max(max(a0.r, a1.r), max(a2.r, a3.r));
	s.r = clamp(s.r + 0.12 * (s.r - nb.r), lo, hi);

	// --- emission along the ring, materialising around the circle from the start angle
	vec2 d = w - c;
	float r = length(d);
	float th = atan(d.y, d.x);
	vec3 rg = ringAt(th, t);
	float since = uState.x;
	float spread = 3.2 * pow(smoothstep(0.0, uInk.w, since), 0.75);
	float dth = abs(mod(th - uState.w + 3.14159265, 6.2831853) - 3.14159265);
	float front = 0.45 * gnoise(vec3(th * 2.0, since * 0.7, uTime.w));
	float covered = smoothstep(spread + 0.25, spread - 0.25, dth + front);
	float prof = exp(-pow((r - rg.x) / max(rg.y, 1e-4), 2.0));
	float grain = 0.55 + 0.9 * smoothstep(-0.2, 0.5, gnoise(vec3(w * 38.0, t * 0.6)));   // blotchy, not uniform
	float ramp = smoothstep(0.0, 0.6, since);
	float emit = uInk.x * prof * rg.z * covered * grain * ramp * uState.y;
	s.r += emit * dt * max(1.0 - s.r / 3.0, 0.0);   // taper: thick ink saturates smoothly
	float edge = exp(-pow((r - rg.x) / max(rg.y * 1.8, 1e-4), 2.0)) - prof;           // wisps from the edges
	s.g += uInk.x * 0.8 * max(edge, 0.0) * rg.z * covered * ramp * uState.y * dt;
	s.b = max(s.b * exp(-dt / 1.5), min(emit * 0.4, 1.0));

	// --- dissipation (faster once released)
	float life = max(uInk.y, 0.1);
	float k = uState.y > 0.5 ? 1.0 / life : 1.0 / life + 1.0 / max(life * 0.35, 0.1) * smoothstep(0.0, 1.5, uState.z);
	s.r *= exp(-dt * k);
	s.g *= exp(-dt * k * 1.8);
	s.r = min(s.r, 4.0);
	s.g = min(s.g, 3.0);
	fragColor = TDOutputSwizzle(vec4(s.rgb, 1.0));
}
