/**
 * ink-particles-art · 水墨渲染器（长卷版）
 * ------------------------------------------------------------------
 * 两套墨的表示，共用同一张"密度场"：
 *
 *  A. 正在写的那个字 → **粒子**（沿骨架、按笔压撒点），有笔尖、有湿边、有飞白。
 *  B. 已经写完的字 → **字模图集四边形**（一次 draw 画几百个字），墨色随"年龄"变淡，
 *     像干在纸上的墨。两者在 0.35s 内交叉淡入淡出，所以不会"啪"地换掉。
 *
 * 坐标系：**世界坐标**，1 单位 = zoom 1 时的画面高度，y 向上。
 *   world → 屏幕 uv:  uv = (world - cam) * vec2(z/aspect, -z) + 0.5
 * 镜头在顶点着色器里直接作用，所以放大不会糊；纸纹按世界坐标取样，纸跟着卷面一起移动。
 *
 * 密度场：所有墨（粒子 + 字模）都累加进一张浮点贴图（R=墨、G=朱砂），
 * 合成时 1-exp(-k·d) 映射成墨色 —— 重叠自然变浓。
 * 之后：全分辨率小半径平滑 → 1/4 分辨率两级模糊得"湿边" → 水线（rim）+ 飞白 + 纸 + 暗角。
 *
 * 确定性：所有量都是 t 的解析函数，没有状态累积。
 */

const VS_HEAD = `#version 300 es
precision highp float;

uniform float uTime;
uniform vec2  uRes;
uniform float uAspect;
uniform vec2  uCam;
uniform float uZoom;
uniform float uSize;
uniform float uAlpha;
uniform float uSpread;
uniform float uFlow;
uniform float uCurl;
uniform vec2  uCenter;
uniform float uGlyphSize;
uniform float uThickness;
uniform float uWrite;
uniform float uFade;
uniform float uRed;
uniform float uDrift;
uniform float uPathLen;
uniform int   uRangeStart;
uniform int   uRangeCount;
uniform sampler2D uPath;
uniform sampler2D uInfo;

out float vRed;
out float vAlpha;

uint hashU(uint x){
  x ^= x >> 16; x *= 0x7feb352du;
  x ^= x >> 15; x *= 0x846ca68bu;
  x ^= x >> 16; return x;
}
float rnd(uint i, uint salt){
  return float(hashU(i * 747796405u + salt * 2891336453u + 1u) & 0x00ffffffu) / 16777215.0;
}
vec3 hash3(vec3 p){
  p = vec3(dot(p, vec3(127.1, 311.7, 74.7)),
           dot(p, vec3(269.5, 183.3, 246.1)),
           dot(p, vec3(113.5, 271.9, 124.6)));
  return fract(sin(p) * 43758.5453123) * 2.0 - 1.0;
}
float noise1(vec3 p){
  vec3 i = floor(p), f = fract(p);
  vec3 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(dot(hash3(i + vec3(0,0,0)), f - vec3(0,0,0)),
                     dot(hash3(i + vec3(1,0,0)), f - vec3(1,0,0)), u.x),
                 mix(dot(hash3(i + vec3(0,1,0)), f - vec3(0,1,0)),
                     dot(hash3(i + vec3(1,1,0)), f - vec3(1,1,0)), u.x), u.y),
             mix(mix(dot(hash3(i + vec3(0,0,1)), f - vec3(0,0,1)),
                     dot(hash3(i + vec3(1,0,1)), f - vec3(1,0,1)), u.x),
                 mix(dot(hash3(i + vec3(0,1,1)), f - vec3(0,1,1)),
                     dot(hash3(i + vec3(1,1,1)), f - vec3(1,1,1)), u.x), u.y), u.z);
}

vec4 worldToClip(vec2 world){
  vec2 uv = (world - uCam) * vec2(uZoom / uAspect, -uZoom) + 0.5;
  return vec4(uv.x * 2.0 - 1.0, uv.y * 2.0 - 1.0, 0.0, 1.0);
}
`;

