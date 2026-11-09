"""GLSL effect passes. Each effect is a fragment shader body; they run as a chain.

Conventions: v_uv (0,0) is the TOP-left of the image (rows are kept in upload order),
u_amt is 0..1 (audio reaction can push it to ~1.6), tx() samples with mirrored wrapping.
"""

# Shared colour palettes: every effect with a colour choice offers this list (its index is the palette id in
# GLSL). The first five keep the old Neon Edges colours' positions so saved looks still match.
PALETTES = ["Rainbow", "Neon cyan", "Neon magenta", "White", "Source colour", "Synthwave", "Vaporwave",
            "Fire", "Ice", "Toxic", "Sunset", "Ocean", "Gold", "Terminal green", "Custom"]
COLOUR_MOTION = ["Static", "Cycle", "Flow", "Audio", "Radial", "Spiral", "Rise", "Breathe", "Beat jump",
                 "Drift"]
MAX_COLOURS = 8   # the Custom palette holds 2 to 8 colours
PALETTE_GLSL = """
// three key colours per palette (Rainbow and Source colour are handled separately)
void palKeys(int id, out vec3 a, out vec3 b, out vec3 c){
  if (id == 1)       { a = vec3(0.,.55,1.);  b = vec3(0.,.94,1.);  c = vec3(.55,1.,1.); }
  else if (id == 2)  { a = vec3(.85,0.,.6);  b = vec3(1.,.17,.84); c = vec3(1.,.6,.95); }
  else if (id == 3)  { a = vec3(.8);         b = vec3(1.);         c = vec3(.9,.95,1.); }
  else if (id == 5)  { a = vec3(1.,.16,.6);  b = vec3(.55,.2,1.);  c = vec3(0.,.9,1.); }
  else if (id == 6)  { a = vec3(1.,.55,.85); b = vec3(.55,.95,1.); c = vec3(.75,.6,1.); }
  else if (id == 7)  { a = vec3(1.,.12,0.);  b = vec3(1.,.55,0.);  c = vec3(1.,.95,.35); }
  else if (id == 8)  { a = vec3(.15,.45,1.); b = vec3(.4,.85,1.);  c = vec3(.9,1.,1.); }
  else if (id == 9)  { a = vec3(.3,1.,0.);   b = vec3(.85,1.,0.);  c = vec3(0.,1.,.55); }
  else if (id == 10) { a = vec3(1.,.3,.35);  b = vec3(1.,.6,.2);   c = vec3(.6,.25,.9); }
  else if (id == 11) { a = vec3(0.,.3,.8);   b = vec3(0.,.75,.8);  c = vec3(.3,1.,.8); }
  else if (id == 12) { a = vec3(.85,.5,.1);  b = vec3(1.,.8,.3);   c = vec3(1.,.95,.7); }
  else if (id == 13) { a = vec3(0.,.55,.1);  b = vec3(.1,1.,.3);   c = vec3(.7,1.,.7); }
  else if (id == 14) { a = u_cols[0]; b = u_cols[u_ncols/2]; c = u_cols[u_ncols - 1]; }
  else               { a = vec3(1.,0.,0.);   b = vec3(0.,1.,0.);   c = vec3(0.,0.,1.); }
}
// bright colours that loop: t is any number, 1 = once round the palette (neon lines, particles, ...)
vec3 palCycle(int id, float t, vec3 src){
  if (id == 0) return .5 + .5*cos(6.2831853*(t + vec3(0., .33, .67)));
  if (id == 4) return src;
  if (id == 14) {   // Custom: round all of the effect's own colours
    float n = float(u_ncols), x = fract(t)*n;
    int i = int(x);
    return mix(u_cols[i], u_cols[(i + 1) % u_ncols], smoothstep(0., 1., fract(x)));
  }
  vec3 a, b, c; palKeys(id, a, b, c);
  t = fract(t)*3.;
  return t < 1. ? mix(a, b, smoothstep(0., 1., t)) : t < 2. ? mix(b, c, smoothstep(1., 2., t))
                                                    : mix(c, a, smoothstep(2., 3., t));
}
// gradient map: t = brightness 0..1, dark to light through the palette (thermal, duotone, fills)
vec3 palMap(int id, float t, vec3 src){
  t = clamp(t, 0., 1.);
  if (id == 0) return (.5 + .5*cos(6.2831853*(t*.8 + vec3(0., .33, .67)))) * smoothstep(0., .3, t);
  if (id == 4) return src;
  if (id == 14) {   // Custom: dark to light through the colours in order
    float x = t*float(u_ncols - 1);
    int i = min(int(x), u_ncols - 2);
    return mix(u_cols[i], u_cols[i + 1], x - float(i))*smoothstep(0., .25, t);
  }
  vec3 a, b, c; palKeys(id, a, b, c);
  if (t < .3) return mix(a*.05, a, t/.3);
  if (t < .65) return mix(a, b, (t - .3)/.35);
  return mix(b, mix(c, vec3(1.), .15), (t - .65)/.35);
}
// how the colours move (COLOUR_MOTION): a phase to add to palCycle's t
float palPhase(int motion, vec2 uv){
  if (motion == 1) return u_time*.12;
  if (motion == 2) return dot(uv, vec2(.6, .4))*1.5 + u_time*.25;
  if (motion == 3) return u_audio*.5 + beatGlide()*.15;
  vec2 p = (uv - .5)*vec2(u_res.x/u_res.y, 1.);
  if (motion == 4) return length(p)*1.6 - u_time*.3;                            // radial: rings outward
  if (motion == 5) return atan(p.y, p.x)/6.2831853 + length(p)*.8 - u_time*.2;  // spiral
  if (motion == 6) return uv.y*1.4 + u_time*.3;                                 // rise: bands moving up
  if (motion == 7) return .5 + .5*sin(u_time*1.3);                              // breathe: all swing together
  if (motion == 8) return floor(u_beats)/3.;                                    // beat jump: next colour per beat
  if (motion == 9) {                                                            // drift: slow wandering blobs
    vec2 q = p*2.2 + vec2(u_time*.07, -u_time*.05);
    return sin(q.x*1.3 + sin(q.y*1.7 + u_time*.2))*.35 + sin(q.y*1.1 - q.x*.6)*.35 + u_time*.04;
  }
  return 0.;
}
"""

VERT = """#version 330 core
const vec2 P[3] = vec2[3](vec2(-1,-1), vec2(3,-1), vec2(-1,3));
out vec2 v_uv;
void main(){ vec2 p = P[gl_VertexID]; v_uv = p*.5+.5; gl_Position = vec4(p,0,1); }
"""

HEAD = """#version 330 core
in vec2 v_uv; out vec4 o;
uniform sampler2D u_tex, u_prev, u_clean;   // chain input, last output frame, untouched feed
uniform vec2 u_res;
uniform float u_time, u_amt, u_audio;
uniform int u_opt0, u_opt1, u_opt2, u_opt3, u_opt4, u_opt5;  // per-effect dropdown choices
uniform float u_p0, u_p1, u_p2, u_p3, u_p4, u_p5;            // per-effect extra sliders
uniform vec3 u_cols[8];                     // the effect's own colours, for the "Custom" palette
uniform int u_ncols;                         // how many of them are in use (2..8)
uniform vec3 u_bands;                        // bass, mid, high (0..1)
uniform vec4 u_hits;                         // kick, snare / clap, hats, big kick: 1 on a hit, fading after
uniform float u_beats, u_since, u_beatlen;   // beats counted so far, seconds since the last one, beat length
uniform sampler2D u_audiotex;                // rows: 128-band spectrum (low..high), waveform, left, right
uniform vec4 u_slow;                         // energy (slow loudness), brightness, busyness, pan (0.5 = middle)
uniform float u_width;                       // stereo width: 0 mono .. 1 wide
uniform vec4 u_swell;                        // bass, mid, high, all as very slow envelopes: how loud it has BEEN
uniform vec4 u_music;                        // flow clock (runs with the energy), beat clock (eased steps), bar position
uniform int u_char;                          // this effect's Music character: 0 Reactive, 1 Swell, 2 Flow, 3 Rhythmic
uniform vec2 u_centre;                       // movable centre for effects with center=True
uniform float u_dt;                          // seconds since last frame
uniform float u_speed;                       // the effect's Speed setting
// The time an effect's internal structure should travel on. Reactive is plain effect time (nothing changes); Swell
// adds the music's flow; Flow travels on the flow clock itself; Rhythmic steps on the beat, eased so it lands on it.
float mClock(){
  // the music's own travel obeys the effect's Speed too (0 holds it still, negative runs it back)
  return u_char == 0 ? u_time : u_char == 1 ? u_time + u_music.x*.5*u_speed : u_char == 2 ? u_time*.3 + u_music.x*u_speed
       : u_time*.3 + u_music.y*.5*u_speed;
}
// A hit-shaped signal for the character: Reactive and Rhythmic take the hit, Swell and Flow take the slow swell.
float mPulse(float hit, float swell){ return (u_char == 1 || u_char == 2) ? swell : hit; }
uniform sampler2D u_s0, u_s1;                // memory buffers for effects with "state" passes
uniform sampler2D u_mask;                    // AI person matte: 1 = subject, 0 = background
float maskAt(vec2 uv){ return texture(u_mask, uv).r; }
uniform sampler2D u_m0, u_m1, u_m2;          // extra sources (Source 2-4)
uniform sampler2D u_plate;                   // the captured empty room (clean plate), if u_plate_on
uniform float u_plate_on;
uniform vec3 u_masp, u_mlive;                // their aspect ratios, and 1 where a source has a picture
vec3 media(int s, vec2 uv){ return s == 0 ? texture(u_m0, uv).rgb : s == 1 ? texture(u_m1, uv).rgb
                                                                        : texture(u_m2, uv).rgb; }
float hash(vec2 p){ p = fract(p*vec2(123.34,456.21)); p += dot(p, p+45.32); return fract(p.x*p.y); }
float lum(vec3 c){ return dot(c, vec3(.299,.587,.114)); }
vec2 mirrorWrap(vec2 uv){ return 1. - abs(mod(uv, 2.) - 1.); }
vec4 tx(vec2 uv){ return texture(u_tex, mirrorWrap(uv)); }
vec4 clean(vec2 uv){ return texture(u_clean, mirrorWrap(uv)); }
mat2 rot(float a){ float c = cos(a), s = sin(a); return mat2(c,-s,s,c); }
vec3 hueRot(vec3 c, float a){ const vec3 k = vec3(.57735); float ca = cos(a);
  return c*ca + cross(k,c)*sin(a) + k*dot(k,c)*(1.-ca); }
float spectrum(float x){ return texture(u_audiotex, vec2(clamp(x, 0., 1.)*127./128. + .5/128., .125)).r; }
float waveform(float x){ return texture(u_audiotex, vec2(clamp(x, 0., 1.)*127./128. + .5/128., .375)).r; }
float waveL(float x){ return texture(u_audiotex, vec2(clamp(x, 0., 1.)*127./128. + .5/128., .625)).r; }
float waveR(float x){ return texture(u_audiotex, vec2(clamp(x, 0., 1.)*127./128. + .5/128., .875)).r; }
// beat count that glides over ~0.2 s instead of jumping
float beatGlide(){ return u_beats - 1. + smoothstep(0., .2, u_since); }
""" + PALETTE_GLSL

# First pass: fits the source into the output frame (cover), or draws the test pattern.
SOURCE = """
uniform vec2 u_scale;
uniform int u_mode;   // 0 = texture, 1 = test pattern
vec3 testPattern(vec2 uv){
  float t = u_time;
  vec3 c = mix(vec3(.08,.02,.18), vec3(.02,.12,.2), uv.x + .2*sin(t*.5));
  for (int i = 0; i < 7; i++){
    float fi = float(i);
    vec2 p = vec2(.5 + cos(t*.7+fi)*.33, .42 + sin(t*1.1+fi*1.7)*.28);
    vec2 d = (uv-p) * vec2(u_res.x/u_res.y, 1.);
    vec3 col = .5+.5*cos(fi*.9 + t + vec3(0,2,4));
    c = mix(c, col, smoothstep(.045+fi*.012, .04+fi*.012, length(d)));
  }
  if (uv.y > .83) c = .5+.5*cos(floor(uv.x*7.)*.9 + t*.6 + vec3(0,2,4));
  float grid = step(.985, fract(uv.x*16.)) + step(.98, fract(uv.y*9.));
  return c + grid*.08;
}
void main(){
  vec2 uv = v_uv;
  if (u_mode == 1) { o = vec4(testPattern(uv), 1.); return; }
  o = vec4(texture(u_tex, (uv-.5)*u_scale+.5).rgb, 1.);
}
"""

COPY = "void main(){ o = texture(u_tex, v_uv); }"
# clean plate capture: running average of the clean feed (u_s0 = the average so far, u_k = 1/(frames+1))
PLATE_ACC = "uniform float u_k; void main(){ o = vec4(mix(texture(u_s0, v_uv).rgb, clean(v_uv).rgb, u_k), 1.); }"

# Appended to every effect (whose main() is renamed fx_main): blends the effect's result `e`
# over its input `b` with the chosen mode, then mixes by opacity x fade (u_mix).
BLEND_MODES = ["Normal", "Add", "Screen", "Multiply", "Overlay", "Soft light",
               "Difference", "Lighten", "Darken"]
BLEND_WRAPPER = """
uniform float u_mix;
uniform int u_blend;
// Apply to, as weights for everywhere / subject / background; they glide when it's changed, so the
// effect fades across instead of snapping
uniform vec3 u_tw;
float targetMask(vec2 uv){ float m = maskAt(uv); return u_tw.x + u_tw.y*m + u_tw.z*(1. - m); }
vec3 blendColor(vec3 b, vec3 e, int m){
  if (m == 1) return b + e;
  if (m == 2) return 1. - (1.-b)*(1.-e);
  if (m == 3) return b * e;
  if (m == 4) return mix(2.*b*e, 1. - 2.*(1.-b)*(1.-e), step(.5, b));
  if (m == 5) return mix(2.*b*e + b*b*(1.-2.*e), sqrt(b)*(2.*e-1.) + 2.*b*(1.-e), step(.5, e));
  if (m == 6) return abs(b - e);
  if (m == 7) return max(b, e);
  if (m == 8) return min(b, e);
  return e;
}
void main(){
  fx_main();
  vec3 b = texture(u_tex, v_uv).rgb, e = clamp(o.rgb, 0., 1.);
  float m = targetMask(v_uv);
  o = vec4(mix(b, blendColor(b, e, u_blend), u_mix * m), 1.);
}"""

# Shared Scale / Rotate for overlay effects. The effect is drawn as if the frame were scaled and turned about its
# Centre: its own picture coordinates (v_uv) are swapped for transformed ones, while the INPUT picture, read through
# tx(), is mapped back so only the effect moves and the video underneath stays where it is.
def xform_code(code):
    import re
    code = code.replace("void main()", "void fx_inner()", 1)
    code = re.sub(r"\bv_uv\b", "xf_uv", code)
    code = re.sub(r"\btx\(", "txx(", code)
    return """
uniform vec2 u_xf;   // scale, angle (radians)
vec2 xf_uv;
vec2 xfMap(vec2 uv, float dir){   // dir -1: the effect's coordinates for this pixel, +1: back again
  float asp = u_res.x/u_res.y, a = u_xf.y*dir, c = cos(a), s = sin(a);
  vec2 p = (uv - u_centre)*vec2(asp, 1.);
  p = mat2(c, s, -s, c)*p;
  p = dir < 0. ? p/max(u_xf.x, 1e-3) : p*max(u_xf.x, 1e-3);
  return p/vec2(asp, 1.) + u_centre;
}
vec4 txx(vec2 uv){ return tx(xfMap(uv, 1.)); }
""" + code + """
void main(){ xf_uv = xfMap(v_uv, -1.); fx_inner(); }
"""

# AI mask refinement = colour guided filter (He et al.), guided by the full-res clean feed. Within each
# window the mask is fitted as a linear function of the image colour, so its edge lands where the colours
# change (hair, fingers, clothing) even if the AI's mask is soft or a few pixels off.
#  pass A: per-pixel fit coefficients a (rgb) and b over the window   -> half-float target
#  pass B: average a, b over the window, apply to this pixel's colour, firm up, then blend with last
#          frame's result (u_s0) for stability, letting big changes through at once so motion can't ghost.
GUIDED_A = """
uniform float u_rad, u_eps;
void main(){
  vec2 st = u_rad/3./u_res;
  vec3 mI = vec3(0.), mIp = vec3(0.);
  float mp = 0.;
  mat3 mII = mat3(0.);
  for (int y = -3; y <= 3; y++)
    for (int x = -3; x <= 3; x++){
      vec2 uv = v_uv + vec2(x, y)*st;
      vec3 I = clean(uv).rgb;
      float p = texture(u_tex, uv).r;
      mI += I; mp += p; mIp += I*p; mII += outerProduct(I, I);
    }
  mI /= 49.; mp /= 49.; mIp /= 49.; mII /= 49.;
  mat3 cov = mII - outerProduct(mI, mI) + mat3(u_eps);
  vec3 a = inverse(cov) * (mIp - mI*mp);
  o = vec4(a, mp - dot(a, mI));
}"""
GUIDED_B = """
uniform float u_rad, u_refine, u_stable, u_first, u_plate_k;
// how different this pixel is from the empty room. Brightness drops with the colour kept (shadows) count
// for little; colour changes, brightening and deep darkening count fully.
float plateDiff(vec3 c, vec3 p){
  float lc = lum(c) + .03, lp = lum(p) + .03, r = lc/lp;
  float chroma = length(c/lc - p/lp)*.8*smoothstep(.08, .3, max(lc, lp));
  return max(chroma, max((r - 1.)*.7, smoothstep(.45, .25, r)));
}
// the plate's view of the person: anything that changed, but only near where the AI found someone (so a
// moved chair across the room doesn't appear), and always the AI's solid core (clothes matching the wall)
float plateMask(){
  vec2 h = 1.2/u_res;
  vec3 c = vec3(0.), p = vec3(0.);
  for (int y = -1; y <= 1; y++)
    for (int x = -1; x <= 1; x++){
      c += clean(v_uv + vec2(x, y)*h).rgb;
      p += texture(u_plate, v_uv + vec2(x, y)*h).rgb; }
  float d = smoothstep(.1, .22, plateDiff(c/9., p/9.));
  float ai = texture(u_tex, v_uv).r, near = ai, core = ai;
  vec2 px = vec2(u_res.y/720.)/u_res;
  for (int i = 0; i < 8; i++){
    vec2 dir = vec2(cos(float(i)*.785), sin(float(i)*.785));
    near = max(near, max(texture(u_tex, v_uv + dir*50.*px).r, max(texture(u_tex, v_uv + dir*100.*px).r,
                                                               texture(u_tex, v_uv + dir.yx*150.*px).r)));
    core = min(core, texture(u_tex, v_uv + dir*8.*px).r);
  }
  return max(d, smoothstep(.35, .75, core))*smoothstep(.1, .5, near);
}
void main(){
  vec2 st = u_rad/3./u_res;
  vec4 ab = vec4(0.);
  for (int y = -3; y <= 3; y++)
    for (int x = -3; x <= 3; x++)
      ab += texture(u_s1, v_uv + vec2(x, y)*st);
  ab /= 49.;
  // the guide colour, lightly smoothed so sensor noise doesn't speckle the edge
  vec2 h = .8/u_res;
  vec3 I = .25*(clean(v_uv + h).rgb + clean(v_uv - h).rgb + clean(v_uv + vec2(h.x, -h.y)).rgb
              + clean(v_uv + vec2(-h.x, h.y)).rgb);
  float q = clamp(dot(ab.rgb, I) + ab.a, 0., 1.);
  float m = mix(texture(u_tex, v_uv).r, q, u_refine);
  m = mix(m, smoothstep(.1, .9, m), u_refine*.6);   // firmer edge
  if (u_plate_on > .5) m = mix(m, plateMask(), u_plate_k);
  float prev = texture(u_s0, v_uv).r;
  float k = u_first > .5 ? 1. : max(mix(1., .3, u_stable), smoothstep(.2, .6, abs(m - prev)));
  o = vec4(mix(prev, m, k), 0., 0., 1.);
}"""

# Look crossfade: u_tex = incoming look, u_s0 = outgoing look, u_p = progress 0..1.
# Styles match shared.LOOK_TRANSITIONS: 0 Dissolve, 1 Grow, 2 Cut, 3 Wipe, 4 Flash.
LOOK_MIX = """
uniform float u_p;
uniform int u_style;
void main(){
  vec3 a = texture(u_s0, v_uv).rgb, b = texture(u_tex, v_uv).rgb;
  float p = smoothstep(0., 1., u_p);
  if (u_style == 3) {   // wipe left to right with a soft, slightly slanted edge
    float edge = u_p*1.2 - .1, x = v_uv.x + (v_uv.y - .5)*.12;
    o = vec4(mix(b, a, smoothstep(edge - .1, edge + .1, x)), 1.); return; }
  if (u_style == 4) {   // flash: out to white, then into the new look
    o = vec4(u_p < .5 ? mix(a, vec3(1.), smoothstep(0., .5, u_p)) : mix(vec3(1.), b, smoothstep(.5, 1., u_p)), 1.);
    return; }
  o = vec4(mix(a, b, p), 1.);
}"""

# Output window blit: GL's screen origin is bottom-left, our images are top-first.
BLIT = "void main(){ o = texture(u_tex, vec2(v_uv.x, 1.-v_uv.y)); }"

CATEGORIES = ["Sources", "Cutout", "Interactive", "Audio", "Motion", "Mirror & Geometry", "Stylize", "Colour", "Overlay", "Feedback"]
_CAT = {
    "zoom": "Motion", "shake": "Motion", "liquid": "Motion",
    "sym_lr": "Mirror & Geometry", "sym_tb": "Mirror & Geometry", "sym_quad": "Mirror & Geometry",
    "kaleido": "Mirror & Geometry", "mirrorslice": "Mirror & Geometry", "fractal": "Mirror & Geometry", "droste": "Mirror & Geometry",
    "pixel": "Stylize", "glitch": "Stylize", "rgb": "Stylize", "edges": "Stylize", "glow": "Stylize",
    "poster": "Stylize", "vhs": "Stylize",
    "thermal": "Colour", "hue": "Colour", "invert": "Colour", "flash": "Colour",
    "bubbles": "Overlay", "trails": "Feedback", "tracers": "Feedback",
    "cutout": "Cutout", "media_a": "Sources", "media_b": "Sources", "media_c": "Sources",
}

# Media Layer: puts Source 2/3/4 into the chain as a box (fill / fit / stretch), placed with the centre,
# sized by the amount, with rotation, rounded corners and a neon border.
MEDIA_LAYER = """
float sdRoundBox(vec2 p, vec2 b, float r){ vec2 q = abs(p) - b + r;
  return length(max(q, 0.)) + min(max(q.x, q.y), 0.) - r; }
void main(){
  vec3 base = tx(v_uv).rgb;
  int s = u_opt0;
  float live = s == 0 ? u_mlive.x : (s == 1 ? u_mlive.y : u_mlive.z);
  float sa = s == 0 ? u_masp.x : (s == 1 ? u_masp.y : u_masp.z);   // source aspect (w/h)
  float oa = u_res.x/u_res.y;
  vec2 p = rot(radians(u_p0)) * ((v_uv - u_centre) * vec2(oa, 1.));   // screen space, in frame heights
  float size = mix(.08, 1., clamp(u_amt, 0., 1.));
  vec2 hb = vec2(oa, 1.) * .5 * size;                                 // fill / stretch: frame-shaped box
  if (u_opt1 == 1) hb = sa > oa ? vec2(oa, oa/sa)*.5*size : vec2(sa, 1.)*.5*size;   // fit: source-shaped
  vec2 q = p / (2.*hb) + .5;
  if (u_opt1 == 0) {   // fill: crop the source to cover the box
    float ba = hb.x/hb.y;
    if (sa > ba) q.x = (q.x - .5)*ba/sa + .5; else q.y = (q.y - .5)*sa/ba + .5;
  }
  float sd = sdRoundBox(p, hb, u_p1*min(hb.x, hb.y));
  float px = 1.5/u_res.y;
  float inside = smoothstep(px, -px, sd) * live;
  vec3 col = mix(base, media(s, clamp(q, 0., 1.)), inside);
  float glow = u_p2 * live * (smoothstep(.006 + .02*u_p2, 0., abs(sd)) * .9 + smoothstep(.06, 0., max(sd, 0.)) * .25);
  o = vec4(col + vec3(0., .94, 1.)*glow, 1.); }"""

# A group that starts from one source (Source 2-4): its effects ran on that video alone (u_s0, the source stretched
# to the frame), and this places the result like a Media Layer: u_amt size, u_centre, u_p0 rotate, u_p1 rounded,
# u_p2 border, u_opt1 fit; u_masp.x = the source's aspect, u_mlive.x = 1 while it has a picture.
GROUP_PLACE = """
uniform sampler2D u_cut;   // the source's own person mask (Cut out person), in the source's own picture space
uniform float u_cut_on;
float sdRoundBox(vec2 p, vec2 b, float r){ vec2 q = abs(p) - b + r;
  return length(max(q, 0.)) + min(max(q.x, q.y), 0.) - r; }
void fx_main(){
  vec3 base = tx(v_uv).rgb;
  float live = u_mlive.x, sa = u_masp.x, oa = u_res.x/u_res.y;
  vec2 p = rot(radians(u_p0)) * ((v_uv - u_centre) * vec2(oa, 1.));
  float size = mix(.08, 1., clamp(u_amt, 0., 1.));
  vec2 hb = vec2(oa, 1.) * .5 * size;
  if (u_opt1 == 1) hb = sa > oa ? vec2(oa, oa/sa)*.5*size : vec2(sa, 1.)*.5*size;
  vec2 q = p / (2.*hb) + .5;
  if (u_opt1 == 0) {
    float ba = hb.x/hb.y;
    if (sa > ba) q.x = (q.x - .5)*ba/sa + .5; else q.y = (q.y - .5)*sa/ba + .5;
  }
  float sd = sdRoundBox(p, hb, u_p1*min(hb.x, hb.y));
  float px = 1.5/u_res.y;
  float inside = smoothstep(px, -px, sd) * live;
  inside *= mix(1., smoothstep(.3, .7, texture(u_cut, clamp(q, 0., 1.)).r), u_cut_on);
  vec3 col = mix(base, texture(u_s0, clamp(q, 0., 1.)).rgb, inside);
  float glow = (1. - u_cut_on) * u_p2 * live * (smoothstep(.006 + .02*u_p2, 0., abs(sd)) * .9 + smoothstep(.06, 0., max(sd, 0.)) * .25);
  o = vec4(col + vec3(0., .94, 1.)*glow, 1.); }"""


