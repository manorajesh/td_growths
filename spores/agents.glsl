// agents.glsl -- physarum agents (one texel = one agent).  Jones-style: sense trail ahead at
// three angles, turn toward the strongest, step forward.  Agents live only inside the
// silhouette, come alive gradually after someone arrives, and respawn along the outline.
// in0: agents (feedback)  in1: trail (previous frame)  in2: growth front (r grown, g arrival time,
// b silhouette, a camera guide).  Agents live only where the mycelium front has grown.
// Presence comes in as a uniform (uP).
// agent texel: rg = position (uv)  b = heading (rad)  a = alive (0/1)
uniform vec4 uS;    // x sensor angle (rad)  y sensor distance (px)  z turn angle (rad)  w step (px)
uniform vec4 uA;    // x time  y grow-in time (s)  z respawn rate (/s)  w dt
uniform vec4 uG;    // x mask threshold  y guide weight  z edge spawn bias  w seed
uniform vec4 uB;    // x flow direction (rad)  y flow strength (rad/step)  z flow curl (noise turn)  w share of fine agents
uniform vec4 uP;    // x seconds someone has been here  y someone is here now (0/1)  z share of body grown
uniform vec4 uSeed; // x variety (per-agent sensor/step spread)  y unused  z grow-outward flow (0..1)  w aspect (w/h)
uniform vec4 uW;    // x wither seconds (agents die off gradually once the person leaves)
uniform vec4 uS2;   // fine 'hair' species: x sensor angle  y sensor distance (px)  z turn angle  w step (px)
layout(location = 0) out vec4 fragColor;

uint pcg(uint v) {
	uint state = v * 747796405u + 2891336453u;
	uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
	return (word >> 22u) ^ word;
}
float rnd(uint a, uint b) { return float(pcg(a * 1973u + pcg(b))) * (1.0 / 4294967296.0); }

float maskAt(vec2 uv) {               // 1 inside the grown mycelium region on the body
	if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) return 0.0;
	vec4 fr = texture(sTD2DInputs[2], uv);
	return min(fr.r, fr.b);
}
bool fading = false;
float sense(vec2 uv, float ang, vec2 px, float dist) {
	vec2 p = uv + vec2(cos(ang), sin(ang)) * dist * px;
	float m = maskAt(p);
	if (m < uG.x && !fading) return -1.0;                                   // never steer out of the body
	float g = texture(sTD2DInputs[2], p).a;
	return texture(sTD2DInputs[1], p).r + uG.y * g * m;
}

void main() {
	ivec2 ip = ivec2(gl_FragCoord.xy);
	uint id = uint(ip.y) * 4096u + uint(ip.x);
	uint f = uint(uA.x * 60.0) + uint(uG.w) * 7777u;
	vec4 s = texelFetch(sTD2DInputs[0], ip, 0);
	vec2 trailRes = uTD2DInfos[1].res.zw;
	vec2 px = 1.0 / trailRes;
	float presence = uP.x;
	fading = uP.y < 0.5;     // person just left: drift, then die off
	// how many agents are alive grows with time present: the network emerges gradually
	// alive agents follow how much of the body the mycelium has covered (constant density)
	float share = clamp(uP.z, 0.0, 1.0) * smoothstep(0.0, uA.y, presence + uA.y * 0.5);
	bool wanted = rnd(id, 11u) < share;

	bool respawn = !fading && (s.a < 0.5 || maskAt(s.rg) < uG.x || rnd(id, f * 3u + 1u) < uA.z * uA.w);
	if (wanted && respawn) {
		// spawn on the body, preferring the outline and the feet (rejection sampling)
		s = vec4(0.0);
		for (int k = 0; k < 12; k++) {
			vec2 c = vec2(rnd(id, f * 31u + uint(k) * 2u), rnd(id, f * 37u + uint(k) * 2u + 1u));
			float m = maskAt(c);
			if (m < uG.x) continue;
			// prefer the freshly grown edge of the mycelium (hyphal tips)
			float age = uA.x - texture(sTD2DInputs[2], c).g;
			float w = 0.2 + uG.z * exp(-age / 6.0);
			if (rnd(id, f * 41u + uint(k)) < w || k == 11) {
				s = vec4(c, rnd(id, f * 43u) * 6.2832, 1.0);
				break;
			}
		}
	} else if (!wanted || fading) {
		if (rnd(id, f * 13u + 5u) < uA.w / max(uW.x * 0.5, 0.05)) s.a = 0.0;   // gradual die-off
	}

	if (s.a > 0.5) {
		// two species share one trail: big veins (uS) and fine hair-like fuzz around them (uS2)
		vec4 sp = rnd(id, 97u) < uB.w ? uS2 : uS;
		sp.y *= 1.0 + uSeed.x * (rnd(id, 77u) * 2.0 - 1.0);         // every agent a little different:
		sp.w *= 1.0 + uSeed.x * 0.6 * (rnd(id, 78u) * 2.0 - 1.0);   // uneven density and texture
		float a = s.b;
		float F = sense(s.rg, a, px, sp.y), L = sense(s.rg, a + sp.x, px, sp.y), R = sense(s.rg, a - sp.x, px, sp.y);
		float r = rnd(id, f * 5u + 2u);
		if (F >= L && F >= R) {
		} else if (F < L && F < R) {
			a += (r < 0.5 ? 1.0 : -1.0) * sp.z;
		} else if (L > R) {
			a += sp.z * (0.6 + 0.4 * r);
		} else {
			a -= sp.z * (0.6 + 0.4 * r);
		}
		a += (rnd(id, f * 7u + 3u) - 0.5) * 0.15;                // a little wander keeps it organic
		// gentle flow: steer toward a direction (dripping / streaming like the references),
		// bent by a slowly drifting curl so the streams meander
		// grow outward: follow the direction the mycelium front moved here (from early to late
		// arrival), so every colony streams away from its own start point
		vec2 fpx = uTD2DInfos[2].res.xy * 3.0;
		vec4 fx0 = texture(sTD2DInputs[2], s.rg - vec2(fpx.x, 0)), fx1 = texture(sTD2DInputs[2], s.rg + vec2(fpx.x, 0));
		vec4 fy0 = texture(sTD2DInputs[2], s.rg - vec2(0, fpx.y)), fy1 = texture(sTD2DInputs[2], s.rg + vec2(0, fpx.y));
		vec2 grad = (fx0.r * fx1.r * fy0.r * fy1.r > 0.5) ? vec2(fx1.g - fx0.g, (fy1.g - fy0.g) / uSeed.w) : vec2(0.0);
		float base = length(grad) > 1e-4 ? mix(uB.x, atan(grad.y, grad.x), uSeed.z) : uB.x;
		float fa = base + uB.z * sin(s.g * 9.0 + uA.x * 0.15) * cos(s.r * 7.0 - uA.x * 0.11);
		a += uB.y * sin(fa - a);
		s.rg += vec2(cos(a), sin(a)) * sp.w * px;
		s.b = a;
	}
	fragColor = TDOutputSwizzle(s);
}