const PARTICLE_VERT = VS_HEAD + `
layout(location=0) in vec2 aSeed;
uniform float uMode;       // 0=浮尘 1=墨团 2=笔画

void main(){
  int idx = max(0, gl_VertexID - uRangeStart);
  uint ui = uint(idx);
  float r1 = rnd(ui, 1u), r2 = rnd(ui, 2u), r3 = rnd(ui, 3u);
  float r4 = rnd(ui, 4u), r5 = rnd(ui, 5u), r6 = rnd(ui, 6u);
  float r7 = rnd(ui, 7u), r8 = rnd(ui, 8u);
  float strat = (float(idx) + 0.5) / max(1.0, float(uRangeCount));

  vec2 world = vec2(0.0);
  float sizeMul = 1.0, alphaMul = 1.0, redSel = 0.0;

  if (uMode < 0.5) {
    // 浮尘：贴着镜头的一层空气感
    vec2 q = vec2(r1, r2) - 0.5;
    float depth = 0.35 + 0.65 * r7;
    world = uCam + q * vec2(uAspect, 1.0) * 1.5 / uZoom;
    float t = uTime * 0.08;
    world += vec2(sin(world.y * 3.1 + t * 2.0 + r3 * 6.28),
                  cos(world.x * 2.7 - t * 1.7 + r4 * 6.28)) * 0.04 * (0.4 + depth) / uZoom;
    sizeMul = (0.35 + depth * 1.5) * (0.7 + 0.6 * r5);
    alphaMul = 0.35 + 0.65 * depth;
  } else if (uMode < 1.5) {
    // 墨团（无词段落的氛围）
    float ang = fract(strat + r1 * 0.002) * 6.2831853;
    float rad = sqrt(r2);
    vec2 base = vec2(cos(ang), sin(ang)) * rad * uSpread;
    float t = uTime * uFlow;
    vec2 flow = 0.55 * vec2(sin(base.y * 2.1 + t * 0.55), cos(base.x * 1.9 - t * 0.47))
              + 0.30 * vec2(sin((base.x + base.y) * 3.7 - t * 0.95), cos((base.x - base.y) * 4.1 + t * 0.82));
    world = uCenter + base + flow * uCurl * 0.16;
    sizeMul = 1.30 - 0.45 * rad;
    alphaMul = pow(max(0.0, 1.0 - rad), 1.15) * 1.15;
  } else {
    // 笔画：沿骨架取样，笔压决定宽度/浓度
    float f = fract(strat + (r1 - 0.5) / max(1.0, uPathLen));
    float fu = f * (uPathLen - 1.0);
    float i0 = floor(fu);
    float fr = fu - i0;
    vec2 t0 = vec2((i0 + 0.5) / uPathLen, 0.5);
    vec2 t1 = vec2((min(i0 + 1.0, uPathLen - 1.0) + 0.5) / uPathLen, 0.5);
    vec4 PA = texture(uPath, t0), PB = texture(uPath, t1);
    float jump = length(PB.xy - PA.xy);
    float wfr = (jump > 0.05) ? 0.0 : fr;      // 跨笔不插值（否则画出细直线）
    vec4 pa = mix(PA, PB, wfr);
    vec2 inf = mix(texture(uInfo, t0).rg, texture(uInfo, t1).rg, wfr);
    float press = inf.x, ord = inf.y;
    vec2 P = pa.xy;
    vec2 N = normalize(pa.zw + vec2(1e-5));

    float r = r2 * 2.0 - 1.0;
    float wet = smoothstep(0.84, 1.0, r3);
    float width = uThickness * uGlyphSize * (0.30 + 0.80 * press);
    float lat = r * (1.0 + 1.9 * wet) * width;
    float dry = smoothstep(0.955, 1.0, r4);
    lat += sign(lat + 1e-4) * dry * width * 0.9;

    vec2 p2 = P - 0.5;
    float jitter = noise1(vec3(P * 6.0, r5 * 3.0)) * 0.5 + 0.5;
    float vis = smoothstep(ord - 0.004, ord + 0.040 + 0.03 * jitter, uWrite);
    float head = exp(-max(0.0, uWrite - ord) * 26.0) * step(ord - 0.02, uWrite);
    lat *= 1.0 + 0.9 * head;

    float wetness = 0.5 + 0.5 * noise1(vec3(P * 4.2, uTime * 0.34 + r5));
    float edgeTaper = pow(max(0.0, 1.0 - abs(r) * abs(r)), 0.85);
    sizeMul = (0.62 + 0.80 * press) * (0.86 + 0.28 * r6) * (1.0 + 0.55 * wet) * (1.0 + 0.25 * head);
    alphaMul = (0.55 + 0.55 * press) * (1.0 - 0.55 * wet) * (1.0 + 0.55 * head)
             * (1.0 - 0.55 * dry) * edgeTaper * (0.70 + 0.55 * wetness) * vis;
    float rp = r7;
    float dis = smoothstep(rp - 0.10, rp + 0.10, uFade);
    alphaMul *= (1.0 - dis);
    vec2 ddir = normalize(vec2(sin(p2.y * 7.0 + r3 * 6.28), cos(p2.x * 7.0 + r4 * 6.28)) + 1e-4);
    p2 += ddir * dis * uDrift * 0.10;
    vec2 shimmer = vec2(sin(uTime * 1.7 + r7 * 6.283), cos(uTime * 1.31 + r8 * 6.283)) * 0.0026 * (0.35 + press);
    world = uCenter + (p2 * uGlyphSize) + N * lat + shimmer;
    redSel = step(r8, uRed);
  }

  gl_Position = worldToClip(world);
  gl_PointSize = max(1.0, uSize * uRes.y * uZoom * sizeMul);
  vAlpha = uAlpha * alphaMul;
  vRed = redSel;
}
`;

