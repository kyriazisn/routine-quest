import { randomUUID } from "node:crypto";
import { API_URL, SIM_URL, dayIndex, expect, magicLinkFor, shot, test } from "./fixtures";

const DEVICE_ID = "rq-0123456789ab";

test("parent onboarding → device pairing → quest completion shows on Today", async ({ page, request }) => {
  const email = `parent-${Date.now()}@example.com`;

  // O1 — magic link
  await page.goto("/");
  await page.getByLabel("Email γονέα").fill(email);
  await shot(page, "o1-login");
  await page.getByRole("button", { name: "Συνέχεια με σύνδεσμο στο email" }).click();
  await expect(page.getByText("Σου στείλαμε σύνδεσμο")).toBeVisible();
  await page.goto(await magicLinkFor(email));

  // O5 — child + templates
  await expect(page).toHaveURL(/\/setup\/child$/);
  await page.getByLabel("Ψευδώνυμο παιδιού").fill("Λένα");
  await shot(page, "o5-child");
  await page.getByRole("button", { name: "Συνέχεια" }).click();

  // O2 — push (not automatable headless: skip)
  await expect(page).toHaveURL(/\/setup\/push$/);
  await page.getByRole("button", { name: "Αργότερα" }).click();
  await expect(page).toHaveURL(/\/setup\/pair$/);

  // O3 — provisioning against the simulator instead of BLE
  await page.goto(`/setup/pair?sim=${encodeURIComponent(SIM_URL)}`);
  await page.getByRole("button", { name: "Αναζήτηση συσκευής" }).click();
  const pop = page.getByLabel(/Κωδικός συσκευής/);
  await pop.fill("wrong-pop");
  await page.getByRole("button", { name: "Σύνδεση" }).click();
  await expect(page.getByText("Λάθος κωδικός συσκευής")).toBeVisible();
  await pop.fill("rq-e2e-pop");
  await page.getByRole("button", { name: "Σύνδεση" }).click();

  // O4 — Wi-Fi: networks come from the device scan; wrong password first, then the right one
  const ssid = page.locator("select[name=ssid]");
  await expect(ssid).toBeVisible();
  await expect(ssid.locator("option")).toHaveCount(2);
  await ssid.selectOption("HomeNet");
  await shot(page, "o4-wifi");
  await page.getByLabel("Κωδικός Wi-Fi").fill("not-it");
  await page.getByRole("button", { name: "Σύνδεση" }).click();
  await expect(page.getByText("Λάθος κωδικός Wi-Fi.")).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("Κωδικός Wi-Fi").fill("secret123");
  await page.getByRole("button", { name: "Σύνδεση" }).click();
  await expect(page.getByText("Περιμένουμε τη συσκευή")).toBeVisible({ timeout: 15_000 });

  // The device received the claim code over the encrypted session; now play the firmware's part.
  const sim = await (await request.get(`${SIM_URL}/_state`)).json();
  expect(sim).toMatchObject({ ssid: "HomeNet", passphrase_set: true, applied: true, session_ok: true });
  const claim = await request.post(`${API_URL}/v1/device/claim`, {
    data: { device_id: DEVICE_ID, claim_code: sim.claim_code, fw_version: "0.1.0" },
  });
  expect(claim.status()).toBe(200);
  const { device_token } = await claim.json();

  await expect(page.getByText("Η συσκευή είναι online")).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: /Ξεκινάμε/ }).click();

  // Pick a quest scheduled today (evening template runs every day) and complete it from the "device".
  const me = await (await page.request.get("/v1/me")).json();
  const childId = me.children[0].id;
  const today = await (await page.request.get(`/v1/children/${childId}/today`)).json();
  const q = today.quests.find((x: { status: string }) => x.status !== "not_today");
  expect(q, "a quest scheduled today").toBeTruthy();
  const day = dayIndex(today.date);
  const n = q.routine.steps.length;
  let seq = 0;
  const ev = (type: string, step = 0) => ({
    event_id: randomUUID(), seq: ++seq, type, ts: Math.floor(Date.now() / 1000), day_index: day,
    routine_id: q.routine.id, step, fast: false,
  });
  const events = [ev("window_open"), ...Array.from({ length: n - 1 }, (_, s) => ev("step_done", s)), ev("quest_complete", n - 1)];
  const sent = await request.post(`${API_URL}/v1/device/events`, {
    headers: { Authorization: `Bearer ${device_token}` },
    data: { device_id: DEVICE_ID, events },
  });
  expect(await sent.json()).toEqual({ accepted: events.length, duplicates: 0 });

  // C1 — Today reflects it
  await page.reload();
  await expect(page.getByTestId(`quest-status-${q.routine.id}`)).toHaveText(/Ολοκληρώθηκε/);
  await shot(page, "c1-today");

  // C4 — History has the XP; C5 — wallet has the star
  await page.getByRole("link", { name: /Ιστορικό/ }).click();
  await expect(page.getByText(/Level \d+ · \d+ XP/)).toBeVisible();
  await shot(page, "c4-history");
  await page.getByRole("link", { name: /Rewards/ }).click();
  await expect(page.getByText("Πορτοφόλι: 1 αστέρι")).toBeVisible();
  await shot(page, "c5-rewards");

  // C6 — device shows up in Settings
  await page.getByRole("link", { name: /Ρυθμίσεις/ }).click();
  await expect(page.getByText(/Συσκευή 89AB/)).toBeVisible();
  await shot(page, "c6-settings");
});

test("unknown session shows login", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Routine Quest" })).toBeVisible();
});
