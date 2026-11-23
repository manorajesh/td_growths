// ink_render.glsl -- fog volume + ink with translucency, shadowing, refraction and haze.
// in0: ink sim   in1: ink sim, small blur   in2: ink sim, large blur
uniform vec4 uTime;   // x time  y aspect  z seed
uniform vec4 uLook;   // x ink density  y haze  z fog amount  w light shafts
uniform vec4 uLook2;  // x shadow  y refraction  z wisp amount  w detail
uniform vec4 cFog;    // fog colour (lit)
uniform vec4 cDeep;   // fog colour (deep / bottom)
uniform vec4 cInk;    // ink colour
layout(location = 0) out vec4 fragColor;

#include noise

void main() {
	vec2 uv = vUV.st;
	float t = uTime.x, aspect = uTime.y;
	vec2 w = uv * vec2(aspect, 1.0);

	vec4 big = texture(sTD2DInputs[2], uv);
	vec4 sm = texture(sTD2DInputs[1], uv);
	vec2 px = uTD2DInfos[2].res.xy * 3.0;
	vec2 grad = vec2(texture(sTD2DInputs[2], uv + vec2(px.x, 0)).r - texture(sTD2DInputs[2], uv - vec2(px.x, 0)).r,
	                 texture(sTD2DInputs[2], uv + vec2(0, px.y)).r - texture(sTD2DInputs[2], uv - vec2(0, px.y)).r);

	// --- fog behind the ink (refracted by the ink's density gradient)
	vec2 fw = w + grad * 0.02 * uLook2.y;
	float f1 = fbm3(vec3(fw * vec2(1.6, 2.4) + vec2(t * 0.012, 0.0), t * 0.03));
	float f2 = fbm3(vec3(fw * 3.7 - vec2(t * 0.02, t * 0.004), t * 0.05 + 4.0));
	float shafts = fbm3(vec3(fw.x * 3.0 + fw.y * 0.55, 0.0, t * 0.025));
	shafts = smoothstep(0.0, 0.45, shafts) * smoothstep(0.1, 1.0, uv.y);
	float height = smoothstep(-0.1, 1.15, uv.y);
	vec3 fog = mix(cDeep.rgb, cFog.rgb, height * 0.85 + 0.15 * f1 * uLook.z + 0.1);
	fog *= 0.85 + 0.35 * uLook.z * (0.6 * f1 + 0.4 * f2);
	fog += cFog.rgb * shafts * 0.35 * uLook.w;
	// ink casts a soft shadow into the fog below/behind it (light from above)
	float shadow = texture(sTD2DInputs[2], uv + vec2(0.0, 0.035)).r;
	fog *= 1.0 - uLook2.x * (1.0 - exp(-shadow * 1.2));

	// --- ink: fine-detail lookup so edges break into filaments
	// two scales of domain warp so edges fray into fibres instead of smooth blobs
	vec2 dn = vec2(gnoise(vec3(w * 18.0, t * 0.35)), gnoise(vec3(w * 18.0 + 5.0, t * 0.35)));
	vec2 dn2 = vec2(gnoise(vec3(w * 70.0, t * 0.6)), gnoise(vec3(w * 70.0 + 9.0, t * 0.6)));
	vec2 suv = uv + (dn * 0.004 + dn2 * 0.0012) * uLook2.w;
	vec4 s = texture(sTD2DInputs[0], suv);
	float dens = s.r + uLook2.z * s.g;
	// fibrous breakup: strongest where ink is thin, the dense core stays solid
	float fib = fbm3(vec3(w * vec2(95.0, 95.0) + dn * 3.0, t * 0.25));
	float grainy = smoothstep(-0.35, 0.45, fib + 0.25 * gnoise(vec3(w * 240.0, t)));
	float thin = 1.0 - smoothstep(0.2, 1.4, dens);
	dens *= mix(1.0, 0.25 + 1.2 * grainy, thin * uLook2.w);
	float body = mix(dens, sm.r + uLook2.z * sm.g, 0.2);
	float alpha = 1.0 - exp(-body * uLook.x);
	// thin ink scatters fog light (lighter, bluish); thick ink is near black
	float thick = smoothstep(0.15, 1.6, body);
	vec3 inkc = mix(fog * 0.55 + cInk.rgb * 0.4, cInk.rgb, thick);
	// lit top edge: density increasing downward means the light hits it
	float rim = clamp(-grad.y * 6.0, 0.0, 1.0) * (1.0 - thick);
	inkc += cFog.rgb * rim * 0.25;
	vec3 col = mix(fog, inkc, alpha);

	// --- haze in front of the ink
	float hz = uLook.y * (0.55 + 0.45 * fbm3(vec3(w * 2.2 + vec2(-t * 0.015, 0.0), t * 0.04 + 9.0)));
	col = mix(col, mix(cDeep.rgb, cFog.rgb, height), clamp(hz, 0.0, 1.0));
	fragColor = TDOutputSwizzle(vec4(col, 1.0));
}
