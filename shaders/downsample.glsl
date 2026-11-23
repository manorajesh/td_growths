// downsample.glsl -- box-filter a supersampled image down to LED pixels (clean anti-aliased edges).
// in0: image at an integer multiple of the output size
layout(location = 0) out vec4 fragColor;
void main() {
	ivec2 o = ivec2(gl_FragCoord.xy);
	ivec2 f = max(ivec2(uTD2DInfos[0].res.zw / uTDOutputInfo.res.zw + 0.5), ivec2(1));
	vec4 acc = vec4(0.0);
	for (int j = 0; j < f.y; j++)
		for (int i = 0; i < f.x; i++)
			acc += texelFetch(sTD2DInputs[0], o * f + ivec2(i, j), 0);
	fragColor = TDOutputSwizzle(acc / float(f.x * f.y));
}