const PARTICLE_FRAG = `#version 300 es
precision highp float;
in float vRed;
in float vAlpha;
uniform sampler2D uInk;
uniform float uSoft;
out vec4 fragColor;
void main(){
  vec2 q = gl_PointCoord - 0.5;
  float g = exp(-dot(q, q) * 9.0) * (1.0 - smoothstep(0.42, 0.5, length(q)));
  float a = mix(texture(uInk, gl_PointCoord).a, g, uSoft) * vAlpha;
  if (a < 0.0015) discard;
  fragColor = vec4(a * (1.0 - vRed), a * vRed, 0.0, a);
}`;

// ---- 写完的字：字模图集四边形（一次 draw 画完全部）----
const MASK_VERT = VS_HEAD + `
layout(location=0) in vec2 aCorner;
layout(location=1) in vec4 aQuad;    // cx, cy, size, rot
layout(location=2) in vec4 aRect;    // u0, v0, u1, v1
layout(location=3) in vec4 aTint;    // alpha, red, -, -
out vec2 vUv;
out float vWrite;
void main(){
  vec2 corner = aCorner * 2.0 - 1.0;
  float c = cos(aQuad.w), s = sin(aQuad.w);
  vec2 local = vec2(corner.x * c - corner.y * s, corner.x * s + corner.y * c) * (aQuad.z * 0.5);
  gl_Position = worldToClip(aQuad.xy + local);
  vUv = mix(aRect.xy, aRect.zw, vec2(aCorner.x, aCorner.y));
  vAlpha = aTint.x;
  vRed = aTint.y;
  vWrite = aTint.z;
}`;

const MASK_FRAG = `#version 300 es
precision highp float;
in vec2 vUv;
in float vAlpha;
in float vRed;
in float vWrite;
uniform sampler2D uAtlas;
out vec4 fragColor;
void main(){
  vec3 m = texture(uAtlas, vUv).rgb;
  float shape = m.r;                       // 字形覆盖（锐利）
  float u = m.g;                           // 这个像素是第几笔写到的
  // 书写前沿：0.045 的窄带 —— 前沿是"干净的边"，不是虚焦
  float reveal = smoothstep(u - 0.035, u + 0.012, vWrite);
  float a = shape * vAlpha * reveal;
  if (a < 0.002) discard;
  fragColor = vec4(a * (1.0 - vRed), a * vRed, 0.0, a);
}`;

const QUAD_VERT = `#version 300 es
precision highp float;
layout(location=0) in vec2 aPos;
out vec2 vUv;
void main(){ vUv = aPos * 0.5 + 0.5; gl_Position = vec4(aPos, 0.0, 1.0); }`;

const BLUR_FRAG = `#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D uSrc;
uniform vec2 uDir;
out vec4 fragColor;
void main(){
  vec2 uv = vUv;
  vec4 s = texture(uSrc, uv) * 0.2270270270;
  s += texture(uSrc, uv + uDir * 1.3846153846) * 0.3162162162;
  s += texture(uSrc, uv - uDir * 1.3846153846) * 0.3162162162;
  s += texture(uSrc, uv + uDir * 3.2307692308) * 0.0702702703;
  s += texture(uSrc, uv - uDir * 3.2307692308) * 0.0702702703;
  fragColor = s;
}`;