# Transparent output (Background Eraser > Transparent): alpha = the person, plus any light effects added around
# them (glows, particles, flares count as visible in proportion to their brightness), for Spout. u_soft / u_mid
# are the eraser's Edge and Shrink / grow.
ALPHA_OUT = """
uniform float u_soft, u_mid;
void main(){
  vec3 c = texture(u_tex, v_uv).rgb;
  float m = smoothstep(u_mid - u_soft, u_mid + u_soft, maskAt(v_uv));
  float a = max(m, max(c.r, max(c.g, c.b)));
  o = vec4(mix(c/max(a, 1e-3), c, m), a); }"""


def _media(letter, default_source):
    return dict(id=f"media_{letter.lower()}", name=f"Media Layer {letter}", amt=.35, amt_label="Size", center=True,
                params=[("Rotate", 0., -180., 180., "%.0f deg"), ("Rounded", 0.), ("Neon border", 0.)],
                options=[("Source", ["Source 2", "Source 3", "Source 4"], default_source),
                         ("Fit", ["Fill frame", "Fit inside", "Stretch"], 1)],
                code=MEDIA_LAYER)

# Neon Edges passes. Detail = less pre-blur (more fine edges, more noise); Threshold = how strong an edge
# must be; lines are thinned to their crest (non-maximum suppression) so they stay crisp.
EDGE_DENOISE = """
void main(){ vec2 px = mix(2.2, .6, u_p2)/u_res;
  vec3 s = tx(v_uv).rgb*4.
         + (tx(v_uv + vec2(px.x, 0.)).rgb + tx(v_uv - vec2(px.x, 0.)).rgb
            + tx(v_uv + vec2(0., px.y)).rgb + tx(v_uv - vec2(0., px.y)).rgb)*2.
         + tx(v_uv + px).rgb + tx(v_uv - px).rgb + tx(v_uv + vec2(px.x, -px.y)).rgb + tx(v_uv + vec2(-px.x, px.y)).rgb;
  o = vec4(s/16., 1.); }"""
EDGE_GRADIENT = """
vec3 S(vec2 d){ return texture(u_s0, v_uv + d/u_res).rgb; }
void main(){
  vec3 tl = S(vec2(-1,-1)), t = S(vec2(0,-1)), tr = S(vec2(1,-1)), l = S(vec2(-1,0)), r = S(vec2(1,0)),
       bl = S(vec2(-1,1)), b = S(vec2(0,1)), br = S(vec2(1,1));
  vec3 gx = (tr + 2.*r + br) - (tl + 2.*l + bl), gy = (bl + 2.*b + br) - (tl + 2.*t + tr);
  // colour edges: the strongest direction across all three channels together (structure tensor)
  float gxx = dot(gx, gx), gyy = dot(gy, gy), gxy = dot(gx, gy);
  float ang = .5*atan(2.*gxy, gxx - gyy + 1e-6);
  float mag = sqrt(max(.5*((gxx + gyy) + (gxx - gyy)*cos(2.*ang) + 2.*gxy*sin(2.*ang)), 0.));
  o = vec4(cos(ang), sin(ang), mag, 1.); }"""
EDGE_MAIN = """
float thr(){ return mix(.12, 1.6, u_p1); }
float crest(vec2 uv){   // edge strength, kept only at the crest across the edge
  vec4 g = texture(u_s1, uv);
  vec2 d = g.xy/u_res;
  float side = max(texture(u_s1, uv + d).z, texture(u_s1, uv - d).z);
  return smoothstep(-.03, .03, g.z - side) * smoothstep(thr(), thr()*1.7, g.z);
}
float outline(vec2 uv, float w){   // the person's silhouette, from the AI mask
  vec2 px = w/u_res;
  vec2 g = vec2(maskAt(uv + vec2(px.x, 0.)) - maskAt(uv - vec2(px.x, 0.)),
                maskAt(uv + vec2(0., px.y)) - maskAt(uv - vec2(0., px.y)));
  return smoothstep(.12, .5, length(g));
}
void main(){
  float w = mix(.6, 3.5, u_p0);   // line thickness in pixels
  vec2 px = w/u_res;
  float e = 0.;
  if (u_opt2 != 1) {
    e = crest(v_uv);
    e = max(e, max(max(crest(v_uv + vec2(px.x, 0.)), crest(v_uv - vec2(px.x, 0.))),
                   max(crest(v_uv + vec2(0., px.y)), crest(v_uv - vec2(0., px.y))))*.9);
    if (u_opt2 == 3) e *= smoothstep(.3, .7, maskAt(v_uv));
  }
  if (u_opt2 == 1 || u_opt2 == 2) e = max(e, outline(v_uv, w + 1.));
  // double: a second, parallel line a few pixels out on each side of every edge
  float e2 = 0.;
  if (u_opt4 == 1) {
    float D = w*2.5 + 3.;
    for (int i = 0; i < 8; i++){
      vec2 o2 = vec2(cos(float(i)*.785), sin(float(i)*.785))*D/u_res;
      e2 = max(e2, u_opt2 == 1 ? outline(v_uv + o2, w + 1.) : crest(v_uv + o2));
    }
    e2 *= 1. - smoothstep(.1, .5, e);
    if (u_opt2 == 3) e2 *= smoothstep(.3, .7, maskAt(v_uv));
  }
  // pulse: bright bands running outward along the lines from the centre of the frame
  float asp = u_res.x/u_res.y;
  float dist = length((v_uv - .5)*vec2(asp, 1.));
  float pulse = mix(1., .5 + 1.5*pow(.5 + .5*sin(dist*18. - u_time*5.), 6.), u_p4);
  // glow: soft halo from strong edges nearby
  float glow = 0., gr = 3. + u_p3*14.;
  for (int i = 0; i < 8; i++){
    vec2 o2 = vec2(cos(float(i)*.785), sin(float(i)*.785))*gr/u_res;
    float m = u_opt2 == 1 ? outline(v_uv + o2, w + 1.) : smoothstep(thr(), thr()*2., texture(u_s1, v_uv + o2).z);
    glow += m;
  }
  glow = glow/8. * u_p3;
  if (u_opt2 == 3) glow *= smoothstep(.3, .7, maskAt(v_uv));
  float ph = palPhase(u_opt3, v_uv);
  vec3 src = tx(v_uv).rgb*1.4;
  vec3 col = palCycle(u_opt0, ph, src), col2 = palCycle(u_opt0, ph + .5, src);
  vec3 lines = ((e + glow*.6)*col + e2*col2*.9)*1.7*pulse;
  if (u_opt1 == 2) {   // white: coloured ink lines on white, the glow a soft tint around them
    float cover = clamp((e + e2*.9)*1.3*pulse, 0., 1.), halo = clamp(glow*1.2, 0., 1.);
    vec3 ink = (e*col + e2*col2*.9)/max(e + e2*.9, 1e-3);
    vec3 paper = mix(vec3(1.), mix(vec3(1.), col, .45), halo);
    o = vec4(mix(tx(v_uv).rgb, mix(paper, ink*.92, cover), clamp(u_amt, 0., 1.)), 1.); return;
  }
  vec3 base = u_opt1 == 1 ? vec3(0.) : tx(v_uv).rgb;
  o = vec4(mix(base, lines, clamp(u_amt, 0., 1.)), 1.); }"""

# Tracers: tails behind anything that moves.
#  state 0 = background model (slow average of the clean feed; adapts slower under moving things)
#  state 1 = tail memory: rgb = last colour of something moving here, a = how strong (fades)
_TRACER_FG = """
float foreground(){
  if (u_opt2 == 0) return smoothstep(.55 - u_p1*.45, .75 - u_p1*.4, maskAt(v_uv));   // AI person mask
  // motion: how much the clean feed here differs from the learned background
  float thr = mix(.35, .06, u_p1);
  return smoothstep(thr, thr*1.5, length(clean(v_uv).rgb - texture(u_s0, v_uv).rgb));
}
"""
TRACER_BG = """
void main(){ vec3 c = clean(v_uv).rgb; vec4 b = texture(u_s0, v_uv);
  float rate = b.a < .5 ? 1. : mix(.04, .008, smoothstep(.05, .2, length(c - b.rgb)));
  o = vec4(mix(b.rgb, c, rate), 1.); }"""
TRACER_TAIL = _TRACER_FG + """
void main(){ vec4 t = texture(u_s1, v_uv);
  float a = t.a * pow(mix(.86, .993, u_p0), u_dt*60.);     // fade, frame-rate independent
  float rate = mix(3., 15., u_p2);                           // echoes per second
  bool stamp = u_opt0 == 0 || floor(u_time*rate) != floor((u_time-u_dt)*rate);
  float fg = foreground();
  if (stamp && fg > a) { t.rgb = tx(v_uv).rgb; a = fg; }    // remember what's moving here now
  o = vec4(t.rgb, a); }"""

# Spec keys: id, name, amt (default amount), code (GLSL main), plus optional
#   react   - starts audio-driven            center - has a movable centre (u_centre)
#   speed   - animated: gets a Speed control  amt_label - name for the main slider
#   params  - extra sliders (label, default[, min, max, format]) -> u_p0..u_p2
#   options - dropdowns (label, [choices], default) -> u_opt0..u_opt2
# Bubble paths, shared by Bubbles and its touch check (BUBBLE_TOUCH)
BUBBLE_PATHS = """
// how one bubble travels: its own heading (any direction) and speed, a lean toward floating up or
// sinking (v_uv y grows downward), and a slow meander plus Wobble sway so the path curves.
// v = straight-line velocity (screen per second), bend = curving offset (never more than ~.1)
void travel(float s, float t, out vec2 v, out vec2 bend){
  float h1 = hash(vec2(s, 11.3)), h2 = hash(vec2(s, 12.9)), h3 = hash(vec2(s, 14.1)), h4 = hash(vec2(s, 15.7));
  float ang = h1*6.2831853;
  v = vec2(cos(ang), sin(ang)) * mix(.006, .055, h2*h2);
  // about a third float up, a third sink, the rest just wander wherever their heading takes them
  v.y += h3 < .35 ? -mix(.012, .045, h3/.35) : (h3 > .65 ? mix(.01, .05, (h3 - .65)/.35) : 0.);
  bend = vec2(sin(t*mix(.08, .22, h4) + s*2.1), cos(t*mix(.06, .19, h1) + s*1.3)) * .06
       + vec2(sin(t*(.7 + h4) + s), cos(t*(.6 + h2) + s*1.7)) * u_p1*.04;
}
// where a popping bubble starts a given life
vec2 spawnAt(float fi, float cycle){
  return vec2(mix(-.05, 1.05, hash(vec2(fi + cycle*13.1, 3.3))), mix(.05, .95, hash(vec2(fi + cycle*7.7, 9.1)))); }
"""
# Pop when touched: for bubble i, pixel (i, 0) remembers (the life it was popped in, the time); it works out
# where bubble i is now exactly as Bubbles does (pop-life path) and pops it if the person's mask touches it.
BUBBLE_TOUCH = BUBBLE_PATHS + """
void main(){
  ivec2 px = ivec2(gl_FragCoord.xy);
  vec4 st = texelFetch(u_s0, px, 0);
  if (px.y != 0 || px.x >= 24 || u_opt3 != 3) { o = st; return; }
  float fi = float(px.x), asp = u_res.x/u_res.y;
  float h1 = hash(vec2(fi,1.3)), h3 = hash(vec2(fi,4.1)), h5 = hash(vec2(fi,7.7));
  float size = .03 + u_amt*.42;
  float vary = exp(mix(u_p0*log(.03/size), u_p0, h5));
  float r = size*(.85 + .3*h3)*vary;
  float lifeSec = u_p3*mix(.6, 1.4, h3);
  float cy = u_time/lifeSec + h1*5., cycle = floor(cy), tl = fract(cy)*lifeSec;
  if (st.x == cycle) { o = st; return; }               // already popped in this life
  vec2 v, bend; travel(fi + cycle*17.3, tl, v, bend);
  vec2 c = spawnAt(fi, cycle) + v*tl + bend;
  float hit = maskAt(c);
  for (int k = 0; k < 8; k++){
    float a = float(k)*.785;
    vec2 q = c + vec2(cos(a)/asp, sin(a))*r*.9;
    if (q.x > 0. && q.x < 1. && q.y > 0. && q.y < 1.) hit = max(hit, maskAt(q));
  }
  o = hit > .55 && tl > .3 ? vec4(cycle, u_time, 0., 1.) : vec4(-1., 0., 0., 1.); }"""

