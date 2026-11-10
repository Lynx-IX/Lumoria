"""3D effects: real geometry with depth, perspective, lighting and a moving camera.

Two kinds:
  Instanced - thousands of small shapes (rods, cubes, shards) drawn with a depth buffer into an antialiased scene
              (spec key "mesh"), then the effect's own pass ("code") lays that scene over a background with glow.
  Raymarched - whole 3D worlds drawn per pixel in the effect's fragment shader (no mesh), using RAY3D helpers.

Mesh spec: mesh=dict(shape="box" | "shard" | "quad", vert=GLSL vertex main, frag=GLSL fragment main,
                     count=instances (int, or a function of the effect -> int), blend="solid" | "add")
The vertex shader sees every uniform an effect does (HEAD) plus in_pos / in_nrm (the shape's corner and normal,
the shape fits in -0.5..0.5) and gl_InstanceID. It writes v_p (world position), v_n (world normal), v_c (colour,
a = how much it glows by itself), v_e (camera position), v_x (anything else) and v_uv. y is up in world space;
the picture sits on the z = 0 plane, aspect wide and 1 high, facing +z.
"""
import numpy as np

from effects import PALETTES

CAMERAS = ["Swing", "Orbit", "Still", "Handheld", "Dive"]
BACKGROUNDS = ["Black", "Dark picture", "Blurred picture", "Picture", "Picture without you"]
DETAIL = ["Low", "Medium", "High", "Ultra"]
FRACTALS = ["Sponge tunnels", "Menger cube", "Mandelbox", "Mandelbulb", "Octahedral sponge", "Kaleido star",
            "Apollonian lace", "Crystal lattice"]
SRC = PALETTES.index("Source colour")

# ---------------------------------------------------------------- geometry (corner xyz, normal xyz) per vertex


def _faces(tris):
    """Flat-shaded triangles -> (n*3, 6) float32 rows of position + face normal."""
    out = []
    for a, b, c in tris:
        a, b, c = map(np.asarray, (a, b, c))
        n = np.cross(b - a, c - a)
        n = n / (np.linalg.norm(n) + 1e-9)
        for v in (a, b, c):
            out.append([*v, *n])
    return np.array(out, np.float32)


def geometry(shape):
    if shape == "box":
        tris = []
        for axis in range(3):
            for sign in (-1, 1):
                q = []
                for u, v in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                    p = [0.0, 0.0, 0.0]
                    p[axis] = 0.5 * sign
                    p[(axis + 1) % 3] = 0.5 * u * sign
                    p[(axis + 2) % 3] = 0.5 * v
                    q.append(p)
                tris += [(q[0], q[1], q[2]), (q[0], q[2], q[3])]
        return _faces(tris)
    if shape == "shard":   # a long, thin octahedron: a crystal splinter
        tip, tail = (0, 0, 0.5), (0, 0, -0.5)
        ring = [(0.22, 0, 0.05), (0, 0.12, 0.05), (-0.22, 0, 0.05), (0, -0.12, 0.05)]
        tris = []
        for i in range(4):
            a, b = ring[i], ring[(i + 1) % 4]
            tris += [(a, b, tip), (b, a, tail)]
        return _faces(tris)
    if shape == "prism":   # a triangular slab; rows: (corner 0-2, 0, side +-0.5, face kind, edge, 0) - the
        rows = []          # shader builds the real corners (kind 0 front, 1 back, 2 the edge strip after corner `edge`)
        rows += [[k, 0, .5, 0, 0, 0] for k in (0, 1, 2)]
        rows += [[k, 0, -.5, 1, 0, 0] for k in (0, 2, 1)]
        for e in range(3):
            quad = [(e, .5), ((e + 1) % 3, .5), ((e + 1) % 3, -.5), (e, -.5)]
            rows += [[quad[i][0], 0, quad[i][1], 2, e, 0] for i in (0, 1, 2, 0, 2, 3)]
        return np.array(rows, np.float32)
    if shape == "quad":
        a, b, c, d = (-0.5, -0.5, 0), (0.5, -0.5, 0), (0.5, 0.5, 0), (-0.5, 0.5, 0)
        return _faces([(a, b, c), (a, c, d)])
    raise ValueError(shape)


# ---------------------------------------------------------------- GLSL shared by mesh and raymarched effects

GL3D = """
const float PI = 3.14159265;
mat3 rx(float a){ float c = cos(a), s = sin(a); return mat3(1.,0.,0., 0.,c,s, 0.,-s,c); }
mat3 ry(float a){ float c = cos(a), s = sin(a); return mat3(c,0.,-s, 0.,1.,0., s,0.,c); }
mat3 rz(float a){ float c = cos(a), s = sin(a); return mat3(c,s,0., -s,c,0., 0.,0.,1.); }
mat3 rAxis(vec3 k, float a){ k = normalize(k); float c = cos(a), s = sin(a), t = 1. - c;
  return mat3(t*k.x*k.x + c, t*k.x*k.y + s*k.z, t*k.x*k.z - s*k.y,
              t*k.x*k.y - s*k.z, t*k.y*k.y + c, t*k.y*k.z + s*k.x,
              t*k.x*k.z + s*k.y, t*k.y*k.z - s*k.x, t*k.z*k.z + c); }
float asp3(){ return u_res.x/u_res.y; }
float h1(float n){ return fract(sin(n*12.9898 + 4.1414)*43758.5453); }
vec3 h3(float n){ return vec3(h1(n), h1(n + 17.17), h1(n + 41.31)); }
// where the camera is: mode = CAMERAS index, tilt / zoom 0..1, dist = the effect's natural distance.
// The kick nudges it in a little (scaled by Amount), so the whole world punches with the music.
vec3 camEye(int mode, float tilt, float zoom, float dist){
  float t = u_time;
  float yaw = mode == 0 ? sin(t*.25)*.75 : mode == 1 ? t*.3 : mode == 3 ? sin(t*.31)*.18 + sin(t*.83)*.05 : 0.;
  float pitch = mix(-.15, 1.25, tilt);
  if (mode == 3) pitch += sin(t*.47)*.06 + sin(t*1.13)*.02;
  if (mode == 4) pitch = mix(.05, 1.3, .5 + .5*sin(t*.2));
  float d = dist*mix(1.7, .5, zoom)*(1. - u_hits.x*.05*clamp(u_amt, 0., 1.5));
  return d*vec3(sin(yaw)*cos(pitch), sin(pitch), cos(yaw)*cos(pitch));
}
mat4 persp3(float fovy, float aspect, float n, float f){ float k = 1./tan(fovy*.5);
  return mat4(k/aspect,0.,0.,0., 0.,k,0.,0., 0.,0.,(f + n)/(n - f),-1., 0.,0.,2.*f*n/(n - f),0.); }
mat4 lookAt3(vec3 eye, vec3 at, vec3 up){ vec3 z = normalize(eye - at), x = normalize(cross(up, z)), y = cross(z, x);
  return mat4(x.x,y.x,z.x,0., x.y,y.y,z.y,0., x.z,y.z,z.z,0., -dot(x,eye),-dot(y,eye),-dot(z,eye),1.); }
// Scale / Rotate / Centre: the finished 3D picture is placed on screen (the background stays put).
// Screen coords here run -1..1 with y down, like the picture. dir 1: scene -> screen, -1: back again.
uniform vec2 u_xf;   // scale, angle (radians)
vec2 xfLin3(vec2 q, float dir){
  float a = u_xf.y*dir, c = cos(a), s = sin(a), k = max(u_xf.x, 1e-3);
  q = mat2(c, s, -s, c)*(q*vec2(asp3(), 1.));
  q = dir > 0. ? q*k : q/k;
  return q/vec2(asp3(), 1.);
}
// world point -> clip space, looking from eye at `at` (y flipped: picture rows run top to bottom)
vec4 project3(vec3 p, vec3 eye, vec3 at){
  vec4 c = persp3(.85, asp3(), .03, 120.)*lookAt3(eye, at, vec3(0., 1., 0.))*vec4(p, 1.);
  c.y = -c.y;
  c.xy = xfLin3(c.xy, 1.) + (u_centre*2. - 1.)*c.w;
  return c;
}
// a picture point (uv, top-left origin) on the z = 0 plane
vec3 picPlane(vec2 uv){ return vec3((uv.x - .5)*asp3(), .5 - uv.y, 0.); }
// lit colour: key light, soft fill, specular and a rim, metal 0..1
vec3 light3(vec3 base, vec3 n, vec3 p, vec3 eye, float metal){
  vec3 L = normalize(vec3(.45, .8, .55)), V = normalize(eye - p), H = normalize(L + V);
  float dif = max(dot(n, L), 0.), amb = .28 + .12*n.y;
  float spec = pow(max(dot(n, H), 0.), mix(24., 90., metal));
  float rim = pow(1. - max(dot(n, V), 0.), 3.);
  return base*(amb + dif*.85)*(1. - metal*.4) + (spec*mix(.3, 1.2, metal) + rim*.3)*mix(vec3(1.), base + .2, metal);
}
"""

# vertex-shader outputs and the matching fragment-shader inputs
VARY_OUT = """
out vec3 v_p, v_n; out vec4 v_c, v_x; flat out vec3 v_e;
"""
VARY_IN = """
in vec3 v_p, v_n; in vec4 v_c, v_x; flat in vec3 v_e;
"""
HIDE = "gl_Position = vec4(2., 2., 2., 1.); v_uv = vec2(0.); v_p = v_n = v_e = vec3(0.); v_c = v_x = vec4(0.); return;"

# a lit, solid surface that fades into the distance (premultiplied: far things show the background through)
SOLID_FRAG = """
uniform float u_fog;
void main(){
  vec3 n = normalize(v_n);
  if (dot(n, v_e - v_p) < 0.) n = -n;   // the inside of an open shape still lights
  vec3 col = light3(v_c.rgb, n, v_p, v_e, v_x.w) + v_c.rgb*v_c.a;
  float k = exp(-pow(max(length(v_p - v_e) - 1.2, 0.)*u_fog, 2.));
  o = vec4(col*k, k);
}"""
# light by itself, added on (streaks, sparks): no depth sorting needed
GLOW_FRAG = """
uniform float u_fog;
void main(){
  float k = exp(-pow(max(length(v_p - v_e) - 1.2, 0.)*u_fog, 2.));
  o = vec4(v_c.rgb*v_c.a*k, 0.);
}"""