const COMPOSITE_FRAG = `#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D uInk;
uniform sampler2D uBleed;
uniform sampler2D uPaper;
uniform sampler2D uDry;
uniform vec2  uRes;
uniform vec2  uCam;
uniform float uZoom;
uniform float uAspect;
uniform float uTime;
uniform float uDensity;
uniform float uBleedAmt;
uniform float uDryAmt;
uniform float uWashAmt;
uniform float uVignette;
uniform float uPaperScale;
uniform float uGrain;
uniform vec3  uInkTint;
uniform vec3  uRedTint;
uniform float uPulse;
out vec4 fragColor;

vec2 toWorld(vec2 uv){ return uCam + (uv - 0.5) * vec2(uAspect, -1.0) / uZoom; }
float fbm2(vec2 p, float t){
  float v = 0.0, a = 0.55;
  for (int i = 0; i < 3; i++){ v += a * texture(uDry, p).r; p = p * 2.07 + vec2(0.31, 0.17); a *= 0.52; }
  return v;
}
void main(){
  vec2 uv = vUv;
  vec2 w = toWorld(uv);
  vec4 den = texture(uInk, uv);
  vec4 bl  = texture(uBleed, uv);

  vec3 paper = texture(uPaper, w * 1.35 * uPaperScale).rgb;

  float fog = fbm2(uv * vec2(5.4, 4.6) + vec2(uTime * 0.013, -uTime * 0.009) + w * 0.08, uTime);
  float wash = smoothstep(0.34, 1.08, fog) * uWashAmt;
  paper *= mix(1.0, 0.945, wash);

  float dInk = 1.0 - exp(-uDensity * den.r);
  float dRed = 1.0 - exp(-uDensity * 1.15 * den.g);
  float bInk = 1.0 - exp(-uDensity * bl.r);

  vec2 tex = 1.0 / uRes;
  float gx = (1.0 - exp(-uDensity * texture(uBleed, uv + vec2(tex.x * 3.0, 0.0)).r))
           - (1.0 - exp(-uDensity * texture(uBleed, uv - vec2(tex.x * 3.0, 0.0)).r));
  float gy = (1.0 - exp(-uDensity * texture(uBleed, uv + vec2(0.0, tex.y * 3.0)).r))
           - (1.0 - exp(-uDensity * texture(uBleed, uv - vec2(0.0, tex.y * 3.0)).r));
  float grad = length(vec2(gx, gy));
  float rim = smoothstep(0.10, 0.55, grad) * smoothstep(0.02, 0.22, bInk);
  float halo = clamp(bInk - dInk * 0.72, 0.0, 1.0);

  float dens = clamp(dInk + halo * 0.30 * uBleedAmt + rim * 0.22 * uBleedAmt, 0.0, 1.0);

  float fw = fbm2(uv * vec2(1.7, 0.95) + vec2(0.0, uTime * 0.004), uTime);
  float cut = smoothstep(0.46, 0.90, fw) * smoothstep(0.10, 0.34, dens)
            * (1.0 - smoothstep(0.52, 0.78, dens));
  dens *= 1.0 - uDryAmt * cut;
  // 四边软淡出：墨在画面边缘 5–7% 内渐隐。
  // 这样上一行被顶边切到、以及段尾近景把长行裁到边，都不会出现"半个字贴着边"的硬口子。
  // 注意方向：本项目 uv.y = 1 在**顶边**、uv.y = 0 在底边（世界 y 向上、屏幕 y 向下）。
  // 顶边要给宽一点（7%），因为"上一行被画面顶边拦腰截断"是原来最扎眼的一处。
  float edgeMask = smoothstep(0.000, 0.070, 1.0 - uv.y)   // 顶边
                 * smoothstep(0.000, 0.045, uv.y)         // 底边（字幕在 DOM 上，不受影响）
                 * smoothstep(0.000, 0.100, uv.x)         // 左边 10%
                 * smoothstep(0.000, 0.100, 1.0 - uv.x);  // 右边 10%
  // 10% 而不是 7.5%：7.5% 时越界列中位 alpha 0.357，差 0.007 没过判据。
  // 与其解释"这点墨看不见"，不如把判据做实。
  dens *= edgeMask;

  vec3 col = paper * mix(vec3(1.0), uInkTint, dens);
  // 朱砂必须走同一层边沿遮罩：它原来只乘在 dens 上，红字一直压到画面边上
  // （实测新样片 9/80 帧左端越界 0.3–0.52%，全是红字）。
  float red = clamp(dRed * 2.6, 0.0, 1.0) * edgeMask;
  col = mix(col, paper * uRedTint, red * 0.92);

  col *= 1.0 + 0.0110 * sin(uTime * 0.37) + 0.0055 * sin(uTime * 0.91 + 1.7);
  col = mix(col, col * col * 1.04 + col * 0.015, 0.045 * (0.5 + 0.5 * sin(uTime * 0.53 + 0.4)));

  float d = distance(uv, vec2(0.5));
  col *= 1.0 - uVignette * smoothstep(0.34, 0.92, d);
  float g = fract(sin(dot(uv * uRes + uTime * 13.0, vec2(12.9898, 78.233))) * 43758.5453);
  col += (g - 0.5) * uGrain;
  fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}`;

