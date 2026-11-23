// look.glsl -- trail density -> glowing filaments: hair-fine violet/blue strands, white-hot
// dense cores, a warm orange haze underneath, sparks.
// in0: trail   in1: trail, small blur   in2: trail, large blur   (density read from .g = shown trail)
uniform vec4 uL;    // x density gain  y filament crispness  z haze amount  w sparks
uniform vec4 uL2;   // x time  y brightness  z shimmer  w unused
uniform vec4 cThin; // thin strands (violet/blue)
uniform vec4 cMid;  // body (lavender)
uniform vec4 cHot;  // dense cores (warm white)
uniform vec4 cHaze; // underlying glow (orange)
uniform vec4 uF;    // flowers: x amount  y start (s present)  z size (px)  w spread (s)
uniform vec4 uF2;   // x seconds present  y flower density (0..1)  z grow seconds  w motes
layout(location = 0) out vec4 fragColor;

float hash12(vec2 p) {
	vec3 p3 = fract(vec3(p.xyx) * 0.1031);
	p3 += dot(p3, p3.yzx + 33.33);
	return fract((p3.x + p3.y) * p3.z);
}

vec2 hash22(vec2 p) {
	return vec2(hash12(p), hash12(p + 19.19));
}

// sporangia: glowing bulbs with fine radiating filament petals, appearing one by one on the
// dense, mature parts of the network, unfurling, breathing and releasing rising spore motes
vec3 flowers(vec2 uv) {
	if (uF.x <= 0.0) return vec3(0.0);
	vec2 res = uTDOutputInfo.res.zw;
	vec2 px = uv * res;
	float cs = uF.z * 2.6;                                   // grid cell size (px)
	vec2 cell = floor(px / cs);
	float t = uL2.x;
	vec3 acc = vec3(0.0);
	for (int j = -1; j <= 1; j++) {
		for (int i = -1; i <= 1; i++) {
			vec2 c = cell + vec2(float(i), float(j));
			float h = hash12(c * 1.31 + 7.7);
			if (h > uF2.y) continue;
			vec2 ctr = (c + 0.2 + 0.6 * hash22(c + 3.3)) * cs;
			float dens = 1.0 - exp(-texture(sTD2DInputs[2], ctr / res).g * uL.x * 0.5);
			float gate = smoothstep(0.08, 0.22, dens);           // fades in as the growth thickens
			if (gate <= 0.0) continue;
			// each flower cycles: unfurls, holds, withers and fades, rests, then blooms again
			float period = uF.w * (0.7 + 0.6 * hash12(c + 13.3));
			float ph = uF2.x - uF.y - hash12(c + 11.1) * period;
			if (ph < 0.0) continue;
			ph = mod(ph, period);
			float hold = period * 0.45;
			float a = smoothstep(0.0, uF2.z, ph) * (1.0 - smoothstep(hold, hold + uF2.z * 1.5, ph)) * gate;
			if (a <= 0.001) continue;
			float R = uF.z * (0.6 + 0.7 * hash12(c + 5.5)) * a * (1.0 + 0.06 * sin(t * 1.3 + h * 20.0));
			vec2 rel = px - ctr;
			float r = length(rel);
			if (r > R * 3.2) continue;
			float th = atan(rel.y, rel.x);
			float N = 7.0 + floor(hash12(c + 2.2) * 7.0);
			float rr = r / max(R, 1.0);
			// filaments curl as they extend and sway gently
			float ang = th + (0.45 + 0.3 * h) * rr * rr + 0.2 * sin(t * 0.7 + h * 30.0) * rr;
			float k = floor((ang / 6.2832 + 0.5) * N + 0.5);                 // which filament
			float len = R * (0.55 + 0.45 * hash12(c + k * 1.7 + 0.3));     // each its own length
			float ray = pow(abs(cos(ang * N * 0.5 + 0.0)), 55.0 * (0.4 + 0.6 * a));
			float along = smoothstep(R * 0.22, R * 0.38, r) * (1.0 - smoothstep(len * 0.88, len, r));
			float tip = exp(-pow((r - len * 0.93) / (R * 0.06 + 0.6), 2.0)) * smoothstep(0.5, 1.0, ray);
			acc += cMid.rgb * ray * along * 0.9 + cHaze.rgb * tip * 1.3;
			// bulb: a shaded sphere with a warm rim
			float rc = R * 0.3;
			if (r < rc) {
				vec3 n = vec3(rel / rc, sqrt(max(1.0 - dot(rel, rel) / (rc * rc), 0.0)));
				float l = clamp(dot(n, normalize(vec3(-0.5, 0.6, 0.65))), 0.0, 1.0);
				float rim = pow(1.0 - n.z, 2.0);
				acc += cHot.rgb * (0.35 + 0.9 * l) * a + cHaze.rgb * rim * 0.8 + vec3(1.0) * pow(l, 30.0) * 0.6;
			}
			acc += cHaze.rgb * 0.25 * exp(-r * r / (R * R * 0.5)) * a;  // soft glow
			// spore motes drifting up from mature blooms
			if (a > 0.9 && uF2.w > 0.0) {
				for (int k = 0; k < 3; k++) {
					float hk = hash12(c + float(k) * 4.7);
					float life = fract(t * (0.08 + 0.05 * hk) + hk);
					vec2 mp = ctr + vec2((hk - 0.5) * R + sin(t * 1.5 + hk * 9.0) * 3.0, life * R * 3.0);
					float d = length(px - mp);
					acc += cHaze.rgb * exp(-d * d / 2.5) * (1.0 - life) * uF2.w * 1.5;
				}
			}
		}
	}
	return acc * uF.x;
}

void main() {
	vec2 uv = vUV.st;
	float t = texture(sTD2DInputs[0], uv).g;
	float s = texture(sTD2DInputs[1], uv).g;
	float b = texture(sTD2DInputs[2], uv).g;
	float d = 1.0 - exp(-t * uL.x);
	float crisp = max(t - s * 0.85, 0.0);                        // fine strands stand out from their halo
	float strand = 1.0 - exp(-crisp * uL.x * uL.y);
	vec3 col = cThin.rgb * strand * 1.3;                             // most strands: violet / blue
	col += cMid.rgb * smoothstep(0.35, 0.85, d) * 0.7;
	col += cHot.rgb * smoothstep(0.8, 1.0, d) * 1.2;                 // white only in the densest cores
	float haze = 1.0 - exp(-b * uL.x * 0.5);
	col += cHaze.rgb * haze * uL.z * 0.55;
	// sparks: sparse warm flecks inside dense regions, twinkling
	vec2 cell = floor(uv * uTDOutputInfo.res.zw / 3.0);
	float h = hash12(cell);
	if (h < 0.04 * uL.w) {
		float tw = pow(0.5 + 0.5 * sin(uL2.x * (3.0 + 5.0 * h) + h * 60.0), 6.0);
		col += cHaze.rgb * 1.6 * tw * smoothstep(0.2, 0.8, haze);
	}
	col *= 1.0 + uL2.z * 0.15 * sin(uL2.x * 0.7 + uv.y * 9.0);  // slow breathing shimmer
	col += flowers(uv);
	// the advancing mycelium edge: a fuzzy band of fresh, bright hyphal tips
	float fresh = texture(sTD2DInputs[0], uv).b;
	col += (cHot.rgb * 0.9 * (0.06 + strand) + cMid.rgb * 0.08) * fresh;   // fibrous, follows the strands
	fragColor = TDOutputSwizzle(vec4(col * uL2.y, 1.0));
}
