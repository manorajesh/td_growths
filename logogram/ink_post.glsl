// ink_post.glsl -- bloom, chromatic aberration, filmic tonemap, grade, vignette, grain.
// in0: render   in1: render blurred (bloom)
uniform vec4 uPost;   // x exposure  y bloom  z grain  w vignette
uniform vec4 uPost2;  // x chromatic aberration  y time  z contrast  w saturation
layout(location = 0) out vec4 fragColor;

#include noise

vec3 aces(vec3 x) {
	return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}
void main() {
	vec2 uv = vUV.st;
	vec2 dc = uv - 0.5;
	float ca = uPost2.x * dot(dc, dc) * 4.0;
	vec3 col;
	col.r = texture(sTD2DInputs[0], uv + dc * ca).r;
	col.g = texture(sTD2DInputs[0], uv).g;
	col.b = texture(sTD2DInputs[0], uv - dc * ca).b;
	col += texture(sTD2DInputs[1], uv).rgb * uPost.y;
	col *= uPost.x;
	col = aces(col * 1.35);
	col = (col - 0.5) * uPost2.z + 0.5;
	float l = dot(col, vec3(0.2126, 0.7152, 0.0722));
	col = mix(vec3(l), col, uPost2.w);
	col *= mix(1.0, smoothstep(1.15, 0.25, length(dc * vec2(1.1, 1.0))), uPost.w);
	vec2 px = uv * uTDOutputInfo.res.zw;
	float g = hash12(px + fract(uPost2.y * 7.31) * 1000.0) - 0.5;
	col += g * uPost.z * (0.35 + 0.65 * (1.0 - l));
	fragColor = TDOutputSwizzle(vec4(clamp(col, 0.0, 1.0), 1.0));
}