# the effect's own pass: background, then the 3D scene over it, with glow from the scene's blurred copies
COMPOSE = """
uniform sampler2D u_scene;
vec3 blurPic(vec2 uv){ vec3 s = vec3(0.);
  for (int i = 0; i < 12; i++){ float a = float(i)*2.3998, r = sqrt(float(i) + .5)*.012;
    s += tx(uv + vec2(cos(a)/asp3(), sin(a))*r).rgb; }
  return s/12.; }
vec3 bg3d(int m, vec2 uv){
  if (m == 0) return vec3(0.);
  vec3 pic = tx(uv).rgb;
  if (m == 1) return pic*.22;
  if (m == 2) return blurPic(uv)*.55;
  if (m == 3) return pic;
  if (u_plate_on > .5) return texture(u_plate, uv).rgb;
  return mix(pic, blurPic(uv)*.4, smoothstep(.3, .7, maskAt(uv)));
}
vec4 scene3d(vec2 uv, float glow){
  vec4 s = texture(u_scene, uv);
  vec3 bloom = textureLod(u_scene, uv, 2.5).rgb*.35 + textureLod(u_scene, uv, 4.5).rgb*.45 + textureLod(u_scene, uv, 6.).rgb*.4;
  return vec4(s.rgb + bloom*glow, s.a);
}
vec3 over3d(int bgMode, float glow){
  vec4 s = scene3d(v_uv, glow);
  return bg3d(bgMode, v_uv)*(1. - clamp(s.a, 0., 1.)) + s.rgb;
}
"""

RAY3D = """
// a camera ray for pixel v_uv from eye toward at (fov in radians)
vec3 rayDir(vec3 eye, vec3 at, float fov){
  vec2 su = xfLin3(v_uv*2. - 1. - (u_centre*2. - 1.), -1.)*.5 + .5;   // undo Scale / Rotate / Centre
  vec2 q = (su - .5)*vec2(asp3(), -1.);
  vec3 z = normalize(at - eye), x = normalize(cross(z, vec3(0., 1., 0.))), y = cross(x, z);
  return normalize(z + (q.x*x + q.y*y)*2.*tan(fov*.5));
}
// the picture as a surrounding world: any direction -> a colour (reflections, skies)
vec3 envPic(vec3 d){
  vec2 uv = vec2(.5 + atan(d.x, -d.z)/(2.*PI), .5 - asin(clamp(d.y, -1., 1.))/PI);
  return tx(uv).rgb;
}
"""


def _mesh(shape, vert, frag=SOLID_FRAG, count=0, blend="solid"):
    return dict(shape=shape, vert=VARY_OUT + GL3D + vert, frag=GL3D + VARY_IN + frag, count=count, blend=blend)


def _detail_count(opt, table):
    return lambda f: table[min(f.opts[opt], len(table) - 1)]


# pins / voxels: rows of the grid per Detail (columns follow the aspect ratio)
GRID_ROWS = "int rowsFor(int d){ return d == 0 ? 40 : d == 1 ? 64 : d == 2 ? 96 : 140; }"
GRID_MAX = [40 * 72, 64 * 114, 96 * 171, 140 * 249]   # enough for 16:9 at each detail (taller frames use fewer)

