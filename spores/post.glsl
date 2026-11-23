// post.glsl -- bloom + filmic tonemap.  in0: look  in1: look blurred
uniform vec4 uPost;   // x exposure  y bloom  z saturation
layout(location = 0) out vec4 fragColor;
vec3 aces(vec3 x) { return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0); }
void main() {
	vec3 c = texture(sTD2DInputs[0], vUV.st).rgb + texture(sTD2DInputs[1], vUV.st).rgb * uPost.y;
	c = aces(c * uPost.x);
	float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
	fragColor = TDOutputSwizzle(vec4(mix(vec3(l), c, uPost.z), 1.0));
}
