// compose.glsl -- places the two sides (2x4 panels of 80x80 = 160x320 each) on the 1024x768 canvas.
// in0: left side   in1: right side
// Offsets are in pixels from the TOP-LEFT of the canvas (how the Absen crop is described).
uniform vec4 uOffL;  // xy offset of left side,  z enabled
uniform vec4 uOffR;  // xy offset of right side, z enabled
uniform vec4 uMode;  // x test pattern (0/1)  y panel size (px)
layout(location = 0) out vec4 fragColor;

vec3 testPattern(ivec2 lp, ivec2 size, float side) {
	int ps = int(uMode.y);
	ivec2 pc = lp / ps;                  // panel col/row (row 0 = top)
	ivec2 q = lp - pc * ps;              // position inside the panel, (0,0) = top-left
	int cols = max(size.x / ps, 1);
	int idx = pc.y * cols + pc.x;
	vec3 base = side < 0.5 ? vec3(0.55, 0.12, 0.05) : vec3(0.05, 0.15, 0.55);
	vec3 c = base * (((pc.x + pc.y) % 2 == 0) ? 1.0 : 0.55);
	if (q.x == 0 || q.y == 0 || q.x == ps - 1 || q.y == ps - 1) c = vec3(1.0);
	// idx+1 dots identify the panel (1 = top-left, counting left->right, top->bottom)
	for (int k = 0; k <= idx; k++) {
		ivec2 d = q - ivec2(6 + k * 9, ps / 2 - 3);
		if (d.x >= 0 && d.x < 6 && d.y >= 0 && d.y < 6) c = vec3(1.0, 1.0, 0.3);
	}
	if (lp.x < 6 && lp.y < 6) c = vec3(0.0, 1.0, 0.0);    // green = side's top-left corner
	return c;
}

void main() {
	ivec2 res = ivec2(uTDOutputInfo.res.zw);
	ivec2 px = ivec2(gl_FragCoord.xy);
	ivec2 tl = ivec2(px.x, res.y - 1 - px.y);           // top-left-origin pixel coords
	vec3 col = vec3(0.0);
	for (int s = 0; s < 2; s++) {
		vec4 off = s == 0 ? uOffL : uOffR;
		if (off.z < 0.5) continue;
		ivec2 size = ivec2(s == 0 ? uTD2DInfos[0].res.zw : uTD2DInfos[1].res.zw);
		ivec2 lp = tl - ivec2(off.xy + 0.5);
		if (lp.x < 0 || lp.y < 0 || lp.x >= size.x || lp.y >= size.y) continue;
		if (uMode.x > 0.5) {
			col = testPattern(lp, size, float(s));
		} else {
			ivec2 sp = ivec2(lp.x, size.y - 1 - lp.y);
			col = s == 0 ? texelFetch(sTD2DInputs[0], sp, 0).rgb : texelFetch(sTD2DInputs[1], sp, 0).rgb;
		}
	}
	fragColor = TDOutputSwizzle(vec4(col, 1.0));
}
