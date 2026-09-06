/* ---------- Резервная тема ---------- */
        const FALLBACK = {
            rhyme: "красотулечка",
            mood: "нежное",
            palette: ["#f7d9c4", "#e7a3b6", "#c8a2d8"],
            style: "bloom",
            art: "petals",
            image: "",
            video: "",
            svg: "",
            scene: "",
            font: "playfair",
            anim: "cascade",
            date: null
        };

        /* ---------- Композиции mesh-фона ---------- */
        const STYLES = {
            aurora: [[12, 18, 62], [88, 8, 58], [50, 92, 72], [92, 78, 52]],
            mesh:   [[18, 22, 58], [82, 18, 58], [22, 82, 58], [80, 78, 58]],
            dawn:   [[50, -5, 95], [8, 28, 62], [92, 38, 62], [50, 86, 54]],
            dusk:   [[50, 105, 95], [12, 68, 62], [88, 58, 62], [50, 12, 54]],
            bloom:  [[28, 28, 52], [72, 32, 52], [50, 78, 62], [14, 86, 46]],
            frost:  [[8, 8, 52], [92, 12, 52], [48, 52, 72], [86, 92, 52]]
        };

        /* ---------- Шрифты дня (все с кириллицей) ---------- */
        const FONTS = {
            playfair:    { fam: "Playfair Display", fb: "serif",      spec: "Playfair+Display:ital,wght@0,500;0,600;1,500" },
            yeseva:      { fam: "Yeseva One",       fb: "serif",      spec: "Yeseva+One" },
            prata:       { fam: "Prata",            fb: "serif",      spec: "Prata" },
            marck:       { fam: "Marck Script",     fb: "cursive",    spec: "Marck+Script" },
            caveat:      { fam: "Caveat",           fb: "cursive",    spec: "Caveat:wght@500;700" },
            pacifico:    { fam: "Pacifico",         fb: "cursive",    spec: "Pacifico" },
            comfortaa:   { fam: "Comfortaa",        fb: "sans-serif", spec: "Comfortaa:wght@500;700" },
            unbounded:   { fam: "Unbounded",        fb: "sans-serif", spec: "Unbounded:wght@500;700" },
            philosopher: { fam: "Philosopher",      fb: "serif",      spec: "Philosopher:ital,wght@0,700;1,700" },
            lobster:     { fam: "Lobster",          fb: "cursive",    spec: "Lobster" }
        };

        const ANIMS = ["cascade", "fade", "blur", "scale", "drop", "glow", "wave"];

        /* ---------- Цветовые утилиты ---------- */
        const HEX = /^#?[0-9a-fA-F]{6}$/;
        const clamp255 = v => Math.max(0, Math.min(255, Math.round(v)));
        const normHex = h => HEX.test(h || "") ? "#" + h.replace("#", "").toLowerCase() : null;
        const toRgb = h => { h = h.replace("#", ""); return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)); };
        const toHex = a => "#" + a.map(v => clamp255(v).toString(16).padStart(2, "0")).join("");
        const rgba = (h, a) => { const [r, g, b] = toRgb(h); return `rgba(${r},${g},${b},${a})`; };
        const lin = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
        const lum = h => { const [r, g, b] = toRgb(h); return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b); };
        const mix = (a, b, t) => { const A = toRgb(a), B = toRgb(b); return toHex([0, 1, 2].map(i => A[i] + (B[i] - A[i]) * t)); };
        const contrast = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
        let rhymeBaseAccent = FALLBACK.palette[1];
        let nameBaseColor = "#6a5f5a";

        function toHsl([r, g, b]) {
            r /= 255; g /= 255; b /= 255;
            const max = Math.max(r, g, b), min = Math.min(r, g, b);
            let h = 0, s = 0, l = (max + min) / 2;
            if (max !== min) {
                const d = max - min;
                s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
                if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
                else if (max === g) h = (b - r) / d + 2;
                else h = (r - g) / d + 4;
                h /= 6;
            }
            return [h * 360, s, l];
        }
        function hslToHex(h, s, l) {
            h /= 360;
            const f = t => {
                if (t < 0) t += 1; if (t > 1) t -= 1;
                if (t < 1 / 6) return p + (q - p) * 6 * t;
                if (t < 1 / 2) return q;
                if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
                return p;
            };
            const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
            const p = 2 * l - q;
            return toHex([f(h + 1 / 3), f(h), f(h - 1 / 3)].map(v => v * 255));
        }
        const sat = h => toHsl(toRgb(h))[1];

        /* ---------- Тема из палитры ---------- */
        function applyTheme(t) {
            let palette = (Array.isArray(t.palette) ? t.palette : []).map(normHex).filter(Boolean);
            if (palette.length < 2) palette = FALLBACK.palette.map(normHex);
            const style = STYLES[t.style] ? t.style : "bloom";

            const avg = palette.reduce((s, c) => s + lum(c), 0) / palette.length;
            const dark = avg < 0.42;

            const tint = palette.reduce((acc, c, i) => mix(acc, c, 1 / (i + 1)), palette[0]);
            const canvas  = dark ? mix("#0e0b12", tint, 0.22) : mix("#fbf8f5", tint, 0.10);
            const ink     = dark ? mix("#ffffff", tint, 0.10) : mix("#1c1614", tint, 0.12);
            const inkSoft = mix(ink, canvas, 0.42);
            const line    = mix(ink, canvas, 0.72);

            let accent = palette.slice().sort((a, b) =>
                (sat(b) + contrast(b, canvas) / 21) - (sat(a) + contrast(a, canvas) / 21))[0];
            let guard = 0;
            while (contrast(accent, canvas) < 3.4 && guard++ < 30) {
                const [h, s, l] = toHsl(toRgb(accent));
                accent = hslToHex(h, Math.min(1, s + 0.02), dark ? Math.min(0.94, l + 0.04) : Math.max(0.10, l - 0.04));
            }

            const alpha = dark ? 0.58 : 0.62;
            const mesh = STYLES[style].map((b, i) =>
                `radial-gradient(circle at ${b[0]}% ${b[1]}%, ${rgba(palette[i % palette.length], alpha)} 0%, transparent ${b[2]}%)`
            ).join(", ");

            const r = document.documentElement.style;
            r.setProperty("--canvas", canvas);
            r.setProperty("--ink", ink);
            r.setProperty("--ink-soft", inkSoft);
            r.setProperty("--accent", accent);
            r.setProperty("--line", line);
            r.setProperty("--mesh", mesh);
            rhymeBaseAccent = accent;
            nameBaseColor = inkSoft;
            applyRhymeContrast(palette.map(c => mix(canvas, c, alpha)));
        }

        /* ---------- Генеративный арт (seed из рифмы) ---------- */
        function hashStr(s) {
            let h = 2166136261;
            for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
            return h >>> 0;
        }
        function mulberry32(a) {
            return function () {
                a |= 0; a = a + 0x6D2B79F5 | 0;
                let t = Math.imul(a ^ a >>> 15, 1 | a);
                t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
                return ((t ^ t >>> 14) >>> 0) / 4294967296;
            };
        }
        const SVG = inner =>
            `<svg viewBox="0 0 1000 1000" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg" width="100%" height="100%">${inner}</svg>`;

        const ART = {
            constellation: (rnd, pal) => {
                const R = (a, b) => a + rnd() * (b - a);
                const pts = [];
                const n = Math.round(R(26, 40));
                for (let i = 0; i < n; i++) pts.push([R(40, 960), R(40, 960), R(1.2, 3.2)]);
                let s = "";
                for (let i = 0; i < pts.length; i++)
                    for (let j = i + 1; j < pts.length; j++) {
                        const d = Math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]);
                        if (d < 175)
                            s += `<line x1="${pts[i][0].toFixed(1)}" y1="${pts[i][1].toFixed(1)}" x2="${pts[j][0].toFixed(1)}" y2="${pts[j][1].toFixed(1)}" stroke="${pal[i % pal.length]}" stroke-width="0.8" stroke-opacity="0.32"/>`;
                    }
                s += pts.map((p, i) => `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="${p[2].toFixed(1)}" fill="${pal[i % pal.length]}" fill-opacity="0.7"/>`).join("");
                return SVG(s);
            },
            petals: (rnd, pal) => {
                const R = (a, b) => a + rnd() * (b - a);
                const cx = 500, cy = 500; let s = "";
                const rings = Math.round(R(3, 5));
                for (let r = 0; r < rings; r++) {
                    const k = Math.round(R(8, 14));
                    const rad = 120 + r * 120 + R(-20, 20);
                    const pl = R(45, 95), pw = R(16, 40), col = pal[r % pal.length];
                    for (let i = 0; i < k; i++) {
                        const ang = (360 / k) * i + R(-4, 4);
                        s += `<ellipse cx="${cx}" cy="${(cy - rad).toFixed(1)}" rx="${pw.toFixed(1)}" ry="${pl.toFixed(1)}" fill="none" stroke="${col}" stroke-width="1" stroke-opacity="0.38" transform="rotate(${ang.toFixed(1)} ${cx} ${cy})"/>`;
                    }
                }
                return SVG(s);
            },
            waves: (rnd, pal) => {
                const R = (a, b) => a + rnd() * (b - a); let s = "";
                const lines = Math.round(R(10, 16));
                for (let l = 0; l < lines; l++) {
                    const y = 60 + l * (880 / lines), amp = R(10, 40), wl = R(120, 260), ph = R(0, Math.PI * 2);
                    let d = `M0 ${y.toFixed(1)}`;
                    for (let x = 0; x <= 1000; x += 20) d += ` L${x} ${(y + Math.sin((x / wl) * Math.PI * 2 + ph) * amp).toFixed(1)}`;
                    s += `<path d="${d}" fill="none" stroke="${pal[l % pal.length]}" stroke-width="1" stroke-opacity="0.3"/>`;
                }
                return SVG(s);
            },
            orbits: (rnd, pal) => {
                const R = (a, b) => a + rnd() * (b - a);
                const cx = R(380, 620), cy = R(380, 620); let s = "";
                const n = Math.round(R(7, 12));
                for (let i = 0; i < n; i++) {
                    const rx = 60 + i * 60 + R(-10, 10), ry = rx * R(0.55, 0.95), rot = R(0, 180);
                    s += `<ellipse cx="${cx.toFixed(0)}" cy="${cy.toFixed(0)}" rx="${rx.toFixed(0)}" ry="${ry.toFixed(0)}" fill="none" stroke="${pal[i % pal.length]}" stroke-width="0.9" stroke-opacity="0.32" transform="rotate(${rot.toFixed(0)} ${cx.toFixed(0)} ${cy.toFixed(0)})"/>`;
                }
                return SVG(s);
            },
            lattice: (rnd, pal) => {
                const R = (a, b) => a + rnd() * (b - a);
                const cx = 500, cy = 500; let s = "";
                const loops = Math.round(R(3, 5));
                for (let g = 0; g < loops; g++) {
                    const Rr = R(200, 360), rr = R(50, 120), dd = R(50, 140), col = pal[g % pal.length];
                    let pts = ""; const steps = 900;
                    for (let i = 0; i <= steps; i++) {
                        const tt = i / steps * Math.PI * 2 * 7;
                        const x = cx + (Rr - rr) * Math.cos(tt) + dd * Math.cos(((Rr - rr) / rr) * tt);
                        const y = cy + (Rr - rr) * Math.sin(tt) - dd * Math.sin(((Rr - rr) / rr) * tt);
                        pts += x.toFixed(1) + "," + y.toFixed(1) + " ";
                    }
                    s += `<polyline points="${pts.trim()}" fill="none" stroke="${col}" stroke-width="0.7" stroke-opacity="0.28"/>`;
                }
                return SVG(s);
            },
            rays: (rnd, pal) => {
                const R = (a, b) => a + rnd() * (b - a);
                const cx = R(200, 800), cy = R(150, 420); let s = "";
                const n = Math.round(R(44, 72));
                for (let i = 0; i < n; i++) {
                    const ang = R(0, Math.PI * 2), len = R(200, 720);
                    s += `<line x1="${cx.toFixed(0)}" y1="${cy.toFixed(0)}" x2="${(cx + Math.cos(ang) * len).toFixed(1)}" y2="${(cy + Math.sin(ang) * len).toFixed(1)}" stroke="${pal[i % pal.length]}" stroke-width="0.6" stroke-opacity="0.2"/>`;
                }
                return SVG(s);
            }
        };
        const STYLE_MOTIF = { aurora: "rays", mesh: "lattice", dawn: "waves", dusk: "orbits", bloom: "petals", frost: "constellation" };

        // Чистим SVG от Gemini: убираем опасное, но СОХРАНЯЕМ defs/use и локальные #-ссылки
        function sanitizeSVG(raw) {
            if (typeof raw !== "string") return null;
            const m = raw.match(/<svg[\s\S]*<\/svg>/i);
            if (!m) return null;
            let doc;
            try { doc = new DOMParser().parseFromString(m[0], "image/svg+xml"); }
            catch (e) { return null; }
            if (doc.querySelector("parsererror")) return null;
            const svg = doc.documentElement;
            if (!svg || svg.nodeName.toLowerCase() !== "svg") return null;

            // Удаляем реально опасное (use, defs и SMIL-анимацию ОСТАВЛЯЕМ — её чистим ниже)
            svg.querySelectorAll("script,foreignObject,iframe,image,a,style,text,tspan,textPath")
                .forEach(n => n.remove());

            const walk = el => {
                [...el.attributes].forEach(attr => {
                    const name = attr.name.toLowerCase(), val = attr.value.trim().toLowerCase();
                    if (name.startsWith("on")) el.removeAttribute(attr.name);
                    else if (name === "href" || name === "xlink:href") {
                        if (!val.startsWith("#")) el.removeAttribute(attr.name);   // только локальные ссылки
                    }
                    else if (val.includes("javascript:")) el.removeAttribute(attr.name);
                    else if (val.includes("url(") && val.includes("http")) el.removeAttribute(attr.name);
                });
                [...el.children].forEach(walk);
            };
            walk(svg);

            // Сплошная фоновая заливка во весь холст — убираем
            svg.querySelectorAll("rect").forEach(r => {
                const w = parseFloat(r.getAttribute("width") || "0");
                const h = parseFloat(r.getAttribute("height") || "0");
                const pct = /%/.test(r.getAttribute("width") || "") || /%/.test(r.getAttribute("height") || "");
                const fill = (r.getAttribute("fill") || "").toLowerCase();
                if ((pct || (w >= 900 && h >= 900)) && fill && fill !== "none") r.remove();
            });

            // Разрешаем безопасную SMIL-анимацию: только transform/opacity/stroke-* и т.п.,
            // НИКАКИХ href/событий/javascript: — иначе удаляем сам анимирующий узел.
            const SAFE_ANIM = new Set(["transform", "opacity", "fill", "fill-opacity",
                "stroke", "stroke-opacity", "stroke-width", "stroke-dashoffset", "stroke-dasharray",
                "r", "cx", "cy", "x", "y", "x1", "y1", "x2", "y2", "rx", "ry", "width", "height",
                "d", "points", "offset", "stop-color", "stop-opacity", "gradienttransform"]);
            const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
            svg.querySelectorAll("animate, animateTransform, animateMotion, set").forEach(el => {
                if (reduceMotion) { el.remove(); return; }   // уважаем «меньше движения»
                const an = (el.getAttribute("attributeName") || "").trim().toLowerCase();
                if (an && !SAFE_ANIM.has(an)) { el.remove(); return; }
                ["values", "from", "to", "by"].forEach(a => {
                    const v = (el.getAttribute(a) || "").toLowerCase();
                    if (v.includes("javascript:") || (v.includes("url(") && v.includes("http"))) el.remove();
                });
            });

            if (!svg.querySelector("path,circle,ellipse,line,polyline,polygon,rect,use")) return null;

            if (!svg.getAttribute("viewBox")) svg.setAttribute("viewBox", "0 0 1000 1000");
            svg.setAttribute("preserveAspectRatio", "xMidYMid slice");
            svg.setAttribute("width", "100%");
            svg.setAttribute("height", "100%");
            return svg.outerHTML;
        }

        // Оборачиваем содержимое в группу для вращения и заставляем кружки мерцать
        const SVGNS = "http://www.w3.org/2000/svg";
        function animateArt(host, motifClass, rnd) {
            const svg = host.querySelector("svg");
            if (!svg) return;
            const g = document.createElementNS(SVGNS, "g");
            g.setAttribute("class", "art-spin " + motifClass);
            while (svg.firstChild) g.appendChild(svg.firstChild);
            svg.appendChild(g);
            svg.querySelectorAll("circle").forEach(c => {           // мерцание точек/звёзд
                c.classList.add("tw");
                const r = rnd();
                c.style.animationDelay = (r * 4).toFixed(2) + "s";
                c.style.animationDuration = (3 + r * 3).toFixed(2) + "s";
            });
        }

        // Приводим цвета SVG к палитре дня (структуру цветов сохраняем, гамму — к фоновой)
        function recolorArt(host, palette, dark) {
            const mixTo = dark ? "#ffffff" : "#2a2024";
            const pal = palette.map(c => mix(c, mixTo, dark ? 0.16 : 0.28));
            const map = new Map();
            let idx = 0;
            const pick = v => {
                if (!map.has(v)) { map.set(v, pal[idx % pal.length]); idx++; }
                return map.get(v);
            };
            host.querySelectorAll("*").forEach(el => {
                ["stroke", "fill"].forEach(attr => {
                    const v = (el.getAttribute(attr) || "").trim().toLowerCase();
                    if (v && v !== "none" && v !== "transparent" && !v.startsWith("url(")) el.setAttribute(attr, pick(v));
                });
                let st = el.getAttribute("style");
                if (st && /(stroke|fill)\s*:/i.test(st)) {
                    st = st.replace(/(stroke|fill)\s*:\s*([^;]+)/gi, (m, p, val) => {
                        val = val.trim().toLowerCase();
                        if (val && val !== "none" && val !== "transparent" && !val.startsWith("url(")) return p + ":" + pick(val);
                        return m;
                    });
                    el.setAttribute("style", st);
                }
            });
        }

        /* ---------- Живая JS-сцена от Gemini в изолированной песочнице ----------
           Код выполняется в <iframe sandbox="allow-scripts"> с CSP default-src 'none':
           нет доступа к странице, нет сети. Gemini доступны: ctx, W(), H(), PALETTE, MOOD, DARK. */
        function buildSceneDoc(code, palette, mood, dark) {
            const safe = String(code).replace(/<\/script/gi, "<\\/script");
            return '<!DOCTYPE html><html><head>'
                + '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data: blob:;">'
                + '<style>html,body{margin:0;height:100%;overflow:hidden;background:transparent}canvas{display:block;width:100vw;height:100vh}</style>'
                + '</head><body><canvas id="c"></canvas><script>(function(){try{'
                + 'var PALETTE=' + JSON.stringify(palette) + ',MOOD=' + JSON.stringify(mood) + ',DARK=' + (dark ? 'true' : 'false') + ';'
                + 'var canvas=document.getElementById("c"),ctx=canvas.getContext("2d"),DPR=Math.min(window.devicePixelRatio||1,2);'
                + 'function W(){return window.innerWidth}function H(){return window.innerHeight}'
                + 'function fit(){canvas.width=W()*DPR;canvas.height=H()*DPR;ctx.setTransform(DPR,0,0,DPR,0,0);}'
                + 'window.addEventListener("resize",fit);fit();'
                + safe
                + '}catch(e){}})();<\/script></body></html>';
        }

        // Фон: AI-изображение может сочетаться с прозрачной живой сценой поверх.
        // Без изображения сохраняется прежний выбор scene либо SVG/параметрики.
        function renderBackdrop(t) {
            const art = document.getElementById("art");
            const scene = document.getElementById("scene");
            const imageLayer = document.getElementById("image-backdrop");
            const imageEl = document.getElementById("image-bg");
            const videoEl = document.getElementById("video-bg");
            let palette = (Array.isArray(t.palette) ? t.palette : []).map(normHex).filter(Boolean);
            if (palette.length < 2) palette = FALLBACK.palette.map(normHex);
            const avg = palette.reduce((s, c) => s + lum(c), 0) / palette.length;
            const dark = avg < 0.42;
            const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
            const code = (!reducedMotion && typeof t.scene === "string" && t.scene.trim().length > 20) ? t.scene : null;
            const imagePath = (typeof t.image === "string" && /^art\/\d{4}-\d{2}-\d{2}\.webp$/.test(t.image)) ? t.image : null;
            const videoPath = (typeof t.video === "string" && /^art\/\d{4}-\d{2}-\d{2}\.mp4$/.test(t.video)) ? t.video : null;
            imageLayer.style.setProperty("--backdrop-image", imagePath ? `url("${imagePath}")` : "none");

            if (art) { art.style.opacity = 0; art.innerHTML = ""; }
            if (scene) { scene.hidden = true; scene.style.opacity = 0; scene.removeAttribute("srcdoc"); }
            if (imageLayer) { imageLayer.style.opacity = 0; imageLayer.classList.remove("has-video"); }
            if (imageEl) {
                imageEl.onload = null; imageEl.onerror = null;
                imageEl.style.opacity = 0;
                if (!imagePath) imageEl.removeAttribute("src");
            }
            if (videoEl) {
                videoEl.pause();
                videoEl.oncanplay = null; videoEl.onloadeddata = null; videoEl.ontimeupdate = null; videoEl.onerror = null;
                videoEl.style.opacity = 0;
                videoEl.removeAttribute("src"); videoEl.removeAttribute("poster");
                videoEl.load();
            }

            if ((imagePath || videoPath) && imageLayer && imageEl) {
                const wash = toRgb(dark ? mix(palette[0], "#ffffff", 0.68) : mix(palette[0], "#ffffff", 0.84));
                imageLayer.style.setProperty("--wash-rgb", wash.join(","));
                imageLayer.style.setProperty("--glow-a", rgba(palette[0], 0.42));
                imageLayer.style.setProperty("--glow-b", rgba(palette[palette.length - 1], 0.36));
                imageEl.onload = () => {
                    imageEl.style.opacity = 1;
                    imageLayer.style.opacity = dark ? 0.82 : 0.76;
                    requestAnimationFrame(() => sampleBackdropForRhyme(imageEl));
                };
                imageEl.onerror = () => { imageLayer.style.opacity = 0; };
                if (imagePath) imageEl.src = imagePath;

                if (videoPath && videoEl) {
                    const reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
                    imageLayer.classList.add("has-video");
                    if (imagePath) videoEl.poster = imagePath;
                    const revealVideo = () => {
                        imageLayer.style.opacity = dark ? 0.84 : 0.8;
                        if (reduced) {
                            videoEl.pause();
                            videoEl.currentTime = 0;
                        } else {
                            videoEl.style.opacity = 1;
                            videoEl.play().catch(() => { videoEl.style.opacity = 0; });
                        }
                        requestAnimationFrame(() => sampleBackdropForRhyme(videoEl));
                    };
                    videoEl.oncanplay = revealVideo;
                    videoEl.onloadeddata = () => { if (reduced) revealVideo(); };
                    let lastContrastSample = 0;
                    videoEl.ontimeupdate = () => {
                        const now = performance.now();
                        if (now - lastContrastSample < 1400) return;
                        lastContrastSample = now;
                        sampleBackdropForRhyme(videoEl);
                    };
                    videoEl.onerror = () => {
                        videoEl.style.opacity = 0;
                        imageLayer.classList.remove("has-video");
                    };
                    videoEl.src = videoPath;
                    videoEl.load();
                }

                if (!videoPath && code && scene) {
                    const pal = palette.map(c => mix(c, dark ? "#ffffff" : "#2a2024", dark ? 0.22 : 0.34));
                    scene.srcdoc = buildSceneDoc(code, pal, t.mood || "", dark);
                    scene.hidden = false;
                    requestAnimationFrame(() => { scene.style.opacity = dark ? 0.46 : 0.38; });
                } else if (!videoPath) {
                    renderArt(t);
                    if (art) art.style.opacity = dark ? 0.3 : 0.24;
                }
                return;
            }

            if (code && scene) {
                const pal = palette.map(c => mix(c, dark ? "#ffffff" : "#2a2024", dark ? 0.16 : 0.28));
                scene.srcdoc = buildSceneDoc(code, pal, t.mood || "", dark);
                scene.hidden = false;
                requestAnimationFrame(() => { scene.style.opacity = dark ? 0.7 : 0.62; });
            } else {
                renderArt(t);
            }
        }

        function renderArt(t) {
            const host = document.getElementById("art");
            if (!host) return;
            let palette = (Array.isArray(t.palette) ? t.palette : []).map(normHex).filter(Boolean);
            if (palette.length < 2) palette = FALLBACK.palette.map(normHex);
            const avg = palette.reduce((s, c) => s + lum(c), 0) / palette.length;
            const dark = avg < 0.42;
            const rnd = mulberry32(hashStr((t.rhyme || "") + "·art"));

            let svg = sanitizeSVG(t.svg);
            const gemini = !!svg;
            let motifClass = null;
            if (gemini) {
                // Если Gemini сам встроил SMIL-анимацию — оставляем ЕЁ, свою не добавляем.
                motifClass = /<animate/i.test(svg) ? null : "art-gen";
            } else {
                const mixTo = dark ? "#ffffff" : "#2a2024";
                const artPal = palette.map(c => mix(c, mixTo, dark ? 0.18 : 0.32));
                const motif = ART[t.art] ? t.art : (STYLE_MOTIF[t.style] || "petals");
                svg = ART[motif](mulberry32(hashStr((t.rhyme || "") + "·" + motif)), artPal);
                motifClass = "art-" + motif;
            }
            host.innerHTML = svg;
            host.style.opacity = dark ? 0.7 : 0.62;
            if (gemini) recolorArt(host, palette, dark);   // SVG от Gemini красим в палитру дня
            if (motifClass) animateArt(host, motifClass, rnd);
        }

        /* ---------- Шрифт дня ---------- */
        function applyFont(key) {
            key = ({unbounded: "comfortaa", lobster: "playfair", pacifico: "marck"})[key] || key;
            const f = FONTS[key] || FONTS.playfair;
            const id = "font-" + f.spec.replace(/[^a-z]/gi, "").toLowerCase();
            if (!document.getElementById(id)) {
                const l = document.createElement("link");
                l.id = id; l.rel = "stylesheet";
                l.href = `https://fonts.googleapis.com/css2?family=${f.spec}&display=swap`;
                // ВАЖНО: пока стилшит не загружен, @font-face ещё не объявлен и
                // document.fonts.load(...) резолвится мгновенно и впустую — слово мерилось
                // запасным шрифтом и вылезало за экран. Ждём сам файл шрифта после onload.
                l.addEventListener("load", () => {
                    if (document.fonts && document.fonts.load) {
                        document.fonts.load(`1em "${f.fam}"`).then(fitRhyme).catch(() => {});
                    }
                });
                document.head.appendChild(l);
            }
            document.documentElement.style.setProperty("--rhyme-font", `"${f.fam}", ${f.fb}`);
            if (document.fonts && document.fonts.load) {
                document.fonts.load(`1em "${f.fam}"`).then(fitRhyme).catch(() => {});
            }
        }

        /* ---------- Анимация появления ---------- */
        function applyAnim(key) {
            ANIMS.forEach(a => rhymeEl.classList.remove("anim-" + a));
            rhymeEl.classList.add("anim-" + (ANIMS.includes(key) ? key : "cascade"));
        }

        /* ---------- Вывод рифмы ---------- */
        const rhymeEl = document.getElementById("rhyme");

        // Подбираем светлоту акцента по реальному участку картинки под рифмой,
        // сохраняя оттенок палитры дня. Контур берём противоположной светлоты:
        // он страхует буквы на неоднородных изображениях и движущемся видео.
        function applyRhymeContrast(backgrounds, target = "both") {
            const samples = (backgrounds || []).map(normHex).filter(Boolean);
            if (!samples.length) samples.push(getComputedStyle(document.documentElement).getPropertyValue("--canvas").trim());
            const pickReadableTone = (base, minSaturation) => {
                const [h, s, originalL] = toHsl(toRgb(base));
                let chosen = base, bestScore = -Infinity;
                for (let i = 14; i <= 88; i += 2) {
                    const candidate = hslToHex(h, Math.max(minSaturation, s), i / 100);
                    const minimum = Math.min(...samples.map(bg => contrast(candidate, bg)));
                    const score = Math.min(minimum, 4.5) - Math.abs(i / 100 - originalL) * 1.5;
                    if (score > bestScore) { chosen = candidate; bestScore = score; }
                }
                return chosen;
            };
            const best = pickReadableTone(rhymeBaseAccent, 0.38);
            const nameColor = pickReadableTone(nameBaseColor, 0.12);
            const lightText = lum(best) > 0.46;
            const lightName = lum(nameColor) > 0.46;
            const mixed = Math.max(...samples.map(lum)) - Math.min(...samples.map(lum)) > 0.22;
            const edgeAlpha = mixed ? 0.76 : 0.62;
            const root = document.documentElement.style;
            if (target !== "name") {
            root.setProperty("--accent", best);
            root.setProperty("--rhyme-edge", lightText
                ? `rgba(18,12,16,${edgeAlpha})`
                : `rgba(255,252,247,${edgeAlpha})`);
            root.setProperty("--rhyme-shadow", lightText
                ? "rgba(255,255,255,0.26)"
                : "rgba(20,12,16,0.42)");
            }
            if (target !== "rhyme") {
            root.setProperty("--name-color", nameColor);
            root.setProperty("--name-edge", lightName
                ? "rgba(18,12,16,0.46)"
                : "rgba(255,252,247,0.48)");
            }
        }

        function sampleBackdropForRhyme(media, target = "rhyme") {
            if (!media || !rhymeEl || !rhymeEl.clientWidth) return;
            const sourceW = media.videoWidth || media.naturalWidth;
            const sourceH = media.videoHeight || media.naturalHeight;
            if (!sourceW || !sourceH) return;
            const mediaRect = media.getBoundingClientRect();
            const textRect = (target === "name" ? document.querySelector(".card") : rhymeEl).getBoundingClientRect();
            const fit = getComputedStyle(media).objectFit === "contain" ? Math.min : Math.max;
            const scale = fit(mediaRect.width / sourceW, mediaRect.height / sourceH);
            const cropX = (sourceW - mediaRect.width / scale) / 2;
            const cropY = (sourceH - mediaRect.height / scale) / 2;
            const sx = Math.max(0, cropX + (textRect.left - mediaRect.left) / scale);
            const sy = Math.max(0, cropY + (textRect.top - mediaRect.top) / scale);
            const sw = Math.max(1, Math.min(sourceW - sx, textRect.width / scale));
            const sh = Math.max(1, Math.min(sourceH - sy, textRect.height / scale));
            const canvas = document.createElement("canvas");
            canvas.width = 9; canvas.height = 3;
            const ctx = canvas.getContext("2d", { willReadFrequently: true });
            try {
                ctx.drawImage(media, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
                const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
                const washRaw = getComputedStyle(document.getElementById("image-backdrop"))
                    .getPropertyValue("--wash-rgb").split(",").map(Number);
                const wash = washRaw.length === 3 && washRaw.every(Number.isFinite) ? toHex(washRaw) : "#fbf8f5";
                const samples = [];
                for (let i = 0; i < pixels.length; i += 4) {
                    // Центральный wash действительно лежит поверх медиа; учитываем
                    // его приблизительную прозрачность, чтобы выбирать цвет по тому,
                    // что видит человек, а не по исходному тёмному кадру.
                    const px = textRect.left + ((i / 4) % 9 + .5) * textRect.width / 9;
                    const py = textRect.top + (Math.floor(i / 4 / 9) + .5) * textRect.height / 3;
                    const layerRect = document.getElementById("image-backdrop").getBoundingClientRect();
                    const distance = Math.hypot((px - layerRect.left - layerRect.width * .5) / (layerRect.width * .54), (py - layerRect.top - layerRect.height * .48) / (layerRect.height * .4));
                    const washAlpha = distance < .34 ? .88 + (.64 - .88) * distance / .34 : distance < .72 ? .64 + (.12 - .64) * (distance - .34) / .38 : Math.max(0, .12 * (1 - distance) / .28);
                    samples.push(mix(toHex([pixels[i], pixels[i + 1], pixels[i + 2]]), wash, washAlpha));
                }
                applyRhymeContrast(samples, target);
            } catch (_) {
                // Если браузер запретил чтение кадра, остаётся безопасный вариант темы.
            }
            if (target === "rhyme") sampleBackdropForRhyme(media, "name");
        }

        function refreshRhymeContrast() {
            const video = document.getElementById("video-bg");
            const image = document.getElementById("image-bg");
            if (video && video.style.opacity !== "0" && video.readyState >= 2) sampleBackdropForRhyme(video);
            else if (image && image.complete && image.naturalWidth) sampleBackdropForRhyme(image);
        }
        document.getElementById("poem").addEventListener("toggle", refreshRhymeContrast);

        function setRhyme(word) {
            rhymeEl.style.fontSize = "";
            rhymeEl.textContent = "";
            const parts = String(word).split("-");
            let i = 0;
            const ch = (text) => {
                const s = document.createElement("span");
                s.className = "ch";
                s.textContent = text;
                s.style.animationDelay = (0.25 + i++ * 0.04).toFixed(2) + "s";
                return s;
            };
            parts.forEach((part, pi) => {
                const w = document.createElement("span");
                w.className = "word";
                [...part].forEach(c => w.appendChild(ch(c)));
                if (pi < parts.length - 1) w.appendChild(ch("-"));
                rhymeEl.appendChild(w);
                if (pi < parts.length - 1) {
                    rhymeEl.appendChild(document.createTextNode("​"));
                }
            });
            fitRhyme();
            // страховка: после проигрывания анимации гарантируем, что буквы видимы
            clearTimeout(setRhyme._t);
            setRhyme._t = setTimeout(() => {
                rhymeEl.querySelectorAll(".ch").forEach(s => { s.style.opacity = "1"; });
            }, 2600);
        }

        function fitRhyme() {
            rhymeEl.style.fontSize = "";
            const avail = rhymeEl.clientWidth;
            if (!avail) return;
            const need = rhymeEl.scrollWidth;
            if (need <= avail) {
                requestAnimationFrame(refreshRhymeContrast);
                return;
            }
            // прикидываем размер по соотношению, затем чуть дожимаем — впишется любое слово
            let size = parseFloat(getComputedStyle(rhymeEl).fontSize);
            size = Math.max(12, Math.floor(size * avail / need) - 1);
            rhymeEl.style.fontSize = size + "px";
            let guard = 0;
            while (rhymeEl.scrollWidth > avail + 1 && size > 10 && guard++ < 80) {
                size -= 1;
                rhymeEl.style.fontSize = size + "px";
            }
            requestAnimationFrame(refreshRhymeContrast);
        }

        /* ---------- Дата ---------- */
        const MONTHS = ["января","февраля","марта","апреля","мая","июня",
                        "июля","августа","сентября","октября","ноября","декабря"];
        function setDate(iso) {
            if (!iso) return;
            const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
            if (!m) return;
            const el = document.getElementById("date");
            el.textContent = `${+m[3]} ${MONTHS[+m[2] - 1]} ${m[1]}`;
            el.hidden = false;
        }

        function render(data) {
            currentCard = data;
            applyTheme(data);
            applyFont(data.font);
            applyAnim(data.anim);
            setRhyme(data.rhyme || FALLBACK.rhyme);
            renderBackdrop(data);
            setDate(data.date);
            document.getElementById("poem-text").textContent = (data.verse || []).join("\n");
            document.getElementById("poem").open = false;
            document.getElementById("poem").hidden = !data.verse?.length;
            document.title = `Юлечка — ${data.rhyme || ""}`.trim();
            // аудио озвучено только для сегодняшней (последней) открытки
            if (audioCtl) audioCtl.setCard(data);
        }

        /* ---------- Листание прошлых дней (архив) ---------- */
        let cards = [FALLBACK];        // прошлые дни + сегодня (последняя)
        let idx = 0;
        let currentCard = FALLBACK;
        let audioCtl = null;           // выставляется в setupAudio()

        function show(i) {
            if (i < 0 || i >= cards.length || i === idx) return;
            idx = i;
            render(cards[idx]);
            updateNav();
        }

        function updateNav() {
            const prev = document.getElementById("nav-prev");
            const next = document.getElementById("nav-next");
            if (!prev || !next) return;
            const many = cards.length > 1;
            prev.hidden = next.hidden = !many;
            if (!many) return;
            requestAnimationFrame(() => { prev.classList.add("show"); next.classList.add("show"); });
            prev.style.visibility = idx === 0 ? "hidden" : "";
            next.style.visibility = idx === cards.length - 1 ? "hidden" : "";
        }

        async function loadArchive(today) {
            try {
                const res = await fetch(`archive.json?t=${Date.now()}`);
                if (!res.ok) return;
                const arch = await res.json();
                if (!Array.isArray(arch)) return;
                // последняя открытка каждого прошлого дня (сегодняшняя берётся из data.json)
                const byDate = new Map();
                arch.forEach(c => { if (c && c.date && Array.isArray(c.palette)) byDate.set(c.date, c); });
                if (today.date) byDate.delete(today.date);
                const past = [...byDate.values()].sort((a, b) => (a.date < b.date ? -1 : 1));
                if (!past.length) return;
                cards = [...past, today];
                idx = cards.length - 1;
                updateNav();
            } catch (e) { /* архива может не быть — просто без листания */ }
        }

        document.getElementById("nav-prev").addEventListener("click", () => show(idx - 1));
        document.getElementById("nav-next").addEventListener("click", () => show(idx + 1));
        window.addEventListener("keydown", (e) => {
            if (e.key === "ArrowLeft") show(idx - 1);
            else if (e.key === "ArrowRight") show(idx + 1);
        });

        // Свайп: влево — к более новым, вправо — к прошлым
        let swX = null, swY = null;
        window.addEventListener("touchstart", (e) => {
            swX = e.touches[0].clientX; swY = e.touches[0].clientY;
        }, { passive: true });
        window.addEventListener("touchend", (e) => {
            if (swX === null) return;
            const dx = e.changedTouches[0].clientX - swX;
            const dy = e.changedTouches[0].clientY - swY;
            swX = swY = null;
            if (Math.abs(dx) > 56 && Math.abs(dx) > Math.abs(dy) * 1.6) show(idx + (dx < 0 ? 1 : -1));
        }, { passive: true });

        // Тап по слову дня — буквы переигрывают анимацию появления
        rhymeEl.addEventListener("click", () => setRhyme(currentCard.rhyme || FALLBACK.rhyme));

        let resizeTimer;
        window.addEventListener("resize", () => {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(fitRhyme, 120);
        });
        if (document.fonts && document.fonts.ready) {
            document.fonts.ready.then(fitRhyme);
        }
        // Страховка: любой дозагрузившийся шрифт (в т.ч. шрифт дня) → перемеряем слово
        if (document.fonts && document.fonts.addEventListener) {
            document.fonts.addEventListener("loadingdone", () => fitRhyme());
        }

        // Плеер: круглая кнопка появляется, только если audio.mp3 реально загрузился,
        // и только на сегодняшней открытке (для прошлых дней озвучки нет)
        function setupAudio() {
            const btn = document.getElementById("play");
            const icon = document.getElementById("play-icon");
            const ring = document.getElementById("play-ring");
            if (!btn || !icon) return;
            const PLAY = "M8 5v14l11-7z";
            const PAUSE = "M7 5h3v14H7zM14 5h3v14h-3z";
            const audio = new Audio();
            audio.preload = "metadata";

            let ready = false;      // файл реально есть
            let onToday = true;     // смотрим сегодняшнюю открытку
            const applyVis = () => {
                if (ready && onToday) {
                    btn.hidden = false;
                    requestAnimationFrame(() => btn.classList.add("show"));
                } else {
                    btn.classList.remove("show");
                    btn.hidden = true;
                }
            };
            const reveal = () => { if (!ready) { ready = true; applyVis(); } };
            audioCtl = {
                setCard(card) {
                    audio.pause();
                    ready = false;
                    const src = /^audio\/\d{4}-\d{2}-\d{2}-[a-z0-9]+\.mp3$/.test(card.audio || "") ? card.audio : "";
                    onToday = !!src;
                    if (src) audio.src = src;
                    else audio.removeAttribute("src");
                    audio.load();
                    // The manifest only references successfully published audio.
                    ready = !!src;
                    applyVis();
                }
            };

            // iOS Safari не шлёт canplay/loadeddata без жеста — показываем по факту наличия файла
            audio.addEventListener("error", () => { ready = false; applyVis(); });
            audio.addEventListener("loadeddata", reveal);
            audio.addEventListener("canplay", reveal);
            btn.addEventListener("click", () => {
                if (audio.paused) audio.play().catch(() => {});
                else audio.pause();
            });

            // Кольцо прогресса вокруг кнопки
            const C = 2 * Math.PI * 26.5;
            let raf = 0;
            if (ring) {
                ring.style.strokeDasharray = C.toFixed(1);
                ring.style.strokeDashoffset = C.toFixed(1);
            }
            const tick = () => {
                if (ring && audio.duration) {
                    ring.style.strokeDashoffset = (C * (1 - audio.currentTime / audio.duration)).toFixed(1);
                }
                raf = requestAnimationFrame(tick);
            };

            audio.addEventListener("play", () => {
                icon.setAttribute("d", PAUSE); btn.setAttribute("aria-label", "Пауза");
                if (ring) ring.style.opacity = 0.9;
                cancelAnimationFrame(raf); raf = requestAnimationFrame(tick);
            });
            audio.addEventListener("pause", () => {
                icon.setAttribute("d", PLAY); btn.setAttribute("aria-label", "Послушать");
                cancelAnimationFrame(raf);
            });
            audio.addEventListener("ended", () => {
                icon.setAttribute("d", PLAY);
                cancelAnimationFrame(raf);
                if (ring) { ring.style.opacity = 0; ring.style.strokeDashoffset = C.toFixed(1); }
            });
            audioCtl.setCard(currentCard);
        }

        async function init() {
            let today = FALLBACK;
            try {
                const res = await fetch(`data.json?t=${Date.now()}`);
                if (res.ok) today = await res.json();
            } catch (e) { /* оставляем FALLBACK */ }
            cards = [today];
            idx = 0;
            render(today);
            loadArchive(today);   // фоном: появятся стрелки и свайп по прошлым дням
        }

        /* ---------- Пуш-уведомления об открытке дня ----------
           На iPhone работают только из приложения, добавленного на экран «Домой» (iOS 16.4+).
           GitHub Pages без бэкенда, поэтому подписка отправляется владельцу сайта один раз
           (через «Поделиться»/буфер) и коммитится в subscriptions.json — оттуда её читает
           notify.py, который шлёт пуш в 12:00 МСК из GitHub Actions. */
        const VAPID_PUBLIC = "BPTN_CVrLVCUYlR7ftakhy2avyfufMxnf0DYEXtDDhl2dErD4Zv9v7Z_2x3D-ZwbobD6boYM6DoHNA41oSM6Nk8";

        function urlB64ToU8(s) {
            const pad = "=".repeat((4 - s.length % 4) % 4);
            const raw = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
            return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
        }

        async function setupPush() {
            const btn = document.getElementById("bell");
            if (!btn) return;
            if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) return;
            const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
            const ua = navigator.userAgent;
            const isIOS = /iphone|ipad|ipod/i.test(ua) || (navigator.maxTouchPoints > 1 && /Macintosh/.test(ua));
            if (isIOS && !standalone) return;   // на iOS пуши доступны только установленному приложению

            let reg;
            try { reg = await navigator.serviceWorker.ready; } catch (e) { return; }
            let sub = null;
            try { sub = await reg.pushManager.getSubscription(); } catch (e) {}

            // Уже подписались и отправили код с этого устройства — кнопка больше не нужна.
            // Если подписка при этом исчезла (сняли разрешение) — покажем колокольчик заново.
            const SENT_KEY = "push-code-sent";
            if (localStorage.getItem(SENT_KEY) === "1") {
                if (sub) return;
                localStorage.removeItem(SENT_KEY);
            }

            // Если эта подписка уже закоммичена в subscriptions.json — всё настроено, кнопка не нужна
            let known = [];
            try {
                const r = await fetch(`subscriptions.json?t=${Date.now()}`);
                if (r.ok) known = await r.json();
            } catch (e) {}
            if (sub && Array.isArray(known) && known.some(k => k && k.endpoint === sub.endpoint)) return;

            btn.hidden = false;
            requestAnimationFrame(() => btn.classList.add("show"));

            const bar = document.getElementById("share-hint");
            const done = () => {
                localStorage.setItem(SENT_KEY, "1");
                btn.classList.remove("show");
                setTimeout(() => { btn.hidden = true; }, 800);
                if (bar) {
                    bar.classList.remove("show");
                    setTimeout(() => { bar.hidden = true; }, 500);
                }
            };

            // Отправка кода. ВАЖНО: share/clipboard на iOS работают только в момент
            // свежего нажатия — эту функцию зовём строго из обработчика клика, без await до неё.
            const sendCode = async () => {
                const text = JSON.stringify(sub.toJSON());
                try {
                    if (navigator.share) {
                        await navigator.share({ title: "Код подписки на открытки", text });
                    } else if (navigator.clipboard) {
                        await navigator.clipboard.writeText(text);
                        alert("Код подписки скопирован — отправь его создателю сайта, и уведомления заработают.");
                    } else {
                        prompt("Скопируй код подписки и отправь создателю сайта:", text);
                    }
                } catch (e) {
                    if (e && e.name === "AbortError") return;   // передумали — оставляем всё как есть
                    // share/clipboard заблокированы — показываем код напрямую, его можно скопировать
                    prompt("Скопируй код подписки и отправь создателю сайта:", text);
                }
                done();
            };

            const showShareBar = () => {
                if (!bar) { sendCode(); return; }
                bar.hidden = false;
                requestAnimationFrame(() => bar.classList.add("show"));
            };
            if (bar) {
                bar.addEventListener("click", () => { if (sub) sendCode(); });
                bar.addEventListener("keydown", (e) => { if ((e.key === "Enter" || e.key === " ") && sub) sendCode(); });
            }

            btn.addEventListener("click", async () => {
                try {
                    // Разрешение уже есть и подписка готова — жест ещё свежий, делимся сразу
                    if (Notification.permission === "granted" && sub) { sendCode(); return; }
                    const perm = await Notification.requestPermission();
                    if (perm !== "granted") return;
                    if (!sub) {
                        sub = await reg.pushManager.subscribe({
                            userVisibleOnly: true,
                            applicationServerKey: urlB64ToU8(VAPID_PUBLIC),
                        });
                    }
                    // После диалога разрешения жест «протух» — share бы молча не сработал (iOS).
                    // Показываем плашку: её нажатие — новый жест, и шэринг откроется.
                    showShareBar();
                } catch (e) { console.warn("push subscribe:", e); }
            });
        }

        // Установка как приложение: предлагаем один раз, после добавления/скрытия — больше нет
        function setupInstall() {
            const bar = document.getElementById("install");
            const text = document.getElementById("install-text");
            const closeBtn = document.getElementById("install-close");
            if (!bar) return;
            const KEY = "pwa-install-dismissed";
            const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
            if (standalone || localStorage.getItem(KEY) === "1") return;   // уже приложение или скрыли

            let deferred = null;
            const show = () => { bar.hidden = false; requestAnimationFrame(() => bar.classList.add("show")); };
            const hide = (remember) => {
                bar.classList.remove("show");
                setTimeout(() => { bar.hidden = true; }, 500);
                if (remember) localStorage.setItem(KEY, "1");
            };

            closeBtn.addEventListener("click", (e) => { e.stopPropagation(); hide(true); });

            // Android/Chrome: системное предложение установки
            window.addEventListener("beforeinstallprompt", (e) => {
                e.preventDefault();
                deferred = e;
                text.textContent = "Добавить на экран телефона";
                show();
            });
            window.addEventListener("appinstalled", () => hide(true));

            const trigger = async () => {
                if (!deferred) return;                 // на iOS бар просто информационный
                deferred.prompt();
                const choice = await deferred.userChoice;
                deferred = null;
                hide(choice && choice.outcome === "accepted");
            };
            bar.addEventListener("click", trigger);
            bar.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") trigger(); });

            // iOS: системного предложения нет (ограничение Apple) — только вручную через «Поделиться».
            // iOS не сообщает, добавлено ли уже на экран, поэтому в Safari не назойливо:
            // показываем максимум 3 раза (потом сами прячем); «×» прячет навсегда.
            const ua = navigator.userAgent;
            const isIOS = /iphone|ipad|ipod/i.test(ua) || (navigator.maxTouchPoints > 1 && /Macintosh/.test(ua));
            if (isIOS && !standalone) {
                const CKEY = "pwa-ios-hint-count";
                const seen = +(localStorage.getItem(CKEY) || 0);
                if (seen >= 3) return;
                localStorage.setItem(CKEY, String(seen + 1));
                const inSafari = /Safari/.test(ua) && !/CriOS|FxiOS|EdgiOS|OPiOS|YaBrowser/.test(ua);
                text.textContent = inSafari
                    ? "Установить: «Поделиться» ↑, затем «На экран „Домой“»"
                    : "Откройте эту страницу в Safari, чтобы добавить на экран";
                show();
            }
        }

        if ("serviceWorker" in navigator) {
            window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
        }

        init();
        document.addEventListener("visibilitychange", () => {
            const video = document.getElementById("video-bg");
            if (document.hidden) video.pause();
            else if (video.getAttribute("src") && !matchMedia("(prefers-reduced-motion: reduce)").matches) video.play().catch(() => {});
        });
        matchMedia("(prefers-reduced-motion: reduce)").addEventListener("change", () => renderBackdrop(currentCard));
        setupAudio();
        setupInstall();
        setupPush();