EFFECTS = [
    # ---- Sources: extra inputs layered into the chain
    _media("A", 0), _media("B", 1), _media("C", 2),

    # ---- Cutout: AI person matte. Subject and background can each be the effected or clean image.
    dict(id="cutout", name="Background Eraser", amt=1., mask=True, first=True,
         params=[("Edge", .5), ("Shrink / grow", 0., -1., 1.)],
         options=[("Background", ["Black", "Green screen", "Blue screen", "Blur", "Clean feed",
                                  "With effects", "White", "Transparent (Spout)"], 0),
                  ("Subject", ["With effects", "Clean feed", "Invisible"], 0)], code="""
vec3 blurred(vec2 uv){ vec3 s = vec3(0.);
  for (int i = 0; i < 16; i++){ float a = float(i)*2.3998, r = sqrt(float(i)+.5)*6.;
    s += tx(uv + vec2(cos(a), sin(a))*r/u_res.y*vec2(u_res.y/u_res.x, 1.)*3.).rgb; }
  return s/16.; }
void main(){
  float soft = mix(.02, .25, u_p0), mid = .5 - u_p1*.35;   // edge softness, matte threshold
  float a = smoothstep(mid - soft, mid + soft, maskAt(v_uv));
  vec3 subj = u_opt1 == 1 ? clean(v_uv).rgb : tx(v_uv).rgb;
  // Invisible: the empty room shows where the person is (needs a captured background)
  if (u_opt1 == 2 && u_plate_on > .5) subj = texture(u_plate, v_uv).rgb;
  vec3 bg = u_opt0 == 1 ? vec3(0.,1.,0.) : u_opt0 == 2 ? vec3(0.,0.,1.) : u_opt0 == 3 ? blurred(v_uv)
          : u_opt0 == 4 ? clean(v_uv).rgb : u_opt0 == 5 ? tx(v_uv).rgb : u_opt0 == 6 ? vec3(1.) : vec3(0.);
  bg = mix(tx(v_uv).rgb, bg, clamp(u_amt, 0., 1.));   // amount = how much background is replaced
  o = vec4(mix(bg, subj, a), 1.); }"""),

    # ---- Motion
    dict(id="zoom", name="Pulse Zoom", amt=.35, react=True, center=True,
         options=[("Direction", ["Zoom in", "Zoom out"], 0)], code="""
void main(){ float z = 1. + u_amt*.6; if (u_opt0 == 1) z = 1./z;
  o = tx((v_uv-u_centre)/z + u_centre); }"""),

    dict(id="shake", name="Shake", amt=.4, react=True, speed=True,
         params=[("Rotate", 0.)], code="""
void main(){ float t = floor(u_time*30.), asp = u_res.x/u_res.y;
  vec2 off = (vec2(hash(vec2(t,1.)), hash(vec2(t,2.)))-.5)*u_amt*.06;
  float ang = (hash(vec2(t,3.))-.5)*u_amt*u_p0*.35;
  vec2 p = rot(ang)*((v_uv-.5)*vec2(asp,1.));
  o = tx(p/vec2(asp,1.)*.95 + .5 + off); }"""),

    dict(id="liquid", name="Liquid", amt=.4, speed=True,
         params=[("Wave size", .5)], code="""
void main(){ vec2 uv = v_uv; float a = u_amt*.04;
  float f = exp2(mix(1.5, -1.5, u_p0));   // small ripples .. big swells
  uv.x += sin(uv.y*18.*f + u_time*2.7)*a + sin(uv.y*41.*f - u_time*4.1)*a*.4;
  uv.y += cos(uv.x*14.*f + u_time*2.1)*a;
  o = tx(uv); }"""),

    # ---- Mirror & geometry. Symmetry: the centre places the mirror line(s); amount nudges
    # them (0.5 = no nudge), so audio react makes them sway around the centre.
    # "Mirror from" picks which side is kept and reflected onto the other (-1 = before the line, +1 = after)
    dict(id="sym_lr", name="Symmetry  left | right", amt=.5, center=True,
         options=[("Mirror from", ["Left side", "Right side"], 0)], code="""
void main(){ vec2 uv = v_uv; float a = u_centre.x + (u_amt-.5)*.5;
  uv.x = a + (u_opt0 == 1 ? 1. : -1.)*abs(uv.x - a); o = tx(uv); }"""),

    dict(id="sym_tb", name="Symmetry  top / bottom", amt=.5, center=True,
         options=[("Mirror from", ["Top", "Bottom"], 0)], code="""
void main(){ vec2 uv = v_uv; float a = u_centre.y + (u_amt-.5)*.5;
  uv.y = a + (u_opt0 == 1 ? 1. : -1.)*abs(uv.y - a); o = tx(uv); }"""),

    dict(id="sym_quad", name="Symmetry  four-way", amt=.5, center=True,
         options=[("Mirror from", ["Top-left", "Top-right", "Bottom-left", "Bottom-right"], 0)], code="""
void main(){ vec2 uv = v_uv; vec2 a = u_centre + (u_amt-.5)*.5;
  vec2 side = vec2(u_opt0 == 1 || u_opt0 == 3 ? 1. : -1., u_opt0 >= 2 ? 1. : -1.);
  uv = a + side*abs(uv - a); o = tx(uv); }"""),

    dict(id="kaleido", name="Kaleidoscope", amt=.4, center=True, speed=True,
         params=[("Zoom", .5), ("Rotation", 0., -180., 180., "%.0f deg"), ("Segments", 6., 2., 32., "%.0f")],
         options=[("Shape", ["Radial", "Triangle mirrors"], 0),
                  ("Symmetry", ["Smooth (Amount sets it)", "Exact (Segments sets it)"], 0)], code="""
float tri(float x, float h){ return h - abs(mod(x, 2.*h) - h); }   // mirror-repeat into 0..h
void main(){ float asp = u_res.x/u_res.y; vec2 p = v_uv-u_centre; p.x *= asp;
  if (u_opt0 == 1) {
    // three mirrors in a triangle (the classic toy): fold across three line families 60 degrees apart
    // until the point lands in one triangle; amount = more, smaller triangles
    float h = mix(.45, .12, clamp(u_amt, 0., 1.)) * exp2(mix(-1., 1., u_p0));
    p = rot(u_time*.1 + radians(u_p1)) * p;
    for (int k = 0; k < 4; k++)
      for (int j = 0; j < 3; j++){
        float a = float(j)*2.0943951 + 1.5707963;
        vec2 n = vec2(cos(a), sin(a));
        float d = dot(p, n) + h*.5;
        p += (tri(d, h) - d)*n;
      }
    p.x /= asp;
    o = tx(p + u_centre); return;
  }
  // Mirror-repeat the angle: continuous for any segment count, so as n grows a new
  // segment slides open from the far side instead of the pattern jumping.
  float n = u_opt1 == 1 ? floor(u_p2 + .5) : mix(3.,14.,clamp(u_amt,0.,1.));   // exact: whole segments only
  float s = 3.14159265/n;
  float t0 = atan(p.y,p.x) - radians(u_p1);                // Rotation turns the symmetry axes about the centre
  float r = length(p) / exp2(mix(-1.,1.,u_p0)), a = abs(atan(sin(t0), cos(t0)));
  a = s - abs(mod(a, 2.*s) - s);
  a += u_time*.15;
  p = vec2(cos(a),sin(a))*r; p.x /= asp;
  o = tx(p+u_centre); }"""),

    # Mirror Slice: the image tool, live. The picture is mirrored into a grid (none / left-right / up-down / both),
    # cut into strips, and the strips laid outside-in: 1, last, 2, second-to-last... first across, then down. Done
    # backwards per pixel (which strip, which mirror copy, which source pixel), so any counts run at full speed.
    dict(id="mirrorslice", name="Mirror Slice", amt=1., amt_label="Density", speed=True,
         params=[("Columns", 50., 2., 120., "%.0f"), ("Rows", 50., 2., 120., "%.0f"), ("Gaps", 0.)],
         options=[("Reflection", ["None", "Left-right", "Up-down", "Both"], 3),
                  ("Left-right copy", ["On the right", "On the left"], 0),
                  ("Up-down copy", ["Below", "Above"], 0),
                  ("Strips", ["Columns and rows", "Columns only", "Rows only"], 0),
                  ("Slice", ["Whole picture", "The person (over the picture)", "The person (over black)",
                             "The background (you stay whole)"], 0),
                  ("Motion", ["Still", "New density on the beat", "Drift"], 0)],
         mask_when=(4, (1, 2, 3)), code="""
// where strip position s (0..1) along an axis cut into n strips takes its picture from: the strips are laid
// 0, n-1, 1, n-2, 2... (outside-in), so position p shows strip p/2 when p is even, n-1-(p-1)/2 when odd
float unslice(float s, float n){
  float p = min(floor(s*n), n - 1.), f = s*n - p;
  float i = mod(p, 2.) < .5 ? p*.5 : n - 1. - (p - 1.)*.5;
  return (i + f)/n;
}
// the mirror grid along one axis: two halves, the original and its flipped copy (copyFirst: the copy comes first)
float unmirror(float c, bool on, bool copyFirst){
  if (!on) return c;
  float l = fract(c*2.);
  bool flipped = (c < .5) == copyFirst;
  return flipped ? 1. - l : l;
}
void main(){
  float dens = mix(.1, 1., clamp(u_amt, 0., 1.));
  if (u_opt5 == 1) {   // a new density on every beat, in a four-beat pattern: full, a third, two-thirds, a fifth
    float k = mod(floor(u_beats), 4.);
    dens *= k < .5 ? 1. : (k < 1.5 ? .35 : (k < 2.5 ? .65 : .2));
  }
  float cols = max(2., floor(u_p0*dens + .5)), rows = max(2., floor(u_p1*dens + .5));
  vec2 s = v_uv;
  if (u_opt5 == 2) s = fract(s + vec2(.05, .031)*u_time);   // the cut lines roll slowly (u_time runs at Speed)
  bool doCols = u_opt3 != 2, doRows = u_opt3 != 1;
  // gaps: thin dark lines between strips (anti-aliased over about a pixel)
  float gap = 1.;
  if (u_p2 > 0.) {
    float w = u_p2*.35;
    if (doCols) { float f = fract(s.x*cols); gap *= smoothstep(w, w + cols/u_res.x, min(f, 1. - f)); }
    if (doRows) { float f = fract(s.y*rows); gap *= smoothstep(w, w + rows/u_res.y, min(f, 1. - f)); }
  }
  if (doCols) s.x = unslice(s.x, cols);
  if (doRows) s.y = unslice(s.y, rows);
  s.x = unmirror(s.x, u_opt0 == 1 || u_opt0 == 3, u_opt1 == 1);
  s.y = unmirror(s.y, u_opt0 == 2 || u_opt0 == 3, u_opt2 == 1);
  vec3 sliced = tx(s).rgb*gap, here = texture(u_tex, v_uv).rgb;
  if (u_opt4 == 1 || u_opt4 == 2) {   // only the person is sliced: their mask travels with their pixels
    vec3 back = vec3(0.);
    if (u_opt4 == 1)   // the picture, with the unsliced you erased if the empty room has been captured
      back = u_plate_on > .5 ? mix(here, texture(u_plate, v_uv).rgb, maskAt(v_uv)) : here;
    o = vec4(mix(back, sliced, maskAt(s)), 1.); return; }
  if (u_opt4 == 3) {   // only the room is sliced; with a captured background, no bits of you in the pieces
    if (u_plate_on > .5) sliced = mix(sliced, texture(u_plate, s).rgb*gap, maskAt(s));
    o = vec4(mix(sliced, here, maskAt(v_uv)), 1.); return; }
  o = vec4(sliced, 1.);
}"""),
    dict(id="fractal", name="Fractal Fold", amt=.5, center=True, speed=True,
         params=[("Fold shape", .5), ("Zoom", .5)], code="""
void main(){ float asp = u_res.x/u_res.y; vec2 p = (v_uv-u_centre)*vec2(asp,1.);
  p /= exp2(mix(-1.,1.,u_p1));
  vec2 fold = vec2(.3,.2) * mix(.3, 1.7, u_p0);
  int depth = 1 + int(clamp(u_amt,0.,1.6)*4.);   // 1..7 folds
  for (int i = 0; i < 8; i++){
    if (i >= depth) break;
    p = abs(p) - fold;                        // fold the plane onto itself
    p = rot(u_time*.07 + float(i)*.6) * p;
    p *= 1.25;
  }
  o = tx(p/vec2(asp,1.) + u_centre); }"""),

    dict(id="droste", name="Infinite Zoom", amt=.4, center=True, speed=True,
         options=[("Spiral", ["Off", "1 turn", "2 turns", "3 turns"], 0)], code="""
void main(){ vec2 c = clamp(u_centre, .02, .98), d = v_uv - c;
  float asp = u_res.x/u_res.y;
  float k = mix(3.5, 1.7, clamp(u_amt,0.,1.));   // size ratio between nested frames
  float lk = log(k);
  // distance to the frame edge, measured from the centre: 0 at the centre, 1 at the edge
  vec2 e = abs(d) / mix(c, 1.-c, step(0., d));
  float rr = max(max(e.x, e.y), 1e-4);
  float m = mod(log(rr) - u_time*.25, lk) - lk;   // fold every ring into one band
  vec2 q = d*exp(m)/rr;
  // whole turns per nesting step keep the seam between rings invisible
  q = rot(float(u_opt0) * 6.2831853 * m/lk) * (q*vec2(asp,1.)) / vec2(asp,1.);
  o = tx(c + q); }"""),

    # ---- Stylize
    dict(id="pixel", name="Pixelate", amt=.3, center=True,
         options=[("Shape", ["Squares", "Circles", "Hexagons", "LED dots"], 0)], code="""
vec2 hexCentre(vec2 p, float s){
  vec2 r = vec2(1., 1.7320508)*s, h = r*.5;
  vec2 a = mod(p, r) - h, b = mod(p - h, r) - h;
  return dot(a,a) < dot(b,b) ? p - a : p - b; }
void main(){ float s = floor(mix(3.,56.,clamp(u_amt*u_amt,0.,1.)));
  vec2 px = (v_uv - u_centre)*u_res;   // the grid is laid out from the centre
  if (u_opt0 == 2) { o = tx(hexCentre(px, s*.6)/u_res + u_centre); return; }
  vec2 c = (floor(px/s)+.5)*s;
  vec3 col = tx(c/u_res + u_centre).rgb;
  float d = length(px - c)/(s*.5);
  if (u_opt0 == 1) col *= smoothstep(1., .85, d);
  else if (u_opt0 == 3) col = col*1.35*smoothstep(.85, .3, d) + col*.12;
  o = vec4(col, 1.); }"""),

    dict(id="glitch", name="Glitch", amt=.5, speed=True,
         params=[("Rate", .5), ("Block size", .5), ("Colour damage", .5)],
         options=[("Trigger", ["Constant", "On the beat"], 0)], code="""
void main(){ float t = floor(u_time*mix(2.,22.,u_p0));
  float amt = u_amt;
  if (u_opt0 == 1) {   // a hit on every beat that dies away, a fresh pattern each time
    amt *= exp(-u_since*mix(9., 3., u_p0));
    t = u_beats*7.31 + floor(u_since*mix(4., 16., u_p0));
  }
  float rows = mix(48.,6.,u_p1) * mix(.6,1.4,hash(vec2(t,1.)));
  float row = floor(v_uv.y*rows);
  vec2 uv = v_uv;
  if (hash(vec2(row,t)) < amt*.5) uv.x += (hash(vec2(row,t+3.))-.5)*.35*amt;
  float sh = .024*amt*u_p2;
  vec4 c = vec4(tx(uv+vec2(sh,0)).r, tx(uv).g, tx(uv-vec2(sh,0)).b, 1.);
  if (hash(vec2(t,row*7.)) < amt*.12*u_p2) c.rgb = 1.-c.rgb;
  o = c; }"""),

    dict(id="rgb", name="RGB Split", amt=.4, center=True,
         params=[("Angle", 0., 0., 360., "%.0f deg")],
         options=[("Direction", ["Radial", "Horizontal", "Vertical", "Angle"], 0),
                  ("Colours", ["RGB", "Red / Cyan", "Magenta / Green"], 0)], code="""
void main(){ vec2 d;
  if (u_opt0 == 0) d = (v_uv-u_centre)*u_amt*.07 + vec2(u_amt*.006,0);
  else { float a = u_opt0 == 1 ? 0. : (u_opt0 == 2 ? 1.5708 : radians(u_p0));
    d = vec2(cos(a), sin(a)*u_res.x/u_res.y)*u_amt*.02; }
  vec3 A = tx(v_uv+d).rgb, B = tx(v_uv).rgb, C = tx(v_uv-d).rgb;
  vec3 c = u_opt1 == 1 ? vec3(A.r, C.g, C.b) : (u_opt1 == 2 ? vec3(A.r, C.g, A.b) : vec3(A.r, B.g, C.b));
  o = vec4(c, 1.); }"""),

    # Neon Edges, in three passes: denoise (state 0) -> colour gradient (state 1) -> thin lines + glow.
    dict(id="edges", name="Neon Edges", amt=.8, speed=True, state=[EDGE_DENOISE, EDGE_GRADIENT],
         mask_when=(2, (1, 2, 3)),
         params=[("Thickness", .3), ("Threshold", .4), ("Detail", .5), ("Glow", .3), ("Pulse", 0.)],
         options=[("Colour", PALETTES, 0),
                  ("Background", ["Video", "Black", "White"], 0),
                  ("Edges from", ["Image", "Person outline", "Image + outline", "Image, on person only"], 0),
                  ("Colour motion", COLOUR_MOTION, 2),
                  ("Lines", ["Single", "Double"], 0)],
         code=EDGE_MAIN),

    dict(id="glow", name="Glow", amt=.5,
         params=[("Threshold", .45)], code="""
void main(){ vec3 c = tx(v_uv).rgb, b = vec3(0);
  float r = 6. + u_amt*14.;
  for (int i = 0; i < 12; i++){
    float a = float(i)*.5236;
    b += max(tx(v_uv + vec2(cos(a),sin(a))*r/u_res).rgb - u_p0, 0.);
  }
  o = vec4(c + b/12.*u_amt*3., 1.); }"""),

    dict(id="poster", name="Posterize", amt=.6, code="""
void main(){ float n = floor(mix(12.,2.,clamp(u_amt,0.,1.))); vec3 c = tx(v_uv).rgb;
  o = vec4(floor(c*n+.5)/n, 1.); }"""),

    dict(id="vhs", name="VHS", amt=.6, speed=True,
         params=[("Noise", .5), ("Scanlines", .5), ("Tracking", .5)], code="""
void main(){ float line = floor(v_uv.y*u_res.y*.5), t = floor(u_time*30.);
  vec2 uv = v_uv;
  uv.x += ((hash(vec2(line,t))-.5)*.012 + sin(v_uv.y*3.+u_time)*.006)*u_amt*u_p2;
  float sh = .004*u_amt;
  vec3 c = vec3(tx(uv+vec2(sh,0)).r, tx(uv).g, tx(uv-vec2(sh,0)).b);
  c *= 1. - u_amt*u_p1*.5*(.5+.5*sin(v_uv.y*u_res.y*3.14159));
  c += (hash(v_uv*u_res+u_time)-.5)*.36*u_amt*u_p0;
  vec2 q = v_uv-.5; c *= 1. - dot(q,q)*1.2*u_amt;
  o = vec4(c, 1.); }"""),

    # ---- Colour
    dict(id="thermal", name="Thermal", amt=1., speed=True,
         options=[("Palette", ["Heat", "Night vision", "Ice", "Acid", "Sunset"] + PALETTES, 0),
                  ("Colour motion", COLOUR_MOTION, 0)], code="""
vec3 palette(float t, int m){
  if (m == 1) return vec3(.15,1.,.25)*pow(t, .8)*1.2 + vec3(0.,.04,0.);
  if (m == 2) return mix(mix(vec3(0.,.02,.1), vec3(0.,.5,.9), smoothstep(0.,.5,t)), vec3(.9,1.,1.), smoothstep(.5,1.,t));
  if (m == 3) return .5 + .5*cos(6.2831*(t*1.5 + vec3(0.,.33,.67)) + u_time);
  if (m == 4) return mix(mix(vec3(.15,0.,.3), vec3(1.,.25,.3), smoothstep(0.,.55,t)), vec3(1.,.85,.4), smoothstep(.55,1.,t));
  vec3 c = mix(vec3(0,0,.2), vec3(.5,0,.8), smoothstep(0.,.25,t));
  c = mix(c, vec3(1,0,.2), smoothstep(.25,.5,t));
  c = mix(c, vec3(1,.8,0), smoothstep(.5,.75,t));
  return mix(c, vec3(1), smoothstep(.75,1.,t)); }
void main(){ vec3 b = tx(v_uv).rgb;
  // colour motion slides the brightness-to-colour mapping (wrapping round, like a cycling heat scale)
  float t = lum(b), ph = palPhase(u_opt1, v_uv);
  if (u_opt1 != 0) t = 1. - abs(fract(t*.5 + ph*.5)*2. - 1.);
  vec3 c = u_opt0 < 5 ? palette(t, u_opt0) : palMap(u_opt0 - 5, t, b);
  o = vec4(mix(b, c, clamp(u_amt,0.,1.)), 1.); }"""),

    dict(id="hue", name="Hue Cycle", amt=.3, speed=True, amt_label="Shift", code="""
void main(){ vec3 c = tx(v_uv).rgb; o = vec4(hueRot(c, u_amt*6.2831 + u_time), 1.); }"""),

    dict(id="invert", name="Invert", amt=1., code="""
void main(){ vec3 c = tx(v_uv).rgb; o = vec4(mix(c, 1.-c, clamp(u_amt,0.,1.)), 1.); }"""),

    dict(id="flash", name="Flash", amt=.5, react=True, code="""
void main(){ vec3 c = tx(v_uv).rgb; float k = clamp(u_amt-.35, 0., 1.);
  o = vec4(mix(c, vec3(1), k*.85), 1.); }"""),

    # ---- Overlay. Soap-bubble spheres, each holding the video; some drift, some fly at the viewer.
    dict(id="bubbles", name="Bubbles", amt=.4, amt_label="Size", center=True, speed=True, xform=True,
         params=[("Variety", .5), ("Wobble", .3), ("Shimmer", .6), ("Lifetime", 8., 2., 30., "%.0f s")],
         options=[("Inside", ["With effects", "Clean feed", "Reflections (recursive)"], 0),
                  ("Background", ["With effects", "Clean feed", "Dark"], 0),
                  ("Count", ["8", "16", "24", "1 (big)"], 1),
                  ("Ending", ["Fade", "Pop", "Pop on beat", "Pop when touched"], 0),
                  ("Film colour", PALETTES, 0),
                  ("Shape", ["Sphere", "Heart", "Star", "Hexagon"], 0)],
         mask_when=(3, (3,)), state=[BUBBLE_TOUCH], state_size=[(1, "f4")],
         code=BUBBLE_PATHS + """
// what a bubble shows: the picture so far, the clean feed, or last frame's finished output (which
// includes the bubbles themselves, so they reflect each other recursively)
vec3 pick(int m, vec2 uv){
  if (m == 2) return texture(u_prev, mirrorWrap(uv)).rgb;
  return m == 1 ? clean(uv).rgb : tx(uv).rgb; }
// outline distance of the bubble's shape in direction p (1 = circle): Sphere, Heart, Star, Hexagon
float shapeRadius(int s, vec2 p, float spin){
  if (s == 0) return 1.;
  if (s == 1) {   // polar heart, point down (v_uv y grows downward), a gentle sway instead of a spin
    vec2 q = rot(sin(spin)*.25) * p;
    float a = atan(-q.y, q.x), sa = sin(a);
    float h = sa*sqrt(abs(cos(a)))/(sa + 1.4) - 2.*sa + 2.;
    return clamp(h*.33, .05, 1.4);
  }
  float a = atan(p.y, p.x) + spin;
  if (s == 2) {   // five-point star with softened tips
    float k = abs(fract(a/1.2566371) - .5)*2.;
    return mix(.5, 1.05, smoothstep(.0, 1., k));
  }
  float k = mod(a, 1.0471976) - .5235988;   // hexagon
  return .93/cos(k);
}
float vnoise(vec2 p){ vec2 i = floor(p), f = fract(p); f = f*f*(3. - 2.*f);
  return mix(mix(hash(i), hash(i + vec2(1,0)), f.x), mix(hash(i + vec2(0,1)), hash(i + vec2(1,1)), f.x), f.y); }
// soap film: thickness swirls like marbling (domain-warped noise flowing over the sphere)
float filmThickness(vec2 p, float t, float seed){
  p = rot(t*.15 + seed) * p;
  vec2 w = vec2(vnoise(p*2.2 + seed + t*.35), vnoise(p*2.2 - seed*1.7 - t*.3));
  return vnoise(p*1.6 + w*2.6 + t*.12) + .35*vnoise(p*4.5 - w*1.5);
}
// pop burst: a cloud of shimmering particles drifting out from where the bubble was. Each has its own
// size, speed, swirl, twinkle rhythm and lifespan; at its brightest it flashes a small four-point glint.
vec3 burst(vec2 uv, vec2 c, float r0, float bt, float seed, float asp){
  vec2 p = (uv - c) * vec2(asp, 1.);
  if (bt <= 0. || bt >= 1. || length(p) > r0*3.2) return vec3(0.);
  float out_ = 1. - (1. - bt)*(1. - bt);               // fast out, slowing down
  vec3 light = vec3(0.);
  for (int j = 0; j < 18; j++){
    float fj = float(j);
    float h1 = hash(vec2(seed, fj)), h2 = hash(vec2(fj, seed + 1.7)), h3 = hash(vec2(seed + fj, 4.1));
    float ang = h1*6.2831853 + out_*(h3 - .5)*1.2;      // a little swirl as they spread
    vec2 dir = vec2(cos(ang), sin(ang));
    vec2 pos = dir * r0*(.2 + .75*h2 + out_*(.3 + .6*h3));
    float life = .45 + .55*h2;                           // some fade sooner than others
    float alive = 1. - smoothstep(life*.5, life, bt);
    if (alive <= 0.) continue;
    vec2 q = p - pos;
    float sr = max(r0*mix(.008, .022, h3), 1.4/u_res.y);
    float d = length(q);
    float tw = pow(.5 + .5*sin(u_time*(22. + 26.*h1) + fj*5.3 + seed), 3.);   // shimmer
    float dot_ = smoothstep(sr, 0., d) + .35*smoothstep(sr*4., 0., d);
    float glint = (smoothstep(sr*.22, 0., abs(q.y))*smoothstep(sr*4., 0., abs(q.x))
                 + smoothstep(sr*.22, 0., abs(q.x))*smoothstep(sr*4., 0., abs(q.y))) * tw*tw;
    vec3 hue = mix(vec3(1.), .55 + .45*cos(6.2831*(h1 + seed*.13 + vec3(0., .33, .67))), .55);
    light += hue * (dot_*(.3 + .7*tw) + glint*.45) * alive;
  }
  // a faint glow where the bubble was, gone almost at once
  float flash = smoothstep(r0*.8, 0., length(p)) * smoothstep(.2, 0., bt) * .18;
  return light*1.1 + vec3(.8, .9, 1.)*flash;
}
void main(){
  float asp = u_res.x/u_res.y;
  vec3 col = u_opt1 == 2 ? vec3(.015,.015,.03) : pick(u_opt1, v_uv);
  bool single = u_opt2 == 3;   // one big bubble floating around the centre
  int n = single ? 1 : (u_opt2 == 0 ? 8 : (u_opt2 == 1 ? 16 : 24));
  float size = .03 + u_amt*.42;   // radius in screen heights: tiny .. ~90% of the screen across
  // every bubble covering this pixel; blended back to front afterwards (radius = nearness), so a bubble
  // fading out never hides the ones behind it all at once
  vec4 hitCol[24]; float hitNear[24]; int hits = 0;
  bool touch = u_opt3 == 3;   // Ending: Pop when touched = popped by the person (see BUBBLE_TOUCH)
  bool pop = u_opt3 == 1 || touch;   // Pop = each bubble lives for a while, then collapses into a sparkle burst
  bool onBeat = u_opt3 == 2;   // Pop on beat: lifetimes counted in beats, every pop lands on one
  vec3 sparks = vec3(0.);
  for (int i = 0; i < 24; i++){
    if (i >= n) break;
    float fi = float(i);
    float h1 = hash(vec2(fi,1.3)), h2 = hash(vec2(fi,2.7)), h3 = hash(vec2(fi,4.1)), h4 = hash(vec2(fi,5.9));
    float h5 = hash(vec2(fi,7.7));
    // per-bubble size factor: Variety 0 = all alike; Variety 1 = anything from the smallest size there is
    // up to ~2.7x the chosen Size, so the bigger the Size the wider the spread, and tiny ones still turn up
    float vary = exp(mix(u_p0*log(.03/size), u_p0, h5));
    vec2 c; float r, fade = 1.;
    float life = -1.;   // pop mode: this bubble's phase through its life (0..1), -1 = not popping
    float cycle = 0., lifeSec = 1.;   // this bubble's lifetime in seconds
    if (single) {
      c = u_centre + vec2(sin(u_time*.31), cos(u_time*.27))*.025;
      r = size*1.25;
      if (pop) { lifeSec = u_p3*1.5; float cy = u_time/lifeSec; cycle = floor(cy); life = fract(cy); }
      if (onBeat) {
        float lifeB = max(1., floor(u_p3*.5 + .5));
        cycle = floor(u_beats/lifeB);
        if (u_beats - cycle*lifeB == 0.) sparks += burst(v_uv, c, r, u_since/.4, cycle*1.7, asp);
        r *= smoothstep(0., .25, (u_beats - cycle*lifeB)*u_beatlen + u_since);
        if (r <= 0.) continue;
      }
    } else if ((pop || onBeat) && (h4 < .6 || touch)) {   // pop modes: appears somewhere, travels, pops
      r = size*(.85 + .3*h3)*vary;
      float tl;
      if (onBeat) {
        // lives a whole number of beats (Lifetime / 2 s per beat, varied) and pops exactly on a beat
        float lifeB = max(1., floor(u_p3*.5*mix(.6, 1.4, h3) + .5));
        float k = u_beats + floor(h1*8.);
        cycle = floor(k/lifeB);
        float pos = k - cycle*lifeB;
        tl = pos*u_beatlen + u_since;
        if (pos == 0.) {   // this beat popped the previous one: sparkle where it was
          float te = lifeB*u_beatlen;
          vec2 v0, b0; travel(fi + (cycle - 1.)*17.3, te, v0, b0);
          sparks += burst(v_uv, spawnAt(fi, cycle - 1.) + v0*te + b0, r, u_since/.4, fi*3.1 + cycle*1.7, asp);
        }
        r *= smoothstep(0., .25, tl);   // and the new one grows in
        if (r <= 0.) continue;
      } else {
        lifeSec = u_p3*mix(.6, 1.4, h3);
        float cy = u_time/lifeSec + h1*5.;
        cycle = floor(cy); life = fract(cy);
        tl = life*lifeSec;
      }
      vec2 v, bend; travel(fi + cycle*17.3, tl, v, bend);   // a new path every life
      c = spawnAt(fi, cycle) + v*tl + bend;
      if (touch) {   // touched in this life: gone, with a sparkle burst where it was
        vec4 st = texelFetch(u_s0, ivec2(i, 0), 0);
        if (st.x == cycle) { sparks += burst(v_uv, c, r, (u_time - st.y)/.4, fi*3.1 + cycle*1.7, asp); continue; }
      }
    } else if (h4 < .6) {   // drifting its own way, wrapping around the screen
      r = size*(.85 + .3*h3)*vary;
      vec2 v, bend; travel(fi, u_time, v, bend);
      // wrap only once the whole bubble (plus wobble and its curving path) is off screen, on any side
      vec2 m = vec2(r*1.1/asp + .11, r*1.1 + .11);
      c = fract(vec2(h1, h2) + v*u_time);
      c = c*(1. + 2.*m) - m + bend;
    } else {         // flying out of the distance and through the screen
      float ph = fract(h1 + u_time*(.04 + .05*h2));
      vec2 dir = vec2(cos(fi*2.4), sin(fi*2.4)) * (.15 + .35*h3);
      c = u_centre + dir*(.2 + ph*ph*1.6);
      r = size*.25*vary / max(1.04 - ph, .04);
      if (pop) {   // pops on the way in, before it gets huge
        life = ph/.8;
        lifeSec = .8/(.04 + .05*h2);
        cycle = floor(h1 + u_time*(.04 + .05*h2));
        fade = smoothstep(0., .08, ph);
      } else {
        fade = smoothstep(.97, .7, ph) * smoothstep(0., .08, ph);   // dissolve as it rushes past
      }
    }
    if (life >= 0.) {
      // grow in, live, then the edge snaps inward (~0.07 s) and it bursts into sparkle (~0.4 s);
      // timed in seconds so the pop is equally quick whatever the lifetime
      float r0 = r, tl = life*lifeSec, popAt = lifeSec - .48;
      r *= smoothstep(0., .25, tl) * (1. - smoothstep(popAt, popAt + .07, tl));
      sparks += burst(v_uv, c, r0, (tl - popAt - .04)/.4, fi*3.1 + cycle*1.7, asp) * fade;
      if (r <= 0.) continue;
    }
    vec2 p = (v_uv - c) * vec2(asp,1.);
    // wobble: the rim breathes like a real soap film
    float wob = 1. + u_p1*.08*sin(atan(p.y,p.x)*3. + u_time*3. + fi)*sin(u_time*1.7 + fi*2.);
    // d = 0 at the middle, 1 on the outline; other shapes stretch it by the outline's distance that way
    float d = length(p) / (r*wob*shapeRadius(u_opt5, p, u_time*(h2 - .5)*.6 + fi));
    float aa = 1.5/(u_res.y*r);                    // ~1.5 px soft edge: crisp outline at any size
    float a = smoothstep(1., 1. - aa, d) * fade;
    if (d >= 1. || a <= .002) continue;
    vec2 nxy = normalize(p + 1e-6) * d;
    float nz = sqrt(1. - d*d);
    vec3 nrm = vec3(nxy, nz);
    vec2 q = nxy * (.62 - .18*nz);   // fisheye: the whole frame wrapped onto the sphere
    vec3 inner = pick(u_opt0, .5 + q*vec2(1./asp, 1.));
    float fres = pow(1. - nz, 2.5);
    // thin-film interference: swirling rainbow bands, strong toward the rim, faint over the middle
    float th = filmThickness(nxy, u_time, fi*3.7) + fres*1.3 - nxy.y*.25;   // film drains thinner at the top
    vec3 film = palCycle(u_opt4, th*1.4, inner);
    float filmAmt = u_p2 * (pow(1. - nz, 1.2)*.75 + .06);
    vec3 L = normalize(vec3(-.45,-.55,.7));
    float spec = pow(max(dot(reflect(-L, nrm), vec3(0,0,1)), 0.), 60.);
    // a fine bright line just inside the edge makes the outline read clearly
    float rim = smoothstep(1. - 6.*aa - .015, 1. - aa, d) * smoothstep(1., 1. - 2.*aa, d);
    vec3 b = inner*(.75 + .25*nz)*(1. - filmAmt*.3) + film*filmAmt + spec*1.2
           + mix(vec3(1.), film, .5)*rim*.55;
    hitCol[hits] = vec4(b, a);
    hitNear[hits] = r;
    hits++;
  }
  for (int k = 0; k < 24; k++){   // farthest (smallest) first
    if (k >= hits) break;
    int back = 0;
    for (int j = 1; j < 24; j++){
      if (j >= hits) break;
      if (hitNear[j] < hitNear[back]) back = j;
    }
    col = mix(col, hitCol[back].rgb, hitCol[back].a);
    hitNear[back] = 1e9;
  }
  o = vec4(col + sparks, 1.); }"""),

    dict(id="tracers", name="Tracers", amt=.85, speed=True, mask=True, state=[TRACER_BG, TRACER_TAIL],
         params=[("Length", .6), ("Sensitivity", .5), ("Echo rate", .4)],
         options=[("Style", ["Smooth", "Echoes", "Strobe clones"], 0),
                  ("Colour", ["Original"] + PALETTES, 0),
                  ("Detect", ["Person (AI)", "Any motion"], 0),
                  ("Colour motion", COLOUR_MOTION, 1)],
         code=_TRACER_FG + """
void main(){ vec3 cur = tx(v_uv).rgb;
  vec4 t = texture(u_s1, v_uv);
  vec3 tail = t.rgb;
  float a = t.a;
  // strobe clones: solid copies that drop away in steps instead of a smooth fade
  if (u_opt0 == 2) a = a > .04 ? ceil(a*4.)/4. : 0.;
  if (u_opt1 == 1) tail = hueRot(tail, (1.-t.a)*5. + palPhase(u_opt3, v_uv)*6.2831);   // rainbow: shifts as it ages
  else if (u_opt1 > 1) {   // palette colour by age, shaded by the original's brightness
    int id = u_opt1 - 1;
    vec3 pc = palCycle(id, (1.-t.a)*.8 + palPhase(u_opt3, v_uv), tail);
    tail = id == 4 ? tail : pc*(.35 + lum(tail));
  }
  // the moving thing itself stays as it is; tails show only where it has been
  o = vec4(mix(cur, tail, a * (1. - foreground()) * clamp(u_amt, 0., 1.)), 1.); }"""),

    # ---- Feedback: the previous frame, zoomed/rotated/hue-shifted, mixed back in. By default it remembers
    # its own result (state 0), so only effects above it in the chain trail; "Final output" feeds back
    # the whole finished frame (everything trails, including effects after it).
    dict(id="trails", name="Trails / Feedback", amt=.7, center=True, state=["""
void main(){ vec4 c = tx(v_uv);
  float asp = u_res.x/u_res.y;
  vec2 p = rot(u_p1*.04) * ((v_uv-u_centre)*vec2(asp,1.)) * (1. - u_p0*.03);
  vec2 puv = p/vec2(asp,1.) + u_centre;
  vec3 prev = u_opt0 == 1 ? texture(u_prev, puv).rgb : texture(u_s0, puv).rgb;
  prev = hueRot(prev, u_p2*.25);
  o = vec4(mix(c.rgb, prev, clamp(u_amt,0.,1.)*.93), 1.); }"""],
         params=[("Zoom", .33, -1., 1.), ("Rotate", 0., -1., 1.), ("Hue drift", 0.)],
         options=[("Feed back", ["This point in the chain", "Final output"], 0)], code="""
void main(){ o = texture(u_s0, v_uv); }"""),
]

def _glyph(*rows):
    """A 5x5 character as bits (x + 5*y), from five strings where '#' is ink."""
    return sum(1 << (x + 5 * y) for y, row in enumerate(rows) for x, ch in enumerate(row) if ch == "#")

# light to dark: space . : - = + * # % @
_RAMP = [0, _glyph(".....", ".....", ".....", ".....", "..#.."), _glyph(".....", "..#..", ".....", "..#..", "....."),
         _glyph(".....", ".....", ".###.", ".....", "....."), _glyph(".....", ".###.", ".....", ".###.", "....."),
         _glyph(".....", "..#..", ".###.", "..#..", "....."), _glyph(".....", ".#.#.", "..#..", ".#.#.", "....."),
         _glyph(".#.#.", "#####", ".#.#.", "#####", ".#.#."), _glyph("#...#", "...#.", "..#..", ".#...", "#...#"),
         _glyph(".###.", "#...#", "#.###", "#....", ".####")]