EFFECTS_3D = [
    # Pin Field 3D: the picture as a bed of rods pushed out toward you, lit, seen by a moving camera.
    dict(id="pins3d", name="Pin Field 3D", amt=.6, amt_label="Push", speed=True,
         params=[("Tilt", .3), ("Zoom", .62), ("Pin size", .6), ("Glow", .35)],
         options=[("Pushed by", ["Brightness", "Darkness", "You (AI mask)", "Music", "Ripples"], 0),
                  ("Colour", PALETTES, SRC),
                  ("Background", BACKGROUNDS, 0),
                  ("Camera", CAMERAS, 0),
                  ("Detail", DETAIL, 1)],
         mask_when=(0, (2,)),
         mesh=_mesh("box", GRID_ROWS + """
uniform float u_fog;
void main(){
  int gh = rowsFor(u_opt4), gw = int(float(gh)*asp3() + .5);
  if (gl_InstanceID >= gw*gh) { """ + HIDE + """ }
  ivec2 ij = ivec2(gl_InstanceID % gw, gl_InstanceID / gw);
  vec2 uv = (vec2(ij) + .5)/vec2(gw, gh);
  vec3 src = tx(uv).rgb;
  float l = lum(src), r = hash(vec2(ij));
  float h = u_opt0 == 0 ? l : u_opt0 == 1 ? 1. - l : u_opt0 == 2 ? maskAt(uv)
          : u_opt0 == 3 ? spectrum(abs(uv.x - .5)*1.8)*(1. - abs(uv.y - .5))
          : .5 + .5*sin(length((uv - .5)*vec2(asp3(), 1.))*16. - u_time*3.);
  h = h*u_amt*.8 + (u_hits.x*.08 + u_hits.y*.04)*r*u_amt;
  float cell = 1./float(gh), thick = cell*mix(.25, 1.05, u_p2);
  vec3 lp = in_pos;
  vec3 p = picPlane(uv) + vec3(lp.xy*thick, (lp.z + .5)*max(h, .004));
  vec3 col = u_opt1 == """ + str(SRC) + """ ? src : palCycle(u_opt1, h*1.6 + l*.3 + u_time*.03, src)*(.35 + .65*l);
  col *= mix(.25, 1.1, lp.z + .5);   // dark at the root, bright at the tip
  vec3 eye = camEye(u_opt3, u_p0, u_p1, 1.9);
  v_p = p; v_n = in_nrm; v_e = eye; v_uv = uv;
  v_c = vec4(col, h*1.5*u_p3); v_x = vec4(0., 0., 0., .3);
  gl_Position = project3(p, eye, vec3(0.));
}""", count=_detail_count(4, GRID_MAX)),
         code="""
void main(){ o = vec4(over3d(u_opt2, u_p3*1.6), 1.); }"""),

    # Shard Storm: the picture as a pane of glass. At rest it IS the picture; the hits crack it, then blow the
    # pieces out of it (shatter, vortex, warp stream or swarm), and they settle back in as the hit fades.
    dict(id="shards3d", name="Shard Storm", amt=.12, amt_label="Scatter", speed=True,
         params=[("Tilt", .25), ("Zoom", .5), ("Burst", .7), ("Spin", .5), ("Glow", .45)],
         options=[("Motion", ["Shatter", "Vortex", "Warp stream", "Swarm"], 0),
                  ("Breaks on", ["Kick", "Snare / clap", "Big kicks", "Any hit", "Never"], 0),
                  ("Colour", PALETTES, SRC),
                  ("Background", BACKGROUNDS, 0),
                  ("Camera", CAMERAS, 0),
                  ("Cracks", ["Impact (from the middle)", "Broken glass"], 0),
                  ("Detail", DETAIL, 1)],
         mesh=_mesh("prism", """
uniform float u_fog;
int shRows(){ return u_opt6 == 0 ? 10 : u_opt6 == 1 ? 16 : u_opt6 == 2 ? 26 : 40; }
// a corner of the crack pattern, in picture uv (corners are shared, so the pieces fit together exactly)
vec2 crackPt(int i, int j, int gw, int gh){
  if (u_opt5 == 0) {   // impact: spokes and rings round the middle
    int ii = i % gw;
    float R = .5*sqrt(asp3()*asp3() + 1.) + .02;
    float a = (float(ii) + (j > 0 ? (hash(vec2(ii, j)) - .5)*.7 : 0.))/float(gw)*2.*PI;
    float rj = float(j)/float(gh) + (j > 0 && j < gh ? (hash(vec2(ii + 91, j)) - .5)*.6/float(gh) : 0.);
    float r = pow(clamp(rj, 0., 1.), 1.4)*R;
    return vec2(cos(a)*r/asp3(), sin(a)*r) + .5;
  }
  vec2 g = vec2(i, j), jit = vec2(hash(g) - .5, hash(g + 37.) - .5)*.8;
  if (i == 0 || i == gw) jit.x = 0.;
  if (j == 0 || j == gh) jit.y = 0.;
  return (g + jit)/vec2(gw, gh);
}
float shHit(){ return u_opt1 == 0 ? u_hits.x : u_opt1 == 1 ? u_hits.y : u_opt1 == 2 ? u_hits.w
                    : u_opt1 == 3 ? max(max(u_hits.x, u_hits.y), u_hits.w) : 0.; }
void main(){
  int gh = shRows(), gw = u_opt5 == 0 ? int(float(gh)*2.25) : int(float(gh)*asp3() + .5);
  if (gl_InstanceID >= gw*gh*2) { """ + HIDE + """ }
  int cell = gl_InstanceID/2, hf = gl_InstanceID % 2, ci = cell % gw, cj = cell/gw;
  vec2 P00 = crackPt(ci, cj, gw, gh), P10 = crackPt(ci + 1, cj, gw, gh),
       P01 = crackPt(ci, cj + 1, gw, gh), P11 = crackPt(ci + 1, cj + 1, gw, gh);
  vec2 A, B, C;
  if (hash(vec2(ci, cj) + 7.3) > .5) { A = P00; if (hf == 0) { B = P10; C = P11; } else { B = P11; C = P01; } }
  else if (hf == 0) { A = P00; B = P10; C = P01; } else { A = P10; B = P11; C = P01; }
  if (any(lessThan(max(max(A, B), C), vec2(0.))) || any(greaterThan(min(min(A, B), C), vec2(1.)))) { """ + HIDE + """ }
  int k = int(in_pos.x + .5);
  vec2 uvk = k == 0 ? A : k == 1 ? B : C, cu = (A + B + C)/3.;
  float id = float(gl_InstanceID);
  vec3 r = h3(id*1.618 + 3.), home = picPlane(cu);
  vec2 fromMid = (cu - .5)*vec2(asp3(), 1.);
  float hit = shHit()*u_p2;
  // how broken this piece is: Scatter, plus the hit (pieces near the middle go first)
  float b = clamp(u_amt, 0., 1.5) + hit*hit*(1.25 - length(fromMid)*.5)*(.6 + .4*r.x);
  float mv = smoothstep(.05, 1., b);     // below ~.05 it only cracks
  float t = u_time;
  vec3 dir = normalize(vec3(fromMid*1.3 + (r.xy - .5)*.5, .3 + r.z*.5));
  vec3 p;
  if (u_opt0 == 0) p = home + dir*(mv*.75 + mv*mv*.7)*(.5 + r.z) - vec3(0., mv*mv*.25*r.y, 0.);
  else {
    vec3 goal;
    if (u_opt0 == 1) {          // vortex: swept round a column
      float ang = r.x*2.*PI + t*(.25 + .6*r.z);
      float rad = .25 + r.z*1.2;
      goal = vec3(cos(ang)*rad, home.y*1.3 + sin(t*.7 + id)*.05, sin(ang)*rad);
    } else if (u_opt0 == 2) {   // warp stream: rushing past toward you
      float z = fract(r.z + t*(.12 + .3*b));
      goal = vec3(home.xy*(1. + z*3.), mix(-6., 2.2, z*z));
    } else {                    // swarm: drifting on slow curls
      vec3 q = home*1.3 + r*6.;
      goal = home + vec3(sin(q.y*1.7 + t*.5) + sin(q.z*2.3 - t*.3), sin(q.z*1.9 + t*.4) + sin(q.x*1.3),
                         sin(q.x*2.1 - t*.45) + sin(q.y*1.1 + t*.2))*.42;
    }
    p = mix(home, goal, mv);
  }
  float ang = mv*(1.5 + 4.*r.x)*mix(.2, 2., u_p3) + (u_opt0 != 0 ? t*(.3 + r.y)*u_p3*mv : 0.);
  mat3 R = rAxis(h3(id + 3.3) - .5, ang);
  float shrink = 1. - smoothstep(.02, .4, b)*.1, thick = .006 + mv*.02;
  vec3 lp = (picPlane(uvk) - home)*shrink + vec3(0., 0., in_pos.z*thick);
  vec3 n = vec3(0., 0., 1.);
  int kind = int(in_nrm.x + .5);
  if (kind == 1) n = -n;
  else if (kind == 2) {
    int e = int(in_nrm.y + .5);
    vec3 E0 = picPlane(e == 0 ? A : e == 1 ? B : C), E1 = picPlane(e == 0 ? B : e == 1 ? C : A);
    n = normalize(cross(E1 - E0, vec3(0., 0., 1.)));
    if (dot(n, (E0 + E1)*.5 - home) < 0.) n = -n;
  }
  vec3 wp = p + R*lp;
  // at rest the camera frames the picture exactly; with Scatter up it moves as chosen
  vec3 eye = mix(vec3(0., 0., .5/tan(.425)), camEye(u_opt4, u_p0, u_p1, 2.1), smoothstep(0., .9, clamp(u_amt, 0., 1.)));
  v_p = wp; v_n = R*n; v_e = eye; v_uv = uvk;
  v_c = vec4(b, mv, 0., 0.); v_x = vec4(k == 0 ? 1. : 0., k == 1 ? 1. : 0., k == 2 ? 1. : 0., float(kind));
  gl_Position = project3(wp, eye, vec3(0.));
}""", frag="""
uniform float u_fog;
void main(){
  vec2 uv = v_uv;
  if (uv.x < 0. || uv.x > 1. || uv.y < 0. || uv.y > 1.) discard;   // pieces are cut off at the frame
  float kind = v_x.w, b = v_c.x, mv = v_c.y;
  vec3 src = tx(uv).rgb;
  vec3 col = u_opt2 == """ + str(SRC) + """ ? src : palCycle(u_opt2, lum(src)*.8 + uv.x*.2 + u_time*.04, src)*(.35 + .8*lum(src));
  vec3 n = normalize(v_n);
  if (dot(n, v_e - v_p) < 0.) n = -n;
  if (kind < .5) {
    col = mix(col, light3(col, n, v_p, v_e, .6)*.75 + col*.3, smoothstep(0., .3, mv));
    float e = min(v_x.x, min(v_x.y, v_x.z));            // cracks: light along the piece's edges as it breaks
    float line = 1. - smoothstep(0., fwidth(e)*1.6, e);
    float crack = smoothstep(0., .06, b)*(1. - smoothstep(.3, .8, mv));
    col += line*crack*(vec3(.9, .95, 1.)*.45 + col*.4)*(.3 + u_p4);
  } else if (kind < 1.5) col = light3(col*.3, n, v_p, v_e, .3);
  else col = light3(vec3(.55, .7, .72), n, v_p, v_e, .9)*.8 + col*.2;   // the glass edge
  float k = exp(-pow(max(length(v_p - v_e) - 1.2, 0.)*u_fog, 2.));
  o = vec4(col*k, k);
}""", count=_detail_count(6, [480, 1216, 3224, 7680])),
         code="""
void main(){
  float hit = u_opt1 == 0 ? u_hits.x : u_opt1 == 1 ? u_hits.y : u_opt1 == 2 ? u_hits.w
            : u_opt1 == 3 ? max(max(u_hits.x, u_hits.y), u_hits.w) : 0.;
  float b = clamp(u_amt, 0., 1.5) + hit*hit*u_p2;   // no glow while the picture is whole
  o = vec4(over3d(u_opt3, u_p4*1.8*smoothstep(.03, .4, b)), 1.);
}"""),

    # Voxel You: you, rebuilt from cubes (AI mask), standing out in relief and bursting apart on the hits.
    dict(id="voxels3d", name="Voxel You", amt=.5, amt_label="Depth", speed=True, mask=True,
         params=[("Tilt", .15), ("Zoom", .5), ("Burst", .5), ("Cube size", .85), ("Glow", .25)],
         options=[("Bursts on", ["Kick", "Snare / clap", "Big kicks", "Any hit", "Never"], 0),
                  ("Colour", PALETTES, SRC),
                  ("Background", BACKGROUNDS, 4),
                  ("Camera", CAMERAS, 0),
                  ("Detail", DETAIL, 1)],
         mesh=_mesh("box", GRID_ROWS + """
uniform float u_fog;
void main(){
  int gh = rowsFor(u_opt4), gw = int(float(gh)*asp3() + .5);
  if (gl_InstanceID >= gw*gh) { """ + HIDE + """ }
  ivec2 ij = ivec2(gl_InstanceID % gw, gl_InstanceID / gw);
  vec2 uv = (vec2(ij) + .5)/vec2(gw, gh);
  float m = maskAt(uv);
  if (m < .5) { """ + HIDE + """ }
  vec3 src = tx(uv).rgb;
  float l = lum(src), cell = 1./float(gh);
  float hit = u_opt0 == 0 ? u_hits.x : u_opt0 == 1 ? u_hits.y : u_opt0 == 2 ? u_hits.w
            : u_opt0 == 3 ? max(max(u_hits.x, u_hits.y), u_hits.w) : 0.;
  vec3 r = h3(float(gl_InstanceID));
  vec3 dir = normalize(r - .5 + vec3(0., 0., .8));
  float burst = hit*hit*u_p2*(.3 + r.z*.7);
  vec3 p = picPlane(uv) + vec3(0., 0., l*u_amt*.35) + dir*burst*.6;
  float s = cell*mix(.4, 1.02, u_p3)*(1. - burst*.5);
  mat3 R = rAxis(r - .5, burst*6.);
  vec3 col = u_opt1 == """ + str(SRC) + """ ? src : palCycle(u_opt1, l*.8 + u_time*.05, src)*(.4 + .7*l);
  vec3 eye = camEye(u_opt3, u_p0, u_p1, 1.8);
  vec3 wp = p + R*(in_pos*s);
  v_p = wp; v_n = R*in_nrm; v_e = eye; v_uv = uv;
  v_c = vec4(col, u_p4*(.2 + burst*2.)); v_x = vec4(0., 0., 0., .25);
  gl_Position = project3(wp, eye, vec3(0.));
}""", count=_detail_count(4, GRID_MAX)),
         code="""
void main(){ o = vec4(over3d(u_opt2, u_p4*1.5), 1.); }"""),

    # Flip Wall: the picture as a wall of tiles that flip over in waves on the beat.
    dict(id="flipwall3d", name="Flip Wall", amt=.5, amt_label="Depth", speed=True,
         params=[("Tilt", .1), ("Zoom", .55), ("Gaps", .3), ("Glow", .2)],
         options=[("Flip every", ["Beat", "2 beats", "Bar"], 0),
                  ("Pattern", ["Sweep", "Ripple", "Random", "Checker"], 1),
                  ("Back shows", ["The picture, mirrored", "Colour", "Source 2"], 1),
                  ("Colour", PALETTES, 5),
                  ("Background", BACKGROUNDS, 0),
                  ("Camera", CAMERAS, 2)],
         mesh=_mesh("box", """
uniform float u_fog;
void main(){
  int gh = 9, gw = int(float(gh)*asp3() + .5);
  if (gl_InstanceID >= gw*gh) { """ + HIDE + """ }
  ivec2 ij = ivec2(gl_InstanceID % gw, gl_InstanceID / gw);
  vec2 cell = 1./vec2(gw, gh), c = (vec2(ij) + .5)*cell;
  float every = u_opt0 == 0 ? 1. : u_opt0 == 1 ? 2. : 4.;
  float B = (u_beats + clamp(u_since/max(u_beatlen, .05), 0., 1.))/every;
  vec2 q = (c - .5)*vec2(asp3(), 1.);
  float d = u_opt1 == 0 ? c.x : u_opt1 == 1 ? length(q)*.9 : u_opt1 == 2 ? hash(vec2(ij)) : float((ij.x + ij.y) % 2)*.5;
  float x = B - d*.6;
  float flips = floor(x) + smoothstep(0., .45, fract(x));
  float ang = PI*flips;
  float lift = sin(PI*smoothstep(0., .45, fract(x)))*u_amt*.25;
  vec3 lp = in_pos*vec3(asp3()*cell.x*(1. - u_p2*.3), cell.y*(1. - u_p2*.3), .03);
  mat3 R = ry(ang);
  vec3 wp = picPlane(c) + R*lp + vec3(0., 0., lift);
  vec3 eye = camEye(u_opt5, u_p0, u_p1, 1.7);
  v_uv = c + in_pos.xy*vec2(1., -1.)*cell;
  v_p = wp; v_n = R*in_nrm; v_e = eye;
  v_c = vec4(1.); v_x = vec4(in_nrm.z, 0., c);   // x: 1 front face, -1 back, 0 an edge
  gl_Position = project3(wp, eye, vec3(0.));
}""", frag="""
uniform float u_fog;
void main(){
  vec3 n = normalize(v_n);
  bool front = v_x.x > .5;
  vec2 uv = vec2(2.*v_x.z - v_uv.x, v_uv.y);   // the back: the tile's own part, mirrored as it turned over
  vec3 col;
  if (abs(v_x.x) < .5) col = vec3(.08);         // tile edges
  else if (front) col = tx(v_uv).rgb;
  else if (u_opt2 == 0) col = tx(uv).rgb;
  else if (u_opt2 == 1) col = palCycle(u_opt3, v_x.z*.6 + v_x.w*.4 + u_time*.05, tx(uv).rgb)*(.35 + .9*lum(tx(uv).rgb));
  else col = u_mlive.x > .5 ? media(0, uv).rgb : tx(uv).rgb*vec3(.3, .6, 1.);
  col = light3(col, n, v_p, v_e, .2)*.6 + col*.55;
  o = vec4(col, 1.);
}""", count=60 * 9),
         code="""
void main(){ o = vec4(over3d(u_opt4, u_p3*1.5), 1.); }"""),

    # Spectrum City: the last few seconds of the music as a lit city of bars. Sound arrives at the front row and
    # rolls back; each band is levelled against its own recent peak so quiet music still fills the skyline,
    # and the kick sends a wave up the front rows.
    dict(id="city3d", name="Spectrum City", amt=.6, amt_label="Height", speed=True,
         params=[("Tilt", .45), ("Zoom", .4), ("Bar size", .75), ("Glow", .6), ("History", .5)],
         options=[("Layout", ["City grid", "Circle", "Mirror valley"], 0),
                  ("Colour", PALETTES, 5),
                  ("Background", BACKGROUNDS, 1),
                  ("Camera", CAMERAS, 0)],
         # history: band i, row k (k steps ago) in a 64 x 48 block grid; row 0 also keeps each band's peak (g)
         # and the step counter (b), so the rows roll back at a steady rate whatever the frame rate
         state=["""
void main(){
  float rows = 48.;
  float row = floor(v_uv.y*rows);
  float step = mod(floor(u_time*mix(40., 5., u_p4)), 256.);
  vec4 r0 = texture(u_s0, vec2(v_uv.x, .5/rows));
  bool shift = abs(step - r0.b) > .5;
  if (row < .5) {
    float raw = spectrum(v_uv.x);
    float peak = max(max(raw, r0.g*.996), .03);
    o = vec4(raw/peak, peak, step, 1.);
    return;
  }
  o = texture(u_s0, vec2(v_uv.x, (row + (shift ? -.5 : .5))/rows));
}"""], state_size=[(1, "f2")],
         mesh=_mesh("box", """
uniform float u_fog;
void main(){
  int nb = 64, nr = 48;
  int i = gl_InstanceID % nb, k = gl_InstanceID / nb;
  if (k >= nr) { """ + HIDE + """ }
  float x = (float(i) + .5)/float(nb), z = (float(k) + .5)/float(nr);
  float v = pow(clamp(texture(u_s0, vec2(x, z)).r, 0., 1.2), 1.6);   // quiet bands stay low, loud ones tower
  float wave = u_hits.x*exp(-z*6.)*.8 + u_hits.y*exp(-z*10.)*.4;     // the kick lifts the front rows
  float h = v*(1. + wave)*u_amt*1.05 + .006;
  vec3 base;
  float w = mix(.25, .95, u_p2);
  vec3 lp = in_pos;
  if (u_opt0 == 1) {          // circle: frequency round a ring, time running outward
    float a = x*2.*PI;
    float rad = .25 + z*1.6;
    base = vec3(cos(a)*rad, 0., sin(a)*rad);
    lp.xz *= vec2(2.*PI*rad/float(nb), 1.6/float(nr))*w;
  } else {
    base = vec3((x - .5)*2.6, 0., z*2.6 - 1.4);
    lp.xz *= vec2(2.6/float(nb), 2.6/float(nr))*w;
    if (u_opt0 == 2) h *= .4 + 1.4*abs(x - .5);   // a valley: the walls rise toward the sides
  }
  vec3 wp = base + vec3(lp.x, (lp.y + .5)*h, lp.z);
  vec3 col = palCycle(u_opt1, x*.8 + v*.4 + u_time*.03, vec3(v))*(.25 + 1.1*v);
  float up = lp.y + .5;
  col *= mix(.3, 1., up);
  col *= 1. - z*.55;   // older sound fades
  vec3 eye = camEye(u_opt3, u_p0, u_p1, 2.5) + vec3(0., .1, 0.);
  v_p = wp; v_n = in_nrm; v_e = eye; v_uv = vec2(x, z);
  // rooftops glow (brighter on the hits); the sides stay mostly lit, not glowing
  v_c = vec4(col, (v + wave*.6)*u_p3*.8*pow(up, 4.)); v_x = vec4(0., 0., 0., .4);
  gl_Position = project3(wp, eye, vec3(0., .15, 0.));
}""", count=64 * 48),
         code="""
void main(){ o = vec4(over3d(u_opt2, u_p3*1.8), 1.); }"""),

    # Warp Tunnel: streaks of light rushing at you down a tunnel (or open space), faster with the bass.
    dict(id="tunnel3d", name="Warp Tunnel", amt=.5, amt_label="Speed", speed=True,
         params=[("Streak length", .5), ("Width", .5), ("Glow", .6)],
         options=[("Shape", ["Tunnel", "Starfield", "Spiral", "Rings"], 0),
                  ("Colour", PALETTES, 5),
                  ("Background", BACKGROUNDS, 1),
                  ("Steer", ["Straight", "Sway", "Roll", "Corkscrew"], 1),
                  ("Detail", DETAIL, 1)],
         mesh=_mesh("box", """
uniform float u_fog;
void main(){
  int n = u_opt4 == 0 ? 2000 : u_opt4 == 1 ? 5000 : u_opt4 == 2 ? 10000 : 18000;
  if (gl_InstanceID >= n) { """ + HIDE + """ }
  float id = float(gl_InstanceID);
  vec3 r = h3(id);
  float t = u_time;
  // travel: Speed (amount) plus the bass pushing; z runs from far away to just behind the camera
  float travel = t*(.15 + u_amt*.9) + u_music.x*.05;
  float z01 = fract(r.z + travel*(.6 + r.x*.4));
  float z = mix(-28., 2.5, z01);
  float ang = r.x*2.*PI, rad;
  if (u_opt0 == 0) rad = mix(1.1, 1.5, r.y);
  else if (u_opt0 == 1) rad = .15 + r.y*3.;
  else if (u_opt0 == 2) { ang = r.x*2.*PI + z*.35; rad = 1.2 + sin(r.x*6.*PI)*.15; }
  else { ang = r.x*2.*PI; rad = 1.3; z = floor(z*1.5)/1.5; }
  rad *= 1. + u_hits.x*.12*u_amt;
  vec2 xy = vec2(cos(ang), sin(ang))*rad;
  float len = mix(.05, 1.4, u_p0)*(.4 + u_amt*1.4)*(u_opt0 == 3 ? .05 : 1.);
  float wid = mix(.004, .03, u_p1)*(u_opt0 == 3 ? 3. : 1.);
  vec3 lp = in_pos*vec3(wid, wid, len);
  if (u_opt0 == 3) lp = (rz(ang)*vec3(in_pos.x*.25, in_pos.y*wid*2., in_pos.z*wid*2.));
  vec3 wp = vec3(xy, z) + lp;
  // the camera, looking down the tunnel, steering a little
  float sway = u_opt3 == 1 ? sin(t*.4)*.35 : u_opt3 == 3 ? sin(t*.6)*.5 : 0.;
  vec3 eye = vec3(sway*.4, cos(t*.33)*.15*float(u_opt3 == 1 || u_opt3 == 3), 3.);
  float roll = u_opt3 == 2 ? t*.25 : u_opt3 == 3 ? t*.5 : 0.;
  wp = rz(roll)*wp;
  vec2 suv = clamp(xy/rad*.45 + .5, 0., 1.);
  vec3 src = tx(vec2(suv.x, 1. - suv.y)).rgb;
  vec3 col = u_opt1 == """ + str(SRC) + """ ? src*1.6 + .05 : palCycle(u_opt1, r.y*.6 + z01*.4 + t*.05, src);
  float fade = smoothstep(0., .25, z01)*smoothstep(1., .9, z01);
  v_p = wp; v_n = in_nrm; v_e = eye; v_uv = suv;
  v_c = vec4(col, (.45 + u_hits.x*.6)*fade*(u_opt0 == 3 ? .25 : 1.)); v_x = vec4(0.);   // rings are much bigger
  gl_Position = project3(wp, eye, vec3(sway, 0., -10.));
}""", frag=GLOW_FRAG, count=18000, blend="add"),
         code="""
void main(){ o = vec4(over3d(u_opt2, u_p2*1.1), 1.); }"""),

    # Picture Orb: the picture wrapped onto a sphere (or other shape) of glowing cubes; the music pushes them out.
    dict(id="orb3d", name="Picture Orb", amt=.5, amt_label="Spikes", speed=True,
         params=[("Tilt", .3), ("Zoom", .45), ("Cube size", .55), ("Glow", .5)],
         options=[("Shape", ["Sphere", "Torus", "Cube", "Helix"], 0),
                  ("Spikes follow", ["Spectrum", "Bass", "Kick", "Picture brightness"], 0),
                  ("Colour", PALETTES, SRC),
                  ("Background", BACKGROUNDS, 2),
                  ("Camera", CAMERAS, 1),
                  ("Detail", DETAIL, 1)],
         mesh=_mesh("box", """
uniform float u_fog;
void main(){
  int n = u_opt5 == 0 ? 1500 : u_opt5 == 1 ? 4000 : u_opt5 == 2 ? 9000 : 16000;
  if (gl_InstanceID >= n) { """ + HIDE + """ }
  float i = float(gl_InstanceID), N = float(n);
  // evenly spread points: a Fibonacci sphere, then bent into the chosen shape
  float y = 1. - (i + .5)/N*2., rr = sqrt(1. - y*y), ph = i*2.39996323;
  vec3 s = vec3(cos(ph)*rr, y, sin(ph)*rr);
  vec2 uv = vec2(fract(ph/(2.*PI)), acos(y)/PI);
  vec3 p, nrm;
  if (u_opt0 == 0) { p = s*.6; nrm = s; }
  else if (u_opt0 == 1) {
    float a = uv.x*2.*PI, b = uv.y*2.*PI;
    vec3 c = vec3(cos(a), 0., sin(a));
    p = c*.55 + (c*cos(b) + vec3(0., sin(b), 0.))*.22; nrm = normalize(p - c*.55);
  } else if (u_opt0 == 2) {
    vec3 a = abs(s); vec3 c = s/max(max(a.x, a.y), a.z);
    p = c*.45; nrm = a.x > a.y && a.x > a.z ? vec3(sign(s.x), 0., 0.) : a.y > a.z ? vec3(0., sign(s.y), 0.) : vec3(0., 0., sign(s.z));
  } else {
    float tt = i/N, a = tt*PI*14., strand = mod(i, 2.);
    vec3 c = vec3(cos(a + strand*PI)*.35, (tt - .5)*1.5, sin(a + strand*PI)*.35);
    p = c; nrm = normalize(vec3(c.x, 0., c.z));
  }
  vec3 src = tx(uv).rgb;
  float sp = u_opt1 == 0 ? spectrum(abs(y)) : u_opt1 == 1 ? u_bands.x : u_opt1 == 2 ? u_hits.x : lum(src);
  float spike = sp*u_amt*.5;
  float sz = mix(.008, .05, u_p2)*(.7 + 1.2*sqrt(1500./N));
  mat3 R = ry(u_time*.2)*rx(.3);
  vec3 lp = in_pos*vec3(sz, sz, sz + spike);
  // point the cube's long side along the surface normal
  vec3 zt = normalize(nrm), xt = normalize(cross(abs(zt.y) < .9 ? vec3(0., 1., 0.) : vec3(1., 0., 0.), zt)), yt = cross(zt, xt);
  mat3 B = mat3(xt, yt, zt);
  vec3 wp = R*(p + nrm*(spike*.5) + B*lp);
  vec3 col = u_opt2 == """ + str(SRC) + """ ? src*1.1 + .04 : palCycle(u_opt2, uv.y*.7 + sp*.4 + u_time*.04, src);
  vec3 eye = camEye(u_opt4, u_p0, u_p1, 2.);
  v_p = wp; v_n = R*(B*in_nrm); v_e = eye; v_uv = uv;
  v_c = vec4(col, u_p3*(.08 + sp*.7)); v_x = vec4(0., 0., 0., .3);
  gl_Position = project3(wp, eye, vec3(0.));
}""", count=16000),
         code="""
void main(){ o = vec4(over3d(u_opt3, u_p3*1.1), 1.); }"""),
]

