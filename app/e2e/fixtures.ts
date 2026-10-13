import { type Browser, type Page, test as base, chromium } from "@playwright/test";
import { readFileSync } from "node:fs";
import { E2E_LOG, PORTS } from "./env";

/*
 * Browser: CHROMIUM_PATH if set (e.g. a system Chrome), else @sparticuz/chromium from npm. The latter
 * avoids `playwright install`, whose CDN is not reachable from every CI/sandbox.
 */
async function executablePath(): Promise<{ path: string; args: string[] }> {
  if (process.env.CHROMIUM_PATH) return { path: process.env.CHROMIUM_PATH, args: [] };
  const sparticuz = (await import("@sparticuz/chromium")).default;
  // Its default args target AWS Lambda; --single-process kills the browser when the first context closes.
  const args = sparticuz.args.filter((a: string) => a !== "--single-process" && !a.startsWith("--headless"));
  return { path: await sparticuz.executablePath(), args };
}

export const test = base.extend<object, { browser: Browser }>({
  browser: [
    async ({}, use) => {
      const { path, args } = await executablePath();
      const browser = await chromium.launch({ executablePath: path, args, headless: true });
      await use(browser);
      await browser.close();
    },
    { scope: "worker" },
  ],
});

export const expect = test.expect;

/** Waits for the console mailer to log a magic link for `email` and returns its path (/auth?token=…). */
export async function magicLinkFor(email: string, timeoutMs = 10_000): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const lines = readFileSync(E2E_LOG, "utf8").split("\n").filter((l) => l.includes(`MAGIC LINK for ${email}:`));
    const last = lines.at(-1);
    if (last) {
      const url = new URL(last.slice(last.lastIndexOf("http")).trim());
      return url.pathname + url.search;
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`no magic link for ${email} in ${E2E_LOG}`);
}

export const SIM_URL = `http://127.0.0.1:${PORTS.SIM_PORT}`;
export const API_URL = `http://127.0.0.1:${PORTS.API_PORT}`;

/** Local day index (days since 1970-01-01) for a YYYY-MM-DD date, as the firmware computes it. */
export function dayIndex(isoDate: string): number {
  const [y, m, d] = isoDate.split("-").map(Number);
  return Date.UTC(y, m - 1, d) / 86_400_000;
}

/** Optional screenshots for docs/review: RQ_SHOTS=<dir> npx playwright test */
export async function shot(page: Page, name: string): Promise<void> {
  if (process.env.RQ_SHOTS) await page.screenshot({ path: `${process.env.RQ_SHOTS}/${name}.png`, fullPage: true });
}