_DIGITS = [_glyph(".###.", "#..##", "#.#.#", "##..#", ".###."), _glyph("..#..", ".##..", "..#..", "..#..", ".###."),
           _glyph(".###.", "#...#", "..##.", ".#...", "#####"), _glyph("####.", "....#", "..##.", "....#", "####."),
           _glyph("#..#.", "#..#.", "#####", "...#.", "...#."), _glyph("#####", "#....", "####.", "....#", "####."),
           _glyph(".###.", "#....", "####.", "#...#", ".###."), _glyph("#####", "...#.", "..#..", ".#...", ".#..."),
           _glyph(".###.", "#...#", ".###.", "#...#", ".###."), _glyph(".###.", "#...#", ".####", "....#", ".###.")]
GLYPHS = f"""
const int RAMP[10] = int[10]({", ".join(map(str, _RAMP))});
const int DIGIT[10] = int[10]({", ".join(map(str, _DIGITS))});
float glyph(int bits, vec2 f){{   // f = position in the cell 0..1: 5x5 dots with a one-dot margin
  vec2 g = floor(f*7.) - 1.;
  if (g.x < 0. || g.y < 0. || g.x > 4. || g.y > 4.) return 0.;
  return float((bits >> int(g.x + 5.*g.y)) & 1);
}}
"""

# Line drawing blur passes: lum blurred at two widths (r = fine, g = wide), horizontal then vertical.
_LINE_BLUR = """
void main(){
  float s1 = mix(.7, 2.6, u_p0), s2 = s1*1.6;
  vec2 dir = DIR/u_res * max(1., s2/2.5);
  float st = max(1., s2/2.5);
  vec2 acc = vec2(0.), wsum = vec2(0.);
  for (int i = -7; i <= 7; i++){
    float x = float(i)*st;
    vec2 w = vec2(exp(-x*x/(2.*s1*s1)), exp(-x*x/(2.*s2*s2)));
    vec2 v = SRC(v_uv + float(i)*dir);
    acc += w*v; wsum += w;
  }
  o = vec4(acc/wsum, 0., 1.); }"""
LINE_BLUR_H = _LINE_BLUR.replace("DIR", "vec2(1., 0.)").replace("SRC(", "vec2(lum(tx(").replace(
    "float(i)*dir);", "float(i)*dir).rgb));")
LINE_BLUR_V = _LINE_BLUR.replace("DIR", "vec2(0., 1.)").replace("SRC(", "texture(u_s0, ").replace(
    "float(i)*dir);", "float(i)*dir).rg;")

# Slit-scan: state 0 is an atlas of 16 recent frames (4 x 4 tiles at half size each); a new tile every
# Time span / 16 seconds, overwriting the oldest.
SLIT_ATLAS = """
void main(){
  float every = mix(.25, 4., u_p0)/16.;
  float wi = mod(floor(u_time/every), 16.);
  vec2 tile = floor(v_uv*4.);
  if (tile.x + 4.*tile.y == wi) { o = vec4(tx(fract(v_uv*4.)).rgb, 1.); return; }
  o = texture(u_s0, v_uv); }"""

# Datamosh: state 0 = the moshed picture, pushed along by the motion of the live video (block motion
# vectors, like a broken video file that lost its keyframes); state 1 = last frame, to measure motion.
MOSH = """
void main(){
  vec4 last = texture(u_s0, v_uv);
  vec3 cur = tx(v_uv).rgb;
  float every = mix(.5, 8., u_p1);
  bool key = last.a < .5
          || (u_opt0 == 0 && floor(u_time/every) != floor((u_time - u_dt)/every))
          || (u_opt0 == 1 && u_since < 1e-4);
  if (key) { o = vec4(cur, 1.); return; }
  // motion of this 16 px block (Lucas-Kanade over a 3 x 3 grid of samples)
  float bs = 16.;
  vec2 bc = (floor(v_uv*u_res/bs) + .5)*bs/u_res;
  vec2 e = 2./u_res;
  float a11 = 1e-4, a12 = 0., a22 = 1e-4, b1 = 0., b2 = 0.;
  for (int y = -1; y <= 1; y++)
    for (int x = -1; x <= 1; x++){
      vec2 s = bc + vec2(x, y)*5./u_res;
      float gx = lum(tx(s + vec2(e.x, 0.)).rgb) - lum(tx(s - vec2(e.x, 0.)).rgb);
      float gy = lum(tx(s + vec2(0., e.y)).rgb) - lum(tx(s - vec2(0., e.y)).rgb);
      float it = lum(tx(s).rgb) - lum(texture(u_s1, s).rgb);
      a11 += gx*gx; a12 += gx*gy; a22 += gy*gy; b1 -= gx*it; b2 -= gy*it;
    }
  float det = a11*a22 - a12*a12;
  vec2 v = det > 1e-6 ? vec2(a22*b1 - a12*b2, a11*b2 - a12*b1)/det*4. : vec2(0.);   // pixels per frame
  v = clamp(v, -14., 14.)*mix(.5, 3., u_p0);
  vec3 moshed = texture(u_s0, v_uv - v/u_res).rgb;
  o = vec4(mix(moshed, cur, mix(.003, .12, u_p2)), 1.); }"""

# Particles: real particles (64 x 64 = 4096), each a texel of a float texture: position, age, depth. Every
# frame an update pass moves them through a velocity field (state 0), then they're drawn as glowing points.
# Fluid: Off = each type's plain drift; Swirl = a churning fluid that the person stirs when they move;
# Flow around subject = the person is also a solid obstacle, with eddies curling off behind them.
PARTICLE_COMMON = """
float pn(vec2 p){ vec2 i = floor(p), f = fract(p); f = f*f*(3. - 2.*f);
  return mix(mix(hash(i), hash(i + vec2(1,0)), f.x), mix(hash(i + vec2(0,1)), hash(i + vec2(1,1)), f.x), f.y); }
// the plain drift for each type, plus Wind (screen heights per second)
vec2 driftVel(){
  int type = u_opt0;
  vec2 v = type == 1 ? vec2(0., -.09) : type == 2 ? vec2(0., .07) : type == 3 ? vec2(0., -.01)
         : type == 4 ? vec2(0., .01) : vec2(.01, -.005);
  return v + vec2(u_p2*.12, 0.);
}
// outward direction from the person's outline (soft mask gradient), and how close to it this is
vec3 outline(vec2 uv){
  vec2 e = 10./u_res;
  vec2 g = vec2(maskAt(uv + vec2(e.x, 0.)) - maskAt(uv - vec2(e.x, 0.)),
                maskAt(uv + vec2(0., e.y)) - maskAt(uv - vec2(0., e.y)));
  float gl = length(g);
  return vec3(gl > .02 ? -g/gl : vec2(0.), smoothstep(.02, .25, gl));
}
// swirling flow without bunching up: the curl of drifting noise (two layers), screen heights per second
vec2 curlFlow(vec2 uv){
  float asp = u_res.x/u_res.y;
  vec2 q = uv*vec2(asp, 1.)*2.5;
  vec2 a = q + vec2(u_time*.11, -u_time*.07), b = q*2.1 - vec2(u_time*.09, u_time*.13);
  float k = .03;
  float n0 = pn(a) + .5*pn(b);
  float nx = pn(a + vec2(k, 0.)) + .5*pn(b + vec2(k*2.1, 0.));
  float ny = pn(a + vec2(0., k)) + .5*pn(b + vec2(0., k*2.1));
  return vec2(ny - n0, -(nx - n0))/k*.4;
}
"""
# state 0: the momentum the person gives the air by moving (xy, screen heights per second; carried along
# and slowly dying away, longer with more Swirl), and last frame's mask (z)
PARTICLE_FLOW = PARTICLE_COMMON + """
void main(){
  float asp = u_res.x/u_res.y, dt = u_dt*abs(u_speed);
  float m = maskAt(v_uv);
  if (u_opt4 == 0) { o = vec4(0., 0., m, 1.); return; }
  vec4 old = texture(u_s0, v_uv);
  vec2 v = texture(u_s0, v_uv - (old.xy + driftVel())*vec2(1./asp, 1.)*dt).xy;
  v *= exp(-dt*mix(2.5, .5, u_p3));
  // pushed out ahead of the person (mask arriving) and drawn in behind (mask leaving) to fill the gap
  vec3 ol = outline(v_uv);
  float dm = clamp((m - old.z)/max(dt, 1e-3), -6., 6.);
  v += ol.xy*dm*(u_opt4 == 1 ? .015 : .04);   // Swirl: moving mostly stirs it (see airAt) rather than shoves
  float L = length(v);
  if (L > .5) v *= .5/L;
  o = vec4(v, m, 1.); }"""
# point update: xy = position (v_uv space), z = age (s), w = lifetime (s; 0 = not placed yet). Each particle
# lives a few seconds, then starts again somewhere random, so swept-up clumps and cleared patches even out.
# Depth (0..1, near = bigger, faster) comes from the particle's texel, the same way in PARTICLE_VERT.
PARTICLE_UPDATE = PARTICLE_COMMON + """
uniform sampler2D u_pos;
// how the air moves at a particle: the type's drift, the person's momentum, swirl, and (Flow around)
// sliding round the person's outline instead of through it
vec2 airAt(vec2 p){
  vec2 base = driftVel();
  if (u_opt4 == 0) return base;
  vec2 mom = texture(u_s0, clamp(p, 0., 1.)).xy;
  vec2 v = base + mom;
  float spd = max(length(base), .05);
  if (u_opt4 == 1) return v + curlFlow(p)*(spd*u_p3*3. + length(mom)*5.);   // movement whips up eddies
  float asp = u_res.x/u_res.y;
  float m = maskAt(p);
  float wake = maskAt(p - normalize(base + 1e-5)*vec2(1./asp, 1.)*.1)*(1. - m);   // just behind the person
  v += curlFlow(p)*spd*u_p3*(.6 + 5.*wake);
  vec3 ol = outline(p);
  float into = dot(v, ol.xy);
  if (into < 0.) {   // blocked: the part heading into the person turns to slide round them
    vec2 side = vec2(-ol.y, ol.x);
    side *= dot(side, v) < 0. ? -1. : 1.;
    v += (ol.xy + side*1.5)*(-into)*ol.z;
  }
  return v + ol.xy*smoothstep(.45, .9, m)*.3;   // caught inside: out it goes
}
void main(){
  vec4 P = texture(u_pos, v_uv);
  vec2 id = floor(v_uv*vec2(textureSize(u_pos, 0)));
  float h1 = hash(id + .5), h2 = hash(id.yx + 3.7), depth = hash(id + 9.1);
  float life = mix(4., 10., h2);
  if (P.w <= 0.) P = vec4(h1, h2, hash(id + 2.2)*life, life);   // first frame: spread out, ages staggered
  float asp = u_res.x/u_res.y, dt = u_dt*u_speed;
  if (P.z > P.w) {   // end of its life: a fresh start somewhere else
    float r = P.x*17.3 + P.y*31.1 + u_time;
    P = vec4(hash(id + r), hash(id.yx + r*1.7), 0., life);
  }
  vec2 v = airAt(P.xy);
  // each particle's own wander (fireflies roam more)
  float wa = u_opt0 == 3 ? .05 : .015;
  v += vec2(sin(P.z*(.6 + h1*1.3) + h2*6.3), cos(P.z*(.5 + depth) + h1*6.3))*wa;
  P.xy += v*mix(.6, 1.4, depth)*vec2(1./asp, 1.)*dt;   // nearer particles move faster
  P.z += abs(dt);
  // off one edge: back in at the opposite one
  const float M = .03;
  if (P.x < -M) P.x += 1. + 2.*M; else if (P.x > 1. + M) P.x -= 1. + 2.*M;
  if (P.y < -M) P.y += 1. + 2.*M; else if (P.y > 1. + M) P.y -= 1. + 2.*M;
  o = P; }"""
PARTICLE_VERT = """#version 330 core
uniform sampler2D u_pos;
uniform vec2 u_res;
uniform float u_amt, u_p0, u_p1;
uniform int u_opt0;
out vec2 v_uv;
out vec4 v_part;   // random seed, depth, how far through its life (0..1), core radius / sprite size
float hash(vec2 p){ p = fract(p*vec2(123.34,456.21)); p += dot(p, p+45.32); return fract(p.x*p.y); }
void main(){
  int N = textureSize(u_pos, 0).x;
  ivec2 ij = ivec2(gl_VertexID % N, gl_VertexID / N);
  vec4 P = texelFetch(u_pos, ij, 0);
  float id = float(gl_VertexID);
  float seed = fract(sin(id*12.9898 + 78.233)*43758.5453);
  float pick = fract(sin(id*39.3467 + 11.135)*24634.6345);
  float depth = hash(vec2(ij) + 9.1);   // as in PARTICLE_UPDATE
  float sz = mix(1.5, 7., u_p0)*mix(.55, 1.5, depth)*(u_opt0 == 2 ? 1.4 : 1.)*u_res.y/720.;
  float sprite = sz*(1. + 4.*u_p1) + 2.;   // room for the glow
  v_uv = P.xy;
  v_part = vec4(seed, depth, clamp(P.z/max(P.w, .01), 0., 1.), sz/sprite);
  gl_PointSize = sprite;
  // Amount = how many of the particles are shown
  bool show = P.w > 0. && pick < clamp(u_amt, 0., 1.)*.95 + .03;
  gl_Position = show ? vec4(P.xy*2. - 1., 0., 1.) : vec4(2., 2., 2., 1.);
}"""
PARTICLE_FRAG = """
in vec4 v_part;
uniform float u_mix;
uniform vec3 u_tw;
vec3 natural(int type, float h, float age){
  if (type == 1) return mix(vec3(1., .85, .35), vec3(1., .2, .02), age);    // embers cool as they rise
  if (type == 2) return vec3(.92, .96, 1.);
  if (type == 3) return mix(vec3(.75, 1., .2), vec3(1., .85, .2), h);
  if (type == 4) return mix(vec3(1.), .6 + .4*cos(6.2831*(h + vec3(0., .33, .67))), .4);
  return vec3(1., .93, .8);
}
void main(){
  vec2 q = gl_PointCoord*2. - 1.;
  float d = length(q);
  if (d > 1.) discard;
  float h = v_part.x, depth = v_part.y, cr = v_part.w, t = u_time;
  int type = u_opt0;
  float bright = 1.;
  if (type == 1) bright = .6 + .4*sin(t*(8. + h*9.) + h*20.);                // flicker
  if (type == 3) bright = pow(.5 + .5*sin(t*(1. + h*1.5) + h*30.), 6.);       // blink
  if (type == 4) bright = pow(.5 + .5*sin(t*(3. + h*5.) + h*47.), 8.)*1.5;    // twinkle
  if (type == 0) bright = .45;
  float core = smoothstep(cr, cr*.3, d);
  float halo = exp(-d/(cr*2.5))*u_p1*.6*smoothstep(1., .5, d);
  float glint = 0.;
  if (type == 4)
    glint = (smoothstep(cr*.15, 0., abs(q.y))*smoothstep(1., 0., abs(q.x))
           + smoothstep(cr*.15, 0., abs(q.x))*smoothstep(1., 0., abs(q.y)))*bright;
  float age = v_part.z;
  bright *= smoothstep(0., .08, age)*smoothstep(1., .85, age);   // fades in when born, out before it ends
  vec3 c = u_opt2 == 0 ? natural(type, h, age)
         : palCycle(u_opt2 - 1, h*.7 + palPhase(u_opt3, v_uv), natural(type, h, age));
  float m = maskAt(v_uv);
  float vis = u_opt1 == 1 ? 1. - smoothstep(.3, .7, m) : 1.;   // behind the person
  if (u_opt4 == 2) vis *= 1. - smoothstep(.5, .9, m);           // flowing round: none left on the person
  vis *= u_tw.x + u_tw.y*m + u_tw.z*(1. - m);
  o = vec4(c*((core + halo)*bright + glint*.8)*mix(.6, 1.3, depth)*vis*u_mix*clamp(u_amt*1.5, 0., 1.), 1.); }"""

# Film Looks: each style is a small colour recipe (u_opt0 picks one, in this order)
FILM_LOOKS = ["Sepia", "Black & white", "Noir", "Vintage", "Old film", "Polaroid", "Teal & orange",
              "Bleach bypass", "Cross-process", "Technicolor", "Cool blue", "Golden hour", "Lomo", "Cyberpunk",
              "Infrared", "Night vision"]
FILM_LOOK_CODE = """
vec3 curve(vec3 c, float k){ return mix(c, c*c*(3. - 2.*c), k); }   // S-curve: more contrast, soft ends
vec3 look(vec3 c, int s, vec2 uv){
  float l = lum(c);
  if (s == 0) return mix(vec3(l), vec3(l*1.07, l*.87, l*.62) + vec3(.06, .03, 0.), .9);          // sepia
  if (s == 1) return curve(vec3(l), .3);                                                         // b&w
  if (s == 2) return vec3(smoothstep(.12, .82, curve(vec3(l), 1.).r));                           // noir
  if (s == 3) { c = mix(vec3(l), c, .7); c = c*vec3(1.08, 1., .82) + vec3(.06, .04, .02);          // vintage
                return mix(c, vec3(.95, .85, .7), .1); }
  if (s == 4) {                                                                                  // old film
    float t = floor(u_time*18.);
    vec3 sp = vec3(l*1.05, l*.92, l*.72);
    sp *= .88 + .12*hash(vec2(t, 1.));                                                           // flicker
    float x = hash(vec2(t, 2.));                                                                 // a scratch
    sp *= 1. - .5*smoothstep(.0015, 0., abs(uv.x - x))*step(.6, hash(vec2(t, 3.)));
    float dust = step(.9993, hash(floor(uv*u_res/3.) + t));
    return mix(sp, vec3(.05), dust); }
  if (s == 5) { c = curve(c, .35)*vec3(1.05, 1.02, .9) + vec3(.03, .05, .07)*(1. - l);              // polaroid
                return mix(vec3(l), c, .85); }
  if (s == 6) { vec3 teal = vec3(0., .5, .55), orange = vec3(1., .55, .25);                         // teal & orange
                c = mix(c, mix(teal, orange, smoothstep(.2, .75, l))*l*1.8, .45); return curve(c, .3); }
  if (s == 7) return mix(c, vec3(l), .55)*1.05 + (curve(vec3(l), 1.) - l)*.6;                     // bleach bypass
  if (s == 8) return vec3(smoothstep(.05, .95, c.r), curve(vec3(c.g), .6).g*1.05,               // cross-process
                          c.b*.7 + .15);
  if (s == 9) { vec3 t = vec3(c.r - (c.g + c.b)*.5, c.g - (c.r + c.b)*.5, c.b - (c.r + c.g)*.5);    // technicolor
                return clamp(c + t*.6, 0., 1.); }
  if (s == 10) return curve(mix(vec3(l), c, .7)*vec3(.82, .97, 1.15) + vec3(0., .02, .05), .2);  // cool blue
  if (s == 11) return curve(c*vec3(1.15, .98, .72) + vec3(.05, .02, 0.), .25);                   // golden hour
  if (s == 12) { c = mix(vec3(l), c, 1.5); return curve(c, .8); }                                 // lomo
  if (s == 13) { c = mix(vec3(.15, 0., .35), mix(vec3(1., .1, .7), vec3(.1, .95, 1.),               // cyberpunk
                     smoothstep(.45, .85, l)), smoothstep(.05, .6, l)); return c*(.5 + l); }
  if (s == 14) { float g = clamp(c.g*1.6 - c.r*.3, 0., 1.);                                       // infrared
                 return vec3(g*1.1 + .1, g*.75 + c.r*.2, c.b*.6 + (1. - g)*.25); }
  float n = hash(uv*u_res + u_time*61.);                                                         // night vision
  float g = curve(vec3(clamp(l*1.8, 0., 1.)), .6).r*(.85 + .3*n);
  g *= .9 + .1*sin(uv.y*u_res.y*1.4);
  return vec3(.15, 1., .25)*g;
}
void main(){
  vec3 src = tx(v_uv).rgb;
  int s = u_opt0;
  vec3 c = clamp(look(src, s, v_uv), 0., 1.);
  c = mix(c, vec3(.08) + c*.84, u_p2);                                             // fade: lifted blacks
  float asp = u_res.x/u_res.y;
  float r = length((v_uv - .5)*vec2(asp, 1.)*.85);
  float vig = u_p1 + (s == 12 ? .45 : s == 4 || s == 15 ? .3 : 0.);                // lomo, old film, nv: more
  c *= 1. - smoothstep(.25, .95, r)*clamp(vig, 0., 1.);
  float gr = hash(floor(v_uv*u_res/1.5) + fract(u_time*7.3)*91.) - .5;           // grain, coarser in shadows
  c += gr*u_p0*.22*(1.2 - lum(c));
  o = vec4(mix(src, clamp(c, 0., 1.), clamp(u_amt, 0., 1.)), 1.); }"""

# Lens flare styles for Light Leaks & Flares ("Flare type", u_opt4). Each draws the light from source point s:
# u_p1 = streak amount, u_opt1 = palette for the coloured parts (the core is always near-white).
FLARE_TYPES = ["Classic", "Anamorphic", "Starburst", "Hex ghosts", "Sun glare", "Rainbow ring", "Bokeh"]
FLARE_HELPERS = """
float sdHex(vec2 p, float r){ p = abs(p); return max(p.x*.866 + p.y*.5, p.y) - r; }
vec3 pc(float t, vec3 base){ return palCycle(u_opt1, t, base); }
// ghosts: copies of the light's shape strung along the line from the light through the middle of the frame
vec2 ghostAt(vec2 s, float k){ return s + (vec2(.5) - s)*k*2.; }
vec3 flare(int type, vec2 s, float asp, float ph, vec3 base){
  vec2 p = (v_uv - s)*vec2(asp, 1.);
  float d = length(p), a = atan(p.y, p.x), t = u_time;
  vec3 L = vec3(0.);
  if (type == 1) {   // anamorphic: the cinema look, a long blue streak and oval ghosts
    vec3 blue = mix(vec3(.3, .55, 1.), pc(ph + .6, base), .35);
    L += vec3(.85, .92, 1.)*(exp(-d*16.)*1.1 + exp(-d*5.)*.2);
    float sx = exp(-abs(p.x)*mix(1.6, .45, u_p1));
    L += blue*(exp(-abs(p.y)*mix(420., 120., u_p1))*1.6 + exp(-abs(p.y)*40.)*.25)*sx*(.9 + u_p1)*1.4;
    for (int i = 1; i <= 3; i++){   // fainter parallel lines above and below
      float off = float(i)*.012;
      L += blue*(exp(-abs(p.y - off)*700.) + exp(-abs(p.y + off)*700.))*sx*.35/float(i);
    }
    for (int i = 0; i < 5; i++){
      float fi = float(i);
      vec2 g = (v_uv - ghostAt(s, .4 + fi*.32))*vec2(asp, 1.);
      float e = length(g*vec2(.45, 1.6)) - mix(.02, .05, hash(vec2(fi, 3.1)));
      L += mix(blue, pc(ph + fi*.15, base), .5)*(smoothstep(.012, -.004, e)*.28 + smoothstep(.006, 0., abs(e))*.3);
    }
  } else if (type == 2) {   // starburst: diffraction spikes from a small aperture, slowly turning
    L += vec3(1., .97, .9)*(exp(-d*22.)*1.4 + exp(-d*6.)*.25);
    float rot = t*.05;
    float sp = pow(abs(cos(a*3. + rot)), 60.) + pow(abs(cos(a*3. + rot + .5236)), 60.)*.6
             + pow(abs(cos(a*6. + rot*2.)), 160.)*.4;
    L += mix(vec3(1.), pc(ph + .3, base), .3)*sp*exp(-d*mix(9., 3.5, u_p1))*1.3;
    L += pc(ph + .1, base)*smoothstep(.012, 0., abs(d - .12))*.25*(.6 + .4*sin(a*12.));   // a rainbow rim
  } else if (type == 3) {   // hex ghosts: the aperture's hexagons, with coloured fringes
    L += vec3(1., .95, .85)*(exp(-d*14.)*1.1 + exp(-d*4.)*.22);
    for (int i = 0; i < 7; i++){
      float fi = float(i), r = mix(.02, .09, hash(vec2(fi, 6.6)));
      vec2 g = (v_uv - ghostAt(s, .3 + fi*.29))*vec2(asp, 1.);
      g = rot(.3)*g;
      vec3 col = pc(ph + fi*.14, base);
      float e = sdHex(g, r);
      L += col*smoothstep(.006, -.006, e)*.2 + col*smoothstep(.005, 0., abs(e))*.45;
      L.r += smoothstep(.005, 0., abs(sdHex(g, r*1.05)))*.2;   // red and blue edges a hair apart
      L.b += smoothstep(.005, 0., abs(sdHex(g, r*.95)))*.2;
    }
    L += pc(ph + .6, base)*exp(-abs(p.y)*mix(260., 60., u_p1))*exp(-abs(p.x)*1.5)*u_p1*.8;
  } else if (type == 4) {   // sun glare: a big warm bloom that washes the frame, with soft rays
    vec3 warm = mix(vec3(1., .78, .45), pc(ph, base), .3);
    L += vec3(1., .96, .85)*exp(-d*9.)*1.2 + warm*exp(-d*2.2)*.55;
    L += warm*.12*smoothstep(1.4, 0., d);   // veiling glare over everything
    float rays = pow(.5 + .5*sin(a*23. + sin(a*7. + t*.1)*2.), 6.)*.6 + pow(.5 + .5*sin(a*41. - t*.07), 10.)*.4;
    L += warm*rays*exp(-d*mix(4., 1.6, u_p1))*.45;
  } else if (type == 5) {   // rainbow ring: a large prismatic halo, and a faint arc on the other side
    float R = .32;
    vec3 ring = vec3(smoothstep(.03, 0., abs(d - R*1.04)), smoothstep(.03, 0., abs(d - R)),
                     smoothstep(.03, 0., abs(d - R*.96)));
    L += vec3(1., .96, .9)*(exp(-d*15.)*1.1 + exp(-d*4.)*.22);
    L += mix(ring, ring*pc(ph + .3, base)*1.6, .3)*.55;
    vec2 g = (v_uv - ghostAt(s, 1.))*vec2(asp, 1.);
    float gd = length(g);
    L += pc(ph + .7, base)*smoothstep(.02, 0., abs(gd - .18))*.18*smoothstep(-.2, .6, dot(normalize(g + 1e-5),
                                                                                          normalize(-p + 1e-5)));
    L += pc(ph + .6, base)*exp(-abs(p.y)*mix(260., 60., u_p1))*exp(-abs(p.x)*1.5)*u_p1*.7;
  } else if (type == 6) {   // bokeh: soft out-of-focus orbs drifting round the light
    L += vec3(1., .95, .88)*(exp(-d*14.)*1. + exp(-d*4.)*.2);
    for (int i = 0; i < 12; i++){
      float fi = float(i), h = hash(vec2(fi, 1.7)), h2 = hash(vec2(fi, 4.3));
      vec2 c = ghostAt(s, .2 + h*1.1) + vec2(sin(t*.15 + fi*2.1)/asp, cos(t*.12 + fi*1.3))*.06;
      c += vec2((h2 - .5)*.35/asp, (hash(vec2(fi, 9.)) - .5)*.3);
      float r = mix(.035, .11, h2), od = length((v_uv - c)*vec2(asp, 1.));
      vec3 col = pc(ph + h*.8, base);
      L += col*(smoothstep(r, r*.75, od)*.17 + smoothstep(.006, 0., abs(od - r*.88))*.22)*(.6 + .4*sin(t*.4 + fi));
    }
  } else {   // classic: core, streak, halo ring and round ghosts
    L += vec3(1., .95, .85)*(exp(-d*14.)*1.2 + exp(-d*4.)*.25);
    L += pc(ph + .6, base)*exp(-abs(p.y)*mix(260., 60., u_p1))*exp(-abs(p.x)*1.5)*u_p1*1.4;
    L += pc(ph + .2, base)*smoothstep(.02, 0., abs(d - .28))*.18;
    for (int i = 0; i < 6; i++){
      float fi = float(i);
      float gr = mix(.015, .07, hash(vec2(fi, 8.8)));
      float gd = length((v_uv - ghostAt(s, .35 + fi*.38))*vec2(asp, 1.));
      L += pc(ph + fi*.17, base)*smoothstep(gr, gr*.6, gd)*.12 + pc(ph + fi*.17 + .3, base)*smoothstep(.006, 0., abs(gd - gr))*.15;
    }
  }
  return L;
}
"""

