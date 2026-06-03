import fs from "node:fs";
import path from "node:path";

const workspace = process.cwd();
const mode = readArg("--mode") || "validate";
const htmlPath = path.join(workspace, "index.html");
const manifestPath = path.join(workspace, "project.manifest.json");
const diagnosticsDir = path.join(workspace, "diagnostics");
const html = fs.existsSync(htmlPath) ? fs.readFileSync(htmlPath, "utf8") : "";
const findings = [];

function readArg(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : "";
}

function add(code, severity, message, index = 0) {
  findings.push({ code, severity, message, index });
}

function has(pattern) {
  return pattern.test(html);
}

function stripComments(source) {
  return source
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
}

function readJson(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch (error) {
    add("json_parse", "error", `${path.basename(filePath)} is not valid JSON: ${error.message}`);
    return null;
  }
}

function extractInlineScripts() {
  const scripts = [];
  const pattern = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi;
  for (const match of html.matchAll(pattern)) {
    const attrs = match[1] || "";
    if (/\bsrc\s*=/i.test(attrs)) continue;
    if (/\btype\s*=\s*["']application\/json["']/i.test(attrs)) continue;
    scripts.push({ text: match[2] || "", index: match.index || 0 });
  }
  return scripts;
}

function validateSyntax() {
  if (!html.trim()) {
    add("missing_index", "error", "index.html is missing or empty.");
    return;
  }
  for (const script of extractInlineScripts()) {
    try {
      new Function(script.text);
    } catch (error) {
      add("script_syntax", "error", `Inline script has invalid syntax: ${error.message}`, script.index);
    }
  }
}

function validateDeterminism() {
  const source = stripComments(html);
  const rules = [
    ["date_now", /\bDate\.now\s*\(/g, "Date.now() is wall-clock based."],
    ["performance_now", /\bperformance\.now\s*\(/g, "performance.now() is wall-clock based."],
    ["math_random", /\bMath\.random\s*\(/g, "Math.random() is unseeded randomness."],
    ["request_animation_frame", /\brequestAnimationFrame\s*\(/g, "requestAnimationFrame() is realtime-driven."],
    ["interval_timer", /\bsetInterval\s*\(/g, "setInterval() is realtime-driven."],
    ["network_asset", /\b(?:src|href|poster)\s*=\s*["']https?:\/\//gi, "Network assets are not deterministic."],
    ["network_asset", /\burl\(\s*["']?https?:\/\//gi, "Network CSS assets are not deterministic."],
    ["network_fetch", /\bfetch\s*\(\s*["']https?:\/\//gi, "Network fetch is not allowed in render paths."]
  ];
  for (const [code, pattern, message] of rules) {
    for (const match of source.matchAll(pattern)) add(code, "error", message, match.index || 0);
  }
}

function validateManifest() {
  if (!fs.existsSync(manifestPath)) {
    add("missing_manifest", "error", "project.manifest.json is required for a HyperFrames task workspace.");
    return;
  }
  const manifest = readJson(manifestPath);
  if (!manifest) return;
  if (manifest.schemaVersion !== 1) add("manifest_schema", "error", "project.manifest.json must use schemaVersion 1.");
  if (manifest.compositionPath !== "index.html") add("manifest_composition_path", "error", "compositionPath must point to index.html.");
  if (!manifest.renderDefaults || manifest.renderDefaults.width !== 1280 || manifest.renderDefaults.height !== 720 || manifest.renderDefaults.fps !== 30) {
    add("manifest_render_defaults", "error", "renderDefaults must declare 1280x720 at 30 fps.");
  }
  if (!manifest.htmlInCanvas || manifest.htmlInCanvas.fallbackMode !== "auto") {
    add("manifest_html_canvas_mode", "error", "htmlInCanvas.fallbackMode must be auto.");
  }
}

function validateTimeline() {
  if (!has(/data-composition-id\s*=/i)) add("missing_composition", "error", "Root composition must declare data-composition-id.");
  if (!has(/data-duration\s*=/i)) add("missing_duration", "error", "Composition must declare duration metadata.");
  if (!has(/data-start\s*=\s*["']0["']/i)) add("missing_start_zero", "error", "Root composition must start at 0.");
  if (!has(/data-width\s*=\s*["']1280["']/i) || !has(/data-height\s*=\s*["']720["']/i) || !has(/data-fps\s*=\s*["']30["']/i)) {
    add("missing_root_render_metadata", "error", "Root composition must declare width, height, and fps metadata.");
  }
  if (!has(/vendor\/gsap\/gsap\.min\.js/i)) add("missing_local_gsap", "error", "Composition must load local vendor/gsap/gsap.min.js.");
  if (!has(/\bgsap\.timeline\s*\(\s*\{[^}]*paused\s*:\s*true/is)) add("missing_paused_gsap_timeline", "error", "Use a real paused GSAP timeline.");
  if (!has(/window\.__timelines\s*\[/)) add("missing_timeline_registration", "error", "Register the timeline in window.__timelines[compositionId].");
  if (!has(/window\.__renderFrame\s*=/)) add("missing_render_frame", "error", "Expose a deterministic window.__renderFrame(seconds).");
  if (!has(/hf-seek/)) add("missing_seek_event", "error", "Respond to the hf-seek event.");
  if (has(/data-layer\s*=/i)) add("legacy_data_layer", "error", "Use data-track-index for timing tracks, not data-layer.");
  if (has(/data-end\s*=/i)) add("legacy_data_end", "error", "Use data-start plus data-duration, not data-end.");
  for (const match of html.matchAll(/<video\b[^>]*>/gi)) {
    const tag = match[0] || "";
    if (!/\bmuted\b/i.test(tag)) add("video_not_muted", "error", "Composition video clips must be muted; audio is modeled separately.");
    if (/\bautoplay\b/i.test(tag)) add("video_autoplay", "error", "Composition media must be seek-driven, not autoplay.");
  }
}

function validatePerformanceWarnings() {
  const rules = [
    ["expensive_backdrop_filter", /backdrop-filter\s*:/gi, "backdrop-filter is expensive in rendered compositions."],
    ["transition_all", /transition\s*:\s*all/gi, "transition: all is too broad for deterministic render QA."],
    ["large_box_shadow", /box-shadow\s*:[^;]*(?:\d{3,}px|\d{2,}rem)/gi, "Very large shadows are expensive in snapshot/render paths."],
    ["image_missing_dimensions", /<img\b(?![^>]*(?:width|height)\s*=)/gi, "Images should declare stable dimensions."]
  ];
  const source = stripComments(html);
  for (const [code, pattern, message] of rules) {
    for (const match of source.matchAll(pattern)) add(code, "warning", message, match.index || 0);
  }
}

function validateHtmlCanvas() {
  const usesDraw = has(/\bdrawElementImage\s*\(/);
  const usesWebglTexture = has(/\btexElementImage2D\s*\(/);
  const usesWebgpuTexture = has(/\bcopyElementImageToTexture\s*\(/);
  const usesDomTexture = usesDraw || usesWebglTexture || usesWebgpuTexture;
  if (!usesDomTexture) return;
  if (!has(/<canvas\b[^>]*\blayoutsubtree\b/i)) add("missing_layoutsubtree", "error", "DOM texture tasks need <canvas layoutsubtree>.");
  if (!has(/data-html-canvas-fallback\b/i)) add("missing_fallback", "error", "DOM texture tasks need [data-html-canvas-fallback].");

  const canvasPattern = /<canvas\b[^>]*\blayoutsubtree\b[^>]*>([\s\S]*?)<\/canvas>/gi;
  let foundDirectChild = false;
  for (const match of html.matchAll(canvasPattern)) {
    const body = (match[1] || "").replace(/<!--[\s\S]*?-->/g, "").trim();
    if (/^<([a-z][\w:-]*)\b[^>]*>/i.test(body)) foundDirectChild = true;
    if (/\bhidden\b/i.test(body) || /display\s*:\s*none/i.test(body)) {
      add("source_display_none", "error", "Drawable source inside layoutsubtree must not be hidden.");
    }
    if (/style\s*=\s*["'][^"']*transform\s*:/i.test(body)) {
      add("source_transform", "error", "Drawable source must not rely on source CSS transform.");
    }
  }
  if (!foundDirectChild) add("missing_direct_child", "error", "<canvas layoutsubtree> must contain a direct drawable child.");
}

function validateCanvasKit() {
  if (!has(/\bCanvasKitInit\b|canvaskit/i)) return;
  if (!has(/vendor\/canvaskit\/canvaskit\.js/i)) add("canvaskit_missing_local_runtime", "error", "CanvasKit must load vendor/canvaskit/canvaskit.js.");
  if (!has(/locateFile\s*:\s*[^}]*vendor\/canvaskit/is)) add("canvaskit_missing_locate_file", "error", "CanvasKit locateFile must resolve vendor/canvaskit/.");
  if (!has(/data-canvaskit-fallback\b|data-html-canvas-fallback\b/i)) add("canvaskit_missing_fallback", "error", "CanvasKit tasks need a visible fallback.");
  if (!has(/\brenderFrame\s*\(\s*seconds|\bfunction\s+renderFrame\s*\(/)) add("canvaskit_missing_render_frame", "error", "CanvasKit drawing must be behind renderFrame(seconds).");
  if (!has(/\.flush\s*\(/)) add("canvaskit_missing_flush", "error", "CanvasKit surfaces must call surface.flush().");
  if (!has(/\.delete\s*\(|try\s*\{[\s\S]*finally|reuse/i)) add("canvaskit_lifecycle", "warning", "CanvasKit WASM-backed objects should be reused or deleted.");
}

function validateWebGpu() {
  if (!has(/\bnavigator\.gpu\b|\brequestAdapter\s*\(|\bGPUDevice\b|\bcopyElementImageToTexture\b/)) return;
  if (!has(/\bnavigator\.gpu\b/) || !has(/\brequestAdapter\s*\(/) || !has(/\brequestDevice\s*\(/)) {
    add("webgpu_missing_device_path", "error", "WebGPU tasks must request adapter and device explicitly.");
  }
  if (!has(/fallback/i)) add("webgpu_missing_fallback", "error", "WebGPU tasks need an unavailable-device fallback.");
  if (!has(/__hfWebGpu\?\.\s*registerDevice\s*\(/)) add("webgpu_missing_register_device", "error", "Register WebGPU device with window.__hfWebGpu.");
  if (!has(/queue\.submit\s*\(/)) add("webgpu_missing_submit", "error", "Submit encoded WebGPU commands through device.queue.submit().");
  if (!has(/__hfWebGpu\?\.\s*registerFrame\s*\(/) || !has(/onSubmittedWorkDone\s*\(/)) {
    add("webgpu_missing_frame_fence", "error", "Register queue.onSubmittedWorkDone() after every submit.");
  }
}

validateSyntax();
if (mode !== "syntax") {
  validateManifest();
  validateDeterminism();
  validateTimeline();
  validatePerformanceWarnings();
  validateHtmlCanvas();
  validateCanvasKit();
  validateWebGpu();
}

fs.mkdirSync(diagnosticsDir, { recursive: true });
const report = {
  ok: findings.every((finding) => finding.severity !== "error"),
  mode,
  findings
};
fs.writeFileSync(path.join(diagnosticsDir, `${mode}-report.json`), JSON.stringify(report, null, 2) + "\n");

if (!report.ok) {
  console.error(JSON.stringify(report, null, 2));
  process.exit(1);
}
console.log(JSON.stringify(report, null, 2));
