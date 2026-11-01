/**
 * ink-particles · 确定性 WebGL2 粒子系统
 * ------------------------------------------------------------
 * 设计目标只有一个：**同一时刻 t 永远渲染出同一帧**。
 * 所有运动都在顶点着色器里由 t 解析计算，没有状态累积，所以：
 *   - 可以任意 seek（拖进度条、逐帧抓取、并行渲染）
 *   - 不依赖帧率（dt 不影响结果）
 *   - 换机器结果一致（只要 GLSL 浮点行为一致）
 *
 * 无依赖，单个 ES module，WebGL2。
 *
 * 用法：
 *   import { InkParticles } from './ink-particles.js';
 *   const p = new InkParticles(canvas, { count: 80000, ink: 'ink-dot.png' });
 *   await p.ready;
 *   p.setTime(12.5);   // 秒
 *   p.render();
 */

const VERT = `#version 300 es
precision highp float;

layout(location=0) in vec2 aSeed;      // 每粒子的随机种子 [0,1)

uniform float uTime;                   // 秒
uniform vec2  uRes;
uniform float uSize;                   // 基础尺寸（像素，按画布高度归一）
uniform float uFlow;                   // 流动强度
uniform float uCurl;                   // 卷曲程度
uniform float uSpread;                 // 扩散半径（相对画布短边）
uniform vec2  uCenter;                 // 主体中心（0..1）
uniform vec3  uColor;
uniform float uAlpha;
uniform sampler2D uPath;     // 笔迹路径：每像素一个点（xy = 位置 0..1，zw = 法线）
uniform float uUsePath;      // 0 = 径向墨团，1 = 沿笔迹
uniform float uThickness;    // 笔画粗细（归一化，相对画布短边）
uniform float uPathLen;      // 路径采样点数（用于换算纹理坐标）

out vec3 vColor;
out float vAlpha;
out float vSeed;

// --- 便宜的 3D hash / 梯度噪声 ---
vec3 hash3(vec3 p) {
  p = vec3(dot(p, vec3(127.1, 311.7, 74.7)),
           dot(p, vec3(269.5, 183.3, 246.1)),
           dot(p, vec3(113.5, 271.9, 124.6)));
  return fract(sin(p) * 43758.5453123) * 2.0 - 1.0;
}

float noise1(vec3 p) {
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

// 向量噪声：三路偏移采样，用于构造势场
vec3 noise3(vec3 p) {
  return vec3(
    noise1(p),
    noise1(p + vec3(17.3, 4.1, 9.7)),
    noise1(p + vec3(5.2, 23.8, 1.4)));
}

// curl noise：对一个势场的旋度取样，得到无散度（不聚成团）的流
vec3 curl(vec3 p) {
  float e = 0.35;
  vec3 dx = vec3(e, 0, 0), dy = vec3(0, e, 0), dz = vec3(0, 0, e);

  float x0 = noise3(p - dy).x - noise3(p + dy).x;
  float x1 = noise3(p - dz).x - noise3(p + dz).x;
  float y0 = noise3(p - dz).y - noise3(p + dz).y;
  float y1 = noise3(p - dx).y - noise3(p + dx).y;
  float z0 = noise3(p - dx).z - noise3(p + dx).z;
  float z1 = noise3(p - dy).z - noise3(p + dy).z;

  return vec3(x0 - x1, y0 - y1, z0 - z1);
}

void main() {
  // 种子决定形态：初始位置、半径、相位、速度
  float ang   = aSeed.x * 6.2831853;
  float rad   = pow(fract(aSeed.y * 13.713), 1.75);   // >1 = 向中心聚，像墨团
  float phase = fract(aSeed.x * 7.919 + aSeed.y * 3.337);

  vec2 base;
  vec2 pathNormal = vec2(0.0);

  if (uUsePath > 0.5) {
    // 沿笔迹分布：种子决定落在笔画的哪一段、偏离中心多远
    float u = fract(aSeed.x * 977.13);
    vec2 tc = vec2((u * (uPathLen - 1.0) + 0.5) / uPathLen, 0.5);
    vec4 p = texture(uPath, tc);
    pathNormal = p.zw;
    // 横向偏移：多数贴着笔画中心，少数是飞白
    float off = (fract(aSeed.y * 31.7) * 2.0 - 1.0);
    off = sign(off) * pow(abs(off), 2.2);        // 中间密、两边稀
    base = (p.xy - 0.5) * 2.0 + pathNormal * off * uThickness;
  } else {
    // 以中心为原点的极坐标散点，压扁成画布比例
    base = vec2(cos(ang), sin(ang) * 1.18) * rad * uSpread;
  }

  // 流动：把种子 + 时间当作 3D 噪声坐标，卷曲场给出速度方向
  vec3 q = vec3(base * 1.6, phase * 2.0 + uTime * 0.06 * uFlow);
  vec3 c = curl(q) * uCurl;

  vec2 pos = base + c.xy * 0.35;
  // 缓慢的整体呼吸，让整团墨会"活着"
  pos *= 1.0 + 0.035 * sin(uTime * 0.55 + phase * 6.0);

  // 纵横比：把（可能是任意比例的）画布当成归一化空间
  float aspect = uRes.x / uRes.y;
  vec2 p01 = vec2(uCenter.x + pos.x * 0.5, uCenter.y + pos.y * 0.5 * min(1.0, aspect));
  vec2 clip = p01 * 2.0 - 1.0;
  clip.x *= (uRes.x / uRes.y) > 1.0 ? 1.0 : 1.0;
  gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);

  // 尺寸：靠外的更小（模拟墨的浓度衰减）
  float depth = clamp(1.0 - rad * 0.55, 0.3, 1.3);
  gl_PointSize = uSize * depth * (0.6 + 0.8 * fract(aSeed.y * 91.7));

  // 明暗：越靠内越深，再叠一点噪声闪动
  float flick = 0.75 + 0.25 * sin(uTime * 1.7 + phase * 12.0);
  vAlpha = uAlpha * depth * flick;
  vColor = uColor;
  vSeed  = phase;
}`;