NEW_EFFECTS = [
    # ---- Overlay
    dict(id="particles", name="Particles", amt=.5, amt_label="Amount", speed=True,
         mask_when=[(1, (1,)), (4, (1, 2))], state=[PARTICLE_FLOW],
         points=dict(n=64, update=PARTICLE_UPDATE, vert=PARTICLE_VERT, frag=PARTICLE_FRAG),
         params=[("Size", .4), ("Glow", .5), ("Wind", 0., -1., 1.), ("Swirl", .5)],
         options=[("Type", ["Dust", "Embers", "Snow", "Fireflies", "Sparkles"], 1),
                  ("Subject", ["In front", "Behind subject"], 0),
                  ("Colour", ["Natural"] + PALETTES, 0),
                  ("Colour motion", COLOUR_MOTION, 0),
                  ("Fluid", ["Off", "Swirl", "Flow around subject"], 0)],
         code="void main(){ o = tx(v_uv); }"),

    dict(id="leaks", name="Light Leaks & Flares", amt=.6, amt_label="Intensity", center=True, speed=True, xform=True,
         params=[("Softness", .5), ("Flare streak", .5), ("Movement size", .5), ("Beat flash", .3)],
         options=[("Style", ["Light leaks", "Lens flare", "Both"], 0),
                  ("Colour", PALETTES, 10),
                  ("Colour motion", COLOUR_MOTION, 1),
                  ("Flare movement", ["Still", "Drift", "Orbit", "Sweep"], 1),
                  ("Flare type", FLARE_TYPES, 0)],
         code=FLARE_HELPERS + """
void main(){
  vec3 base = tx(v_uv).rgb;
  float asp = u_res.x/u_res.y;
  vec3 light = vec3(0.);
  float ph = palPhase(u_opt2, vec2(0.));
  if (u_opt0 != 1) {   // light leaks: big soft colour blooms drifting in from the edges
    for (int i = 0; i < 5; i++){
      float fi = float(i), h = hash(vec2(fi, 2.3)), h2 = hash(vec2(fi, 5.1));
      float t = u_time*(.05 + .05*h);
      vec2 c = vec2(.5 + .75*sin(t + h*6.3), .5 + .6*cos(t*1.3 + h2*6.3));
      float rad = mix(.25, .7, h2)*mix(.6, 1.4, u_p0);
      float d = length((v_uv - c)*vec2(asp, 1.));
      float k = exp(-d*d/(rad*rad))*(.55 + .45*sin(u_time*.3 + fi*2.));
      light += palCycle(u_opt1, h + ph + fi*.21, base)*k*.8;
    }
    // a burn along one edge that slowly wanders round the frame
    float side = sin(u_time*.07)*.5 + .5;
    float edge = mix(v_uv.x, 1. - v_uv.y, step(.5, fract(u_time*.02)));
    light += palCycle(u_opt1, ph + .5, base)*smoothstep(.35*mix(.6, 1.4, u_p0), 0., edge)*.6*side;
  }
  if (u_opt0 != 0) {   // lens flare: placed by the centre point, moved by Flare movement
    vec2 s = u_centre;
    float ms = mix(.08, .55, u_p2), t = u_time;
    if (u_opt3 == 1)        // drift: wanders around the centre on a slow, never-repeating path
      s += vec2(sin(t*.23) + .5*sin(t*.61 + 1.3), cos(t*.19) + .5*sin(t*.47 + 2.1))*ms*vec2(.7, .5);
    else if (u_opt3 == 2)   // orbit: circles the centre
      s += vec2(cos(t*.35)/asp, sin(t*.35))*ms;
    else if (u_opt3 == 3) { // sweep: passes across the frame like a light going by, then comes round again
      float ph = fract(t*.06);
      s = vec2(mix(-.3, 1.3, ph), u_centre.y + sin(ph*3.14159)*-.15*ms*3.);
    }
    // a gentle shimmer, and a flash on every beat
    float flick = (.88 + .12*sin(t*7.3)*sin(t*3.1)) * (1. + u_p3*1.2*exp(-u_since*6.));
    vec3 leaks = light;
    light += flare(u_opt4, s, asp, ph, base);
    light = leaks + (light - leaks)*flick;
  }
  light *= clamp(u_amt, 0., 1.6);
  o = vec4(1. - (1. - base)*(1. - clamp(light, 0., 1.)), 1.); }"""),

    dict(id="rays", name="Light Rays", amt=.6, amt_label="Intensity", center=True, xform=True, mask_when=(0, (0,)),
         params=[("Length", .6), ("Threshold", .55), ("Spread", .5)],
         options=[("Rays from", ["Behind subject (AI)", "Bright areas"], 0),
                  ("Colour", PALETTES, 12),
                  ("Colour motion", COLOUR_MOTION, 0)],
         code="""
float emit(vec2 uv, vec2 c, float asp){
  if (u_opt0 == 0) {   // a light behind the person: the open background glows around the light point
    float d = length((uv - c)*vec2(asp, 1.));
    return (1. - smoothstep(.3, .7, maskAt(uv)))*exp(-d*d/(mix(.01, .15, u_p2)));
  }
  return max(lum(tx(uv).rgb) - mix(.4, .95, u_p1), 0.)*3.;
}
void main(){
  vec3 base = tx(v_uv).rgb;
  float asp = u_res.x/u_res.y;
  vec2 c = u_centre;
  float reach = mix(.2, .95, u_p0);
  float acc = 0., w = 1., wsum = 0.;
  float jitter = hash(v_uv*u_res);   // hides the banding of the samples
  for (int i = 0; i < 40; i++){
    float k = (float(i) + jitter)/40.*reach;
    acc += emit(mix(v_uv, c, k), c, asp)*w;
    wsum += w;
    w *= .96;
  }
  acc /= wsum;
  float a = atan(v_uv.y - c.y, (v_uv.x - c.x)*asp);
  vec3 col = palCycle(u_opt1, a*.3 + palPhase(u_opt2, v_uv), base);
  vec3 rays = col*acc*clamp(u_amt, 0., 1.6)*1.3;
  o = vec4(1. - (1. - base)*(1. - clamp(rays, 0., 1.)), 1.); }"""),

    dict(id="shapes", name="Neon Shapes", amt=.4, amt_label="Size", speed=True, center=True, xform=True,
         params=[("Line width", .35), ("Glow", .5), ("Spin", .5), ("Beat pulse", .5)],
         options=[("Shape", ["Rings", "Triangles", "Squares", "Hexagons", "Mixed"], 4),
                  ("Count", ["6", "12", "20"], 1),
                  ("Colour", PALETTES, 5),
                  ("Colour motion", COLOUR_MOTION, 1)],
         code="""
void main(){
  vec3 base = tx(v_uv).rgb;
  float asp = u_res.x/u_res.y;
  int n = u_opt1 == 0 ? 6 : (u_opt1 == 1 ? 12 : 20);
  float pulse = 1. + u_p3*.3*exp(-u_since*7.);
  vec3 light = vec3(0.);
  for (int i = 0; i < 20; i++){
    if (i >= n) break;
    float fi = float(i);
    float h1 = hash(vec2(fi, 1.1)), h2 = hash(vec2(fi, 2.2)), h3 = hash(vec2(fi, 3.3)), h4 = hash(vec2(fi, 4.4));
    float R = (.03 + u_amt*.22)*mix(.5, 1.5, h3)*pulse;
    // drift in its own direction, wrapping once fully off screen
    float ang = h4*6.2831;
    vec2 m = vec2(R*1.5/asp + .02, R*1.5 + .02);
    vec2 c = fract(vec2(h1, h2) + vec2(cos(ang), sin(ang))*u_time*mix(.01, .04, h3));
    c = c*(1. + 2.*m) - m;
    vec2 p = (v_uv - c)*vec2(asp, 1.);
    p = rot(u_time*(h1 - .5)*mix(0., 2.5, u_p2) + fi) * p;
    p.x /= max(abs(cos(u_time*.4*(h2 - .3) + fi)), .25);   // a slow tumble in depth
    int s = u_opt0 == 4 ? int(h1*4.) : u_opt0;
    float d;
    if (s == 0) d = abs(length(p) - R);
    else {
      float sides = s == 1 ? 3. : (s == 2 ? 4. : 6.);
      float an = 6.2831853/sides, a = atan(p.y, p.x) + an*.5;
      d = abs(cos(floor(.5 + a/an)*an - a)*length(p) - R*cos(an*.5));
    }
    float w = mix(.0015, .012, u_p0);
    float line = smoothstep(w, w*.4, d);
    float glow = exp(-d/(w*5.))*u_p1*.7;
    light += palCycle(u_opt2, h2 + palPhase(u_opt3, c), base)*(line + glow);
  }
  o = vec4(base + light, 1.); }"""),

    dict(id="visualizer", name="Audio Visualizer", amt=.5, amt_label="Height", center=True, xform=True,
         params=[("Bars", .5), ("Glow", .5), ("Width", .5)],
         options=[("Style", ["Spectrum bars", "Mirrored bars", "Circle", "Waveform", "Pulse rings"], 0),
                  ("Position", ["Bottom", "Middle", "Top"], 0),
                  ("Colour", PALETTES, 5),
                  ("Colour motion", COLOUR_MOTION, 2)],
         code="""
void main(){
  vec3 base = tx(v_uv).rgb;
  float asp = u_res.x/u_res.y;
  float H = u_amt*.6;
  float px = 1./u_res.y;
  float shape = 0., glow = 0.;
  float hue = v_uv.x;
  float baseY = u_opt1 == 0 ? .97 : (u_opt1 == 1 ? .5 : .03);
  float nb = floor(mix(12., 96., u_p0));
  float span = mix(.4, 1., u_p2);
  if (u_opt0 <= 1) {   // bars, from one edge (or mirrored out from the middle, both ways)
    float x = (v_uv.x - .5)/span + .5;
    if (u_opt0 == 1) x = abs(v_uv.x - .5)/span*2.;
    if (x >= 0. && x <= 1.) {
      float i = floor(x*nb), f = fract(x*nb);
      float v = spectrum((i + .5)/nb);
      float h = max(v*H, 2.*px);
      float dy = u_opt1 == 1 || u_opt0 == 1 ? abs(v_uv.y - baseY) : (u_opt1 == 0 ? baseY - v_uv.y : v_uv.y - baseY);
      float inBar = step(.12, f)*step(f, .88);
      shape = inBar*step(0., dy)*smoothstep(h + px, h - px, dy);
      glow = inBar*step(0., dy)*exp(-max(dy - h, 0.)*40.)*v;
      hue = x;
    }
  } else if (u_opt0 == 2) {   // circle: spectrum around a ring, mirrored left/right
    vec2 p = (v_uv - u_centre)*vec2(asp, 1.);
    float r = length(p), a = atan(p.x, -p.y);
    float x = abs(a)/3.14159;
    float i = floor(x*nb), f = fract(x*nb);
    float v = spectrum((i + .5)/nb);
    float R = mix(.08, .25, u_p2)*(1. + u_bands.x*.15);
    float dr = r - R;
    shape = step(.15, f)*step(f, .85)*step(0., dr)*smoothstep(v*H*.6 + px, v*H*.6 - px, dr)
          + smoothstep(2.*px, 0., abs(dr))*.8;
    glow = exp(-abs(dr)*30.)*(.3 + u_bands.x);
    hue = x;
  } else if (u_opt0 == 3) {   // waveform line
    float x = (v_uv.x - .5)/span + .5;
    if (x >= 0. && x <= 1.) {
      float y = (u_opt1 == 1 ? .5 : (u_opt1 == 0 ? .85 : .15)) + waveform(x)*H*.8;
      float d = abs(v_uv.y - y);
      float w = mix(1.5, 4., u_p1)*px;
      shape = smoothstep(w + px, w - px, d);
      glow = exp(-d*90.)*.8;
    }
  } else {   // rings sent out from the centre on every beat
    vec2 p = (v_uv - u_centre)*vec2(asp, 1.);
    float r = length(p);
    for (int k = 0; k < 6; k++){
      float age = u_since + float(k)*u_beatlen;
      float rr = age*mix(.3, .9, u_amt);
      float fade = exp(-age*1.2);
      shape += smoothstep(3.*px, 0., abs(r - rr))*fade;
      glow += exp(-abs(r - rr)*40.)*fade*.5;
    }
    float core = mix(.03, .1, u_p2)*(1. + u_bands.x*.8);
    shape += smoothstep(core + px, core - px, r)*.9;
    hue = r;
  }
  vec3 col = palCycle(u_opt2, hue*.9 + palPhase(u_opt3, v_uv), base);
  o = vec4(base*(1. - shape*.85) + col*(shape*1.2 + glow*u_p1*1.5), 1.); }"""),

    # ---- Stylize
    dict(id="ascii", name="ASCII / Matrix", amt=.35, amt_label="Character size", speed=True, center=True,
         params=[("Contrast", .5), ("Picture shows", .5)],
         options=[("Style", ["ASCII", "Matrix rain", "Binary"], 0),
                  ("Colour", PALETTES, 13),
                  ("Colour motion", COLOUR_MOTION, 0),
                  ("Background", ["Black", "Dim video"], 0)],
         code=GLYPHS + """
void main(){
  float cs = floor(mix(6., 30., clamp(u_amt, 0., 1.)));
  vec2 px = (v_uv - u_centre)*u_res;   // characters are laid out from the centre
  vec2 cell = floor(px/cs), f = fract(px/cs);
  vec2 cuv = (cell + .5)*cs/u_res + u_centre;
  vec3 src = tx(cuv).rgb;
  float l = clamp((lum(src) - .5)*mix(.8, 2.4, u_p0) + .5, 0., 1.);
  vec3 ink = palCycle(u_opt1, palPhase(u_opt2, cuv), src*1.3);
  vec3 col;
  if (u_opt0 == 0) {
    col = ink*glyph(RAMP[int(min(l*10., 9.))], f)*(u_opt1 == 4 ? 1. : .55 + .45*l);
  } else if (u_opt0 == 1) {   // streams of changing digits falling down each column
    float colx = cell.x;
    float speed = mix(5., 16., hash(vec2(colx, 3.1)));
    float len = mix(8., 28., hash(vec2(colx, 5.3)));
    float dy = mod(u_time*speed + hash(vec2(colx, 7.7))*90. - cell.y, len + mix(6., 40., hash(vec2(colx, 9.9))));
    float trail = dy < len ? pow(1. - dy/len, 1.5) : 0.;
    float head = step(dy, 1.);
    float tch = floor(u_time*mix(2., 10., hash(cell)) + hash(cell.yx)*9.);
    float g = glyph(DIGIT[int(hash(cell + tch*.37)*9.99)], vec2(1. - f.x, f.y));   // mirrored, as in the film
    float lit = trail*mix(1., .25 + 1.5*l, u_p1) + l*u_p1*.18;
    col = mix(ink, vec3(.85, 1., .9), head*.75)*g*clamp(lit + head, 0., 1.6);
  } else {   // binary: 0s and 1s, brighter where the picture is
    float b = hash(cell + floor(u_time*mix(1., 6., hash(cell.yx))));
    col = ink*glyph(DIGIT[b > .5 ? 1 : 0], f)*smoothstep(.08, .5, l)*(.3 + .9*l);
  }
  vec3 bg = u_opt3 == 1 ? tx(v_uv).rgb*.18 : vec3(0.);
  o = vec4(bg + col, 1.); }"""),

    dict(id="halftone", name="Halftone / Comic", amt=.35, amt_label="Dot size", center=True,
         params=[("Angle", 15., 0., 90., "%.0f deg"), ("Ink lines", .5)],
         options=[("Style", ["CMYK print", "Dots", "Comic", "Engraving lines"], 0),
                  ("Paper", ["White", "Black", "Video"], 0),
                  ("Ink colour", ["Auto"] + PALETTES, 0)],
         code="""
float cs(){ return mix(4., 26., clamp(u_amt, 0., 1.)); }
// one screen of dots at an angle; cov picks the channel from the colour at each dot's centre
float dots(vec2 px, float ang, int ch){
  vec2 rp = rot(ang)*px;
  float s = cs();
  vec2 cell = (floor(rp/s) + .5)*s;
  vec3 c = tx(rot(-ang)*cell/u_res + u_centre).rgb;
  float k = 1. - max(c.r, max(c.g, c.b));
  float v = ch == 0 ? (1. - c.r - k)/max(1. - k, 1e-3) : ch == 1 ? (1. - c.g - k)/max(1. - k, 1e-3)
          : ch == 2 ? (1. - c.b - k)/max(1. - k, 1e-3) : ch == 3 ? k : 1. - lum(c);
  if (ch == 5) v = c.r; if (ch == 6) v = c.g; if (ch == 7) v = c.b;   // additive screens for black paper
  float r = sqrt(clamp(v, 0., 1.))*s*.66;
  return smoothstep(r + .7, r - .7, length(rp - cell));
}
float inkEdge(vec2 uv){
  vec2 e = 1.5/u_res;
  float gx = lum(tx(uv + vec2(e.x, 0.)).rgb) - lum(tx(uv - vec2(e.x, 0.)).rgb);
  float gy = lum(tx(uv + vec2(0., e.y)).rgb) - lum(tx(uv - vec2(0., e.y)).rgb);
  return smoothstep(mix(.4, .08, u_p1), mix(.5, .15, u_p1), length(vec2(gx, gy)));
}
void main(){
  vec2 px = (v_uv - u_centre)*u_res;   // dots are laid out from the centre
  float a = radians(u_p0);
  vec3 src = tx(v_uv).rgb;
  bool dark = u_opt1 == 1;
  vec3 paper = dark ? vec3(.02) : (u_opt1 == 2 ? src : vec3(.97, .96, .93));
  vec3 ink = u_opt2 == 0 ? (dark ? vec3(1.) : vec3(.05)) : palCycle(u_opt2 - 1, 0., src);
  vec3 col;
  if (u_opt0 == 0) {
    if (dark) col = vec3(dots(px, a, 5), dots(px, a + .5236, 6), dots(px, a + 1.0472, 7));
    else {
      col = paper;
      col *= 1. - vec3(.95, 0., 0.)*dots(px, a + .2618, 0);
      col *= 1. - vec3(0., .95, 0.)*dots(px, a + 1.309, 1);
      col *= 1. - vec3(0., 0., .95)*dots(px, a, 2);
      col *= 1. - .9*dots(px, a + .7854, 3);
    }
  } else if (u_opt0 == 1) {
    col = mix(paper, ink, dots(px, a + .7854, 4));
  } else if (u_opt0 == 2) {   // comic: flat boosted colours, dots in the shadows, black ink outlines
    vec3 c = floor(src*4. + .5)/4.;
    c = mix(vec3(lum(c)), c, 1.5);
    float shade = dots(px, a + .7854, 4)*smoothstep(.55, .25, lum(src));
    col = c*(1. - shade*.7);
    col = mix(col, dark ? vec3(1.) : vec3(0.), inkEdge(v_uv));
  } else {   // engraving: parallel lines, thicker where it's darker
    vec2 rp = rot(a)*px;
    float s = cs()*.6;
    float t = abs(fract(rp.y/s) - .5)*2.;
    float d = 1. - lum(src);
    col = mix(paper, ink, smoothstep(d + .08, d - .08, 1. - t));
  }
  o = vec4(col, 1.); }"""),

    dict(id="linedraw", name="Line Drawing", amt=1., state=[LINE_BLUR_H, LINE_BLUR_V],
         params=[("Line weight", .35), ("Detail", .5), ("Shading", .5), ("Paper grain", .4)],
         options=[("Style", ["Pencil", "Ink", "Blueprint", "Chalkboard", "Coloured pencil"], 0),
                  ("Line colour", ["Style default"] + PALETTES, 0),
                  ("Colour motion", COLOUR_MOTION, 0),
                  ("Background", ["Paper", "Over video"], 0)],
         code="""
float vn(vec2 p){ vec2 i = floor(p), f = fract(p); f = f*f*(3. - 2.*f);
  return mix(mix(hash(i), hash(i + vec2(1,0)), f.x), mix(hash(i + vec2(0,1)), hash(i + vec2(1,1)), f.x), f.y); }
void main(){
  vec2 g = texture(u_s1, v_uv).rg;   // r = fine blur, g = wide blur of brightness
  vec3 src = tx(v_uv).rgb;
  vec2 px = v_uv*u_res;
  // lines: where it's darker than its surroundings (difference of Gaussians), cleaned by a soft threshold
  float dog = g.g - g.r;
  float thr = mix(.02, .002, u_p1);
  float line = smoothstep(thr, thr*2.5, dog);
  // pencil wobble: the line strength breaks up along its length
  float grain = vn(px*.35)*.6 + vn(px*1.3)*.4;
  int st = u_opt0;
  if (st == 0 || st == 4) line *= mix(1., .55 + .7*grain, u_p3);
  if (st == 3) line *= smoothstep(.25, .6, grain + .25);   // chalk skips
  // shading: cross-hatching in the darker areas
  float dark = 1. - g.r;
  vec2 r1 = rot(.785)*px, r2 = rot(-.785)*px;
  float sp = mix(5., 3., u_p0);
  float h1 = smoothstep(.55, .9, 1. - abs(fract(r1.x/sp) - .5)*2.)*smoothstep(.35, .55, dark);
  float h2 = smoothstep(.55, .9, 1. - abs(fract(r2.x/sp) - .5)*2.)*smoothstep(.6, .8, dark);
  float hatch = max(h1, h2)*u_p2*(st == 1 ? .0 : .7)*(.6 + .4*grain);
  float ink = clamp(max(line, hatch), 0., 1.);
  // paper and ink per style
  vec3 paper, lc;
  if (st == 2) { paper = vec3(.06, .22, .52); lc = vec3(.92, .97, 1.);
    vec2 gr = abs(fract(px/24.) - .5); paper += .05*smoothstep(.47, .5, max(gr.x, gr.y)); }
  else if (st == 3) { paper = vec3(.08, .13, .1); lc = vec3(.95, .97, .92); }
  else if (st == 4) { paper = vec3(.97, .95, .91)*mix(vec3(1.), src*1.2 + .15, .35); lc = src*.55; }
  else { paper = vec3(.97, .95, .91); lc = st == 1 ? vec3(.02) : vec3(.18, .18, .2); }
  paper *= 1. - u_p3*.08*vn(px*.9);   // paper texture
  if (u_opt1 > 0) lc = palCycle(u_opt1 - 1, palPhase(u_opt2, v_uv), src);
  if (u_opt3 == 1) paper = src;
  vec3 col = mix(paper, lc, ink);
  o = vec4(mix(src, col, clamp(u_amt, 0., 1.)), 1.); }"""),

    # ---- Mirror & geometry
    dict(id="tunnel", name="Warp Tunnel", amt=.6, center=True, speed=True,
         params=[("Repeats", 2., 1., 6., "%.0f"), ("Twist", 0., -1., 1.)],
         options=[("Style", ["Tunnel", "Warp speed", "Hyperspace"], 0)],
         code="""
void main(){
  float asp = u_res.x/u_res.y;
  vec2 p = (v_uv - u_centre)*vec2(asp, 1.);
  float r = length(p), a = atan(p.y, p.x);
  if (u_opt0 == 0) {   // the picture wrapped round the inside of a tube rushing towards you
    float reps = floor(u_p0 + .5);
    vec2 t = vec2(a/6.2831853*reps + u_p1*.4/max(r, .02), .25/max(r, .002) + u_time*.4);
    vec3 c = tx(t).rgb;
    float fog = mix(1., smoothstep(0., .35, r), clamp(u_amt, 0., 1.));
    o = vec4(c*fog, 1.); return;
  }
  // warp speed: zoom blur out from the centre with the colours splitting; hyperspace adds star streaks
  vec3 acc = vec3(0.);
  float k = clamp(u_amt, 0., 1.6)*.25;
  for (int i = 0; i < 16; i++){
    float s = 1. - float(i)/16.*k;
    vec2 q = u_centre + (v_uv - u_centre)*s;
    acc += vec3(tx(u_centre + (q - u_centre)*(1. - .02*k)).r, tx(q).g, tx(u_centre + (q - u_centre)*(1. + .02*k)).b);
  }
  vec3 c = acc/16.;
  if (u_opt0 == 2) {
    c *= .45;
    float lane = floor(a*120./6.2831853);
    float h = hash(vec2(lane, 1.7));
    if (h > .6) {
      float dash = fract(log(r + .001)*1.6 - u_time*(1.2 + h*2.) + h*9.);
      float streak = smoothstep(0., .05, dash)*smoothstep(.45, .05, dash)*smoothstep(.04, .2, r);
      float w = smoothstep(.5, 0., abs(fract(a*120./6.2831853) - .5)*2.);
      c += vec3(.75, .88, 1.)*streak*w*1.6;
    }
  }
  o = vec4(c, 1.); }"""),

    # ---- Cutout
    dict(id="silfill", name="Silhouette Fill", amt=1., amt_label="Fill", mask=True, speed=True,
         params=[("Edge glow", .5), ("Pattern scale", .5)],
         options=[("Fill with", ["Gradient", "Plasma", "Stripes", "Starfield", "Source 2", "Source 3", "Source 4"], 1),
                  ("Fill", ["Subject", "Background"], 0),
                  ("Colour", PALETTES, 5),
                  ("Colour motion", COLOUR_MOTION, 1)],
         code="""
vec3 fillCol(vec2 uv, vec3 src){
  float asp = u_res.x/u_res.y;
  vec2 p = (uv - .5)*vec2(asp, 1.)*mix(.5, 3., u_p1);
  float ph = palPhase(u_opt3, uv);
  int f = u_opt0;
  if (f == 0) return palCycle(u_opt2, uv.y*.8 + ph, src);
  if (f == 1) {
    float v = sin(p.x*4. + u_time) + sin(p.y*5. - u_time*1.3) + sin((p.x + p.y)*3. + u_time*.7)
            + sin(length(p)*6. - u_time*1.6);
    return palCycle(u_opt2, v*.15 + ph, src);
  }
  if (f == 2) {
    float s = fract((p.x + p.y)*3. - u_time*.3);
    return palCycle(u_opt2, floor(s*3.)/3. + ph, src)*(.8 + .2*smoothstep(.0, .05, abs(fract(s*3.) - .5)));
  }
  if (f == 3) {   // stars drifting on deep space
    vec3 c = palMap(u_opt2, .12 + .1*sin(p.y + u_time*.2), src)*.6;
    for (int L = 0; L < 3; L++){
      float sc = 20. + float(L)*25.;
      vec2 q = p*sc + vec2(u_time*(1. + float(L)), 0.);
      vec2 id = floor(q), fq = fract(q) - .5;
      float h = hash(id + float(L)*7.);
      if (h > .9) c += vec3(1.)*smoothstep(.12, 0., length(fq - (vec2(hash(id + 1.), hash(id + 2.)) - .5)*.6))
                       *(.5 + .5*sin(u_time*3. + h*40.));
    }
    return c;
  }
  int s = f - 4;
  float live = s == 0 ? u_mlive.x : (s == 1 ? u_mlive.y : u_mlive.z);
  float sa = s == 0 ? u_masp.x : (s == 1 ? u_masp.y : u_masp.z);
  vec2 q = uv;
  if (sa > asp) q.x = (q.x - .5)*asp/sa + .5; else q.y = (q.y - .5)*sa/asp + .5;
  return media(s, q)*live;
}
void main(){
  vec3 src = tx(v_uv).rgb;
  float m = smoothstep(.35, .65, maskAt(v_uv));
  float region = u_opt1 == 0 ? m : 1. - m;
  vec3 col = mix(src, fillCol(v_uv, src), region*clamp(u_amt, 0., 1.));
  // glow along the outline
  float glow = 0.;
  for (int i = 0; i < 8; i++){
    vec2 o2 = vec2(cos(float(i)*.785), sin(float(i)*.785))*mix(3., 14., u_p0)/u_res;
    glow += abs(maskAt(v_uv + o2) - maskAt(v_uv - o2));
  }
  glow = clamp(glow/4., 0., 1.)*u_p0;
  col += palCycle(u_opt2, palPhase(u_opt3, v_uv) + .3, src)*glow;
  o = vec4(col, 1.); }"""),

    # ---- Colour
    # Colour Adjust: the everyday corrections. Each slider sits at "no change" in the middle (0).
    dict(id="adjust", name="Colour Adjust", amt=1., amt_label="Strength",
         params=[("Brightness", 0., -1., 1.), ("Contrast", 0., -1., 1.), ("Saturation", 0., -1., 1.),
                 ("Hue", 0., -180., 180., "%.0f deg"), ("Warmth", 0., -1., 1.), ("Shadows", 0., -1., 1.)],
         options=[("Highlights", ["Normal", "Soft roll-off"], 0)],
         code="""
void main(){
  vec3 src = tx(v_uv).rgb, c = src;
  c *= exp2(u_p0*1.5);                                            // brightness, like exposure
  float l = lum(c);
  c += (1. - smoothstep(0., .5, l))*u_p5*.25;                      // shadows: lift or crush the darks only
  c = (c - .5)*(u_p1 >= 0. ? 1. + u_p1*1.5 : 1. + u_p1*.85) + .5;  // contrast around mid grey
  c = hueRot(c, radians(u_p3));
  c *= vec3(1. + .22*u_p4, 1. + .04*u_p4, 1. - .22*u_p4);          // warmth: orange <-> blue
  l = lum(c);
  c = mix(vec3(l), c, 1. + u_p2*(u_p2 > 0. ? 1.2 : 1.));           // saturation (-1 = black & white)
  if (u_opt0 == 1) c = mix(c, .7 + .3*(1. - exp(-(c - .7)/.3)), step(.7, c));   // ease bright parts in, not clip
  o = vec4(mix(src, clamp(c, 0., 1.), clamp(u_amt, 0., 1.)), 1.); }"""),

    # Film Looks: one-click styles, plus film grain, vignette and faded blacks to finish them.
    dict(id="looks", name="Film Looks", amt=1., amt_label="Strength",
         params=[("Grain", .15), ("Vignette", .3), ("Fade", 0.)],
         options=[("Look", FILM_LOOKS, 0)],
         code=FILM_LOOK_CODE),

    dict(id="duotone", name="Duotone / Gradient Map", amt=1., speed=True,
         params=[("Contrast", .5)],
         options=[("Colours", PALETTES, 5),
                  ("Mode", ["Gradient map", "Two colours"], 0),
                  ("Colour motion", COLOUR_MOTION, 0)],
         code="""
void main(){
  vec3 src = tx(v_uv).rgb;
  float t = clamp((lum(src) - .5)*mix(.6, 2.2, u_p0) + .5, 0., 1.);
  float ph = palPhase(u_opt2, v_uv);
  vec3 c;
  if (u_opt1 == 0) {
    if (u_opt2 != 0) t = 1. - abs(fract(t*.5 + ph*.5)*2. - 1.);
    c = palMap(u_opt0, t, src);
  } else {
    vec3 A = palCycle(u_opt0, ph, src), B = palCycle(u_opt0, ph + .5, src);
    c = mix(A*.22, mix(B, vec3(1.), .2), smoothstep(0., 1., t));
  }
  o = vec4(mix(src, c, clamp(u_amt, 0., 1.)), 1.); }"""),

    # ---- Feedback / time
    dict(id="slitscan", name="Slit-scan / Time Warp", amt=1., amt_label="Delay", speed=True,
         state=[SLIT_ATLAS], state_size=[(2, "f1")],
         params=[("Time span", .4, 0., 1.)],
         options=[("Direction", ["Top newest", "Bottom newest", "Left newest", "Right newest",
                                 "Centre newest", "Edges newest", "Bright areas older"], 0)],
         code="""
vec3 frameAt(float idx, vec2 uv){
  idx = mod(idx, 16.);
  vec2 tile = vec2(mod(idx, 4.), floor(idx/4.));
  vec4 c = texture(u_s0, (tile + clamp(uv, 2./u_res, 1. - 2./u_res))/4.);
  return c.a < .5 ? tx(uv).rgb : c.rgb;   // tiles not filled yet: the live picture
}
void main(){
  float every = mix(.25, 4., u_p0)/16.;
  float wi = mod(floor(u_time/every), 16.);
  float asp = u_res.x/u_res.y;
  int m = u_opt0;
  float d = m == 0 ? v_uv.y : m == 1 ? 1. - v_uv.y : m == 2 ? v_uv.x : m == 3 ? 1. - v_uv.x
          : m == 4 ? length((v_uv - .5)*vec2(asp, 1.))*1.3 : m == 5 ? 1. - length((v_uv - .5)*vec2(asp, 1.))*1.3
          : lum(tx(v_uv).rgb);
  float back = clamp(d, 0., 1.)*15.*clamp(u_amt, 0., 1.);
  float pos = wi - back;
  float i0 = floor(pos);
  vec3 c = mix(frameAt(i0, v_uv), frameAt(i0 + 1., v_uv), pos - i0);
  if (back < 1.) c = mix(tx(v_uv).rgb, c, back);   // the newest edge is the live picture
  o = vec4(c, 1.); }"""),

    dict(id="datamosh", name="Datamosh", amt=1., state=[MOSH, "void main(){ o = vec4(tx(v_uv).rgb, 1.); }"],
         speed=True,
         params=[("Smear", .5), ("Keyframe every", .4), ("Bleed through", .2)],
         options=[("Refresh", ["Every few seconds", "On the beat", "Never (melt)"], 0)],
         code="void main(){ o = vec4(mix(tx(v_uv).rgb, texture(u_s0, v_uv).rgb, clamp(u_amt, 0., 1.)), 1.); }"),
]