function compile(gl, type, src) {
  const sh = gl.createShader(type);
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(sh);
    gl.deleteShader(sh);
    throw new Error('shader 编译失败: ' + log + '\n---\n' +
      src.split('\n').map((l, i) => (i + 1) + ': ' + l).join('\n'));
  }
  return sh;
}
function program(gl, vs, fs) {
  const p = gl.createProgram();
  gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, vs));
  gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error('program 链接失败: ' + gl.getProgramInfoLog(p));
  return p;
}

const COUNT_DUST = 9000;
const COUNT_WASH = 10000;
const COUNT_GLYPH = 120000;
const TOTAL = COUNT_DUST + COUNT_WASH + COUNT_GLYPH;
const MAX_QUADS = 600;

export class InkArt {
  constructor(canvas, opt = {}) {
    this.canvas = canvas;
    const gl = canvas.getContext('webgl2', {
      alpha: false, antialias: false, preserveDrawingBuffer: true,
      premultipliedAlpha: false, powerPreference: 'high-performance',
    });
    if (!gl) throw new Error('需要 WebGL2');
    this.gl = gl;
    this.floatRT = !!gl.getExtension('EXT_color_buffer_float');
    this.rtFormat = this.floatRT ? gl.RGBA16F : gl.RGBA8;
    this.rtType = this.floatRT ? gl.HALF_FLOAT : gl.UNSIGNED_BYTE;

    const seeds = new Float32Array(TOTAL * 2);
    let s = 20260306;
    const rnd = () => { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; };
    for (let i = 0; i < TOTAL * 2; i++) seeds[i] = rnd();

    this.vao = gl.createVertexArray();
    gl.bindVertexArray(this.vao);
    const vbo = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
    gl.bufferData(gl.ARRAY_BUFFER, seeds, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

    this.prog = program(gl, PARTICLE_VERT, PARTICLE_FRAG);
    this.uni = this._uniforms(this.prog, [
      'uTime', 'uRes', 'uAspect', 'uCam', 'uZoom', 'uMode', 'uSize', 'uAlpha',
      'uSpread', 'uFlow', 'uCurl', 'uCenter', 'uGlyphSize', 'uThickness', 'uWrite',
      'uFade', 'uRed', 'uDrift', 'uPathLen', 'uPath', 'uInfo', 'uInk', 'uSoft',
      'uRangeStart', 'uRangeCount',
    ]);

    // ---- 字模四边形 ----
    this.maskProg = program(gl, MASK_VERT, MASK_FRAG);
    this.maskUni = this._uniforms(this.maskProg, ['uTime', 'uRes', 'uAspect', 'uCam', 'uZoom', 'uAtlas']);
    this.quadVao = gl.createVertexArray();
    gl.bindVertexArray(this.quadVao);
    const cb = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, cb);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    this.instBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.instBuf);
    gl.bufferData(gl.ARRAY_BUFFER, MAX_QUADS * 12 * 4, gl.DYNAMIC_DRAW);
    for (let k = 0; k < 3; k++) {
      gl.enableVertexAttribArray(1 + k);
      gl.vertexAttribPointer(1 + k, 4, gl.FLOAT, false, 48, k * 16);
      gl.vertexAttribDivisor(1 + k, 1);
    }
    this.instData = new Float32Array(MAX_QUADS * 12);
    this.atlas = null;
    this.maskRects = {};

    this.blurProg = program(gl, QUAD_VERT, BLUR_FRAG);
    this.blurUni = this._uniforms(this.blurProg, ['uSrc', 'uDir']);
    this.compProg = program(gl, QUAD_VERT, COMPOSITE_FRAG);
    this.compUni = this._uniforms(this.compProg, [
      'uInk', 'uBleed', 'uPaper', 'uDry', 'uRes', 'uCam', 'uZoom', 'uAspect',
      'uTime', 'uDensity', 'uBleedAmt', 'uDryAmt', 'uWashAmt', 'uVignette',
      'uPaperScale', 'uGrain', 'uInkTint', 'uRedTint', 'uPulse',
    ]);

