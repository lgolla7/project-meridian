
(function () {
  function multiply(a, b) {
    const out = new Array(16).fill(0);
    for (let c = 0; c < 4; c += 1) {
      for (let r = 0; r < 4; r += 1) {
        out[c * 4 + r] =
          a[r] * b[c * 4] +
          a[4 + r] * b[c * 4 + 1] +
          a[8 + r] * b[c * 4 + 2] +
          a[12 + r] * b[c * 4 + 3];
      }
    }
    return out;
  }

  function perspective(fov, aspect, near, far) {
    const f = 1 / Math.tan(fov / 2);
    const nf = 1 / (near - far);
    return [
      f / aspect, 0, 0, 0,
      0, f, 0, 0,
      0, 0, (far + near) * nf, -1,
      0, 0, 2 * far * near * nf, 0,
    ];
  }

  function rotation(yaw, pitch) {
    const cy = Math.cos(yaw);
    const sy = Math.sin(yaw);
    const cx = Math.cos(pitch);
    const sx = Math.sin(pitch);
    const ry = [cy, 0, -sy, 0, 0, 1, 0, 0, sy, 0, cy, 0, 0, 0, 0, 1];
    const rx = [1, 0, 0, 0, 0, cx, sx, 0, 0, -sx, cx, 0, 0, 0, 0, 1];
    return multiply(rx, ry);
  }

  function meshFrom(spec) {
    const positions = [];
    const normals = [];

    function tri(a, b, c, n) {
      [a, b, c].forEach((p) => {
        positions.push(p[0], p[1], p[2]);
        normals.push(n[0], n[1], n[2]);
      });
    }

    function face(p0, p1, p2, p3, n) {
      tri(p0, p1, p2, n);
      tri(p0, p2, p3, n);
    }

    function box(cx, cy, cz, sx, sy, sz) {
      const x = sx / 2;
      const y = sy / 2;
      const z = sz / 2;
      const v = [
        [cx - x, cy - y, cz - z],
        [cx + x, cy - y, cz - z],
        [cx + x, cy + y, cz - z],
        [cx - x, cy + y, cz - z],
        [cx - x, cy - y, cz + z],
        [cx + x, cy - y, cz + z],
        [cx + x, cy + y, cz + z],
        [cx - x, cy + y, cz + z],
      ];
      face(v[4], v[5], v[6], v[7], [0, 0, 1]);
      face(v[1], v[0], v[3], v[2], [0, 0, -1]);
      face(v[5], v[1], v[2], v[6], [1, 0, 0]);
      face(v[0], v[4], v[7], v[3], [-1, 0, 0]);
      face(v[3], v[2], v[6], v[7], [0, 1, 0]);
      face(v[0], v[1], v[5], v[4], [0, -1, 0]);
    }

    function cylinder(y0, y1, radius, count) {
      const n = count || 32;
      for (let i = 0; i < n; i += 1) {
        const a0 = (i / n) * Math.PI * 2;
        const a1 = ((i + 1) / n) * Math.PI * 2;
        const x0 = Math.cos(a0) * radius;
        const z0 = Math.sin(a0) * radius;
        const x1 = Math.cos(a1) * radius;
        const z1 = Math.sin(a1) * radius;
        const n0 = [Math.cos(a0), 0, Math.sin(a0)];
        const n1 = [Math.cos(a1), 0, Math.sin(a1)];
        positions.push(x0, y0, z0, x1, y0, z1, x1, y1, z1);
        normals.push(n0[0], n0[1], n0[2], n1[0], n1[1], n1[2], n1[0], n1[1], n1[2]);
        positions.push(x0, y0, z0, x1, y1, z1, x0, y1, z0);
        normals.push(n0[0], n0[1], n0[2], n1[0], n1[1], n1[2], n0[0], n0[1], n0[2]);
        tri([0, y0, 0], [x1, y0, z1], [x0, y0, z0], [0, -1, 0]);
        tri([0, y1, 0], [x0, y1, z0], [x1, y1, z1], [0, 1, 0]);
      }
    }

    if (spec.shape === "frame") {
      const [width, height, thick] = spec.params.outer_mm;
      const [openingW, openingH] = spec.params.opening_mm;
      const borderX = (width - openingW) / 2;
      const borderY = (height - openingH) / 2;
      box(-width / 2 + borderX / 2, 0, 0, borderX, height, thick);
      box(width / 2 - borderX / 2, 0, 0, borderX, height, thick);
      box(0, -height / 2 + borderY / 2, 0, openingW, borderY, thick);
      box(0, height / 2 - borderY / 2, 0, openingW, borderY, thick);
    } else if (spec.shape === "plate") {
      const [width, height, thick] = spec.params.size_mm;
      box(0, 0, 0, width, height, thick);
    } else if (spec.shape === "shaft") {
      const segments = spec.params.segments_mm;
      const total = segments.reduce((sum, seg) => sum + seg.length, 0);
      let y = -total / 2;
      segments.forEach((seg) => {
        cylinder(y, y + seg.length, seg.diameter / 2);
        y += seg.length;
      });
    }

    let max = 1;
    for (let i = 0; i < positions.length; i += 1) max = Math.max(max, Math.abs(positions[i]));
    const scale = 1.35 / max;
    for (let i = 0; i < positions.length; i += 1) positions[i] *= scale;
    return { positions: new Float32Array(positions), normals: new Float32Array(normals) };
  }

  function compile(gl, type, source) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      throw new Error(gl.getShaderInfoLog(shader));
    }
    return shader;
  }

  function create(canvas) {
    const gl = canvas.getContext("webgl", { antialias: true, alpha: false });
    if (!gl) return { setSpec() {}, stop() {} };
    const program = gl.createProgram();
    const vs = compile(gl, gl.VERTEX_SHADER, `
      attribute vec3 aPos;
      attribute vec3 aNrm;
      uniform mat4 uMvp;
      uniform mat3 uN;
      varying vec3 vN;
      void main() {
        vN = uN * aNrm;
        gl_Position = uMvp * vec4(aPos, 1.0);
      }
    `);
    const fs = compile(gl, gl.FRAGMENT_SHADER, `
      precision mediump float;
      varying vec3 vN;
      uniform vec3 uColor;
      void main() {
        vec3 n = normalize(vN);
        float shade = 0.32 + 0.68 * max(dot(n, normalize(vec3(0.35, 0.75, 0.55))), 0.0);
        float fill = 0.18 * max(dot(n, normalize(vec3(-0.4, -0.2, -0.4))), 0.0);
        gl_FragColor = vec4(uColor * (shade + fill), 1.0);
      }
    `);
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    gl.useProgram(program);
    gl.enable(gl.DEPTH_TEST);
    gl.clearColor(0.93, 0.91, 0.86, 1);

    const posBuf = gl.createBuffer();
    const nrmBuf = gl.createBuffer();
    let count = 0;
    let yaw = 0.6;
    let pitch = 0.45;
    let distance = 3.4;
    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    let auto = true;
    let frame = 0;
    const color = [0.45, 0.52, 0.56];

    function resize() {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
      gl.viewport(0, 0, canvas.width, canvas.height);
    }

    function draw() {
      resize();
      if (auto && !dragging) yaw += 0.008;
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      if (!count) {
        frame = requestAnimationFrame(draw);
        return;
      }
      const aspect = canvas.width / canvas.height;
      const proj = perspective(0.7, aspect, 0.1, 20);
      const rot = rotation(yaw, pitch);
      const view = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, -distance, 1];
      const mvp = multiply(proj, multiply(view, rot));
      gl.uniformMatrix4fv(gl.getUniformLocation(program, "uMvp"), false, new Float32Array(mvp));
      const normal = [rot[0], rot[1], rot[2], rot[4], rot[5], rot[6], rot[8], rot[9], rot[10]];
      gl.uniformMatrix3fv(gl.getUniformLocation(program, "uN"), false, new Float32Array(normal));
      gl.uniform3fv(gl.getUniformLocation(program, "uColor"), color);
      gl.drawArrays(gl.TRIANGLES, 0, count);
      frame = requestAnimationFrame(draw);
    }

    canvas.addEventListener("pointerdown", (event) => {
      dragging = true;
      auto = false;
      lastX = event.clientX;
      lastY = event.clientY;
      canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener("pointerup", () => { dragging = false; });
    canvas.addEventListener("pointermove", (event) => {
      if (!dragging) return;
      yaw += (event.clientX - lastX) * 0.01;
      pitch += (event.clientY - lastY) * 0.01;
      pitch = Math.max(-1.2, Math.min(1.2, pitch));
      lastX = event.clientX;
      lastY = event.clientY;
    });
    canvas.addEventListener("wheel", (event) => {
      event.preventDefault();
      distance = Math.max(1.8, Math.min(8, distance + event.deltaY * 0.004));
    }, { passive: false });

    frame = requestAnimationFrame(draw);
    return {
      setSpec(spec) {
        const mesh = meshFrom(spec);
        count = mesh.positions.length / 3;
        gl.bindBuffer(gl.ARRAY_BUFFER, posBuf);
        gl.bufferData(gl.ARRAY_BUFFER, mesh.positions, gl.STATIC_DRAW);
        const posLoc = gl.getAttribLocation(program, "aPos");
        gl.enableVertexAttribArray(posLoc);
        gl.vertexAttribPointer(posLoc, 3, gl.FLOAT, false, 0, 0);
        gl.bindBuffer(gl.ARRAY_BUFFER, nrmBuf);
        gl.bufferData(gl.ARRAY_BUFFER, mesh.normals, gl.STATIC_DRAW);
        const nLoc = gl.getAttribLocation(program, "aNrm");
        gl.enableVertexAttribArray(nLoc);
        gl.vertexAttribPointer(nLoc, 3, gl.FLOAT, false, 0, 0);
        if (spec.shape === "shaft") color.splice(0, 3, 0.62, 0.58, 0.5);
        else if (spec.shape === "plate") color.splice(0, 3, 0.55, 0.6, 0.64);
        else color.splice(0, 3, 0.71, 0.68, 0.6);
        auto = true;
      },
      clear() { count = 0; },
      stop() { cancelAnimationFrame(frame); },
    };
  }

  window.MeridianViewer = { create };
})();
