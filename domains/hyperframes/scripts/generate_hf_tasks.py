"""Generate the v1 HyperFrames AutoResearch task bank."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hf_factory_lib import TASKS_DIR, load_task_file


COMMON_CONSTRAINTS = [
    "Use deterministic HyperFrames HTML with seek-driven animation only.",
    "Edit only index.html unless the task explicitly allows assets/generated/**.",
    "Do not fetch external assets, shaders, fonts, scripts, WASM, or media at render time.",
    "Keep a visible, inspectable result at 1280x720 desktop snapshot size.",
    "Preserve the project manifest contract and root composition metadata.",
    "Load GSAP from vendor/gsap/gsap.min.js and register a paused timeline in window.__timelines.",
    "Expose window.__renderFrame(seconds) and respond to hf-seek.",
    "Include meaningful fallbacks for experimental HTML-in-Canvas, CanvasKit, and WebGPU paths.",
]

BASE_CHECKS = [
    "allowed_file_only",
    "solution_changed",
    "clean_replay",
    "typecheck",
    "lint",
    "validate",
    "snapshot",
    "desktop_screenshot",
    "no_console_errors",
    "snapshot_nonblank",
    "snapshot_frame_variation",
    "snapshot_frames_retained",
    "deterministic_source",
    "codex_success",
    "solution_size",
]

SOURCE_REFS = {
    "html_canvas": [
        {"label": "WICG HTML-in-Canvas specification draft", "url": "https://wicg.github.io/html-in-canvas/"},
        {"label": "WICG HTML-in-Canvas explainer", "url": "https://github.com/WICG/html-in-canvas"},
        {"label": "HTML-in-Canvas live examples", "url": "https://html-in-canvas.dev/"},
        {"label": "HyperFrames HTML-in-Canvas skill", "url": "file:///Users/trevor/Documents/New%20project%203/skills/hyperframes-html-canvas/SKILL.md"},
        {"label": "HTML-in-Canvas research notes", "url": "file:///Users/trevor/Documents/New%20project%203/docs/research/html-in-canvas/README.md"},
    ],
    "webgpu": [
        {"label": "WebGPU samples compute boids", "url": "https://webgpu.github.io/webgpu-samples/samples/computeBoids/"},
        {"label": "WebGPU samples particles", "url": "https://webgpu.github.io/webgpu-samples/samples/particles/"},
        {"label": "WebGPU Fundamentals texture imports", "url": "https://webgpufundamentals.org/webgpu/lessons/webgpu-importing-textures.html"},
        {"label": "MDN GPUQueue onSubmittedWorkDone", "url": "https://developer.mozilla.org/en-US/docs/Web/API/GPUQueue/onSubmittedWorkDone"},
        {"label": "HyperFrames WebGPU TypeGPU skill", "url": "file:///Users/trevor/Documents/New%20project%203/skills/hyperframes-webgpu-typegpu/SKILL.md"},
        {"label": "GPU readiness reference", "url": "file:///Users/trevor/Documents/New%20project%203/skills/hyperframes-webgpu-typegpu/references/gpu-readiness.md"},
    ],
    "typegpu": [
        {"label": "TypeGPU why TypeGPU", "url": "https://docs.swmansion.com/TypeGPU/why-typegpu/"},
        {"label": "TypeGPU getting started", "url": "https://docs.swmansion.com/TypeGPU/getting-started"},
        {"label": "HyperFrames WebGPU TypeGPU skill", "url": "file:///Users/trevor/Documents/New%20project%203/skills/hyperframes-webgpu-typegpu/SKILL.md"},
    ],
    "canvaskit": [
        {"label": "Skia CanvasKit documentation", "url": "https://docs.skia.org/docs/user/modules/canvaskit/"},
        {"label": "Skia CanvasKit quickstart", "url": "https://skia.org/docs/user/modules/quickstart/"},
        {"label": "HyperFrames Skia CanvasKit skill", "url": "file:///Users/trevor/Documents/New%20project%203/skills/hyperframes-skia-canvaskit/SKILL.md"},
        {"label": "Skia research notes", "url": "file:///Users/trevor/Documents/New%20project%203/docs/research/skia/README.md"},
    ],
    "timeline": [
        {"label": "GSAP Timeline docs", "url": "https://gsap.com/docs/v3/GSAP/Timeline/"},
        {"label": "GSAP timeline pause docs", "url": "https://gsap.com/docs/v3/GSAP/Timeline/pause()/"},
        {"label": "HyperFrames rendering docs", "url": "file:///Users/trevor/Documents/New%20project%203/docs/rendering.md"},
        {"label": "Timeline contract validator", "url": "file:///Users/trevor/Documents/New%20project%203/packages/hyperframes-project/src/timelineContract.ts"},
    ],
    "validation": [
        {"label": "HTML canvas validator", "url": "file:///Users/trevor/Documents/New%20project%203/packages/hyperframes-project/src/htmlCanvasValidation.ts"},
        {"label": "Determinism validator", "url": "file:///Users/trevor/Documents/New%20project%203/packages/hyperframes-project/src/determinism.ts"},
    ],
    "composition": [
        {"label": "HyperFrames rendering contract", "url": "file:///Users/trevor/Documents/New%20project%203/docs/rendering.md"},
        {"label": "Timeline contract tests", "url": "file:///Users/trevor/Documents/New%20project%203/packages/hyperframes-project/src/timelineContract.test.ts"},
        {"label": "Project manifest factory", "url": "file:///Users/trevor/Documents/New%20project%203/packages/hyperframes-project/src/createProject.ts"},
    ],
    "performance": [
        {"label": "Performance diagnostics", "url": "file:///Users/trevor/Documents/New%20project%203/packages/hyperframes-project/src/performanceDiagnostics.ts"},
        {"label": "Snapshot feedback", "url": "file:///Users/trevor/Documents/New%20project%203/packages/hyperframes-project/src/snapshotFeedback.ts"},
    ],
    "assets": [
        {"label": "Asset import tests", "url": "file:///Users/trevor/Documents/New%20project%203/packages/hyperframes-project/src/assets.test.ts"},
        {"label": "Project file classification tests", "url": "file:///Users/trevor/Documents/New%20project%203/packages/hyperframes-project/src/projectFiles.test.ts"},
    ],
}


def check(name: str, points: int = 150, **kwargs: Any) -> dict[str, Any]:
    return {"name": name, "points": points, **kwargs}


TIMELINE_CHECKS = [
    check("local_gsap_timeline", regex_all=[r"vendor/gsap/gsap\.min\.js", r"gsap\.timeline\s*\(\s*\{[^}]*paused\s*:\s*true", r"window\.__timelines\s*\["]),
    check("seek_render_contract", regex_all=[r"window\.__renderFrame\s*=", r"hf-seek", r"renderFrame\s*\("]),
    check("root_composition_metadata", regex_all=[r"data-composition-id\s*=", r"data-start\s*=\s*['\"]0['\"]", r"data-duration\s*=", r"data-width\s*=\s*['\"]1280['\"]", r"data-height\s*=\s*['\"]720['\"]", r"data-fps\s*=\s*['\"]30['\"]"], points=100),
    check("no_legacy_timeline_contract", regex_none=[r"window\.__hfAppSeekHelperVersion", r"data-layer\s*=", r"data-end\s*="], points=100),
]

HTML_CANVAS_CHECKS = [
    check("layoutsubtree_canvas", regex_all=[r"<canvas\b[^>]*\blayoutsubtree\b"]),
    check("html_canvas_fallback", regex_all=[r"data-html-canvas-fallback"]),
    check("draw_element_image", regex_all=[r"drawElementImage\s*\("]),
    check("direct_canvas_child", regex_all=[r"<canvas\b[^>]*\blayoutsubtree\b[^>]*>\s*<(article|section|div|figure)\b"]),
]

HTML_CANVAS_PAINT_CHECKS = [
    check("paint_or_request_paint", regex_any=[[r"\.onpaint\s*=", r"addEventListener\s*\(\s*['\"]paint", r"\.requestPaint\s*\("]], points=100),
    check("resize_or_dpr_sync", regex_any=[[r"ResizeObserver", r"devicePixelRatio", r"device-pixel-content-box", r"\.width\s*=", r"\.height\s*="]], points=100),
]

WEBGL_CHECKS = [
    check("dom_texture_source", regex_all=[r"<canvas\b[^>]*\blayoutsubtree\b", r"data-html-canvas-fallback"]),
    check("webgl_texture_route", regex_any=[[r"texElementImage2D\s*\(", r"getContext\s*\(\s*['\"]webgl", r"WebGLRenderingContext"]]),
]

WEBGPU_CHECKS = [
    check("webgpu_device_path", regex_all=[r"navigator\.gpu", r"requestAdapter\s*\(", r"requestDevice\s*\("]),
    check("webgpu_fallback", regex_any=[[r"fallback", r"Fallback", r"WebGPU unavailable"]], case_sensitive=False),
    check("webgpu_frame_fence", regex_all=[r"__hfWebGpu\?\.\s*registerDevice\s*\(", r"__hfWebGpu\?\.\s*registerFrame\s*\(", r"onSubmittedWorkDone\s*\(", r"queue\.submit\s*\("], points=200),
]

WEBGPU_TEXTURE_CHECKS = [
    check("webgpu_texture_usage", regex_any=[[r"GPUTextureUsage\.COPY_DST", r"GPUTextureUsage\.TEXTURE_BINDING", r"GPUTextureUsage\.RENDER_ATTACHMENT"]], points=100),
    check("webgpu_texture_copy_intent", regex_any=[[r"copyExternalImageToTexture", r"copyElementImageToTexture", r"createTexture\s*\("]], points=100),
]

CANVASKIT_CHECKS = [
    check("canvaskit_local_runtime", regex_all=[r"CanvasKitInit", r"vendor/canvaskit/canvaskit\.js", r"locateFile"]),
    check("canvaskit_fallback", regex_any=[[r"data-canvaskit-fallback", r"data-html-canvas-fallback"]]),
    check("canvaskit_flush", regex_all=[r"\.flush\s*\("], points=200),
    check("canvaskit_object_lifecycle", regex_any=[[r"\.delete\s*\(", r"try\s*\{[\s\S]*finally", r"reuse"]], points=100),
    check("canvaskit_ready_gate", regex_any=[[r"window\.__renderReady\s*=", r"await\s+CanvasKitInit", r"CanvasKitInit\s*\([^)]*\)\.then"]], points=100),
]

RENDER_QA_CHECKS = [
    check("qa_visible_fallback", regex_any=[[r"data-html-canvas-fallback", r"data-canvaskit-fallback", r"fallback"]], case_sensitive=False),
    check("qa_no_banned_timing", regex_none=[r"Date\.now\s*\(", r"performance\.now\s*\(", r"Math\.random\s*\(", r"requestAnimationFrame\s*\(", r"setInterval\s*\("], points=200),
]

COMPOSITION_CONTRACT_CHECKS = [
    check("clip_timing_contract", regex_all=[r"data-start\s*=", r"data-duration\s*=", r"data-track-index\s*="], points=100),
    check("z_index_for_visual_stack", regex_any=[[r"z-index\s*:", r"\.style\.zIndex"]], points=100),
]

CAPTION_CHECKS = [
    check("caption_timing_contract", regex_all=[r"caption|subtitle|cue", r"data-start\s*=", r"data-duration\s*=", r"data-track-index\s*="], case_sensitive=False, points=100),
    check("caption_seek_state", regex_any=[[r"window\.__hfCurrentTime", r"renderFrame\s*\([^)]*seconds", r"timeline\.to"]], points=100),
]

PERFORMANCE_CHECKS = [
    check("no_known_expensive_css", regex_none=[r"backdrop-filter\s*:", r"transition\s*:\s*all", r"will-change\s*:\s*(?:[^;,\n]+,\s*){4,}", r"box-shadow\s*:[^;]*(?:\d{3,}px|\d{2,}rem)"], points=100),
    check("explicit_media_dimensions", regex_none=[r"<img\b(?![^>]*(?:width|height)\s*=)", r"<video\b(?![^>]*(?:width|height|style)\s*=)"], points=100),
]

ASSET_LOCALITY_CHECKS = [
    check("local_asset_policy", regex_none=[r"https?://", r"fetch\s*\(", r"import\s*\(\s*['\"]https?://"], points=100),
    check("procedural_or_local_asset", regex_any=[[r"assets/", r"data:image/svg\+xml", r"linear-gradient", r"CanvasKit", r"drawElementImage"]], points=100),
]

TYPEGPU_CHECKS = [
    check("typegpu_pipeline_intent", regex_any=[[r"typegpu", r"TypeGPU", r"tgpu", r"WGSL", r"shader"]], points=100),
    check("typed_uniform_or_schema", regex_any=[[r"uniform", r"schema", r"struct", r"buffer", r"Float32Array"]], case_sensitive=False, points=100),
]


@dataclass(frozen=True)
class Blueprint:
    stem: str
    kind: str
    family: str
    difficulty: str
    prompt: str
    topics: list[str]
    refs: list[str]
    semantic_checks: list[dict[str, Any]]
    threshold: int = 1450


def refs(*keys: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for key in keys:
        out.extend(SOURCE_REFS[key])
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for item in out:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)
    return unique


BLUEPRINTS = [
    Blueprint("html-canvas-card", "generation", "html_canvas", "medium", "Build a validator-visible HTML-in-Canvas DOM card capture with a semantically equivalent fallback", ["html-in-canvas", "hyperframes", "fallback"], ["html_canvas", "timeline"], TIMELINE_CHECKS + HTML_CANVAS_CHECKS),
    Blueprint("html-canvas-data-table", "generation", "html_canvas", "hard", "Capture a dense DOM data table into canvas with requestPaint/onpaint synchronization, deterministic row highlight motion, DPR-aware sizing, and a readable fallback", ["html-in-canvas", "data-ui", "timeline"], ["html_canvas", "timeline"], TIMELINE_CHECKS + HTML_CANVAS_CHECKS + HTML_CANVAS_PAINT_CHECKS),
    Blueprint("html-canvas-form-mockup", "generation", "html_canvas", "medium", "Render a form-like DOM control panel through drawElementImage without hiding the drawable source", ["html-in-canvas", "forms", "fallback"], ["html_canvas", "validation"], TIMELINE_CHECKS + HTML_CANVAS_CHECKS),
    Blueprint("html-canvas-code-panel", "generation", "html_canvas", "hard", "Capture a syntax-highlighted DOM code panel into canvas with seeked scanline treatment and explicit repaint/backing-store handling", ["html-in-canvas", "code-ui", "timeline"], ["html_canvas", "timeline"], TIMELINE_CHECKS + HTML_CANVAS_CHECKS + HTML_CANVAS_PAINT_CHECKS),
    Blueprint("html-canvas-caption-card", "generation", "html_canvas", "medium", "Build a caption/title card whose DOM source is captured to canvas and whose cue timing remains export-safe", ["html-in-canvas", "captions", "video"], ["html_canvas", "validation", "composition"], TIMELINE_CHECKS + HTML_CANVAS_CHECKS + CAPTION_CHECKS),
    Blueprint("html-canvas-responsive-ticket", "generation", "html_canvas", "hard", "Create a responsive ticket/status card capture that stays legible in the desktop snapshot", ["html-in-canvas", "responsive", "fallback"], ["html_canvas", "validation"], TIMELINE_CHECKS + HTML_CANVAS_CHECKS),
    Blueprint("html-canvas-dpr-inspector", "generation", "html_canvas", "hard", "Implement a DPR-aware DOM-to-canvas inspector with explicit backing store sizing, requestPaint/onpaint handling, and fallback", ["html-in-canvas", "canvas", "dpr"], ["html_canvas", "validation"], TIMELINE_CHECKS + HTML_CANVAS_CHECKS + HTML_CANVAS_PAINT_CHECKS + [check("dpr_backing_store", regex_any=[[r"devicePixelRatio", r"\.width\s*=", r"\.height\s*="]])]),
    Blueprint("html-canvas-fallback-repair", "repair", "html_canvas", "medium", "Repair an HTML-in-Canvas effect by adding a meaningful fallback and preserving the captured DOM semantics", ["html-in-canvas", "repair", "fallback"], ["html_canvas", "validation"], TIMELINE_CHECKS + HTML_CANVAS_CHECKS),
    Blueprint("html-canvas-transform-repair", "repair", "html_canvas", "hard", "Repair a DOM capture design so motion happens in the draw call or timeline, not through source CSS transform", ["html-in-canvas", "repair", "timeline"], ["html_canvas", "validation"], TIMELINE_CHECKS + HTML_CANVAS_CHECKS + [check("no_source_transform", regex_none=[r"<canvas[\s\S]*?style=['\"][^'\"]*transform\s*:"])]),
    Blueprint("html-canvas-hidden-source-repair", "repair", "html_canvas", "hard", "Repair a capture block so the drawable source remains in layout and visible to drawElementImage", ["html-in-canvas", "repair", "validation"], ["html_canvas", "validation"], TIMELINE_CHECKS + HTML_CANVAS_CHECKS + [check("no_hidden_source", regex_none=[r"<canvas[\s\S]*?\bhidden\b", r"<canvas[\s\S]*display\s*:\s*none"])]),
    Blueprint("webgl-dom-transition", "generation", "webgl", "hard", "Build a WebGL DOM-texture transition with two layoutsubtree DOM sources and a fallback path", ["webgl", "html-in-canvas", "transition"], ["html_canvas", "timeline"], TIMELINE_CHECKS + WEBGL_CHECKS),
    Blueprint("webgl-liquid-card", "generation", "webgl", "hard", "Create a liquid-glass DOM texture card effect with seeked distortion and non-WebGL fallback", ["webgl", "shader", "fallback"], ["html_canvas", "timeline"], TIMELINE_CHECKS + WEBGL_CHECKS),
    Blueprint("webgl-page-flip", "generation", "webgl", "hard", "Implement a page-flip transition using DOM texture concepts and deterministic timeline progress", ["webgl", "transition", "timeline"], ["html_canvas", "timeline"], TIMELINE_CHECKS + WEBGL_CHECKS),
    Blueprint("webgl-shatter-panels", "generation", "webgl", "hard", "Build a shatter-panels scene where DOM cards feed a WebGL texture route with a fallback", ["webgl", "particles", "html-in-canvas"], ["html_canvas", "timeline"], TIMELINE_CHECKS + WEBGL_CHECKS),
    Blueprint("webgl-portal-compare", "generation", "webgl", "hard", "Create a before/after portal comparison using DOM texture upload semantics and seeked reveal", ["webgl", "comparison", "timeline"], ["html_canvas", "timeline"], TIMELINE_CHECKS + WEBGL_CHECKS),
    Blueprint("webgl-texture-atlas", "generation", "webgl", "hard", "Compose multiple DOM mini-panels into a WebGL texture atlas concept with validator-visible sources", ["webgl", "texture-atlas", "html-in-canvas"], ["html_canvas", "validation"], TIMELINE_CHECKS + WEBGL_CHECKS + [check("multiple_dom_sources", count_at_least=[{"pattern": r"<article\b|<section\b|<div\b[^>]*data-source", "count": 2}])]),
    Blueprint("webgl-dpr-resize", "generation", "webgl", "hard", "Handle WebGL DOM texture resizing with DPR-aware canvas dimensions and stable fallback", ["webgl", "dpr", "resize"], ["html_canvas", "validation"], TIMELINE_CHECKS + WEBGL_CHECKS + [check("dpr_resize", regex_any=[[r"devicePixelRatio", r"resize", r"canvas\.width"]])]),
    Blueprint("webgl-fallback-repair", "repair", "webgl", "hard", "Repair a WebGL DOM texture composition so unsupported texture APIs render a meaningful fallback", ["webgl", "repair", "fallback"], ["html_canvas", "validation"], TIMELINE_CHECKS + WEBGL_CHECKS),
    Blueprint("webgpu-particle-field", "generation", "webgpu", "hard", "Build a WebGPU particle-field concept with explicit device fallback and frame-fence registration", ["webgpu", "particles", "readiness"], ["webgpu", "timeline"], TIMELINE_CHECKS + WEBGPU_CHECKS),
    Blueprint("webgpu-dom-displacement", "generation", "webgpu", "hard", "Use DOM-to-WebGPU texture concepts for a displacement transition with texture usage flags, submit fencing, and safe fallback", ["webgpu", "dom-texture", "transition"], ["webgpu", "html_canvas"], TIMELINE_CHECKS + WEBGPU_CHECKS + WEBGPU_TEXTURE_CHECKS + [check("dom_texture_copy_intent", regex_any=[[r"copyElementImageToTexture", r"GPUTexture", r"layoutsubtree"]])]),
    Blueprint("webgpu-compute-progress", "generation", "webgpu", "hard", "Create a TypeGPU-style compute progress visualization with deterministic buffers, typed uniforms, and WebGPU fallback", ["webgpu", "typegpu", "compute", "timeline"], ["webgpu", "typegpu", "timeline"], TIMELINE_CHECKS + WEBGPU_CHECKS + TYPEGPU_CHECKS),
    Blueprint("webgpu-timeline-ripple", "generation", "webgpu", "hard", "Drive a TypeGPU/WGSL ripple effect entirely from HyperFrames seek time with registered GPU work", ["webgpu", "typegpu", "shader", "timeline"], ["webgpu", "typegpu", "timeline"], TIMELINE_CHECKS + WEBGPU_CHECKS + TYPEGPU_CHECKS),
    Blueprint("webgpu-device-fallback", "repair", "webgpu", "medium", "Repair WebGPU initialization so missing adapters/devices show a clear export-safe fallback", ["webgpu", "repair", "fallback"], ["webgpu", "validation"], TIMELINE_CHECKS + WEBGPU_CHECKS),
    Blueprint("webgpu-frame-fence-repair", "repair", "webgpu", "hard", "Repair a WebGPU render path to register queue completion after every submit", ["webgpu", "repair", "readiness"], ["webgpu", "validation"], TIMELINE_CHECKS + WEBGPU_CHECKS),
    Blueprint("webgpu-texture-copy-guard", "generation", "webgpu", "hard", "Guard DOM texture copies into WebGPU with layoutsubtree source constraints, texture usage flags, and fallback", ["webgpu", "html-in-canvas", "dom-texture"], ["webgpu", "html_canvas"], TIMELINE_CHECKS + HTML_CANVAS_CHECKS[:2] + HTML_CANVAS_PAINT_CHECKS + WEBGPU_CHECKS + WEBGPU_TEXTURE_CHECKS),
    Blueprint("typegpu-pipeline-fallback", "generation", "webgpu", "hard", "Design a TypeGPU-style pipeline block with safe WebGPU fallback, typed uniforms, and deterministic shader inputs", ["webgpu", "typegpu", "pipeline"], ["webgpu", "typegpu", "timeline"], TIMELINE_CHECKS + WEBGPU_CHECKS + TYPEGPU_CHECKS),
    Blueprint("canvaskit-vector-title", "generation", "canvaskit", "medium", "Build a CanvasKit vector title card with local runtime, renderFrame(seconds), flush, and fallback", ["canvaskit", "skia", "title"], ["canvaskit", "timeline"], TIMELINE_CHECKS + CANVASKIT_CHECKS),
    Blueprint("canvaskit-chart-card", "generation", "canvaskit", "hard", "Render a deterministic Skia-style chart card with CanvasKit and fallback DOM summary", ["canvaskit", "charts", "fallback"], ["canvaskit", "validation"], TIMELINE_CHECKS + CANVASKIT_CHECKS),
    Blueprint("canvaskit-sksl-rings", "generation", "canvaskit", "hard", "Create a SkSL-inspired animated rings surface using CanvasKit primitives and explicit flush", ["canvaskit", "sksl", "animation"], ["canvaskit", "timeline"], TIMELINE_CHECKS + CANVASKIT_CHECKS + [check("sksl_intent", regex_any=[[r"SkSL", r"shader", r"Paint", r"Path"]])]),
    Blueprint("canvaskit-paragraph-layout", "generation", "canvaskit", "hard", "Build a CanvasKit shaped-text or paragraph layout scene with fallback text preserving meaning", ["canvaskit", "text", "layout"], ["canvaskit", "validation"], TIMELINE_CHECKS + CANVASKIT_CHECKS + [check("text_layout_intent", regex_any=[[r"Paragraph", r"Font", r"drawText", r"shaped"]], case_sensitive=False)]),
    Blueprint("canvaskit-local-font-title", "generation", "canvaskit", "hard", "Use local font/runtime assumptions for a CanvasKit title treatment with no remote font dependency", ["canvaskit", "fonts", "determinism"], ["canvaskit", "validation"], TIMELINE_CHECKS + CANVASKIT_CHECKS),
    Blueprint("canvaskit-skottie-badge", "generation", "canvaskit", "hard", "Create a Skottie/Lottie-style badge concept with local JSON fallback and deterministic frame seeking", ["canvaskit", "skottie", "lottie"], ["canvaskit", "timeline"], TIMELINE_CHECKS + CANVASKIT_CHECKS + [check("skottie_intent", regex_any=[[r"Skottie", r"Lottie", r"MakeAnimation", r"seek"]])]),
    Blueprint("canvaskit-flush-repair", "repair", "canvaskit", "medium", "Repair a CanvasKit block so every captured frame flushes the surface after drawing", ["canvaskit", "repair", "flush"], ["canvaskit", "validation"], TIMELINE_CHECKS + CANVASKIT_CHECKS),
    Blueprint("canvaskit-runtime-fallback", "repair", "canvaskit", "medium", "Repair CanvasKit loading so the local runtime path and fallback both work", ["canvaskit", "repair", "fallback"], ["canvaskit", "validation"], TIMELINE_CHECKS + CANVASKIT_CHECKS),
    Blueprint("timeline-multi-track", "generation", "timeline", "medium", "Build a multi-track HyperFrames source composition with visible staggered clips and canvas effect", ["timeline", "hyperframes", "composition"], ["timeline", "html_canvas", "composition"], TIMELINE_CHECKS + HTML_CANVAS_CHECKS[:2] + COMPOSITION_CONTRACT_CHECKS + [check("multi_track_clips", count_at_least=[{"pattern": r"data-track-index", "count": 4}])]),
    Blueprint("timeline-gsap-labels", "generation", "timeline", "medium", "Use a paused GSAP timeline with labels to drive visible composition states from seek time", ["timeline", "gsap", "labels"], ["timeline", "composition"], TIMELINE_CHECKS + COMPOSITION_CONTRACT_CHECKS + [check("gsap_labels", regex_any=[[r"\.addLabel\s*\(", r"labels", r"timeline\.to"]])]),
    Blueprint("timeline-media-card", "generation", "timeline", "hard", "Create source-backed media-card timing with explicit data-start, data-duration, muted media semantics, and fallback visuals", ["timeline", "media", "source"], ["timeline", "validation", "composition"], TIMELINE_CHECKS + COMPOSITION_CONTRACT_CHECKS + [check("timeline_metadata", regex_all=[r"data-start", r"data-duration", r"data-track-index"]), check("media_export_contract", regex_none=[r"<video\b(?![^>]*muted)", r"\bautoplay\b"], points=100)]),
    Blueprint("timeline-seek-state", "generation", "timeline", "hard", "Make a composition whose labels, counters, and canvas state update correctly at 0%, 50%, and 100% seek", ["timeline", "seek", "render-qa"], ["timeline", "validation", "composition"], TIMELINE_CHECKS + COMPOSITION_CONTRACT_CHECKS + [check("seek_state_text", regex_any=[[r"toFixed", r"currentTime", r"__hfCurrentTime"]])]),
    Blueprint("timeline-stagger-panels", "generation", "timeline", "medium", "Build staggered source panels driven by GSAP while keeping export deterministic", ["timeline", "gsap", "panels"], ["timeline", "composition"], TIMELINE_CHECKS + COMPOSITION_CONTRACT_CHECKS + [check("stagger_or_sequence", regex_any=[[r"stagger", r"\.to\s*\(", r"\.fromTo\s*\("]])]),
    Blueprint("timeline-clip-overlap-repair", "repair", "timeline", "hard", "Repair a crowded composition by assigning clear track indices and non-overlapping readable clip timing", ["timeline", "repair", "layout"], ["timeline", "validation", "composition"], TIMELINE_CHECKS + COMPOSITION_CONTRACT_CHECKS + [check("clip_timing_metadata", count_at_least=[{"pattern": r"data-duration", "count": 3}])]),
    Blueprint("renderqa-blank-frame-repair", "repair", "render_qa", "medium", "Repair a composition so snapshot frames are nonblank and visibly different at seeked times", ["render-qa", "repair", "snapshot"], ["validation", "timeline", "performance"], TIMELINE_CHECKS + RENDER_QA_CHECKS),
    Blueprint("renderqa-static-snapshot-repair", "repair", "render_qa", "hard", "Repair static-looking snapshot output by making visual state depend on seek time only", ["render-qa", "repair", "timeline"], ["validation", "timeline", "performance"], TIMELINE_CHECKS + RENDER_QA_CHECKS + [check("seek_dependent_visuals", regex_any=[[r"sin\(", r"time", r"progress", r"seconds"]])]),
    Blueprint("renderqa-performance-repair", "repair", "render_qa", "hard", "Repair a dense composition so it remains readable in the desktop snapshot without expensive CSS or text overlap", ["render-qa", "layout", "performance"], ["validation", "timeline", "performance"], TIMELINE_CHECKS + RENDER_QA_CHECKS + PERFORMANCE_CHECKS),
    Blueprint("renderqa-network-asset-repair", "repair", "render_qa", "medium", "Repair a render path so all visual assets are local or procedurally generated", ["render-qa", "repair", "assets"], ["validation", "assets"], TIMELINE_CHECKS + RENDER_QA_CHECKS + ASSET_LOCALITY_CHECKS),
    Blueprint("renderqa-randomness-repair", "repair", "render_qa", "medium", "Repair unseeded randomness by replacing it with deterministic seek-derived variation", ["render-qa", "repair", "determinism"], ["validation", "timeline", "performance"], TIMELINE_CHECKS + RENDER_QA_CHECKS),
    Blueprint("cross-html-canvas-webgl", "generation", "cross_route", "hard", "Combine HTML-in-Canvas DOM capture with a WebGL texture-style transition and fallback", ["html-in-canvas", "webgl", "fallback"], ["html_canvas", "timeline"], TIMELINE_CHECKS + HTML_CANVAS_CHECKS + WEBGL_CHECKS),
    Blueprint("cross-canvaskit-html-fallback", "generation", "cross_route", "hard", "Combine CanvasKit vector rendering with an equivalent HTML fallback and timeline-controlled state", ["canvaskit", "html", "fallback"], ["canvaskit", "timeline"], TIMELINE_CHECKS + CANVASKIT_CHECKS),
    Blueprint("cross-webgpu-html-canvas", "generation", "cross_route", "hard", "Combine WebGPU readiness with HTML-in-Canvas source constraints, texture-copy intent, and export-safe fallback", ["webgpu", "html-in-canvas", "readiness"], ["webgpu", "html_canvas"], TIMELINE_CHECKS + HTML_CANVAS_CHECKS[:2] + WEBGPU_CHECKS + WEBGPU_TEXTURE_CHECKS),
    Blueprint("cross-timeline-canvas-gpu", "generation", "cross_route", "hard", "Coordinate HyperFrames timeline state across DOM capture, canvas fallback, and GPU-ready metadata", ["timeline", "canvas", "webgpu"], ["webgpu", "html_canvas", "timeline", "composition"], TIMELINE_CHECKS + HTML_CANVAS_CHECKS[:2] + WEBGPU_CHECKS + COMPOSITION_CONTRACT_CHECKS),
    Blueprint("cross-production-template", "generation", "cross_route", "hard", "Build a production template scene that demonstrates route choice among HTML-in-Canvas, CanvasKit, and WebGPU fallback", ["production", "canvaskit", "webgpu", "html-in-canvas"], ["html_canvas", "webgpu", "canvaskit", "composition"], TIMELINE_CHECKS + HTML_CANVAS_CHECKS[:2] + CANVASKIT_CHECKS + WEBGPU_CHECKS + COMPOSITION_CONTRACT_CHECKS, threshold=1750),
]


TRAIN_CONTEXTS = [
    "for a product launch render",
    "for a video editor diagnostics panel",
    "for a motion design explainer",
    "for a data dashboard sequence",
    "for a developer documentation animation",
    "for a social ad composition",
]
EVAL_CONTEXT = "for a held-out release QA composition"


def make_task(blueprint: Blueprint, split: str, serial: int, context: str) -> dict[str, Any]:
    semantic_names = [item["name"] for item in blueprint.semantic_checks]
    checks = BASE_CHECKS + semantic_names
    return {
        "id": f"hf-{split}-{blueprint.stem}-{serial:03d}",
        "factory": "hyperframes",
        "schema_version": 1,
        "split": split,
        "kind": blueprint.kind,
        "prompt": (
            f"{blueprint.prompt} {context}.\n\n"
            "Build it as production-quality HyperFrames source, not a toy demo. "
            "The result must be clear from 1280x720 snapshots and safe for deterministic export."
        ),
        "constraints": COMMON_CONSTRAINTS,
        "topics": sorted(set([blueprint.family, *blueprint.topics])),
        "difficulty": blueprint.difficulty,
        "allowed_files": ["index.html"],
        "allow_generated_assets": False,
        "checks": checks,
        "required_checks": checks,
        "semantic_checks": blueprint.semantic_checks,
        "score_threshold": blueprint.threshold,
        "source_refs": refs(*blueprint.refs),
        "template_id": "hf-project-template-v1",
        "scorer_id": "hf-scorer-v1",
        "max_index_chars": 80_000,
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")


def main() -> None:
    train: list[dict[str, Any]] = []
    evals: list[dict[str, Any]] = []
    serial = 1
    for blueprint in BLUEPRINTS:
        for context in TRAIN_CONTEXTS:
            train.append(make_task(blueprint, "train", serial, context))
            serial += 1
    for index, blueprint in enumerate(BLUEPRINTS, start=1):
        evals.append(make_task(blueprint, "eval", index, EVAL_CONTEXT))

    if len(train) != 300:
        raise RuntimeError(f"expected 300 train tasks, got {len(train)}")
    if len(evals) != 50:
        raise RuntimeError(f"expected 50 eval tasks, got {len(evals)}")
    write_jsonl(TASKS_DIR / "train_tasks.jsonl", train)
    write_jsonl(TASKS_DIR / "eval_tasks.jsonl", evals)
    load_task_file(TASKS_DIR / "train_tasks.jsonl", expected_split="train")
    load_task_file(TASKS_DIR / "eval_tasks.jsonl", expected_split="eval")
    print(json.dumps({"train": len(train), "eval": len(evals)}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