    this.quad = gl.createVertexArray();
    gl.bindVertexArray(this.quad);
    const qb = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, qb);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

    this.pathTex = this._dataTex(1, 1, gl.RGBA32F);
    this.infoTex = this._dataTex(1, 1, gl.RG32F);
    this.pathLen = 1;

    this.params = {
      inkTint: [0.085, 0.072, 0.062],
      redTint: [0.60, 0.135, 0.105],
      vignette: 0.16, paperScale: 1.0, grain: 0.0055,
      density: 1.25, bleedAmt: 1.15, dryAmt: 0.30, washAmt: 0.5, pulse: 0, smooth: 1.5,
    };

    this.ready = (async () => {
      this.inkTex = await this._load('art/inkdot.png', false, false);
      // paper.png 不是可平铺贴图：用 REPEAT 会在 uv 整数边界留下一条硬色阶
      // （实测振幅 4–12/255，随镜头扫过画面）。MIRRORED_REPEAT 在边界处左右镜像，
      // 值连续，接缝消失。
      this.paperTex = await this._load('art/paper.png', 'mirror');
      this.dryTex = await this._load('art/drybrush.png', true);
      this.atlas = await this._load('art/masks.png', true, false);
      this.resize();
      return this;
    })();
  }

  _uniforms(prog, names) {
    const gl = this.gl, out = {};
    for (const n of names) out[n] = gl.getUniformLocation(prog, n);
    return out;
  }
  _dataTex(w, h, fmt) {
    const gl = this.gl;
    const t = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texImage2D(gl.TEXTURE_2D, 0, fmt, w, h, 0, fmt === gl.RG32F ? gl.RG : gl.RGBA, gl.FLOAT,
      new Float32Array(w * h * (fmt === gl.RG32F ? 2 : 4)));
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    return t;
  }
  _load(url, repeat = false, mip = true) {
    const gl = this.gl;
    return new Promise((res, rej) => {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => {
        const t = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, t);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
        if (mip) {
          gl.generateMipmap(gl.TEXTURE_2D);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
        } else {
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        }
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        const wrap = (repeat === 'mirror') ? gl.MIRRORED_REPEAT
          : (repeat ? gl.REPEAT : gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, wrap);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, wrap);
        res(t);
      };
      img.onerror = () => rej(new Error('贴图加载失败: ' + url));
      img.src = url;
    });
  }
  _rt(w, h) {
    const gl = this.gl;
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, this.rtFormat, w, h, 0, gl.RGBA, this.rtType, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const fbo = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    return { tex, fbo };
  }
  resize() {
    const gl = this.gl, c = this.canvas;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(c.clientWidth * dpr));
    const h = Math.max(1, Math.round(c.clientHeight * dpr));
    if (w === this.w && h === this.h && this.ink) return;
    c.width = w; c.height = h;
    this.w = w; this.h = h;
    if (this.ink) for (const o of [this.ink, this.sm, this.sm2, this.b1, this.b2]) {
      gl.deleteTexture(o.tex); gl.deleteFramebuffer(o.fbo);
    }
    this.ink = this._rt(w, h);
    this.sm = this._rt(w, h);
    this.sm2 = this._rt(w, h);
    const bw = Math.max(2, Math.round(w / 2)), bh = Math.max(2, Math.round(h / 2));
    this.b1 = this._rt(bw, bh);
    this.b2 = this._rt(bw, bh);
    this.bw = bw; this.bh = bh;
  }

  setGlyphRects(rects) { this.maskRects = rects; return this; }
  hasGlyph(ch) { return !!this.maskRects[ch]; }

  setGlyph(points) {
    const gl = this.gl;
    const n = Math.min(4096, points.length);
    const data = new Float32Array(n * 4);
    const info = new Float32Array(n * 2);
    for (let i = 0; i < n; i++) {
      const p = points[i];
      data[i * 4] = p[0]; data[i * 4 + 1] = p[1];
      data[i * 4 + 2] = p[2]; data[i * 4 + 3] = p[3];
      info[i * 2] = Math.max(0.02, p[4]); info[i * 2 + 1] = p[5];
    }
    gl.bindTexture(gl.TEXTURE_2D, this.pathTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, n, 1, 0, gl.RGBA, gl.FLOAT, data);
    gl.bindTexture(gl.TEXTURE_2D, this.infoTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RG32F, n, 1, 0, gl.RG, gl.FLOAT, info);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    this.pathLen = n;
    return this;
  }

  set(p = {}) { Object.assign(this.params, p); return this; }

  draw(mode, o) {
    const gl = this.gl, u = this.uni;
    gl.useProgram(this.prog);
    gl.bindVertexArray(this.vao);
    gl.uniform1f(u.uTime, o.time ?? 0);
    gl.uniform2f(u.uRes, this.w, this.h);
    gl.uniform1f(u.uAspect, this.w / this.h);
    gl.uniform2f(u.uCam, (o.cam ?? [0, 0])[0], (o.cam ?? [0, 0])[1]);
    gl.uniform1f(u.uZoom, o.zoom ?? 1);
    gl.uniform1f(u.uMode, mode);
    gl.uniform1f(u.uSize, o.size ?? 0.006);
    gl.uniform1f(u.uAlpha, o.alpha ?? 0.05);
    gl.uniform1f(u.uSpread, o.spread ?? 0.18);
    gl.uniform1f(u.uFlow, o.flow ?? 1.0);
    gl.uniform1f(u.uCurl, o.curl ?? 1.0);
    gl.uniform2f(u.uCenter, (o.center ?? [0, 0])[0], (o.center ?? [0, 0])[1]);
    gl.uniform1f(u.uGlyphSize, o.glyphSize ?? 0.5);
    gl.uniform1f(u.uThickness, o.thickness ?? 0.10);
    gl.uniform1f(u.uWrite, o.write ?? 1.0);
    gl.uniform1f(u.uFade, o.fade ?? 0.0);
    gl.uniform1f(u.uRed, o.red ?? 0.0);
    gl.uniform1f(u.uDrift, o.drift ?? 1.0);
    gl.uniform1f(u.uPathLen, this.pathLen);
    gl.uniform1f(u.uSoft, o.soft ?? 0.0);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, this.pathTex); gl.uniform1i(u.uPath, 0);
    gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, this.infoTex); gl.uniform1i(u.uInfo, 1);
    gl.activeTexture(gl.TEXTURE2); gl.bindTexture(gl.TEXTURE_2D, this.inkTex); gl.uniform1i(u.uInk, 2);
    const start = mode === 0 ? 0 : (mode === 1 ? COUNT_DUST : COUNT_DUST + COUNT_WASH);
    const count = mode === 0 ? COUNT_DUST : (mode === 1 ? COUNT_WASH : COUNT_GLYPH);
    gl.uniform1i(u.uRangeStart, start);
    gl.uniform1i(u.uRangeCount, count);
    gl.drawArrays(gl.POINTS, start, count);
    return this;
  }

  /** 写完的字：一次画完。quads = [{c, x, y, size, rot, alpha, red}] */
  drawMasks(quads, o) {
    if (!quads.length || !this.atlas) return this;
    const gl = this.gl, u = this.maskUni;
    let n = 0;
    for (const q of quads) {
      const r = this.maskRects[q.c];
      if (!r || n >= MAX_QUADS) continue;
      const k = n * 12;
      this.instData[k] = q.x; this.instData[k + 1] = q.y;
      this.instData[k + 2] = q.size; this.instData[k + 3] = q.rot ?? 0;
      this.instData[k + 4] = r[0]; this.instData[k + 5] = r[1];
      this.instData[k + 6] = r[2]; this.instData[k + 7] = r[3];
      this.instData[k + 8] = q.alpha; this.instData[k + 9] = q.red ?? 0;
      this.instData[k + 10] = q.write ?? 1.0; this.instData[k + 11] = 0;
      n++;
    }
    if (!n) return this;
    gl.useProgram(this.maskProg);
    gl.bindVertexArray(this.quadVao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.instBuf);
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, this.instData.subarray(0, n * 12));
    gl.uniform1f(u.uTime, o.time ?? 0);
    gl.uniform2f(u.uRes, this.w, this.h);
    gl.uniform1f(u.uAspect, this.w / this.h);
    gl.uniform2f(u.uCam, (o.cam ?? [0, 0])[0], (o.cam ?? [0, 0])[1]);
    gl.uniform1f(u.uZoom, o.zoom ?? 1);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.atlas);
    gl.uniform1i(u.uAtlas, 0);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, n);
    return this;
  }

  begin() {
    const gl = this.gl;
    this.resize();
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.ink.fbo);
    gl.viewport(0, 0, this.w, this.h);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE);
    gl.disable(gl.DEPTH_TEST);
    return this;
  }

  _blurPass(src, dst, dx, dy, w, h) {
    const gl = this.gl, u = this.blurUni;
    const W = w ?? this.bw, H = h ?? this.bh;
    gl.bindFramebuffer(gl.FRAMEBUFFER, dst.fbo);
    gl.viewport(0, 0, W, H);
    gl.disable(gl.BLEND);
    gl.useProgram(this.blurProg);
    gl.bindVertexArray(this.quad);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, src.tex);
    gl.uniform1i(u.uSrc, 0);
    gl.uniform2f(u.uDir, dx / W, dy / H);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  finish(o = {}) {
    const gl = this.gl, p = this.params;
    const sr = o.smooth ?? p.smooth ?? 1.5;
    this._blurPass(this.ink, this.sm, sr, 0.0, this.w, this.h);
    this._blurPass(this.sm, this.sm2, 0.0, sr, this.w, this.h);
    this._blurPass(this.sm2, this.b1, 1.2, 0.0);
    this._blurPass(this.b1, this.b2, 0.0, 1.2);

    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, this.w, this.h);
    gl.disable(gl.BLEND);
    gl.useProgram(this.compProg);
    gl.bindVertexArray(this.quad);
    const u = this.compUni;
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, this.sm2.tex); gl.uniform1i(u.uInk, 0);
    gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, this.b2.tex); gl.uniform1i(u.uBleed, 1);
    gl.activeTexture(gl.TEXTURE2); gl.bindTexture(gl.TEXTURE_2D, this.paperTex); gl.uniform1i(u.uPaper, 2);
    gl.activeTexture(gl.TEXTURE3); gl.bindTexture(gl.TEXTURE_2D, this.dryTex); gl.uniform1i(u.uDry, 3);
    gl.uniform2f(u.uRes, this.w, this.h);
    gl.uniform1f(u.uAspect, this.w / this.h);
    gl.uniform2f(u.uCam, (o.cam ?? [0, 0])[0], (o.cam ?? [0, 0])[1]);
    gl.uniform1f(u.uZoom, o.zoom ?? 1);
    gl.uniform1f(u.uTime, o.time ?? 0);
    gl.uniform1f(u.uDensity, o.density ?? p.density);
    gl.uniform1f(u.uBleedAmt, o.bleedAmt ?? p.bleedAmt);
    gl.uniform1f(u.uDryAmt, o.dryAmt ?? p.dryAmt);
    gl.uniform1f(u.uWashAmt, o.washAmt ?? p.washAmt);
    gl.uniform1f(u.uVignette, o.vignette ?? p.vignette);
    gl.uniform1f(u.uPaperScale, o.paperScale ?? p.paperScale);
    gl.uniform1f(u.uGrain, o.grain ?? p.grain);
    gl.uniform1f(u.uPulse, o.pulse ?? 0);
    gl.uniform3f(u.uInkTint, p.inkTint[0], p.inkTint[1], p.inkTint[2]);
    gl.uniform3f(u.uRedTint, p.redTint[0], p.redTint[1], p.redTint[2]);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    return this;
  }

  probe() {
    const gl = this.gl;
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.ink.fbo);
    const w = Math.min(this.w, 640), h = Math.min(this.h, 360);
    const ox = Math.max(0, Math.round((this.w - w) / 2)), oy = Math.max(0, Math.round((this.h - h) / 2));
    const px = new Float32Array(w * h * 4);
    if (this.floatRT) gl.readPixels(ox, oy, w, h, gl.RGBA, gl.FLOAT, px);
    else {
      const b = new Uint8Array(w * h * 4);
      gl.readPixels(ox, oy, w, h, gl.RGBA, gl.UNSIGNED_BYTE, b);
      for (let i = 0; i < b.length; i++) px[i] = b[i] / 255;
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    let maxR = 0, maxG = 0, sum = 0, n = 0;
    for (let i = 0; i < px.length; i += 4) {
      if (px[i] > maxR) maxR = px[i];
      if (px[i + 1] > maxG) maxG = px[i + 1];
      if (px[i] > 0.02) { sum += px[i]; n++; }
    }
    return { maxR, maxG, meanR: n ? sum / n : 0, covered: n / (px.length / 4) };
  }
}

export default InkArt;