const FRAG = `#version 300 es
precision highp float;

in vec3 vColor;
in float vAlpha;
in float vSeed;
uniform sampler2D uInk;      // 墨点贴图（用 .a 或亮度都行）
uniform float uUseInk;        // 0 = 纯圆点，1 = 用贴图

out vec4 fragColor;

void main() {
  vec2 uv = gl_PointCoord;
  // 圆形裁剪
  float r = length(uv - 0.5) * 2.0;
  if (r > 1.0) discard;

  float a;
  if (uUseInk > 0.5) {
    float t = texture(uInk, uv).a;
    if (t < 0.02) t = max(texture(uInk, uv).r, 0.0);
    a = t * vAlpha;
  } else {
    a = smoothstep(1.0, 0.0, r) * vAlpha;
  }
  fragColor = vec4(vColor, a);
}`;

const QUAD_VERT = `#version 300 es
precision highp float;
layout(location=0) in vec2 aPos;
out vec2 vUv;
void main(){ vUv = aPos * 0.5 + 0.5; gl_Position = vec4(aPos, 0.0, 1.0); }`;

const COMPOSITE_FRAG = `#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D uScene;
uniform sampler2D uPaper;
uniform float uUsePaper;
uniform float uVignette;
out vec4 fragColor;
void main(){
  vec4 s = texture(uScene, vUv);
  vec3 bg = vec3(0.937, 0.902, 0.839);           // 宣纸底色
  if (uUsePaper > 0.5) {
    vec3 p = texture(uPaper, vUv).rgb;
    bg = mix(bg, p, 0.85);
  }
  vec3 col = mix(bg, s.rgb, s.a);
  float d = distance(vUv, vec2(0.5));
  col *= 1.0 - uVignette * smoothstep(0.35, 0.85, d);
  fragColor = vec4(col, 1.0);
}`;

function compile(gl, type, src) {
  const sh = gl.createShader(type);
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(sh);
    gl.deleteShader(sh);
    throw new Error('shader 编译失败: ' + log);
  }
  return sh;
}

function program(gl, vs, fs) {
  const p = gl.createProgram();
  gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, vs));
  gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
    throw new Error('program 链接失败: ' + gl.getProgramInfoLog(p));
  }
  return p;
}