# fog per effect (how quickly far things fade), set as u_fog
FOG = {"pins3d": .25, "shards3d": .22, "voxels3d": .2, "flipwall3d": 0., "city3d": .35, "tunnel3d": .1, "orb3d": .15}


# ---------------------------------------------------------------- raymarched worlds (per-pixel, no mesh)
# Each defines map3(p) (distance to the nearest surface), then RAY_TOOLS adds marching, normals and shading aids.

RAY_TOOLS = """
float rayMarch(vec3 ro, vec3 rd, float maxd, int maxSteps, out float steps){
  float t = 0.; steps = 0.;
  for (int i = 0; i < 200; i++){
    if (i >= maxSteps) break;
    steps = float(i);
    float d = map3(ro + rd*t);
    if (d < .0006 + .0008*t) return t;
    t += d*.85;
    if (t > maxd) break;
  }
  return -1.;
}
vec3 calcNormal(vec3 p, float t){
  vec2 e = vec2(.0012 + .0004*t, -.0012 - .0004*t);
  return normalize(e.xyy*map3(p + e.xyy) + e.yyx*map3(p + e.yyx) + e.yxy*map3(p + e.yxy) + e.xxx*map3(p + e.xxx));
}
float ao3(vec3 p, vec3 n){
  float o = 0., s = 1.;
  for (int i = 1; i <= 4; i++){ float h = .05*float(i); o += (h - map3(p + n*h))*s; s *= .6; }
  return clamp(1. - o*2.2, 0., 1.);
}
"""
SDF_TOOLS = """
float sdBox3(vec3 p, vec3 b){ vec3 d = abs(p) - b; return length(max(d, 0.)) + min(max(d.x, max(d.y, d.z)), 0.); }
float smin3(float a, float b, float k){ float h = clamp(.5 + .5*(b - a)/k, 0., 1.); return mix(b, a, h) - k*h*(1. - h); }
"""

