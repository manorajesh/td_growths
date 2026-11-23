// crop_topleft.glsl -- copies the top-left (output size) region of the input, pixel for pixel.
// Used to send only the part of the 1024x768 canvas the LED controller actually shows.
layout(location = 0) out vec4 fragColor;
void main() {
	ivec2 o = ivec2(gl_FragCoord.xy);                         // origin bottom-left
	ivec2 inRes = ivec2(uTD2DInfos[0].res.zw);
	ivec2 outRes = ivec2(uTDOutputInfo.res.zw);
	ivec2 src = ivec2(o.x, inRes.y - outRes.y + o.y);         // same pixel, measured from the top-left
	fragColor = (src.x < inRes.x && src.y >= 0) ? texelFetch(sTD2DInputs[0], src, 0) : vec4(0, 0, 0, 1);
}
