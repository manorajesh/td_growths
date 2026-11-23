// front.glsl -- mycelium growth front: starts at a seed point on the body, then new colonies
// sprout elsewhere over time; each creeps outward (organic, uneven) and they grow into each other.
// in0: previous (feedback)   in1: mask_guide (r = held silhouette, g = camera guide)
// out: r = grown (0/1)  g = arrival time (s)  b = held silhouette  a = camera guide
uniform vec4 uF;    // x time  y dt  z spread speed (cells/s)  w seed active (0/1)
uniform vec4 uF2;   // x seed u  y seed v  z seconds present (last frame)  w noise seed
uniform vec4 uF3;   // x new colony rate  y colonies start after (s present)
layout(location = 0) out vec4 fragColor;

uint pcg(uint v) {
	uint state = v * 747796405u + 2891336453u;
	uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
	return (word >> 22u) ^ word;
}
float rnd(ivec2 p, uint salt) {
	uint f = uint(uF.x * 60.0) * 7919u + salt * 104729u;
	return float(pcg(uint(p.x) * 1973u + pcg(uint(p.y) * 9277u + pcg(f)))) * (1.0 / 4294967296.0);
}
float vnoise(vec2 p) {
	vec2 i = floor(p), f = fract(p), u = f * f * (3.0 - 2.0 * f);
	float a = fract(sin(dot(i, vec2(127.1, 311.7))) * 43758.55), b = fract(sin(dot(i + vec2(1, 0), vec2(127.1, 311.7))) * 43758.55);
	float c = fract(sin(dot(i + vec2(0, 1), vec2(127.1, 311.7))) * 43758.55), d = fract(sin(dot(i + vec2(1, 1), vec2(127.1, 311.7))) * 43758.55);
	return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

void main() {
	ivec2 res = ivec2(uTDOutputInfo.res.zw);
	ivec2 ip = ivec2(gl_FragCoord.xy);
	vec2 uv = vUV.st;
	vec4 prev = texelFetch(sTD2DInputs[0], ip, 0);
	vec4 mg = texture(sTD2DInputs[1], uv);
	bool body = mg.r > 0.5;
	float grown = prev.r, arrival = prev.g;
	if (uF2.z < 0.05) {                                         // nobody here: start over next time
		grown = 0.0;
	} else if (grown < 0.5 && body) {
		vec2 seed = uF2.xy * vec2(res);
		if (uF.w > 0.5 && length(vec2(ip) + 0.5 - seed) < 3.0) {
			grown = 1.0; arrival = uF.x;
		} else {
			float n = 0.0;
			for (int j = -1; j <= 1; j++)
				for (int i = -1; i <= 1; i++)
					n += texelFetch(sTD2DInputs[0], clamp(ip + ivec2(i, j), ivec2(0), res - 1), 0).r;
			// uneven, patchy speed -> an organic, lobed front
			float speed = uF.z * (0.25 + 1.5 * vnoise(vec2(ip) * 0.06 + uF2.w * 13.0));
			if (n > 0.5 && rnd(ip, 1u) < speed * uF.y * n / 3.0) { grown = 1.0; arrival = uF.x; }
			// new colonies: rare spontaneous starts anywhere on the body, more as time goes on
			float ramp = smoothstep(uF3.y, uF3.y + 30.0, uF2.z);
			if (n < 0.5 && rnd(ip, 2u) < uF3.x * 2e-6 * uF.y * ramp) { grown = 1.0; arrival = uF.x; }
		}
	}
	fragColor = TDOutputSwizzle(vec4(grown, arrival, mg.r, mg.g));
}