# ---- Interactive effects: they react to you. "Movement" is measured per pixel from the AI person mask
# (Source: Person) or from the picture's own brightness changing (Source: Any movement), against last frame's
# values that each effect keeps in its memory buffer.
MOTION_GLSL = """
vec2 motionNow(vec2 uv){ return vec2(maskAt(uv), lum(clean(uv).rgb)); }
float motionAt(vec2 uv, vec2 prev, int source){
  vec2 now = motionNow(uv);
  float picture = smoothstep(.03, .14, abs(now.y - prev.y));   // the picture itself changed here
  if (source != 0) return picture;
  // Person: the outline moving, or something moving in front of you (a hand across your body changes the
  // picture there but not the mask), but never the background
  return max(smoothstep(.04, .35, abs(now.x - prev.x)), picture*smoothstep(.4, .8, min(now.x, prev.x)));
}
vec2 outward(vec2 uv){   // away from the person, from the mask's slope (0 away from any edge)
  vec2 e = 14./u_res;
  vec2 g = vec2(maskAt(uv + vec2(e.x, 0.)) - maskAt(uv - vec2(e.x, 0.)), maskAt(uv + vec2(0., e.y)) - maskAt(uv - vec2(0., e.y)));
  float l = length(g);
  return l > .02 ? -g/l : vec2(0.);
}
float fnoise(vec2 p){ vec2 i = floor(p), f = fract(p); f = f*f*(3. - 2.*f);
  return mix(mix(hash(i), hash(i + vec2(1,0)), f.x), mix(hash(i + vec2(0,1)), hash(i + vec2(1,1)), f.x), f.y); }
vec2 curl(vec2 p){ float k = .05, n = fnoise(p); return vec2(fnoise(p + vec2(0., k)) - n, -(fnoise(p + vec2(k, 0.)) - n))/k; }
"""

# Smoke and Flames: a small fluid. State 0 = what's carried (smoke colour + density, or heat in .a); state 1 =
# the air's velocity (xy) and last frame's mask and brightness (zw). Movement pours smoke/heat in and kicks the
# air; it rises, swirls (curl noise) and fades. u_p0 Rise, u_p1 Swirl, u_p2 Linger; u_opt0 Source.
def _fluid(fire):
    head = MOTION_GLSL + ("#define FIRE 1\n" if fire else "#define FIRE 0\n")
    carried = head + """
void main(){
  float asp = u_res.x/u_res.y, dt = min(u_dt, .05)*abs(u_speed);
  vec2 toUv = vec2(1./asp, 1.);
  vec4 air = texture(u_s1, v_uv);
  vec4 d = texture(u_s0, v_uv - air.xy*toUv*dt);                    // carried along by the air
  d *= exp(-dt*mix(FIRE == 1 ? 4. : 2.5, FIRE == 1 ? .6 : .12, u_p2));   // Linger
  // movement here, or a little way round (a wider brush)
  float mot = motionAt(v_uv, air.zw, u_opt0);
  vec2 e = 6./u_res;
  mot = max(mot, .6*max(max(motionAt(v_uv + vec2(e.x, 0.), texture(u_s1, v_uv + vec2(e.x, 0.)).zw, u_opt0),
                             motionAt(v_uv - vec2(e.x, 0.), texture(u_s1, v_uv - vec2(e.x, 0.)).zw, u_opt0)),
                         max(motionAt(v_uv + vec2(0., e.y), texture(u_s1, v_uv + vec2(0., e.y)).zw, u_opt0),
                             motionAt(v_uv - vec2(0., e.y), texture(u_s1, v_uv - vec2(0., e.y)).zw, u_opt0))));
  float add = mot*dt*14.*clamp(u_amt, 0., 1.5);
#if FIRE
  d.a += add*1.6;
#else
  vec3 col = palCycle(u_opt1, palPhase(u_opt2, v_uv) + u_time*.04, clean(v_uv).rgb);
  d.rgb += col*add;
  d.a += add;
#endif
  o = min(d, vec4(4.)); }"""
    air = head + """
void main(){
  float asp = u_res.x/u_res.y, dt = min(u_dt, .05)*abs(u_speed);
  vec2 toUv = vec2(1./asp, 1.);
  vec4 old = texture(u_s1, v_uv);
  vec2 vel = texture(u_s1, v_uv - old.xy*toUv*dt).xy*exp(-dt*.7);
  float dens = texture(u_s0, v_uv).a;                                   // this frame's smoke / heat
  vel.y -= min(dens, 2.)*dt*mix(.05, 1.3, u_p0)*(FIRE == 1 ? 2.2 : 1.);   // Rise (y grows downward)
  float mot = motionAt(v_uv, old.zw, u_opt0);
  vel += outward(v_uv)*mot*.35;                                         // a move shoves the air aside
  vec2 q = v_uv*vec2(asp, 1.)*(FIRE == 1 ? 7. : 3.5) + vec2(0., u_time*(FIRE == 1 ? 1.2 : .25));
  vel += curl(q)*dt*mix(.05, 1.6, u_p1)*(.25 + min(dens, 1.5));         // Swirl
  float L = length(vel);
  if (L > .9) vel *= .9/L;
  o = vec4(vel, motionNow(v_uv)); }"""
    if fire:
        main = MOTION_GLSL + """
void main(){
  vec3 base = tx(v_uv).rgb;
  float heat = texture(u_s0, v_uv).a;
  // tongues: noise streaming upward breaks the heat into flickering flames (Flicker = u_p1)
  float asp = u_res.x/u_res.y;
  vec2 q = v_uv*vec2(asp, 1.)*vec2(9., 4.) + vec2(0., u_time*mix(1., 4., u_p1));
  heat *= mix(1., .35 + 1.1*fnoise(q)*fnoise(q*2.1 + 3.7), clamp(heat*1.5, 0., 1.));
  vec3 c = palMap(u_opt1, clamp(heat*.55, 0., 1.), base)*smoothstep(.02, .35, heat);
  c *= u_opt3 == 1 ? .7 : 1.25;                                        // Look: Bright / Soft
  float vis = u_opt4 == 1 ? 1. - smoothstep(.3, .7, maskAt(v_uv)) : 1.;
  o = vec4(base + c*vis, 1.); }"""
    else:
        main = """
void main(){
  vec3 base = tx(v_uv).rgb;
  vec4 d = texture(u_s0, v_uv);
  vec3 col = d.rgb/max(d.a, 1e-3);
  float cover = 1. - exp(-d.a*1.4);
  float vis = u_opt4 == 1 ? 1. - smoothstep(.3, .7, maskAt(v_uv)) : 1.;
  vec3 c = u_opt3 == 0 ? base + col*cover*1.3                          // Look: Glowing (light)
                       : mix(base, col*.85 + .08, cover*.9);           // or Smoke (opaque)
  o = vec4(mix(base, c, vis), 1.); }"""
    return carried, air, main


_SMOKE, _FIRE = _fluid(False), _fluid(True)
SOURCES = ["Person (AI)", "Any movement"]
INTERACTIVE_EFFECTS = [
    dict(id="smoke", name="Smoke", amt=.7, speed=True, state=[_SMOKE[0], _SMOKE[1]],
         mask_when=[(0, (0,)), (4, (1,))],
         params=[("Rise", .35), ("Swirl", .55), ("Linger", .55)],
         options=[("Source", SOURCES, 0), ("Colour", PALETTES, 0), ("Colour motion", COLOUR_MOTION, 1),
                  ("Look", ["Glowing", "Smoke"], 0), ("Show", ["In front", "Behind you"], 0)],
         code=_SMOKE[2]),
    dict(id="flames", name="Flames", amt=.7, speed=True, state=[_FIRE[0], _FIRE[1]],
         mask_when=[(0, (0,)), (4, (1,))],
         params=[("Rise", .6), ("Flicker", .6), ("Height", .45)],
         options=[("Source", SOURCES, 0), ("Colour", PALETTES, 7), ("Colour motion", COLOUR_MOTION, 0),
                  ("Look", ["Bright", "Soft"], 0), ("Show", ["In front", "Behind you"], 0)],
         code=_FIRE[2]),
]

# Water ripples: the classic two-height wave equation. State: r = height now, g = height a frame ago,
# ba = last mask and brightness. Movement pushes the surface; Drops adds rain or a drop on every beat.
# u_p0 Calm (how long ripples last), u_p1 Refraction, u_p2 Rain; u_opt0 Source, u_opt1 Look, u_opt3 Drops.
RIPPLE_SIM = MOTION_GLSL + """
float drop(vec2 at, float r){ return smoothstep(r, 0., length((v_uv - at)*vec2(u_res.x/u_res.y, 1.))); }
void main(){
  vec4 c = texture(u_s0, v_uv);
  vec2 e = 2./u_res;
  float sum = texture(u_s0, v_uv + vec2(e.x, 0.)).r + texture(u_s0, v_uv - vec2(e.x, 0.)).r
            + texture(u_s0, v_uv + vec2(0., e.y)).r + texture(u_s0, v_uv - vec2(0., e.y)).r;
  float h = (sum*.5 - c.g)*mix(.95, .996, u_p0);
  h += motionAt(v_uv, c.ba, u_opt0)*.18*clamp(u_amt, 0., 2.);
  float rate = 1. + u_p2*14.;   // rain: drops per second at random spots
  if (u_opt3 == 1 && floor(u_time*rate) != floor((u_time - u_dt)*rate)) {
    float id = floor(u_time*rate);
    h -= drop(vec2(hash(vec2(id, 1.3)), hash(vec2(id, 7.1))), .012 + .02*hash(vec2(id, 3.))) * 1.5;
  }
  if (u_opt3 == 2 && u_since < u_dt*1.01)   // a big drop on every beat
    h -= drop(vec2(hash(vec2(u_beats, 2.1)), hash(vec2(u_beats, 5.3))), .05) * 2.5;
  o = vec4(clamp(h, -3., 3.), c.r, motionNow(v_uv)); }"""
RIPPLE_MAIN = """
float H(vec2 uv){ return texture(u_s0, uv).r; }
void main(){
  vec2 e = 2./u_res;
  vec2 g = vec2(H(v_uv + vec2(e.x, 0.)) - H(v_uv - vec2(e.x, 0.)), H(v_uv + vec2(0., e.y)) - H(v_uv - vec2(0., e.y)));
  vec3 col = tx(v_uv + g*mix(.004, .04, u_p1)).rgb;                   // the picture seen through the water
  float slope = length(g);
  float spec = pow(clamp(dot(g, normalize(vec2(-.6, -.8)))*4., 0., 1.), 2.)*.35;   // light catching the crests
  if (u_opt1 == 1) col = mix(col, col*palCycle(u_opt2, palPhase(u_opt4, v_uv) + slope*2., col)*1.4,
                             clamp(slope*6., 0., .7));                  // Tinted: colour in the waves
  if (u_opt1 == 2) {                                                    // Night pool: blue, with caustics
    col = col*vec3(.45, .7, 1.) + vec3(0., .05, .12);
    col += vec3(.4, .8, 1.)*pow(clamp(slope*7., 0., 1.), 1.5)*.6;
  }
  o = vec4(col + vec3(spec), 1.); }"""

# Light painting: movement (or bright lights, like a phone torch) leaves glowing strokes that fade slowly; the
# colour moves through the palette over time, so a stroke turns into a gradient. State: rgb = paint, a = last
# mask or brightness. u_p0 Trail length, u_p1 Sensitivity, u_p2 Glow; u_opt0 Source.
PAINT_SIM = MOTION_GLSL + """
void main(){
  vec4 c = texture(u_s0, v_uv);
  float dt = min(u_dt, .05)*abs(u_speed);
  vec3 paint = c.rgb*exp(-dt*mix(3., .06, u_p0));
  float l = lum(clean(v_uv).rgb), now = u_opt0 == 0 ? maskAt(v_uv) : l;
  float stroke;
  if (u_opt0 == 2) stroke = smoothstep(mix(.97, .65, u_p1), 1., l);   // bright lights draw
  else {
    float k = mix(.35, .06, u_p1);
    stroke = smoothstep(k*.3, k, abs(now - c.a));
    if (u_opt0 == 0) {   // the person: only their moving outline draws, so strokes are lines, not smears
      vec2 ee = 3./u_res;
      float gm = length(vec2(maskAt(v_uv + vec2(ee.x, 0.)) - maskAt(v_uv - vec2(ee.x, 0.)),
                             maskAt(v_uv + vec2(0., ee.y)) - maskAt(v_uv - vec2(0., ee.y))));
      stroke *= smoothstep(.15, .45, gm);
    }
    vec2 e = 4./u_res;   // a slightly wider brush
    for (int i = 0; i < 4; i++){
      vec2 o2 = vec2(i == 0 ? e.x : i == 1 ? -e.x : 0., i == 2 ? e.y : i == 3 ? -e.y : 0.);
      vec4 n = texture(u_s0, v_uv + o2);
      float nn = u_opt0 == 0 ? maskAt(v_uv + o2) : lum(clean(v_uv + o2).rgb);
      stroke = max(stroke, (u_opt0 == 0 ? .5 : .7)*smoothstep(k*.3, k, abs(nn - n.a))*(u_opt0 == 0 ? smoothstep(.3, .6, stroke + .3) : 1.));
    }
  }
  vec3 col = palCycle(u_opt1, palPhase(u_opt2, v_uv) + u_time*.15, clean(v_uv).rgb);
  paint = max(paint, col*stroke*.85*clamp(u_amt, 0., 1.5));
  o = vec4(paint, now); }"""
PAINT_MAIN = """
void main(){
  vec3 base = tx(v_uv).rgb;
  vec3 paint = texture(u_s0, v_uv).rgb, glow = vec3(0.);
  float r = 4. + 14.*u_p2;
  for (int i = 0; i < 8; i++){
    float a = float(i)*.785;
    glow += texture(u_s0, v_uv + vec2(cos(a), sin(a))*r/u_res).rgb + texture(u_s0, v_uv + vec2(cos(a), sin(a))*r*.5/u_res).rgb;
  }
  float vis = u_opt3 == 1 ? 1. - smoothstep(.3, .7, maskAt(v_uv)) : 1.;
  o = vec4(base + (paint*1.2 + glow/16.*u_p2*1.5)*vis, 1.); }"""

INTERACTIVE_EFFECTS += [
    dict(id="ripples", name="Water Ripples", amt=.6, amt_label="Splash", state=[RIPPLE_SIM],
         mask_when=(0, (0,)),
         params=[("Calm", .55), ("Refraction", .5), ("Rain", .3)],
         options=[("Source", SOURCES, 0), ("Look", ["Clear water", "Tinted", "Night pool"], 0),
                  ("Colour", PALETTES, 11), ("Drops", ["None", "Rain", "On the beat"], 0),
                  ("Colour motion", COLOUR_MOTION, 0)],
         code=RIPPLE_MAIN),
    dict(id="lightpaint", name="Light Painting", amt=.9, amt_label="Brightness", state=[PAINT_SIM],
         mask_when=[(0, (0,)), (3, (1,))],
         params=[("Trail length", .6), ("Sensitivity", .5), ("Glow", .5)],
         options=[("Source", SOURCES + ["Bright lights"], 0), ("Colour", PALETTES, 0),
                  ("Colour motion", COLOUR_MOTION, 1), ("Show", ["In front", "Behind you"], 0)],
         code=PAINT_MAIN),
]

# Snow that settles: falling flakes (drawn) land on the person and the floor and pile up (state, like falling
# sand: a cell of snow stays only while something holds it up: the person, more snow, or the floor; otherwise it
# falls). Move away from under it and it slides off. u_amt Snowfall, u_p0 Flakes, u_p1 Pile height, u_p2 Melt;
# u_opt0 Type (Snow / Ash / Petals), u_opt1 Colour.
SNOW_SIM = """
// r = snow, g = grounded: resting on you or the floor, directly or through the snow below (passed up a cell a
// frame). Snow that isn't grounded falls, so a pile comes down when what held it moves away.
void main(){
  float dt = min(u_dt, .05)*abs(u_speed);
  vec2 dn = vec2(0., 2./u_res.y);                 // a cell is 2 px tall; y grows downward
  vec4 h4 = texture(u_s0, v_uv), b4 = texture(u_s0, v_uv + dn);
  vec4 a4 = texture(u_s0, v_uv - dn);
  float here = h4.r, above = a4.r, below = b4.r;
  float m = maskAt(v_uv);
  bool ground = v_uv.y > 1. - dn.y;
  bool base = maskAt(v_uv + dn) > .5 || ground;
  bool held = base || (below > .5 && b4.g > .5);
  float s;
  if (m > .5) s = a4.g > .5 ? 0. : above;         // nothing rests inside you: falling snow passes, in front
  else if (held) {
    float maxH = mix(6., 60., u_p1)/u_res.y;      // Pile height: how far up from you / the floor it can build
    bool near = maskAt(v_uv + vec2(0., maxH*.33)) > .5 || maskAt(v_uv + vec2(0., maxH*.66)) > .5
             || maskAt(v_uv + vec2(0., maxH)) > .5 || v_uv.y > 1. - maxH*.5;
    float landing = (above < .5 && near) ? dt*mix(.15, 2.5, clamp(u_amt, 0., 1.5))*mix(.3, 1.4, u_p0) : 0.;
    s = min(1., here + landing);
  } else s = above;                               // nothing under it: it falls
  s = max(0., s - dt*u_p2*u_p2*.4);               // Melt
  o = vec4(s, held && m <= .5 && s > .5 ? 1. : 0., 0., 1.); }"""
