// sprite.glsl -- soft round dot used to draw each spore particle
layout(location = 0) out vec4 fragColor;
void main() {
	vec2 d = vUV.st - 0.5;
	float k = exp(-dot(d, d) * 18.0) - exp(-4.5);
	k = max(k, 0.0) / (1.0 - exp(-4.5));
	fragColor = TDOutputSwizzle(vec4(k, k, k, k));
}
