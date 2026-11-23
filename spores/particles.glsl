// particles.glsl -- spores rising off mature growth: drift outward from the seed and upward,
// swirl in turbulence, leave the body into the dark, shrink and fade.
// in0: particles (feedback)  in1: growth front (r grown, g arrival time, b silhouette)
// particle texel: rg = position (uv)  b = age (s, < 0 = dead)  a = brightness/size envelope (fades in and out)
uniform vec4 uQ;    // x time  y dt  z spawn rate (/s per particle)  w lifetime (s)
uniform vec4 uQ2;   // x outward speed (px/s)  y rise (px/s)  z turbulence (px/s)  w mature age (s)
uniform vec4 uQ3;   // x seed u  y seed v  z someone is here (0/1)  w trail px per uv (height)
layout(location = 0) out vec4 fragColor;

uint pcg(uint v) {
	uint state = v * 747796405u + 2891336453u;
	uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
	return (word >> 22u) ^ word;
}
float rnd(uint a, uint b) { return float(pcg(a * 1973u + pcg(b))) * (1.0 / 4294967296.0); }
vec2 swirl(vec2 p, float t) {                       // cheap divergence-free-ish turbulence
	return vec2(sin(p.y * 7.0 + t * 0.6) + 0.5 * sin(p.y * 17.0 - t * 1.1 + p.x * 5.0),
	            cos(p.x * 6.0 - t * 0.5) + 0.5 * cos(p.x * 15.0 + t * 0.9 + p.y * 4.0));
}

void main() {
	ivec2 ip = ivec2(gl_FragCoord.xy);
	uint id = uint(ip.y) * 4096u + uint(ip.x);
	uint f = uint(uQ.x * 60.0);
	vec4 s = texelFetch(sTD2DInputs[0], ip, 0);
	float life = uQ.w * (0.5 + rnd(id, 3u));
	vec2 aspect = vec2(uTD2DInfos[1].res.z / uTD2DInfos[1].res.w, 1.0);
	if (s.b < 0.0) {
		if (uQ3.z > 0.5 && rnd(id, f * 3u + 1u) < uQ.z * uQ.y) {
			for (int k = 0; k < 8; k++) {
				vec2 c = vec2(rnd(id, f * 31u + uint(k) * 2u), rnd(id, f * 37u + uint(k) * 2u + 1u));
				vec4 fr = texture(sTD2DInputs[1], c);
				if (fr.r > 0.5 && fr.b > 0.5 && uQ.x - fr.g > uQ2.w) {     // only from mature growth
					s = vec4(c, 0.0, 0.0);
					break;
				}
			}
		}
	} else {
		// drift away from where the growth came from (growth direction), plus rise and swirl
		vec2 fpx = uTD2DInfos[1].res.xy * 3.0;
		vec2 grad = vec2(texture(sTD2DInputs[1], s.rg + vec2(fpx.x, 0)).g - texture(sTD2DInputs[1], s.rg - vec2(fpx.x, 0)).g,
		                 texture(sTD2DInputs[1], s.rg + vec2(0, fpx.y)).g - texture(sTD2DInputs[1], s.rg - vec2(0, fpx.y)).g);
		vec2 out_ = (s.rg - uQ3.xy) * aspect;
		vec2 dir = length(grad) > 1e-4 ? normalize(grad) : (length(out_) > 1e-4 ? normalize(out_) : vec2(0.0, 1.0));
		vec2 vel = dir * uQ2.x + vec2(0.0, uQ2.y) + swirl(s.rg * 3.0 + rnd(id, 5u), uQ.x) * uQ2.z;
		s.rg += vel * uQ.y / uQ3.w / aspect;
		s.b += uQ.y;
		float x = s.b / life;
		s.a = smoothstep(0.0, 0.18, x) * (1.0 - smoothstep(0.55, 1.0, x))      // ease in, ease out,
		      * mix(0.25, 1.0, pow(rnd(id, 9u), 2.0));                        // mostly faint, a few bright
		if (x >= 1.0) s = vec4(0.0, 0.0, -1.0, 0.0);
	}
	fragColor = TDOutputSwizzle(s);
}
