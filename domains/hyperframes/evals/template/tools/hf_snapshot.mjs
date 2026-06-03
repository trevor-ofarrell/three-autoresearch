import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright";

const workspace = process.cwd();
const snapshotDir = process.env.HF_EVAL_SNAPSHOT_DIR || path.join(workspace, "snapshots");
const desktopPath = process.env.HF_EVAL_DESKTOP_SCREENSHOT_PATH || path.join(snapshotDir, "desktop.png");
const diagnosticsDir = path.join(workspace, "diagnostics");
const htmlPath = path.join(workspace, "index.html");
const duration = readDuration();
const frameTimes = [0, duration / 2, duration].map((value) => Number(value.toFixed(3)));
const consoleErrors = [];
const pageErrors = [];
const frames = [];

function readDuration() {
  const html = fs.existsSync(htmlPath) ? fs.readFileSync(htmlPath, "utf8") : "";
  const match = html.match(/data-duration\s*=\s*["']([^"']+)["']/i);
  const parsed = Number(match?.[1] || 5);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 5;
}

function sha256(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex").slice(0, 16);
}

fs.mkdirSync(snapshotDir, { recursive: true });
fs.mkdirSync(path.dirname(desktopPath), { recursive: true });
fs.mkdirSync(diagnosticsDir, { recursive: true });

const browser = await chromium.launch({
  headless: true,
  args: ["--no-sandbox", "--disable-gpu"]
});
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1 });
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) consoleErrors.push(`${message.type()}: ${message.text()}`);
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "load" });
  await page.waitForTimeout(250);

  for (const [index, time] of frameTimes.entries()) {
    await page.evaluate((seconds) => {
      window.__hfCurrentTime = seconds;
      if (typeof window.__renderFrame === "function") window.__renderFrame(seconds);
      window.dispatchEvent(new CustomEvent("hf-seek", { detail: { time: seconds } }));
    }, time);
    await page.waitForTimeout(120);
    const outPath = path.join(snapshotDir, `frame-${String(index).padStart(3, "0")}.png`);
    await page.screenshot({ path: outPath, fullPage: false });
    frames.push({
      time,
      path: outPath,
      bytes: fs.statSync(outPath).size,
      hash: sha256(outPath)
    });
    if (index === 1) fs.copyFileSync(outPath, desktopPath);
  }

  const visibility = await page.evaluate(() => {
    const bodyText = (document.body?.innerText || "").trim();
    const visibleElements = Array.from(document.querySelectorAll("body *")).filter((element) => {
      const rect = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      return rect.width > 1 && rect.height > 1 && style.visibility !== "hidden" && style.display !== "none";
    }).length;
    const canvases = Array.from(document.querySelectorAll("canvas")).map((canvas) => ({
      id: canvas.id || "",
      width: canvas.width,
      height: canvas.height,
      displayed: window.getComputedStyle(canvas).display !== "none"
    }));
    return { bodyTextLength: bodyText.length, visibleElements, canvases };
  });

  const uniqueFrameHashes = new Set(frames.map((frame) => frame.hash)).size;
  const report = {
    ok: consoleErrors.length === 0 && pageErrors.length === 0 && fs.existsSync(desktopPath) && visibility.visibleElements > 0 && uniqueFrameHashes > 1,
    desktopPath,
    frames,
    uniqueFrameHashes,
    consoleErrors,
    pageErrors,
    visibility
  };
  fs.writeFileSync(path.join(diagnosticsDir, "snapshot-report.json"), JSON.stringify(report, null, 2) + "\n");
  if (!report.ok) {
    console.error(JSON.stringify(report, null, 2));
    process.exit(1);
  }
  console.log(JSON.stringify(report, null, 2));
} finally {
  await browser.close();
}