export class InkParticles {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {object} opt
   *   count   粒子数（默认 60000）
   *   ink     墨点贴图 URL（可选；不给就是纯圆点）
   *   paper   纸纹贴图 URL（可选）
   *   color   [r,g,b] 0..1，默认墨色
   *   size    基础尺寸（相对画布高度，默认 0.012）
   *   spread  扩散半径（默认 0.75）
   *   center  [x,y] 0..1，默认 [0.5,0.5]
   *   flow / curl  流动与卷曲强度
   *   vignette 暗角强度（默认 0.25）
   */
  constructor(canvas, opt = {}) {
    this.canvas = canvas;
    const gl = canvas.getContext('webgl2', {
      alpha: false, antialias: false, preserveDrawingBuffer: true,
      premultipliedAlpha: false,
    });
    if (!gl) throw new Error('需要 WebGL2');
    this.gl = gl;

    this.count = opt.count ?? 60000;
    this.opts = {
      color: opt.color ?? [0.11, 0.086, 0.063],
      size: opt.size ?? 0.012,
      spread: opt.spread ?? 0.75,
      center: opt.center ?? [0.5, 0.5],
      flow: opt.flow ?? 1.0,
      curl: opt.curl ?? 1.4,
      alpha: opt.alpha ?? 0.55,
      vignette: opt.vignette ?? 0.25,
    };
    this.time = 0;

    // 粒子种子（一次生成，永久复用 —— 这是"确定性"的另一半）
    const seeds = new Float32Array(this.count * 2);
    let s = 1234567;
    const rnd = () => { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; };
    for (let i = 0; i < this.count * 2; i++) seeds[i] = rnd();

    this.vao = gl.createVertexArray();
    gl.bindVertexArray(this.vao);
    const vbo = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
    gl.bufferData(gl.ARRAY_BUFFER, seeds, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

    this.prog = program(gl, VERT, FRAG);
    this.uni = this._uniforms(this.prog, [
      'uTime', 'uRes', 'uSize', 'uFlow', 'uCurl', 'uSpread', 'uCenter',
      'uColor', 'uAlpha', 'uInk', 'uUseInk',
      'uPath', 'uUsePath', 'uThickness', 'uPathLen',
    ]);
    this.opts.thickness = opt.thickness ?? 0.03;

    // 离屏场景（粒子先画到这里，再和纸底合成）
    this.scene = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.scene);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    this.fbo = gl.createFramebuffer();

    // 合成用全屏三角形
    this.quad = gl.createVertexArray();
    gl.bindVertexArray(this.quad);
    const qb = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, qb);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

    this.compProg = program(gl, QUAD_VERT, COMPOSITE_FRAG);
    this.compUni = this._uniforms(this.compProg, ['uScene', 'uPaper', 'uUsePaper', 'uVignette']);

    this.inkTex = this._white(gl);
    this.paperTex = this._white(gl);
    this.pathTex = this._white(gl);
    this.useInk = 0;
    this.usePaper = 0;
    this.usePath = 0;
    this.pathLen = 1;