SNOW_MAIN = """
float flakes(vec2 uv, float t, float layer, float asp){
  float scale = mix(9., 26., layer);
  float fall = (u_opt0 == 1 ? .04 : u_opt0 == 2 ? .06 : .09)*mix(1.4, .7, layer);
  vec2 q = uv*vec2(asp, 1.)*scale;
  q.y -= t*fall*scale;
  q.x += sin(t*.6 + layer*3. + q.y*.35)*(u_opt0 == 0 ? .35 : .8);   // sway (ash and petals drift more)
  vec2 id = floor(q), f = fract(q) - .5;
  float h = hash(id + layer*17.);
  if (h > mix(.15, .8, u_p0)) return 0.;
  f -= (vec2(hash(id + 3.1), hash(id + 7.7)) - .5)*.6;
  float size = mix(.05, .13, hash(id + 5.3))*(u_opt0 == 2 ? 1.8 : 1.);
  if (u_opt0 == 2) f = rot(t*(1. + h*2.) + h*6.) * f * vec2(1., 1.9);   // petals: tumbling ovals
  return smoothstep(size, size*.35, length(f))*mix(.5, 1., layer);
}
void main(){
  vec3 base = tx(v_uv).rgb;
  float asp = u_res.x/u_res.y;
  vec3 snow = u_opt0 == 1 ? vec3(.38, .37, .36) : u_opt0 == 2 ? vec3(1., .62, .74) : vec3(.95, .97, 1.);
  if (u_opt1 > 0) snow = palCycle(u_opt1 - 1, hash(floor(v_uv*u_res/6.))*.3 + u_time*.02, base)*1.1;
  float s = texture(u_s0, v_uv).r;
  float top = s - texture(u_s0, v_uv - vec2(0., 3./u_res.y)).r;   // light on the top of a pile
  vec3 c = mix(base, snow*(.82 + .25*clamp(top*3., 0., 1.)), smoothstep(.3, .6, s));
  // the two farther layers pass behind you (and land on you); the nearest falls in front of you
  float f = (flakes(v_uv, u_time, 0., asp) + flakes(v_uv, u_time, .5, asp))*(1. - smoothstep(.3, .6, maskAt(v_uv)))
          + flakes(v_uv, u_time, 1., asp);
  o = vec4(mix(c, snow, clamp(f, 0., 1.)), 1.); }"""

# Pin Art: a field of pins that shows the picture (bigger, brighter pins where it's bright) and bulges away from
# the person. u_amt Pins (density), u_p0 Push, u_p1 Reach; u_opt0 Style, u_opt1 Colour, u_opt2 Background,
# u_opt3 You (shown normally, or made of pins too).
PIN_MAIN = """
vec2 pushAt(vec2 uv, float asp){
  vec2 acc = vec2(0.);
  float R = mix(.04, .2, u_p1);
  for (int i = 0; i < 12; i++){
    float a = float(i)*.5236;
    vec2 d = vec2(cos(a), sin(a));
    acc += d*(maskAt(uv + d*R*vec2(1./asp, 1.)) + 1.5*maskAt(uv + d*R*.5*vec2(1./asp, 1.)));
  }
  return -acc/30.*mix(0., .9, u_p0)*R;
}
void main(){
  float asp = u_res.x/u_res.y;
  vec2 push = pushAt(v_uv, asp);
  float bulge = length(push)*25.;
  float N = mix(22., 90., clamp(u_amt, 0., 1.));
  vec2 q = (v_uv*vec2(asp, 1.) - push)*N;
  vec2 id = floor(q), f = fract(q) - .5;
  vec3 pic = clean(clamp((id + .5)/N/vec2(asp, 1.), 0., 1.)).rgb;
  float l = lum(pic);
  float pin;
  if (u_opt0 == 1) pin = smoothstep(mix(.08, .35, l), mix(.08, .35, l) - .08, abs(f.y));   // lines
  else if (u_opt0 == 2) pin = max(smoothstep(.08, .02, abs(f.x)), smoothstep(.08, .02, abs(f.y)))*(.4 + .8*l);   // grid
  else { float r = mix(.12, .46, l); pin = smoothstep(r, r - .1, length(f)); }                // dots
  vec3 col = u_opt1 == 0 ? pic*1.25 : palCycle(u_opt1 - 1, l*.6 + u_time*.04, pic)*(.35 + l);
  col *= 1. + bulge*.8;                                         // pushed pins catch more light
  vec3 bg = u_opt2 == 0 ? vec3(.02) : tx(v_uv).rgb*.25;
  vec3 c = mix(bg, col, pin);
  if (u_opt3 == 0) c = mix(c, tx(v_uv).rgb, smoothstep(.4, .7, maskAt(v_uv)));   // you, as you are
  o = vec4(c, 1.); }"""

INTERACTIVE_EFFECTS += [
    dict(id="snowfall", name="Snow That Settles", amt=.6, amt_label="Snowfall", mask=True, speed=True,
         state=[SNOW_SIM],
         params=[("Flakes", .5), ("Pile height", .45), ("Melt", .15)],
         options=[("Type", ["Snow", "Ash", "Petals"], 0), ("Colour", ["Natural"] + PALETTES, 0)],
         code=SNOW_MAIN),
    dict(id="pinart", name="Pin Art", amt=.45, amt_label="Pins", mask_when=(3, (0, 1)),
         params=[("Push", .6), ("Reach", .45)],
         options=[("Style", ["Dots", "Lines", "Grid"], 0), ("Colour", ["Picture"] + PALETTES, 0),
                  ("Background", ["Black", "Dim video"], 0), ("You", ["Shown as you are", "Made of pins too"], 0)],
         code=PIN_MAIN),
]

_CAT.update({"particles": "Overlay", "leaks": "Overlay", "rays": "Overlay", "shapes": "Overlay",
             "visualizer": "Overlay", "ascii": "Stylize", "halftone": "Stylize", "linedraw": "Stylize",
             "tunnel": "Mirror & Geometry", "silfill": "Cutout", "duotone": "Colour", "adjust": "Colour",
             "looks": "Colour",
             "slitscan": "Feedback", "datamosh": "Feedback"})

EFFECTS += NEW_EFFECTS
EFFECTS += INTERACTIVE_EFFECTS
_CAT.update({fx["id"]: "Interactive" for fx in INTERACTIVE_EFFECTS}, particles="Interactive")

# Settings that redraw the whole picture (lines / characters / dots on a plain background), so effects earlier in
# the chain only show through as part of that drawing: effect id -> (option index, those choices, whether it
# only does so at full Amount). The UI warns on the cards it hides.
REDRAWS = {"edges": (1, (1, 2), True), "linedraw": (3, (0,), True), "ascii": (3, (0,), False),
           "halftone": (1, (0, 1), False)}


# ---- More effects (2026-11): glitch art, painterly, lens, and person effects built on the AI mask
MORE_EFFECTS = [
    # Pixel Sort: along each line, runs of qualifying pixels (bright, dark, you, the background or everything)
    # are sorted by brightness / hue / saturation into streaks. Each run is sampled 12 times and those samples
    # are sorted, so any run length works live. Long stretches are cut into blocks staggered per line.
    dict(id="pixelsort", name="Pixel Sort", amt=1., amt_label="Mix",
         params=[("Threshold", .45), ("Streak length", .45), ("Reverse", 0., 0., 1., "%.0f")],
         options=[("Direction", ["Down", "Up", "Right", "Left"], 0),
                  ("Sort by", ["Brightness", "Hue", "Saturation"], 0),
                  ("Sort where", ["Bright areas", "Dark areas", "The person", "The background", "Everywhere"], 0)],
         mask_when=(2, (2, 3)), code="""
float sortKey(vec3 c){
  float mx = max(max(c.r, c.g), c.b), mn = min(min(c.r, c.g), c.b), d = mx - mn + 1e-5;
  if (u_opt1 == 1) return (mx == c.r ? mod((c.g - c.b)/d, 6.) : mx == c.g ? (c.b - c.r)/d + 2. : (c.r - c.g)/d + 4.)/6.;
  if (u_opt1 == 2) return mx > 0. ? (mx - mn)/mx : 0.;
  return lum(c);
}
bool inSpan(vec2 uv){
  if (uv.x < 0. || uv.x > 1. || uv.y < 0. || uv.y > 1.) return false;
  if (u_opt2 == 4) return true;
  if (u_opt2 == 2) return maskAt(uv) > .5;
  if (u_opt2 == 3) return maskAt(uv) < .5;
  float l = lum(tx(uv).rgb);
  return u_opt2 == 0 ? l > u_p0 : l < u_p0;
}
void main(){
  vec3 here = tx(v_uv).rgb;
  if (!inSpan(v_uv)) { o = vec4(here, 1.); return; }
  bool vert = u_opt0 < 2;
  vec2 dir = u_opt0 == 0 ? vec2(0., 1.) : u_opt0 == 1 ? vec2(0., -1.) : u_opt0 == 2 ? vec2(1., 0.) : vec2(-1., 0.);
  float along = vert ? v_uv.y*u_res.y : v_uv.x*u_res.x, line = vert ? floor(v_uv.x*u_res.x) : floor(v_uv.y*u_res.y);
  if (dir.x + dir.y < 0.) along = (vert ? u_res.y : u_res.x) - along;
  float block = mix(24., 520., u_p1);                      // the longest streak, in pixels
  float a = along + hash(vec2(line, 3.1))*block;           // blocks staggered line by line
  float st = max(1., block/16.);                           // marching step, in pixels
  vec2 px = dir/u_res*st;
  float maxBack = floor((a - floor(a/block)*block)/st), maxFwd = floor((block - (a - floor(a/block)*block))/st);
  float back = 0., fwd = 0.;
  for (int i = 1; i <= 16; i++){ if (float(i) > maxBack || !inSpan(v_uv - px*float(i))) break; back = float(i); }
  for (int i = 1; i <= 16; i++){ if (float(i) > maxFwd || !inSpan(v_uv + px*float(i))) break; fwd = float(i); }
  float len = back + fwd;
  if (len < 1.) { o = vec4(here, 1.); return; }
  vec2 start = v_uv - px*back;
  vec3 col[12]; float key[12];
  for (int i = 0; i < 12; i++){
    vec3 c = tx(start + px*len*(float(i) + .5)/12.).rgb;
    col[i] = c; key[i] = (u_p2 > .5 ? -sortKey(c) : sortKey(c)) + float(i)*1e-5;   // ties broken by position
  }
  // this pixel's place in the run picks a rank; find the samples ranked there and next (no array shuffling,
  // which graphics cards are slow at)
  float f = clamp(back/len, 0., 1.)*11.;
  float r0 = floor(f), r1 = min(r0 + 1., 11.);
  vec3 c0 = col[0], c1 = col[0];
  for (int i = 0; i < 12; i++){
    float rank = 0.;
    for (int j = 0; j < 12; j++) rank += step(key[j], key[i]) - (j == i ? 1. : 0.);
    if (rank == r0) c0 = col[i];
    if (rank == r1) c1 = col[i];
  }
  vec3 sorted = mix(c0, c1, f - r0);
  o = vec4(mix(here, sorted, clamp(u_amt, 0., 1.)), 1.);
}"""),

    # Stained Glass: the picture as glass cells (each the colour at its centre) with dark leading between them
    # and a little light falling across each pane. Cells can re-shatter on the beat or drift.
    dict(id="stainedglass", name="Stained Glass", amt=.45, amt_label="Cells", speed=True, center=True, music=True,
         params=[("Leading", .35), ("Glass light", .5), ("Colour boost", .4)],
         options=[("Shatter", ["Still", "New pattern on the beat", "Drifting cells"], 0),
                  ("Leading colour", ["Dark lead", "Gold", "White", "Glowing (palette)"], 0),
                  ("Colours", PALETTES, 0)], code="""
vec2 cellPoint(vec2 c, float seed){
  vec2 h = vec2(hash(c + seed), hash(c + seed + 17.3));
  if (u_opt0 == 2) h = .5 + .45*sin(mClock()*.5 + h*6.2831853);   // drifting: on the music's time
  return c + .1 + .8*h;
}
void main(){
  float asp = u_res.x/u_res.y;
  float n = mix(70., 5., clamp(u_amt, 0., 1.));          // cells down the picture
  float seed = u_opt0 == 1 ? floor(u_beats)*3.17 : 0.;
  vec2 p = (v_uv - u_centre)*vec2(asp, 1.)*n, g = floor(p);   // laid out from the centre
  vec2 best = vec2(0.), bestCell = vec2(0.); float d1 = 1e9;
  for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++){
    vec2 c = g + vec2(x, y), q = cellPoint(c, seed); float d = dot(q - p, q - p);
    if (d < d1) { d1 = d; best = q; bestCell = c; }
  }
  float edge = 1e9;   // distance to the nearest border (to the next cell's half-way line)
  for (int y = -2; y <= 2; y++) for (int x = -2; x <= 2; x++){
    vec2 c = g + vec2(x, y); if (c == bestCell) continue;
    vec2 q = cellPoint(c, seed);
    edge = min(edge, dot((best + q)*.5 - p, normalize(q - best)));
  }
  vec2 centre = best/n/vec2(asp, 1.) + u_centre;
  vec3 glass = (tx(centre).rgb*2. + tx(mix(centre, v_uv, .5)).rgb)/3.;
  float l = lum(glass);
  glass = clamp(mix(vec3(l), glass, 1. + u_p2*1.5)*(1. + u_p2*.25), 0., 1.);
  vec2 lightDir = normalize(vec2(-.6, -.8));
  glass *= 1. + u_p1*(.35*dot(normalize(p - best + 1e-4), lightDir)*smoothstep(0., .5, sqrt(d1)) + .1);
  float w = mix(.015, .2, u_p0), aa = 1.5*n/u_res.y;
  float lead = 1. - smoothstep(w, w + aa, edge);
  vec3 leadCol = u_opt1 == 0 ? vec3(.05, .045, .04) : u_opt1 == 1 ? vec3(.85, .65, .25) : u_opt1 == 2 ? vec3(.95)
               : palCycle(u_opt2, hash(bestCell) + u_time*.1, glass)*1.4;
  leadCol *= .8 + .4*smoothstep(w, 0., edge);   // a rounded highlight along the lead
  o = vec4(mix(glass, leadCol, lead), 1.);
}"""),

    # Oil Paint: a Kuwahara filter. Around each pixel, of four overlapping squares the calmest one's average
    # colour wins, so flat areas become brush-strokes and edges stay sharp. Watercolour blends them softly,
    # adds paper texture and pigment pooling at the edges.
    dict(id="oilpaint", name="Oil Paint", amt=.5, amt_label="Brush size",
         params=[("Canvas texture", .35), ("Outline", .2), ("Colour boost", .25)],
         options=[("Style", ["Oil", "Watercolour"], 0)], code="""
void main(){
  float r = mix(2., 10., clamp(u_amt, 0., 1.));            // brush radius in pixels
  float st = max(1., r/4.);                                 // keep it to 5 x 5 samples per square
  vec2 px = st/u_res;
  vec3 m[4]; vec3 s[4];
  for (int k = 0; k < 4; k++){ m[k] = vec3(0.); s[k] = vec3(0.); }
  for (int y = 0; y <= 4; y++) for (int x = 0; x <= 4; x++){
    vec2 o2 = vec2(x, y);
    vec3 c0 = tx(v_uv + vec2(-o2.x, -o2.y)*px).rgb, c1 = tx(v_uv + vec2(o2.x, -o2.y)*px).rgb;
    vec3 c2 = tx(v_uv + vec2(-o2.x, o2.y)*px).rgb, c3 = tx(v_uv + vec2(o2.x, o2.y)*px).rgb;
    m[0] += c0; s[0] += c0*c0; m[1] += c1; s[1] += c1*c1;
    m[2] += c2; s[2] += c2*c2; m[3] += c3; s[3] += c3*c3;
  }
  vec3 outc = vec3(0.); float best = 1e9, wsum = 0.;
  for (int k = 0; k < 4; k++){
    m[k] /= 25.; vec3 v = abs(s[k]/25. - m[k]*m[k]); float var = v.r + v.g + v.b;
    if (u_opt0 == 0) { if (var < best) { best = var; outc = m[k]; } }
    else { float w = 1./(1. + var*400.); outc += m[k]*w; wsum += w; }
  }
  if (u_opt0 == 1) outc /= wsum;
  float l = lum(outc);
  outc = clamp(mix(vec3(l), outc, 1. + u_p2), 0., 1.);
  vec2 q = v_uv*u_res;
  if (u_opt0 == 0) {   // canvas weave
    float weave = sin(q.x*1.7)*sin(q.y*1.7)*.5 + (hash(floor(q*.5)) - .5);
    outc *= 1. + u_p0*.12*weave;
  } else {             // paper grain, lighter washes
    outc = mix(outc, vec3(1.), .12);
    outc *= 1. - u_p0*.18*hash(floor(q/2.))*hash(floor(q/7.) + 3.);
  }
  // outline: where the painted colour changes fast, like ink or pooled pigment
  vec2 e = r*.6/u_res;
  float g = length(tx(v_uv + vec2(e.x, 0.)).rgb - tx(v_uv - vec2(e.x, 0.)).rgb)
          + length(tx(v_uv + vec2(0., e.y)).rgb - tx(v_uv - vec2(0., e.y)).rgb);
  outc *= 1. - u_p1*smoothstep(.15, .6, g)*(u_opt0 == 0 ? .7 : .45);
  o = vec4(outc, 1.);
}"""),

    # Tiny Planet: the picture wrapped round into a little world (the bottom of the picture becomes the ground
    # at the centre, the sky all around) or the other way, a tunnel with the sky in the middle.
    dict(id="tinyplanet", name="Tiny Planet", amt=.5, amt_label="Size", center=True, speed=True,
         params=[("Twist", 0., -1., 1.)],
         options=[("Shape", ["Planet", "Tunnel"], 0),
                  ("Seam", ["One full turn (seam underneath)", "Mirrored (seamless, twice round)"], 0)], code="""
void main(){
  float asp = u_res.x/u_res.y;
  vec2 p = (v_uv - u_centre)*vec2(asp, 1.);
  float R = mix(.06, .5, clamp(u_amt, 0., 1.));          // the horizon's radius, in picture heights
  float r = length(p);
  // the middle of the picture points up, so you stand on top of the planet; the seam is underneath
  float a = atan(p.x, -p.y)/6.2831853 + .5 + u_time*.02 + u_p0*r/R*.15;
  float x = u_opt1 == 1 ? 1. - abs(fract(a)*2. - 1.) : fract(a);
  float h = .5*r/R;                                       // ground at the centre, horizon at R, sky beyond
  // the planet's sky stops at the top of the picture; the tunnel mirrors on inwards forever
  float y = u_opt0 == 0 ? clamp(1. - h, .002, .998) : h;
  o = vec4(tx(vec2(x, y)).rgb, 1.);
}"""),
]

# What's behind the person, for effects that make them see-through or take them away: the captured empty room
# if there is one, otherwise a guess from the picture around them (an average of nearby background).
BEHIND_GLSL = """
vec3 behindYou(vec2 uv){
  if (u_plate_on > .5) return texture(u_plate, uv).rgb;
  vec3 s = vec3(0.); float w = 0.;
  for (int i = 0; i < 12; i++){
    float a = float(i)*.5236, r = .06 + .05*float(i % 3);
    vec2 q = uv + vec2(cos(a)*u_res.y/u_res.x, sin(a))*r;
    float k = 1. - maskAt(q); s += tx(q).rgb*k; w += k;
  }
  return w > .5 ? s/w : tx(uv).rgb*.25;
}
"""
VNOISE_GLSL = """
float vnz(vec2 p){ vec2 i = floor(p), f = fract(p); f = f*f*(3. - 2.*f);
  return mix(mix(hash(i), hash(i + vec2(1., 0.)), f.x), mix(hash(i + vec2(0., 1.)), hash(i + vec2(1., 1.)), f.x), f.y); }
"""

MORE_EFFECTS += [
    # Hologram: you as a flickering projection: tinted, scanlined, with glitch tears, a glowing edge and a beam of
    # light rising from the projector (drag the centre point to move it).
    dict(id="hologram", name="Hologram", amt=1., amt_label="Strength", mask=True, center=True,
         params=[("Flicker", .4), ("Scanlines", .6), ("Glitch", .3), ("See-through", .35), ("Beam", .5)],
         options=[("Colours", PALETTES, 1), ("Colour motion", COLOUR_MOTION, 0),
                  ("Behind you", ["The room", "Dark room", "Black"], 0)], code=BEHIND_GLSL + """
void main(){
  float asp = u_res.x/u_res.y;
  // glitch tears: a few bands of rows jump sideways for a moment
  float band = floor(v_uv.y*90.), tick = floor(u_time*9.);
  float tear = step(1. - u_p2*.12, hash(vec2(band, tick)))*(hash(vec2(band, tick + 5.)) - .5)*.08;
  vec2 uv = v_uv + vec2(tear, 0.);
  vec3 here = tx(v_uv).rgb, src = tx(uv).rgb;
  float m = maskAt(uv), mHere = maskAt(v_uv);
  vec3 room = mix(here, behindYou(v_uv), mHere);
  if (u_opt2 == 1) room *= .3;
  if (u_opt2 == 2) room = vec3(0.);
  vec3 tint = palCycle(u_opt0, palPhase(u_opt1, v_uv), src);
  vec3 holo = tint*(.2 + 1.15*lum(src));
  float scan = 1. - u_p1*.55*(.5 + .5*sin(v_uv.y*u_res.y*1.1 - u_time*30.));
  float roll = u_p1*.35*exp(-pow((fract(v_uv.y*.8 - u_time*.18) - .5)*14., 2.));   // a bright band sweeping
  float flick = 1. - u_p0*(.3*step(.8, hash(vec2(floor(u_time*24.), 1.))) + .12*(.5 + .5*sin(u_time*9.)));
  holo = holo*scan*flick + tint*roll*m;
  vec2 e = 2.5/u_res;
  float edge = clamp((abs(maskAt(uv + vec2(e.x, 0.)) - maskAt(uv - vec2(e.x, 0.)))
                    + abs(maskAt(uv + vec2(0., e.y)) - maskAt(uv - vec2(0., e.y))))*1.6, 0., 1.);
  vec3 c = mix(room, holo, m*mix(.95, .35, u_p3)*flick) + tint*edge*flick;
  // the projector's beam, from the bottom of the picture under the centre point, widening upward
  float up = 1. - v_uv.y, half_ = .02 + up*.3;
  float beam = (1. - smoothstep(half_*.15, half_, abs(v_uv.x - u_centre.x)*asp))*pow(1. - up, 1.5);
  c += tint*beam*u_p4*.45*(.7 + .3*flick);
  o = vec4(mix(here, c, clamp(u_amt, 0., 1.)), 1.);
}"""),

    # Aura: a glow streaming off your outline, rising like heat, radiating in wisps, or a soft halo; it pulses
    # with the bass (Bass pulse) and takes any palette and colour motion.
    dict(id="aura", name="Aura", amt=.45, amt_label="Size", mask=True, speed=True,
         params=[("Glow", .7), ("Bass pulse", .5), ("Wisps", .6)],
         options=[("Colours", PALETTES, 5), ("Colour motion", COLOUR_MOTION, 2),
                  ("Shape", ["Rising", "Radiating wisps", "Soft halo"], 0)], code=VNOISE_GLSL + """
void main(){
  vec3 here = tx(v_uv).rgb;
  float asp = u_res.x/u_res.y;
  float size = mix(.03, .3, clamp(u_amt, 0., 1.))*(1. + u_bands.x*u_p1);
  float t = u_time, acc = 0., wsum = 0.;
  for (int i = 1; i <= 14; i++){
    float k = float(i)/14.;
    vec2 off;
    if (u_opt2 == 0) {   // rising: the glow here came from below, wavering sideways like heat
      float w = (vnz(v_uv*vec2(7., 3.) + vec2(0., t*1.5) + k*2.) - .5)*u_p2;
      off = vec2(w*.6/asp, k)*size;
    } else {             // all round; wisps turn slowly
      float a = float(i)*2.39996 + (u_opt2 == 1 ? (vnz(v_uv*4. + t*.5) - .5)*u_p2*6. : 0.);
      off = vec2(cos(a)/asp, sin(a))*k*size;
    }
    float w = 1. - k*.85;
    acc += maskAt(v_uv + off)*w; wsum += w;
  }
  float aura = pow(clamp(acc/wsum*1.6, 0., 1.), .8)*(1. - maskAt(v_uv));   // outside you only
  vec3 col = palCycle(u_opt0, palPhase(u_opt1, v_uv) + aura*.3, here);
  o = vec4(here + col*aura*u_p0*1.6, 1.);
}"""),

    # Disintegrate: you crumble into dust / embers / pixels that drift away on the wind, and come back.
    # Each little cell of you leaves at its own moment (the side the wind blows toward first); for every pixel
    # the cells upwind are checked to see if one of their particles has landed here.
    dict(id="disintegrate", name="Disintegrate", amt=.5, amt_label="Progress", mask=True, center=True, speed=True,
         params=[("Particle size", .3), ("Travel", .5), ("Swirl", .4)],
         options=[("Drive", ["Loop", "Amount slider (or MIDI)", "Out and back on the beat (2 bars)"], 0),
                  ("Drift", ["Up (ash)", "Right (wind)", "Left (wind)", "Down (sand)", "Outward"], 0),
                  ("Style", ["Dust", "Embers", "Pixels"], 0)], code=BEHIND_GLSL + """
float progress(){
  if (u_opt0 == 0) return smoothstep(0., 1., 1. - abs(fract(u_time*.15)*2. - 1.));   // ~7 s out and back
  if (u_opt0 == 2) return smoothstep(0., 1., 1. - abs(fract(beatGlide()/8.)*2. - 1.));
  return clamp(u_amt, 0., 1.);
}
vec2 windAt(vec2 P){   // the direction particles leave in, in pixels
  if (u_opt1 == 0) return vec2(0., -1.);
  if (u_opt1 == 1) return normalize(vec2(1., -.2));
  if (u_opt1 == 2) return normalize(vec2(-1., -.2));
  if (u_opt1 == 3) return vec2(0., 1.);
  vec2 d = P - u_centre*u_res; return length(d) > 1. ? d/length(d) : vec2(0., -1.);
}
float leaveAt(vec2 cell, vec2 cc){   // when (0..0.75 of the way) this cell lets go: downwind side first
  vec2 w = windAt(cc);
  float side = dot(cc/u_res - .5, w*vec2(u_res.x/u_res.y, 1.)) + .5;
  return .75*mix(hash(cell), 1. - clamp(side, 0., 1.), .55);
}
void main(){
  float p = progress();
  float cs = mix(2., 12., u_p0)*(u_opt2 == 2 ? 2. : 1.);   // particle cell, pixels
  float D = mix(.08, .8, u_p1)*u_res.y;                   // how far they fly, pixels
  vec2 P = v_uv*u_res;
  vec3 here = tx(v_uv).rgb;
  float m = maskAt(v_uv);
  vec2 cellH = floor(P/cs);
  float thH = leaveAt(cellH, (cellH + .5)*cs);
  float intact = step(p, thH);
  vec3 c = mix(here, behindYou(v_uv), m*(1. - intact));
  if (u_opt2 == 1) c += vec3(1., .45, .1)*m*intact*smoothstep(.06, 0., thH - p)*step(.001, p)*1.5;   // burning edge
  // particles in flight: look back upwind for cells whose particle lands on this pixel
  vec2 w = windAt(P), perp = vec2(-w.y, w.x);
  float stepPx = max(cs, D*1.4/32.);
  for (int k = 0; k < 32; k++){
    vec2 S = P - w*stepPx*float(k);
    for (int l = -1; l <= 1; l++){
      vec2 C = floor(S/cs) + floor(perp*float(l) + .5);
      vec2 cc = (C + .5)*cs;
      if (maskAt(cc/u_res) < .5) continue;
      float th = leaveAt(C, cc);
      if (p <= th) continue;
      float life = (p - th)/(1. - th + 1e-3);
      float d = (p - th)*D*(.6 + .8*hash(C + 9.1));
      vec2 L = cc + windAt(cc)*d + perp*sin(d/D*10. + hash(C)*6.28)*D*.08*u_p2;
      float r = cs*.55*(1. - smoothstep(.5, 1., life));
      vec2 q = abs(P - L);
      if ((u_opt2 == 2 ? max(q.x, q.y) : length(P - L)) < r) {
        vec3 pc = tx(cc/u_res).rgb;
        if (u_opt2 == 1) pc = mix(vec3(1., .85, .4), vec3(1., .3, .05), life)*1.6;
        c = mix(c, pc, 1. - life*.5);
        o = vec4(mix(here, c, step(.001, p)), 1.); return;
      }
    }
  }
  o = vec4(c, 1.);
}"""),
]