RAY_EFFECTS = [
    # Picture Object: a solid shape covered in (or made of a window onto) the picture, chrome optional,
    # over a mirror or neon-grid floor. Size follows the music when set to Audio.
    dict(id="object3d", name="Picture Object", amt=.55, amt_label="Size", speed=True,
         params=[("Spin", .4), ("Roundness", .35), ("Glow", .35), ("Tilt", .25), ("Zoom", .5)],
         options=[("Shape", ["Cube", "Sphere", "Torus", "Octahedron (diamond)", "Twisted pillar", "Tetrahedron",
                             "Dodecahedron", "Icosahedron"], 0),
                  ("Surface", ["Picture wrapped round", "Window onto the picture", "Chrome", "Glass"], 0),
                  ("Floor", ["None", "Mirror", "Neon grid"], 1),
                  ("Background", BACKGROUNDS, 2),
                  ("Camera", CAMERAS, 0),
                  ("Colour", PALETTES, 5)],
         code=SDF_TOOLS + """
mat3 objR(){ float t = u_time*mix(0., 1.4, u_p0); return ry(t)*rx(t*.63)*rz(sin(t*.3)*.3); }
float objSize(){ return .42*(.55 + .7*clamp(u_amt, 0., 1.6)); }
float sdObj(vec3 q){
  float s = objSize(), r = u_p1*s*.6;
  if (u_opt0 == 0) return sdBox3(q, vec3(s - r)) - r;
  if (u_opt0 == 1) return length(q) - s*1.15;
  if (u_opt0 == 2) { vec2 d = vec2(length(q.xz) - s*1.05, q.y); return length(d) - s*.4; }
  if (u_opt0 == 3) return (abs(q.x) + abs(q.y) + abs(q.z) - s*1.55)*.57735 - r*.25;
  if (u_opt0 == 5) {   // tetrahedron
    float k = s*.62 - r*.3;
    return (max(max(-q.x - q.y - q.z, q.x + q.y - q.z), max(-q.x + q.y + q.z, q.x - q.y + q.z))*.57735 - k) - r*.3;
  }
  if (u_opt0 == 6 || u_opt0 == 7) {   // dodecahedron, icosahedron (golden-ratio face planes)
    const float PHI = 1.618034;
    vec3 a = abs(q);
    float k = s*1.02 - r*.35;
    vec3 n = normalize(vec3(0., PHI, 1.));
    float d = max(max(dot(a, n), dot(a, n.zxy)), dot(a, n.yzx));
    if (u_opt0 == 7) {
      vec3 m = normalize(vec3(0., 1., PHI + 1.));
      d = max(max(max(dot(a, m), dot(a, m.zxy)), dot(a, m.yzx)), dot(a, vec3(.57735)));
    }
    return d - k - r*.35;
  }
  float a = q.y*2.4; q.xz = mat2(cos(a), -sin(a), sin(a), cos(a))*q.xz;
  return (sdBox3(q, vec3(s*.42, s*1.35, s*.42) - r*.3) - r*.3)*.6;
}
float map3(vec3 p){ return sdObj(transpose(objR())*p); }
""" + RAY_TOOLS + """
float floorY(){ return -objSize()*1.55 - .1; }
vec3 surfCol(vec3 p, vec3 n){
  mat3 R = objR(); vec3 q = transpose(R)*p, qn = transpose(R)*n;
  float s = objSize()*1.2;
  if (u_opt1 == 0) {   // wrapped: the picture projected along each side (triplanar)
    vec3 w = pow(abs(qn), vec3(5.)); w /= dot(w, vec3(1.));
    vec2 k = vec2(.5/s, -.5/s);
    return tx(q.zy*k + .5).rgb*w.x + tx(q.xz*k + .5).rgb*w.y + tx(q.xy*k + .5).rgb*w.z;
  }
  if (u_opt1 == 1) return tx(v_uv + n.xy*vec2(.02, -.02)).rgb;   // a window: the picture as seen from here
  return vec3(.9);
}
vec3 shadeObj(vec3 p, vec3 rd, vec3 eye, float t){
  vec3 n = calcNormal(p, t);
  vec3 base = surfCol(p, n);
  float metal = u_opt1 == 2 ? 1. : .12;
  vec3 c = light3(base, n, p, eye, metal)*ao3(p, n);
  float fres = pow(1. - max(dot(n, -rd), 0.), 4.);
  if (u_opt1 == 2) c = envPic(reflect(rd, n))*.85 + c*.2;
  if (u_opt1 == 3) {   // glass: the picture behind bent through it, with a reflection at grazing angles
    vec3 rr = refract(rd, n, .7);
    c = mix(tx(v_uv + rr.xy*vec2(.12, -.12)).rgb*1.05, envPic(reflect(rd, n)), .15 + fres*.7);
  }
  return c + fres*.25*palCycle(u_opt5, .3 + u_time*.05, base);
}
void main(){
  vec3 eye = camEye(u_opt4, u_p3, u_p4, 2.6);
  vec3 rd = rayDir(eye, vec3(0.), .85);
  float steps, t = rayMarch(eye, rd, 14., 110, steps);
  float fy = floorY();
  float tf = (u_opt2 > 0 && rd.y < 0.) ? (fy - eye.y)/rd.y : -1.;
  vec3 col;
  if (t > 0. && (tf < 0. || t < tf)) col = shadeObj(eye + rd*t, rd, eye, t);
  else if (tf > 0.) {
    vec3 fp = eye + rd*tf;
    vec3 back = bg3d(u_opt3, v_uv);
    if (u_opt2 == 1) {   // mirror floor: what's above, reflected, darker with distance
      vec3 rr = reflect(rd, vec3(0., 1., 0.));
      float s2, t2 = rayMarch(fp + vec3(0., .002, 0.), rr, 8., 70, s2);
      vec3 refl = t2 > 0. ? shadeObj(fp + rr*t2, rr, fp, t2) : back*.5;
      col = mix(back*.35, refl*.75, .85);
    } else {             // neon grid
      vec2 g = abs(fract(fp.xz*2.) - .5);
      float line = smoothstep(.05, 0., min(g.x, g.y));
      col = back*.3 + palCycle(u_opt5, fp.x*.15 + u_time*.05, back)*line*(1. + u_hits.x);
    }
    col = mix(col, back, smoothstep(2., 9., tf));
  } else col = bg3d(u_opt3, v_uv);
  col += (steps/110.)*u_p2*.9*palCycle(u_opt5, u_time*.05, tx(vec2(.5)).rgb);   // a soft halo round the edges
  o = vec4(col, 1.);
}"""),

    # Liquid Metal: blobs of chrome (or gold, glass...) that merge and part, swelling with the bass and
    # rippling on the hits. Chrome reflects the picture.
    dict(id="metal3d", name="Liquid Metal", amt=.5, amt_label="Size", speed=True,
         params=[("Blend", .55), ("Ripple", .6), ("Glow", .3), ("Tilt", .2), ("Zoom", .5)],
         options=[("Material", ["Chrome", "Gold", "Picture skin", "Iridescent", "Glass"], 0),
                  ("Blobs", ["3", "5", "7"], 1),
                  ("Background", BACKGROUNDS, 2),
                  ("Camera", CAMERAS, 0)],
         code=SDF_TOOLS + """
float map3(vec3 p){
  float t = u_time*.55, k = mix(.06, .45, u_p0);
  int n = u_opt1 == 0 ? 3 : u_opt1 == 1 ? 5 : 7;
  float d = 1e9;
  for (int i = 0; i < 7; i++){
    if (i >= n) break;
    float fi = float(i);
    vec3 c = vec3(sin(t*(.5 + fi*.13) + fi*1.7), sin(t*(.37 + fi*.11) + fi*2.9)*.75,
                  sin(t*(.43 + fi*.07) + fi*4.1))*.42*(.55 + .6*clamp(u_amt, 0., 1.5));
    float r = (.2 + .07*sin(fi*3.1 + t*1.3))*(.8 + .5*clamp(u_amt, 0., 1.5)) + u_bands.x*.06;
    d = smin3(d, length(p - c) - r, k);
  }
  float rip = (u_hits.x + u_hits.y*.7)*u_p1;
  return d + sin(length(p)*26. - u_time*14.)*.01*rip;
}
""" + RAY_TOOLS + """
vec3 shadeMetal(vec3 p, vec3 rd, vec3 eye, float t){
  vec3 n = calcNormal(p, t), r = reflect(rd, n);
  float fres = pow(1. - max(dot(n, -rd), 0.), 3.);
  vec3 env = envPic(r);
  vec3 L = normalize(vec3(.45, .8, .55));
  float spec = pow(max(dot(r, L), 0.), 60.);
  vec3 c;
  if (u_opt0 == 0) c = env*.9 + spec;
  else if (u_opt0 == 1) c = env*vec3(1., .78, .4)*1.05 + spec*vec3(1., .9, .6);
  else if (u_opt0 == 2) c = light3(envPic(n), n, p, eye, .3);
  else if (u_opt0 == 3) c = env*.55 + (.5 + .5*cos(6.2831*(fres*1.3 + u_time*.05 + vec3(0., .33, .67))))*.7 + spec;
  else c = mix(tx(v_uv + refract(rd, n, .75).xy*vec2(.15, -.15)).rgb, env, .1 + fres*.8) + spec;
  return c*mix(.75, 1., ao3(p, n));
}
void main(){
  vec3 eye = camEye(u_opt3, u_p3, u_p4, 2.5);
  vec3 rd = rayDir(eye, vec3(0.), .85);
  float steps, t = rayMarch(eye, rd, 10., 100, steps);
  vec3 col = t > 0. ? shadeMetal(eye + rd*t, rd, eye, t) : bg3d(u_opt2, v_uv);
  col += (steps/100.)*u_p2*vec3(.6, .7, .9)*.8;
  o = vec4(col, 1.);
}"""),

    # Fractal Flight: sponges, boxes, bulbs and crystal forms, flown through, orbited or dived into. Infinite ones
    # (tunnels, lace, lattice) go on forever; the objects are flown through the middle or dived into an opening.
    # The camera steers itself off any wall. Morph is the music's hand on the shape; Variation reshapes it.
    dict(id="fractal3d", name="Fractal Flight", amt=.4, amt_label="Morph", speed=True,
         params=[("Glow", .55), ("Fog", .45), ("Picture on walls", .0), ("Zoom", .5), ("Travel", .45),
                 ("Variation", .0)],
         options=[("Fractal", FRACTALS, 0),
                  ("Colour", PALETTES, 5),
                  ("Camera", ["Fly through", "Orbit", "Drift", "Dive in"], 0),
                  ("Detail", DETAIL, 1)],
         code=SDF_TOOLS + """
float trap;
float fMorph(){ return clamp(u_amt, 0., 1.6); }
float fSponge(vec3 p){     // endless sponge tunnels; Variation turns each level against the last
  float m = fMorph();
  p = mod(p + 1., 2.) - 1.;
  float d = sdBox3(p, vec3(1.)), s = 1.;
  int it = 3 + u_opt3;
  mat2 tw = rot(u_p5*.5);
  for (int i = 0; i < 7; i++){
    if (i >= it) break;
    vec3 a = mod(p*s, 2.) - 1.;
    s *= 3.;
    vec3 r = abs(1. - 3.*abs(a));
    d = max(d, (min(max(r.x, r.y), min(max(r.y, r.z), max(r.z, r.x))) - 1. - m*.25)/s);
    trap = min(trap, length(a)*.7 + float(i)*.15);
    p.xy = tw*p.xy;
  }
  return d;
}
float fMenger(vec3 p){     // the Menger cube (folded form); Variation twists the folds into new shapes
  float m = fMorph(), s = 1.;
  mat2 ra = rot(u_p5*.6 + m*.05), rb = rot(u_p5*.35);
  int it = 4 + u_opt3;
  for (int i = 0; i < 8; i++){
    if (i >= it) break;
    p = abs(p);
    if (p.x < p.y) p.xy = p.yx;
    if (p.x < p.z) p.xz = p.zx;
    if (p.y < p.z) p.yz = p.zy;
    p = p*3. - vec3(2., 2., 0.)*(1. + m*.06);
    if (p.z > 1.) p.z -= 2.;
    p.xy = ra*p.xy; p.yz = rb*p.yz;
    s *= 3.;
    trap = min(trap, length(p)*.12 + float(i)*.12);
  }
  return sdBox3(p, vec3(1.))/s;
}
float fBox(vec3 p){        // Mandelbox
  vec3 z = p; float dr = 1., scale = -1.6 - u_p5 - .35*fMorph();
  int it = 8 + u_opt3*2;
  for (int i = 0; i < 16; i++){
    if (i >= it) break;
    z = clamp(z, -1., 1.)*2. - z;
    float r2 = dot(z, z);
    if (r2 < .25) { z *= 4.; dr *= 4.; } else if (r2 < 1.) { z /= r2; dr /= r2; }
    z = z*scale + p; dr = dr*abs(scale) + 1.;
    trap = min(trap, r2*.3);
  }
  return length(z)/abs(dr);
}
float fBulb(vec3 p){       // Mandelbulb: the 3D Mandelbrot
  float pw = 8. + (u_p5 - .25)*8. - fMorph()*1.5, dr = 1., r = length(p);
  vec3 z = p;
  int it = 5 + u_opt3;
  for (int i = 0; i < 9; i++){
    if (i >= it) break;
    r = length(z);
    if (r > 2.) break;
    float th = acos(clamp(z.y/max(r, 1e-6), -1., 1.))*pw + u_time*.05, ph = atan(z.z, z.x)*pw;
    dr = pow(r, pw - 1.)*pw*dr + 1.;
    z = pow(r, pw)*vec3(sin(th)*cos(ph), cos(th), sin(th)*sin(ph)) + p;
    trap = min(trap, length(z)*.35);
  }
  r = length(z);
  return .5*log(max(r, 1e-6))*r/dr;
}
float fOcta(vec3 p){       // octahedral sponge: a sponge built of knobbly balls (holes through every face)
  float s = 1., m = fMorph();
  mat3 Rv = rAxis(vec3(.3, 1., .5), u_p5*.5);
  vec3 p0 = p;
  int it = 4 + u_opt3;
  for (int i = 0; i < 8; i++){
    if (i >= it) break;
    p = abs(p);
    if (p.x < p.y) p.xy = p.yx;
    if (p.x < p.z) p.xz = p.zx;
    if (p.y < p.z) p.yz = p.zy;
    p = p*3. - vec3(2., 2., 0.);
    if (p.z > 1.) p.z -= 2.;
    p = Rv*p;
    s *= 3.;
    trap = min(trap, length(p)*.12 + float(i)*.12);
  }
  float d = max(length(p) - 1.22 - m*.1, (abs(p.x) + abs(p.y) + abs(p.z) - 1.75)*.577)/s;   // truncated balls
  return max(d, (abs(p0.x) + abs(p0.y) + abs(p0.z) - 2.05)*.577);   // cut to an octahedral cluster
}
float fStar(vec3 p){       // kaleidoscope star: a folded, turning tetrahedron (spiky, faceted)
  mat3 Rv = rAxis(vec3(1., .7, .4), .08 + u_p5*.35 + fMorph()*.04);
  float s = 1.;
  int it = 7 + u_opt3;
  for (int i = 0; i < 11; i++){
    if (i >= it) break;
    if (p.x + p.y < 0.) p.xy = -p.yx;
    if (p.x + p.z < 0.) p.xz = -p.zx;
    if (p.y + p.z < 0.) p.zy = -p.yz;
    p = Rv*p;
    p = p*2. - vec3(1.);
    s *= 2.;
    trap = min(trap, length(p)*.15 + float(i)*.07);
  }
  return (max(max(-p.x - p.y - p.z, p.x + p.y - p.z), max(-p.x + p.y + p.z, p.x - p.y + p.z)) - 1.)/(1.732*s);
}
float fApollo(vec3 p){     // Apollonian lace: endless bubbles inside bubbles
  p *= .5;
  float k1 = 1.15 + u_p5*.45 + fMorph()*.08, sc = 1.;
  int it = 6 + u_opt3;
  for (int i = 0; i < 10; i++){
    if (i >= it) break;
    p = -1. + 2.*fract(.5*p + .5);
    float r2 = max(dot(p, p), 1e-4), k = k1/r2;
    p *= k; sc *= k;
    trap = min(trap, r2*.8);
  }
  return .5*abs(p.y)/sc;
}
float fCrystal(vec3 p){    // crystal lattice
  float m = fMorph(), s = 1.;
  p = mod(p + 1.5, 3.) - 1.5;
  int it = 4 + u_opt3;
  for (int i = 0; i < 8; i++){
    if (i >= it) break;
    p = abs(p);
    if (p.x < p.y) p.xy = p.yx;
    if (p.x < p.z) p.xz = p.zx;
    if (p.y < p.z) p.yz = p.zy;
    p = p*1.85 - vec3(1., .8, .6)*(.9 + .25*m);
    p.xy = rot(.25 + .15*sin(u_time*.07) + u_p5*.4)*p.xy;
    s *= 1.85;
    trap = min(trap, length(p)*.4);
  }
  return sdBox3(p, vec3(.7))/s;
}
// Endless dive: the Menger sponge at every size at once, all sizes centred on the z axis, so the axis is a tunnel
// that is open at every size. The world grows 3x per cycle about a point down that tunnel: we sink toward it
// forever, the finest size fading in as the coarsest fades out, and a cycle ends exactly where the next begins.
bool fEndless(){ return u_opt2 == 3 && (u_opt0 == 0 || u_opt0 == 1 || u_opt0 == 4); }
float fDiveF(){ return fract(u_time*mix(.025, .2, u_p4)); }
float fEndlessSponge(vec3 p){
  float f = fDiveF(), m = fMorph(), A = u_p5*.6;
  int n = 7 + u_opt3;
  float d = -1e9, best = 0.;
  for (int j = 0; j < 12; j++){
    if (j > n) break;
    float s = pow(3., float(j) - 1. - f);           // coarsest cells 6 across: a tunnel 2 wide
    vec3 q = p;
    q.xy = rot(A*(float(j) - f))*q.xy;              // Variation: each size turned against the next (seamlessly)
    vec3 a = mod(q*s, 2.) - 1.;
    vec3 r = abs(1. - 3.*abs(a));
    float w = j == 0 ? 1. - f : j == n ? f : 1.;
    float c = (min(max(r.x, r.y), min(max(r.y, r.z), max(r.z, r.x))) - mix(2.2, 1. + m*.2, w))/(3.*s);
    if (c > d) { d = c; best = float(j); }
  }
  trap = (best - f)*.16;   // colour by size: drifts smoothly as you sink
  return d;
}
float map3(vec3 p){
  trap = 1e9;
  if (fEndless()) return fEndlessSponge(p);
  int f = u_opt0;
  if (f == 0) return fSponge(p);
  if (f == 1) return fMenger(p);
  if (f == 2) return fBox(p);
  if (f == 3) return fBulb(p);
  if (f == 4) return fOcta(p);
  if (f == 5) return fStar(p);
  if (f == 6) return fApollo(p);
  return fCrystal(p);
}
""" + RAY_TOOLS + """
bool fInfinite(){ return u_opt0 == 0 || u_opt0 >= 6 || fEndless(); }
float fSize(){ int f = u_opt0; return f == 1 ? 1.5 : f == 2 ? 4. : f == 3 ? 1.2 : f == 4 ? 2. : f == 5 ? 1.8 : 2.; }
// push the camera off any wall it would sit in
vec3 avoid3(vec3 e, float margin){
  for (int i = 0; i < 5; i++){
    float d = map3(e);
    if (d > margin) break;
    e += calcNormal(e, 0.)*(margin - d);
  }
  return e;
}
// a slow wandering direction round a shape
vec3 wander3(float t){
  return normalize(vec3(sin(t*.13) + .3*sin(t*.31), sin(t*.09)*.55 + .2*sin(t*.23), cos(t*.13) + .3*cos(t*.27)));
}
// what a ray that misses shows: a soft coloured haze, never a flat fill
vec3 nebula(vec3 rd, float t){
  float a = atan(rd.x, rd.z), b = rd.y;
  float n = sin(a*3. + t*.05) + sin(b*4. - a*2. + t*.07) + sin((a + b)*5. + t*.03)*.5;
  return palCycle(u_opt1, .5 + n*.12 + b*.2 + t*.02, tx(vec2(.5)).rgb)*(.07 + .05*n*n);
}
void main(){
  float t = u_time, tr = mix(.2, 2., u_p4), R = fSize();
  int cam = u_opt2;
  bool inf = fInfinite();
  vec3 eye, at;
  float margin = .02*R;
  if (fEndless()) {                       // sinking down the endless tunnel, looking round as we go
    eye = vec3(sin(t*.11)*.25, cos(t*.08)*.2, 2.4);
    at = vec3(sin(t*.07)*.9, cos(t*.05)*.7, 0.);
    margin = .03;
  } else if (cam == 1 || (cam == 2 && !inf)) {   // orbit (Zoom: how close)
    float d = R*mix(2.8, .45, u_p3)*(cam == 2 ? .8 + .3*sin(t*.07) : 1.);
    float ya = t*.12*tr, pi = cam == 2 ? sin(t*.09)*.7 : .35 + sin(t*.05)*.1;
    eye = d*vec3(sin(ya)*cos(pi), sin(pi), cos(ya)*cos(pi));
    at = vec3(0.);
  } else if (cam == 2) {                  // drift through the endless ones
    eye = vec3(sin(t*.11)*2.2, cos(t*.09)*1.4, t*.25*tr);
    at = eye + vec3(cos(t*.07), sin(t*.05)*.4, 1.);
  } else if (inf) {                       // endless flight down the tunnels (Dive: faster, closer)
    vec3 base = u_opt0 == 7 ? vec3(1.5, 1.5, 0.) : u_opt0 == 6 ? vec3(2., 2., 0.) : vec3(0.);
    eye = base + vec3(sin(t*.3)*.08, cos(t*.23)*.08, t*.45*tr*(cam == 3 ? 1.8 : 1.) + u_music.x*.1);
    at = eye + vec3(sin(t*.17)*.3, sin(t*.13)*.2, 1.);
  } else {   // shapes: always on or in the structure, drifting over it and sinking deep into it and back out
    float tw = t*tr*.5;
    vec3 dir = wander3(tw);
    float breathe = .5 - .5*cos(tw*.3);
    float deep = cam == 0 ? .75 : mix(.5, .1, u_p3);
    float rad = R*mix(1.12, deep, breathe);
    eye = dir*rad;
    at = mix(vec3(0.), wander3(tw + .5)*rad, .4);
    margin = R*mix(.03, .006, breathe);
    if (u_opt0 == 3) {   // the Mandelbulb is solid inside: find its surface and hover over it, sinking close
      float st, from = R*2.2, ts = rayMarch(dir*from, -dir, from, 80, st);
      float surf = ts > 0. ? from - ts : R*.8;
      float gap = R*mix(.35, cam == 0 ? .1 : mix(.06, .004, u_p3), breathe);
      eye = dir*(surf + gap);
      at = wander3(tw + .35)*surf*.9;
      margin = gap*.5;
    }
  }
  vec3 e0 = eye;
  eye = avoid3(eye, margin);
  at += eye - e0;
  vec3 rd = rayDir(eye, at, 1.1);
  int maxS = 70 + u_opt3*30;
  float steps, d = rayMarch(eye, rd, inf ? 30. : R*5., maxS, steps);
  vec3 fogC = nebula(rd, t);
  vec3 col = fogC;
  if (d > 0.) {
    vec3 p = eye + rd*d, n = calcNormal(p, d);
    map3(p);
    float tr2 = trap;
    vec3 base = palCycle(u_opt1, tr2*1.2 + t*.03, tx(fract(p.xy*.25)).rgb);
    if (u_p2 > 0.) {   // the picture on the walls (triplanar)
      vec3 w = pow(abs(n), vec3(4.)); w /= dot(w, vec3(1.));
      vec3 pic = tx(fract(p.zy*.3)).rgb*w.x + tx(fract(p.xz*.3)).rgb*w.y + tx(fract(p.xy*.3)).rgb*w.z;
      base = mix(base, pic*1.2, u_p2);
    }
    col = light3(base, n, p, eye, .25)*ao3(p, n);
    col += base*(u_hits.x*.35 + u_hits.y*.15);
    col = mix(fogC, col, exp(-d*d*mix(.002, .08, u_p1)/(R*R*.25)));
  }
  col += palCycle(u_opt1, .1 + steps/float(maxS)*.5 + t*.02, vec3(.5))*pow(steps/float(maxS), 2.)*u_p0*1.4;
  o = vec4(col, 1.);
}"""),


    # Infinite Halls: flying down an endless hall of arches (or a tunnel, pillars, or a visionary hall of nested
    # arches with you standing in glowing alcoves), with the picture on screens along the walls and waiting at the
    # far end; neon edges pulse with the music. Walls can be plain or covered in eye cells, squiggles or chrome hex.
    dict(id="halls3d", name="Infinite Halls", amt=.45, amt_label="Speed", speed=True,
         params=[("Neon", .6), ("Fog", .4), ("Screens", .8), ("Pattern size", .5)],
         options=[("Style", ["Arches", "Square tunnel", "Pillars", "Visionary hall"], 0),
                  ("Colour", PALETTES, 5),
                  ("Far end shows", BACKGROUNDS, 3),
                  ("Steer", ["Straight", "Sway", "Roll"], 1),
                  ("Walls", ["Style's own", "Plain", "Eye cells", "Squiggle maze", "Chrome hex"], 0)],
         mask_when=(0, (3,)),
         code=SDF_TOOLS + """
float archIn(vec3 p, float r0){ vec2 qa = vec2(p.x, p.y - .2); return qa.y < 0. ? abs(qa.x) - r0 : length(qa) - r0; }
float map3(vec3 p){
  float rep = 2.2;
  vec3 q = p; q.z = mod(q.z + rep*.5, rep) - rep*.5;
  float flo = p.y + 1.;
  float d;
  if (u_opt0 == 0) {          // arches: a frame every few metres, walls between
    float outer = sdBox3(q, vec3(1.9, 2.4, .18));
    d = max(outer, -archIn(p, 1.35));
    d = min(d, 1.75 - abs(p.x));   // side walls
  } else if (u_opt0 == 1) {   // square tunnel with ribs
    d = min(1.5 - abs(p.x), 1.6 - p.y);
    d = min(d, max(sdBox3(q, vec3(1.6, 1.8, .07)), -sdBox3(q, vec3(1.4, 1.5, 1.))));
  } else if (u_opt0 == 2) {   // pillars in the open
    d = length(vec2(abs(q.x) - 1.3, q.z)) - .17;
  } else {                    // visionary hall: nested arch ribs, a vaulted shell, an alcove every few metres
    float inner = archIn(p, 1.25);
    float qz = mod(p.z + .275, .55) - .275;
    float rib = max(max(-inner, abs(qz) - .07), inner - .3);
    float shell = .45 - inner;
    float alc = sdBox3(vec3(abs(p.x) - 1.75, p.y + .15, q.z), vec3(.5, .85, .5));
    shell = max(shell, -alc);
    rib = max(rib, -alc);
    d = min(shell, rib);
  }
  return min(flo, d);
}
""" + RAY_TOOLS + """
// ---- wall patterns, on a 2D surface coordinate u
float patScale(){ return mix(2.5, 10., 1. - u_p3); }
vec3 eyeCells(vec2 u){        // a honeycomb of eyes: skin, a gold ring, a glowing iris, a dark pupil
  u *= patScale();
  vec2 r = vec2(1., 1.732), h = r*.5;
  vec2 a = mod(u, r) - h, b = mod(u - h, r) - h;
  vec2 g = dot(a, a) < dot(b, b) ? a : b;
  vec2 id = floor((u - g)*2. + .5);
  float d = length(g), hv = hash(id);
  float open = .8 + .2*sin(u_time*1.3 + hv*6.28) + u_hits.x*.3;
  vec3 skin = palCycle(u_opt1, .05 + hv*.08, vec3(.6, .3, .15))*(.55 + .25*sin(atan(g.y, g.x)*14. + d*30.));
  vec3 gold = palCycle(u_opt1, .2 + hv*.05, vec3(1., .8, .3))*1.1;
  vec3 iris = palCycle(u_opt1, .55 + hv*.1 + u_time*.03, vec3(.2, .5, 1.))*(1.2 + u_hits.x*.8)*(.6 + .4*sin(d*90. - u_time*3.));
  vec3 c = skin*smoothstep(.5, .3, d);
  c = mix(c, gold, smoothstep(.31*open, .29*open, d));
  c = mix(c, iris, smoothstep(.25*open, .23*open, d));
  c = mix(c, vec3(.02), smoothstep(.1*open, .08*open, d));
  return c;
}
vec3 squiggle(vec2 u){         // contour bands that wind like a maze, rainbow between dark lines
  u *= patScale()*.8;
  float t = u_time*.15;
  float f = sin(u.x*1.7 + sin(u.y*1.3 + t)*2.2) + sin(u.y*1.9 + sin(u.x*1.1 - t)*2.4) + sin((u.x + u.y)*.7 + t*2.)*.5;
  float k = f*2.5, e = min(fract(k), 1. - fract(k));
  vec3 band = palCycle(u_opt1, floor(k)*.11 + u_time*.04, vec3(.6));
  return band*(.5 + .7*smoothstep(0., .5, e))*smoothstep(.03, .14, e);
}
float hexEdge(vec2 u){          // 0 on a hex lattice's edges, rising to the cell middle
  u *= patScale()*.7;
  vec2 r = vec2(1., 1.732), h = r*.5;
  vec2 a = mod(u, r) - h, b = mod(u - h, r) - h;
  vec2 g = dot(a, a) < dot(b, b) ? a : b;
  g = abs(g);
  return .5 - max(dot(g, normalize(vec2(1., 1.732))), g.x);
}
vec2 surfUV(vec3 p, vec3 n){ return abs(n.x) > .6 ? p.zy : abs(n.y) > .6 ? p.xz : p.xy; }
int wallMode(){ return u_opt4 == 0 ? (u_opt0 == 3 ? 2 : 1) : u_opt4; }
void main(){
  float t = u_time, rep = 2.2;
  float z = t*(.4 + u_amt*1.6) + u_music.x*.15;
  float sway = u_opt3 == 1 ? sin(t*.4)*.35 : 0.;
  vec3 eye = vec3(sway, -.15 + sin(t*.7)*.04 + u_hits.x*.03, -z);
  vec3 at = eye + vec3(sin(t*.3)*.15*float(u_opt3 == 1), 0., -1.);
  vec3 rd = rayDir(eye, at, 1.05);
  if (u_opt3 == 2) rd = rz(t*.2)*rd;
  float steps, d = rayMarch(eye, rd, 40., 110, steps);
  vec3 far = bg3d(u_opt2, v_uv);
  vec3 col = far;
  int wm = wallMode();
  if (d > 0.) {
    vec3 p = eye + rd*d, n = calcNormal(p, d);
    float qz = mod(p.z + rep*.5, rep) - rep*.5;
    float cell = floor((p.z + rep*.5)/rep);
    vec3 neonC = palCycle(u_opt1, cell*.13 + t*.05, far);
    vec3 base = vec3(.06, .065, .08), glow = vec3(0.);
    bool floorHit = p.y < -.99;
    vec2 su = surfUV(p, n);
    if (wm == 2) { base = eyeCells(su); glow = base*.3; }
    else if (wm == 3) { base = squiggle(su); glow = base*.3; }
    else if (wm == 4) {
      float e = hexEdge(su), tube = smoothstep(.08, .02, e);
      vec3 chrome = envPic(reflect(rd, n))*.9 + pow(max(dot(reflect(rd, n), normalize(vec3(.45, .8, .55))), 0.), 30.);
      base = mix(squiggle(su*1.3)*.45, chrome, tube);
      glow = base*.15;
    } else if (floorHit) {   // plain floor: polished, catching the neon
      vec2 g = abs(fract(vec2(p.x*1.2, p.z*.9)) - .5);
      base = vec3(.03) + neonC*smoothstep(.04, 0., min(g.x, g.y))*.5*u_p0;
    }
    col = light3(base, n, p, eye, wm == 4 ? .7 : .5)*ao3(p, n) + glow;
    if (wm >= 2 && floorHit) col *= .55;   // patterned floor a step darker than the walls
    // screens on the side walls, between the arches
    if (abs(n.x) > .8 && u_opt0 < 2 && abs(qz) < .8 && p.y > -.55 && p.y < .75) {
      vec2 suv = vec2((qz/.8)*.5*sign(p.x) + .5, 1. - (p.y + .55)/1.3);
      vec3 pic = tx(suv).rgb;
      float edge = smoothstep(.0, .03, min(min(suv.x, 1. - suv.x), min(suv.y, 1. - suv.y)));
      col = mix(col, pic*1.15, edge*u_p2);
    }
    // visionary hall: you, standing in each alcove, with a halo
    if (u_opt0 == 3 && abs(p.x) > 1.27 && n.z > .7 && abs(qz) < .6) {   // on the alcove wall that faces you
      vec2 suv = vec2(.5 + (p.x - sign(p.x)*1.75)/1.7/asp3(), .5 - (p.y + .15)/1.7);
      float m = maskAt(suv);
      vec3 pic = tx(suv).rgb;
      float halo = 0.;
      for (int i = 0; i < 8; i++){ float a = float(i)*.785; halo += maskAt(suv + vec2(cos(a)/asp3(), sin(a))*.07); }
      halo = smoothstep(0., .5, halo/8.);
      col = mix(col, neonC*1.4, halo*.6*u_p2);
      col = mix(col, pic*1.2 + neonC*.15, m*u_p2);
    }
    // neon along the edges of the openings
    float inner = u_opt0 == 0 ? archIn(p, 1.35) : u_opt0 == 1 ? max(abs(p.x) - 1.4, p.y - 1.5)
                : u_opt0 == 3 ? archIn(p, 1.25) : 1.;
    float rim = smoothstep(.05, .0, abs(inner))*step(.7, abs(n.z));
    float edgeGlow = pow(1. - abs(dot(n, normalize(eye - p))), 6.);
    col += neonC*(edgeGlow*.5 + rim*1.2)*u_p0*(1. + u_hits.x*1.2 + u_hits.y*.6);
    col = mix(far*.6, col, exp(-d*d*mix(.0008, .02, u_p1)));
  }
  col += palCycle(u_opt1, t*.05, far)*pow(steps/110., 2.)*u_p0*.6;
  o = vec4(col, 1.);
}"""),
]

FOG.update({"object3d": 0., "metal3d": 0., "fractal3d": 0., "halls3d": 0.})
EFFECTS_3D += RAY_EFFECTS