    this.ready = (async () => {
      if (opt.ink) { this.inkTex = await this._load(opt.ink); this.useInk = 1; }
      if (opt.paper) { this.paperTex = await this._load(opt.paper); this.usePaper = 1; }
      this.resize();
      return this;
    })();
  }

  _uniforms(prog, names) {
    const gl = this.gl, out = {};
    for (const n of names) out[n] = gl.getUniformLocation(prog, n);
    return out;
  }

  _white(gl) {
    const t = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE,
      new Uint8Array([255, 255, 255, 255]));
    return t;
  }

  _load(url) {
    const gl = this.gl;
    return new Promise((res, rej) => {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => {
        const t = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, t);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        res(t);
      };
      img.onerror = () => rej(new Error('贴图加载失败: ' + url));
      img.src = url;
    });
  }

  resize() {
    const gl = this.gl, c = this.canvas;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(c.clientWidth * dpr));
    const h = Math.max(1, Math.round(c.clientHeight * dpr));
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    gl.bindTexture(gl.TEXTURE_2D, this.scene);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.fbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, this.scene, 0);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    this.w = w; this.h = h;
  }

  /**
   * 给一条"笔迹路径"：粒子会沿着它分布成墨线。
   * @param {Array<[number,number]>} pts 归一化坐标（0..1），按顺序连成折线
   * @param {number} thickness 笔画粗细（相对画布短边，默认 0.03）
   */
  setPath(pts, thickness = 0.03) {
    if (!pts || pts.length < 2) { this.usePath = 0; return this; }
    const gl = this.gl;
    // 注意：点列**按原样使用**，不沿折线插值。
    // 因为从图片提取出来的点是无序点云（按行扫描），插值会把相邻但不相连的点连成折线，
    // 结果就是"填充"而不是"线条"。这里改成等间隔抽稀。
    const n = Math.min(1024, pts.length);
    const step = pts.length / n;
    const data = new Float32Array(n * 4);
    for (let i = 0; i < n; i++) {
      const a = pts[Math.floor(i * step)];
      const b = pts[Math.min(pts.length - 1, Math.floor(i * step) + 1)];
      const x = a[0], y = a[1];
      let dx = b[0] - x, dy = b[1] - y;
      const L = Math.hypot(dx, dy) || 1;
      data[i * 4 + 0] = x;
      data[i * 4 + 1] = y;
      data[i * 4 + 2] = -dy / L;
      data[i * 4 + 3] = dx / L;
    }
    gl.bindTexture(gl.TEXTURE_2D, this.pathTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, n, 1, 0, gl.RGBA, gl.FLOAT, data);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    this.pathLen = n;
    this.usePath = 1;
    this.opts.thickness = thickness;
    return this;
  }

  /** 取消笔迹，回到径向墨团 */
  clearPath() { this.usePath = 0; return this; }

  /** 设定时刻（秒）。同一 t 必然得到同一帧。 */
  setTime(t) { this.time = t; return this; }

  /** 调参（可逐帧调用，例如跟音乐能量） */
  set(params = {}) { Object.assign(this.opts, params); return this; }

  render() {
    const gl = this.gl, o = this.opts;
    this.resize();

    // 1) 粒子画到离屏
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.fbo);
    gl.viewport(0, 0, this.w, this.h);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    gl.useProgram(this.prog);
    gl.bindVertexArray(this.vao);
    gl.uniform1f(this.uni.uTime, this.time);
    gl.uniform2f(this.uni.uRes, this.w, this.h);
    gl.uniform1f(this.uni.uSize, o.size * this.h);
    gl.uniform1f(this.uni.uFlow, o.flow);
    gl.uniform1f(this.uni.uCurl, o.curl);
    gl.uniform1f(this.uni.uSpread, o.spread);
    gl.uniform2f(this.uni.uCenter, o.center[0], o.center[1]);
    gl.uniform3f(this.uni.uColor, o.color[0], o.color[1], o.color[2]);
    gl.uniform1f(this.uni.uAlpha, o.alpha);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.inkTex);
    gl.uniform1i(this.uni.uInk, 0);
    gl.uniform1f(this.uni.uUseInk, this.useInk);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.pathTex);
    gl.uniform1i(this.uni.uPath, 1);
    gl.uniform1f(this.uni.uUsePath, this.usePath);
    gl.uniform1f(this.uni.uThickness, this.opts.thickness);
    gl.uniform1f(this.uni.uPathLen, this.pathLen);
    gl.drawArrays(gl.POINTS, 0, this.count);

    // 2) 合成：纸底 + 粒子 + 暗角
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, this.w, this.h);
    gl.clearColor(0, 0, 0, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.disable(gl.BLEND);
    gl.useProgram(this.compProg);
    gl.bindVertexArray(this.quad);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.scene);
    gl.uniform1i(this.compUni.uScene, 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.paperTex);
    gl.uniform1i(this.compUni.uPaper, 1);
    gl.uniform1f(this.compUni.uUsePaper, this.usePaper);
    gl.uniform1f(this.compUni.uVignette, o.vignette);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    return this;
  }
}

export default InkParticles;
