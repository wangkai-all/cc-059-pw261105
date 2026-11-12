import { chromium } from "playwright";
import fs from "node:fs";

const shots = "/tmp/shots";
fs.mkdirSync(shots, { recursive: true });

const fontDir = "/tmp/fonts";
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || "/tmp/chromium",
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--font-render-hinting=none"],
  env: { ...process.env, FONTCONFIG_PATH: fontDir, FONTCONFIG_FILE: "/tmp/fonts/fonts.conf", HOME: "/tmp/home" },
});
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
const errors = [];
page.on("console", (msg) => {
  if (msg.type() === "error") errors.push(msg.text());
});
page.on("pageerror", (err) => errors.push(`PAGEERROR ${err.message}`));

const baseUrl = process.env.BASE_URL || "http://localhost:4173";

await page.goto(baseUrl, { waitUntil: "networkidle" });
await page.waitForTimeout(1200);
await page.evaluate(() => document.fonts.ready);
await page.waitForTimeout(600);
await page.screenshot({ path: `${shots}/01-graph.png`, fullPage: false });

// click an edge by dispatching on an edge line via element handle
// Prefer the repeated-citation edge if present, so the drawer shows 2 records.
const point = await page.evaluate(() => {
  const lines = [...document.querySelectorAll(".edge-hit")];
  const target = lines.find((l) => l.closest("g").textContent.includes("×")) ?? lines[0];
  const mid = target.getPointAtLength(target.getTotalLength() / 2);
  const ctm = document.querySelector(".graph-svg").getScreenCTM();
  return { x: ctm.a * mid.x + ctm.c * mid.y + ctm.e, y: ctm.b * mid.x + ctm.d * mid.y + ctm.f };
});
await page.mouse.click(point.x, point.y);
await page.waitForTimeout(900);
await page.evaluate(() => document.fonts.ready);
await page.screenshot({ path: `${shots}/02-edge-drawer.png`, fullPage: false });

// hover a node for tooltip
const nodes = page.locator(".node circle").nth(3);
await nodes.hover();
await page.waitForTimeout(400);
await page.screenshot({ path: `${shots}/03-tooltip.png`, fullPage: false });

// ranking tab
await page.getByRole("tab", { name: /排名与详情/ }).click();
await page.waitForTimeout(500);
await page.screenshot({ path: `${shots}/04-ranking.png`, fullPage: false });

// matrix tab
await page.getByRole("tab", { name: /年度 × 主题/ }).click();
await page.waitForTimeout(500);
await page.locator(".heatmap .cell").nth(6).hover();
await page.waitForTimeout(300);
await page.screenshot({ path: `${shots}/05-matrix.png`, fullPage: false });

// author tab
await page.getByRole("tab", { name: /作者视角/ }).click();
await page.waitForTimeout(500);
await page.locator(".author-row").first().click();
await page.waitForTimeout(400);
await page.evaluate(() => document.fonts.ready);
await page.screenshot({ path: `${shots}/06-authors.png`, fullPage: false });

// pending tab
await page.getByRole("tab", { name: /待确认/ }).click();
await page.waitForTimeout(500);
await page.screenshot({ path: `${shots}/07-pending.png`, fullPage: false });

console.log(JSON.stringify({ errors }, null, 2));
await browser.close();