# Frame memory for Echo Clones and Time Grid: 16 half-size frames in a 4 x 4 atlas (the state buffer is twice the
# picture's size), one refreshed per interval, round and round. Alpha keeps the person mask (0.5 + mask/2), and
# 0 marks a tile that hasn't been filled yet.
def _atlas_writer(every):
    return """
void main(){
  float every = """ + every + """;
  float wi = mod(floor(u_time/every), 16.);
  vec2 tile = floor(v_uv*4.);
  if (tile.x + 4.*tile.y == wi) { vec2 uv = fract(v_uv*4.); o = vec4(tx(uv).rgb, .5 + .5*maskAt(uv)); return; }
  o = texture(u_s0, v_uv); }"""


ATLAS_READ = """
// a remembered frame, `back` intervals ago (0 = the one being written now), and the person mask then
vec4 pastFrame(float back, vec2 uv, float every){
  float idx = mod(mod(floor(u_time/every), 16.) - back, 16.);
  vec2 tile = vec2(mod(idx, 4.), floor(idx/4.));
  vec4 c = texture(u_s0, (tile + clamp(uv, 2./u_res, 1. - 2./u_res))/4.);
  return c.a < .25 ? vec4(tx(uv).rgb, maskAt(uv)) : vec4(c.rgb, (c.a - .5)*2.);
}
"""

MORE_EFFECTS += [
    # Echo Clones: copies of you, each a little further back in time, standing beside you (or behind, smaller),
    # so every move ripples down the line. Amount = spacing, so audio / wave mode makes the line breathe.
    dict(id="echoclones", name="Echo Clones", amt=.35, amt_label="Spacing", mask=True,
         state=[_atlas_writer("mix(.04, .5, u_p1)*.5")], state_size=[(2, "f1")],
         params=[("Copies", 4., 1., 7., "%.0f"), ("Delay", .35), ("Fade", .4), ("Tint", 0.)],
         options=[("Layout", ["Both sides", "To the right", "To the left", "Behind you (into the distance)"], 0),
                  ("Colours", PALETTES, 0), ("Colour motion", COLOUR_MOTION, 0)], code=ATLAS_READ + """
void main(){
  float every = mix(.04, .5, u_p1)*.5;   // two memory slots per copy
  vec3 here = tx(v_uv).rgb, c = here;
  int n = int(u_p0 + .5);
  float gap = mix(.05, .45, clamp(u_amt, 0., 1.));
  for (int j = 7; j >= 1; j--){          // the furthest copy first, so nearer ones cover it
    if (j > n) continue;
    float fj = float(j);
    vec2 uv;
    if (u_opt0 == 3) {   // behind: each one smaller and a little higher, toward a vanishing point
      float s = pow(.82, fj);
      uv = (v_uv - vec2(.5, .95))/s + vec2(.5, .95) + vec2(0., gap*.9*fj);   // each one smaller and higher
    } else {
      float side = u_opt0 == 1 ? 1. : u_opt0 == 2 ? -1. : (mod(fj, 2.) > .5 ? 1. : -1.);
      float dist = u_opt0 == 0 ? ceil(fj*.5) : fj;
      uv = v_uv - vec2(side*dist*gap, 0.);
    }
    if (uv.x < 0. || uv.x > 1. || uv.y < 0. || uv.y > 1.) continue;
    vec4 pf = pastFrame(fj*2., uv, every);
    vec3 col = mix(pf.rgb, palCycle(u_opt1, palPhase(u_opt2, v_uv) + fj/float(n + 1), pf.rgb)*(.35 + lum(pf.rgb)), u_p3);
    c = mix(c, col, pf.a*pow(1. - u_p2*.6, fj));
  }
  o = vec4(mix(c, here, maskAt(v_uv)), 1.);   // the live you stays in front
}"""),

    # Time Grid: tiles, each showing a different moment, a little further back. Tiles can show the whole picture
    # or just their own part of it (a mosaic of moments). Amount = time between tiles.
    dict(id="timegrid", name="Time Grid", amt=.3, amt_label="Delay",
         state=[_atlas_writer("mix(.03, .6, clamp(u_amt, 0., 1.))")], state_size=[(2, "f1")],
         params=[("Gaps", .25)],
         options=[("Grid", ["2 x 2", "3 x 3", "4 x 4"], 1),
                  ("Each tile shows", ["The whole picture", "Its own part"], 0),
                  ("Order", ["Reading order", "From the centre out", "Shuffled on the beat"], 0)],
         code=ATLAS_READ + """
void main(){
  float every = mix(.03, .6, clamp(u_amt, 0., 1.));
  float n = float(u_opt0 + 2);
  vec2 cell = floor(v_uv*n), f = fract(v_uv*n);
  float k = cell.x + n*cell.y;
  if (u_opt2 == 1) k = floor(length(cell + .5 - n*.5)*1.5);   // rings out from the middle
  if (u_opt2 == 2) k = floor(hash(cell + floor(u_beats)*1.7)*n*n);
  k = min(k, 15.);
  vec2 uv = u_opt1 == 0 ? f : v_uv;
  vec3 c = pastFrame(k, uv, every).rgb;
  float g = u_p0*.06*n, aa = n*1.5/u_res.y;
  float edge = min(min(f.x, 1. - f.x)*u_res.x/u_res.y, min(f.y, 1. - f.y));
  c *= smoothstep(g*.5, g*.5 + aa, edge);
  o = vec4(c, 1.);
}"""),
]

# ---- Audio visuals (2026-11): visualizers that work on any source, or none. The "Audio" category.
# Spectrum Terrain keeps the spectrum's recent history in its memory buffer (128 columns x 96 rows spread over the
# whole texture, one row refreshed per interval, round and round); Vectorscope keeps a fading trace of its light.
TERRAIN_ROWS = 96
TERRAIN_HIST = """
void main(){
  float every = mix(.12, .015, u_p0);
  float wi = mod(floor(u_time/every), 96.);
  float r = floor(v_uv.y*96.);
  if (abs(r - wi) < .5) { o = vec4(spectrum(v_uv.x), 0., 0., 1.); return; }
  o = texture(u_s0, v_uv); }"""

SCOPE_TRACE = """
// the stereo picture: left against right, turned 45 degrees so a mono sound is a vertical line and a wide one a cloud
vec2 scopePoint(float t, float R){
  float l = waveL(t), r = waveR(t);
  return vec2((l - r)*.7071, -(l + r)*.7071)*R;
}
void main(){
  float asp = u_res.x/u_res.y;
  vec2 p = (v_uv - u_centre)*vec2(asp, 1.);
  float R = .12 + 1.2*pow(clamp(u_amt, 0., 1.), 2.6);   // up to ~1.3 picture heights: bigger than the frame
  float keep = texture(u_s0, v_uv).r*pow(mix(.55, .97, u_p0), u_dt*60.);   // the afterglow
  float inten = 0.;
  if (length(p) < R*1.6) {
    float w = mix(.0022, .009, u_p1)*(.6 + .8*R);
    vec2 a = scopePoint(0., R);
    for (int i = 1; i < 128; i++){
      float t = float(i)/127.;
      vec2 b = scopePoint(t, R);
      float age = mix(.35, 1., t);   // the newest samples are brightest
      if (u_opt0 == 0) {   // lines
        vec2 pa = p - a, ba = b - a;
        float h = clamp(dot(pa, ba)/max(dot(ba, ba), 1e-7), 0., 1.);
        inten += smoothstep(w, w*.2, length(pa - ba*h))*age;
      } else {             // dots
        inten += smoothstep(w*1.8, w*.3, length(p - b))*age;
      }
      a = b;
    }
  }
  o = vec4(max(keep, min(inten*.5, 1.6)), 0., 0., 1.); }"""

AUDIO_EFFECTS = [
    # Spectrum Terrain: the spectrum's last couple of seconds as rows of ridges receding into the distance, newest at
    # the front: like the famous pulsar plot. Each ridge hides the ones behind it, with the picture (or black) showing
    # through, so it works over any source.
    dict(id="terrain", name="Spectrum Terrain", amt=.5, amt_label="Height", speed=True, center=True, xform=True,
         state=[TERRAIN_HIST], state_size=[(1, "f2")],
         params=[("Scroll speed", .45), ("Lines", .7), ("Line weight", .4), ("Glow", .35), ("Picture warp", 0.)],
         options=[("Style", ["Ridge lines", "Solid terrain"], 0),
                  ("Behind", ["The picture", "Dark picture", "Black"], 1),
                  ("Colour", PALETTES, 5), ("Colour motion", COLOUR_MOTION, 0)],
         code="""
void main(){
  float every = mix(.12, .015, u_p0);
  float wi = mod(floor(u_time/every), 96.);
  int nl = int(mix(14., 48., u_p1));
  float H = clamp(u_amt, 0., 1.)*.62;
  // Picture warp: the picture behind is pushed by the terrain's own heights, row by row in the same perspective, so
  // the ridges seem to lift it (up where a peak is, sideways along its slopes)
  vec2 wp = vec2(0.);
  if (u_p4 > .001) {
    float wz = pow(clamp((v_uv.y - .34)/.61, 0., 1.), 1./1.5);
    float wr = floor(mod(wi - (1. - wz)*float(nl - 1)*(96./float(nl)) + 96., 96.));
    float wx = (v_uv.x - .5)/mix(.62, 1., pow(wz, 1.5)) + .5, rv = (wr + .5)/96.;
    float hc = texture(u_s0, vec2(wx, rv)).r;
    float hs = texture(u_s0, vec2(wx + .015, rv)).r - texture(u_s0, vec2(wx - .015, rv)).r;
    wp = vec2(hs*.5, -hc)*u_p4*.16*(.3 + clamp(u_amt, 0., 1.));
  }
  vec3 base = tx(v_uv + wp).rgb;
  float edge = mix(1.2, 3.2, u_p2)/u_res.y;
  vec3 bg = u_opt1 == 0 ? base : (u_opt1 == 1 ? base*.22 : vec3(0.));
  vec3 outc = bg;
  for (int i = 0; i < 48; i++){
    if (i >= nl) break;
    float z = float(i)/float(max(nl - 1, 1));
    float zz = pow(z, 1.5);
    float yb = mix(.34, .95, zz);
    float sc = mix(.4, 1., zz);
    float xr = (v_uv.x - .5)/mix(.62, 1., zz) + .5;
    if (xr < 0. || xr > 1.) continue;
    float age = float(nl - 1 - i)*(96./float(nl));          // newest in front
    float r = floor(mod(wi - age + 96., 96.));
    float h = texture(u_s0, vec2(xr, (r + .5)/96.)).r;
    float top = yb - h*H*sc;
    vec3 lc = palCycle(u_opt2, h*.7 + z*.4 + palPhase(u_opt3, v_uv), base)*mix(.4, 1.25, zz);
    if (u_opt0 == 1 && v_uv.y > top) {   // solid: the ground under the ridge, shaded by its height
      float depth = smoothstep(0., .22, v_uv.y - top);
      outc = mix(lc*(.35 + .9*h), bg, depth*.85);
    } else if (v_uv.y > top) {
      outc = bg;                                              // hides the ridges behind this one
    }
    float d = abs(v_uv.y - top);
    float line = smoothstep(edge*1.6, edge*.4, d);
    outc += lc*(line + exp(-d*70.)*u_p3*.9*(.3 + h))*step(top, yb + .01);
  }
  o = vec4(outc, 1.); }"""),

    # Vectorscope: the stereo sound drawn as light (left against right): a line for a mono sound, a swirling cloud for
    # a wide mix, with an afterglow like a real scope. Nothing but the sound is needed; it glows over any picture.
    dict(id="vectorscope", name="Vectorscope", amt=.5, amt_label="Size", center=True, xform=True,
         state=[SCOPE_TRACE], state_size=[(1, "f2")],
         params=[("Afterglow", .55), ("Line weight", .4), ("Brightness", .6)],
         options=[("Draw", ["Lines", "Dots"], 0), ("Colour", PALETTES, 1), ("Colour motion", COLOUR_MOTION, 0),
                  ("Frame", ["None", "Graticule"], 1), ("Behind", ["The picture", "Dark picture", "Black"], 1)],
         code="""
void main(){
  vec3 base = tx(v_uv).rgb;
  vec3 bg = u_opt4 == 0 ? base : (u_opt4 == 1 ? base*.22 : vec3(0.));
  float s = clamp(texture(u_s0, v_uv).r, 0., 2.);
  float asp = u_res.x/u_res.y;
  vec2 p = (v_uv - u_centre)*vec2(asp, 1.);
  float R = .12 + 1.2*pow(clamp(u_amt, 0., 1.), 2.6);   // up to ~1.3 picture heights: bigger than the frame
  vec3 col = palCycle(u_opt1, length(p)/R*.6 + palPhase(u_opt2, v_uv) + s*.15, base);
  vec3 outc = bg + col*s*mix(.9, 2.4, u_p2);
  if (u_opt3 == 1) {   // graticule: a ring and a cross, faint
    float r = length(p), px = 1.5/u_res.y;
    float g = smoothstep(px*1.4, 0., abs(r - R)) + smoothstep(px*1.4, 0., abs(r - R*.5))*.5
            + smoothstep(px, 0., abs(p.x))*step(r, R)*.5 + smoothstep(px, 0., abs(p.y))*step(r, R)*.5;
    outc += col*g*.18;
  }
  o = vec4(outc, 1.); }"""),

    # Audio Warp: the picture bends with the music: the spectrum bounces its columns, the bass pumps it, and every
    # kick, snare and hat sends a ring rippling out from the centre. Strength is the main slider.
    dict(id="audiowarp", name="Audio Warp", amt=.5, amt_label="Strength", center=True, music=True,
         params=[("Ring width", .45), ("Colour split", .35), ("Sideways", .3)],
         options=[("Mode", ["Spectrum waves", "Bass pump", "Shockwaves on hits", "All of them"], 3),
                  ("Rings from", ["The centre", "A different spot per drum"], 0)],
         code="""
vec2 ringPush(vec2 p, float h, float speed, float width, float amp){
  float age = -.22*log(max(h, .003));            // seconds since the hit (its level fades as e^(-t/.22))
  float rad = age*speed, r = length(p);
  float prof = exp(-pow((r - rad)/width, 2.))*h*amp;
  return p/max(r, 1e-3)*prof;
}
void main(){
  float asp = u_res.x/u_res.y;
  float A = clamp(u_amt, 0., 1.);
  vec2 p = (v_uv - u_centre)*vec2(asp, 1.);
  vec2 d = vec2(0.);
  float spec = spectrum(v_uv.x);
  if (u_opt0 == 0 || u_opt0 == 3) {   // each column bounces with its own part of the spectrum
    d.y += (spec - .3)*A*.16 + ((u_char == 2) ? sin(v_uv.x*7. + mClock()*1.2)*A*.025*u_swell.w : 0.);
    d.x += (spectrum(v_uv.y) - .3)*A*.12*u_p2;
  }
  if (u_opt0 == 1 || u_opt0 == 3) {   // the bass breathes the whole picture; the pan tilts it
    float z = ((u_char == 1 || u_char == 2) ? u_swell.x : u_bands.x*.7 + u_hits.x*.3)*A*.2;   // swell: a slow breath
    p *= 1. - z;
    float a = (u_slow.w - .5)*A*.35;
    p = mat2(cos(a), -sin(a), sin(a), cos(a))*p;
  }
  if (u_opt0 == 2 || u_opt0 == 3) {   // rings: kick is the big slow one, snare medium, hats fine and quick
    float w = mix(.025, .1, u_p0);
    vec2 o1 = u_opt1 == 1 ? vec2(0., .0) : vec2(0.), o2 = u_opt1 == 1 ? vec2(.28, -.12) : vec2(0.),
         o3 = u_opt1 == 1 ? vec2(-.28, .14) : vec2(0.);
    d += ringPush(p - o1, u_hits.x, .55, w*1.4, A*.34) + ringPush(p - o1, u_hits.w, .8, w*2.2, A*.26)
       + ringPush(p - o2, u_hits.y, .75, w, A*.24) + ringPush(p - o3, u_hits.z, 1.1, w*.6, A*.15);
  }
  vec2 uv = p/vec2(asp, 1.) + u_centre + d*vec2(1./asp, 1.);
  float split = u_p1*(u_bands.z*.7 + u_hits.z*.5 + .15)*A*.05;
  vec2 sp = normalize(p + vec2(1e-4))*split;
  o = vec4(tx(uv + sp).r, tx(uv).g, tx(uv - sp).b, 1.); }"""),

    # Picture Spectrum: spectrum bars made of the picture itself: the bars show the video, the rest is dark (or dim).
    dict(id="picspectrum", name="Picture Spectrum", amt=.55, amt_label="Height", center=True,
         params=[("Bars", .45), ("Gap", .25), ("Tint", .25), ("Cap glow", .5)],
         options=[("Style", ["Bars from the bottom", "Mirrored from the middle", "Radial"], 0),
                  ("Outside the bars", ["Black", "Dim picture", "Picture"], 1),
                  ("Colour", PALETTES, 5), ("Colour motion", COLOUR_MOTION, 2)],
         code="""
void main(){
  vec3 src = tx(v_uv).rgb;
  float asp = u_res.x/u_res.y, px = 1./u_res.y;
  float nb = floor(mix(8., 72., u_p0));
  float gap = mix(.04, .45, u_p1);
  float H = mix(.15, .92, clamp(u_amt, 0., 1.));
  float inside = 0., cap = 0., hue = v_uv.x, v = 0.;
  if (u_opt0 == 2) {
    vec2 p = (v_uv - u_centre)*vec2(asp, 1.);
    float r = length(p), a = abs(atan(p.x, -p.y))/3.14159;
    float i = floor(a*nb), f = fract(a*nb);
    v = spectrum((i + .5)/nb);
    float R0 = .1*(1. + u_bands.x*.2), len = v*H*.42;
    float dr = r - R0;
    inside = step(gap*.5, f)*step(f, 1. - gap*.5)*step(0., dr)*step(dr, len);
    cap = step(gap*.5, f)*step(f, 1. - gap*.5)*smoothstep(3.*px, 0., abs(dr - len))*step(.02, v);
    hue = a;
  } else {
    float x = u_opt0 == 1 ? abs(v_uv.x - .5)*2. : v_uv.x;
    float i = floor(x*nb), f = fract(x*nb);
    v = spectrum((i + .5)/nb);
    float dy = u_opt0 == 1 ? abs(v_uv.y - .5)*2. : 1. - v_uv.y;
    float len = v*H*(u_opt0 == 1 ? 1. : 1.05);
    float inBar = step(gap*.5, f)*step(f, 1. - gap*.5);
    inside = inBar*step(dy, len);
    cap = inBar*smoothstep(3.*px*(u_opt0 == 1 ? 2. : 1.), 0., abs(dy - len))*step(.02, v);
    hue = x;
  }
  vec3 tint = palCycle(u_opt2, hue*.9 + palPhase(u_opt3, v_uv), src);
  vec3 lit = mix(src, src*tint*1.7, u_p2)*(1. + v*.35);
  vec3 out_ = u_opt1 == 0 ? vec3(0.) : (u_opt1 == 1 ? src*.16 : src*.55);
  vec3 col = mix(out_, lit, inside) + tint*cap*u_p3*1.6;
  o = vec4(col, 1.); }"""),

    # Aurora: a flowing field of colour that follows the music's slow side: loudness swells it, brightness shifts its
    # colour, busyness stirs it up, the pan leans it left or right, and every kick flares it. No picture needed.
    dict(id="aurora", name="Aurora Field", amt=.6, amt_label="Intensity", speed=True, music=True, char=2, center=True, xform=True,
         params=[("Detail", .5), ("Picture shows", .25), ("Kick flare", .5), ("Drift", 0.)],
         options=[("Style", ["Curtains", "Nebula", "Ribbons"], 0),
                  ("Colour", PALETTES, 5), ("Colour motion", COLOUR_MOTION, 0)],
         code=VNOISE_GLSL + """
float fbm(vec2 p){ float a = .5, s = 0.; for (int i = 0; i < 5; i++){ s += a*vnz(p); p = p*2.03 + 7.1; a *= .5; } return s; }
// A noise field that MORPHS instead of travelling: it fades from one random field to the next in place, so the smoke
// changes shape without sliding across the picture or going back and forth. ph is the morph clock.
float mfbm(vec2 p, float ph){
  float i = floor(ph), x = smoothstep(0., 1., ph - i);
  float a = fbm(p + vec2(hash(vec2(i, 3.)), hash(vec2(i, 9.)))*40.);
  float b = fbm(p + vec2(hash(vec2(i + 1., 3.)), hash(vec2(i + 1., 9.)))*40.);
  float k = 1./sqrt((1. - x)*(1. - x) + x*x);              // two unrelated fields blended lose contrast; put it back
  return .5 + (mix(a, b, x) - .5)*k;
}
void main(){
  vec3 src = tx(v_uv).rgb;
  float asp = u_res.x/u_res.y;
  vec2 p = vec2(v_uv.x*asp, v_uv.y);
  // the music's own time: flows, swells or steps on the beat. Scaled out, the folds get small, so time slows with
  // them (else a fine pattern shimmers like static); Speed 0 holds the whole thing still
  float tc = mClock()*min(u_xf.x, 1.);
  float t = tc*.1;
  float lean = (u_slow.w - .5)*2.;                         // pan: -1 left .. 1 right
  float busy = u_slow.z, energy = u_slow.x;
  float dens = mix(1.2, 3.2, u_p0)*(1. + .3*u_swell.y);   // the folds tighten as the mids swell
  vec2 q = u_opt0 == 0 ? vec2(p.x*dens*1.2, p.y*dens*.35) : p*dens;
  float drift = u_p3;                                       // Drift: how much it also slides across (0 = only morphs in place)
  q.x -= lean*tc*.12*drift;                                 // toward where the sound is, when it's allowed to slide
  float ph = tc*.5;                                         // the morph clock
  vec2 w = vec2(mfbm(q, ph), mfbm(q + vec2(5.2, 1.3), ph + .37));
  float n = mfbm(q + w*(1.9 + 1.0*u_swell.x*min(abs(u_speed), 1.)) + vec2(t*.6, 0.)*drift, ph*.8);   // folds over on itself
  float f;
  if (u_opt0 == 0) {          // curtains: bright vertical folds, fading toward the bottom
    f = smoothstep(.28, .85, n)*smoothstep(1.05, .15, v_uv.y + (w.y - .5)*.25);
  } else if (u_opt0 == 1) {   // nebula: soft clouds everywhere
    f = smoothstep(.3, .95, n);
  } else {                    // ribbons: thin bright lines along the folds
    f = smoothstep(.07, 0., abs(n - .5 - .12*sin(tc*.3)))*1.3 + smoothstep(.4, .9, n)*.25;
  }
  float bright = (.2 + 1.1*energy)*clamp(u_amt, 0., 1.)*1.6 + mPulse(u_hits.x, u_swell.x)*u_p2*.6;   // flare: a hit, or in Swell / Flow a slow glow
  vec3 col = palCycle(u_opt1, n*.8 + u_slow.y*.6 + w.x*.3 + palPhase(u_opt2, v_uv), src);
  vec3 outc = src*u_p1 + col*f*bright;
  o = vec4(outc, 1.); }"""),
]

EFFECTS += MORE_EFFECTS
EFFECTS += AUDIO_EFFECTS
_CAT.update(pixelsort="Stylize", stainedglass="Stylize", oilpaint="Stylize", tinyplanet="Mirror & Geometry",
            hologram="Cutout", aura="Cutout", disintegrate="Cutout", echoclones="Cutout", timegrid="Feedback")
_CAT.update(visualizer="Audio", terrain="Audio", vectorscope="Audio", audiowarp="Audio", picspectrum="Audio",
            aurora="Audio")

for _fx in EFFECTS:
    _fx["cat"] = _CAT.get(_fx["id"], "Other")
