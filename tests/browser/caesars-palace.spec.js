const { test, expect } = require("@playwright/test");

const REQUIRED_AUTOMATION_STEPS = [
  "automation_step_discovery",
  "automation_step_data",
  "automation_step_prepare",
  "automation_step_open",
  "automation_step_transport",
  "automation_step_reconcile",
  "automation_step_complete"
];

test.describe("Caesar's Palace on iPhone WebKit", () => {
  test.skip(({ browserName }) => browserName !== "webkit");

  for (const appearance of ["light", "dark"]) {
    for (const viewport of [
      { name: "portrait", width: 393, height: 852 },
      { name: "landscape", width: 852, height: 393 }
    ]) {
      test(`${viewport.name} ${appearance} keeps every status visible`, async ({ page }) => {
        await page.setViewportSize(viewport);
        await page.emulateMedia({ colorScheme: appearance });
        await page.goto("/", { waitUntil: "domcontentloaded" });

        await expect(page.locator("#operational-state")).toBeVisible();
        await expect(page.locator("#dashboard-heartbeat")).toContainText(
          "DASHBOARD HEARTBEAT");
        for (const key of REQUIRED_AUTOMATION_STEPS) {
          await expect(page.locator(`[data-key="${key}"]`)).toBeVisible();
        }
        for (const key of ["alpaca_account", "backup_restore", "runtime_identity"]) {
          await expect(page.locator(`[data-key="${key}"]`)).toBeVisible();
        }

        const layout = await page.evaluate(() => {
          const body = getComputedStyle(document.body);
          return {
            viewport: window.innerWidth,
            documentWidth: document.documentElement.scrollWidth,
            paddingLeft: Number.parseFloat(body.paddingLeft),
            paddingRight: Number.parseFloat(body.paddingRight)
          };
        });
        expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewport + 1);
        expect(layout.paddingLeft).toBeGreaterThan(0);
        expect(layout.paddingRight).toBeGreaterThan(0);
      });
    }
  }

  test("dynamic text, long errors, and wide detail tables stay contained", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await page.addStyleTag({ content: "body{font-size:24px!important}" });
    await page.locator(".detail").first().evaluate((node) => {
      node.textContent = "BROKER_ACCOUNT_RUNTIME_FAILURE_".repeat(80);
    });
    const details = page.locator("details").first();
    if (await details.count()) {
      await details.locator("summary").click();
      await details.locator("table").evaluate((table) => {
        const row = table.insertRow();
        row.insertCell().textContent = "WIDE_COLUMN_".repeat(100);
      });
    }

    const sizes = await page.evaluate(() => ({
      viewport: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      heartbeat: document.querySelector("#dashboard-heartbeat").getBoundingClientRect(),
      finalStep: document.querySelector('[data-key="automation_step_complete"]').getBoundingClientRect()
    }));
    expect(sizes.documentWidth).toBeLessThanOrEqual(sizes.viewport + 1);
    expect(sizes.heartbeat.width).toBeGreaterThan(0);
    expect(sizes.finalStep.width).toBeGreaterThan(0);
  });

  test("offline transition immediately withdraws current status", async ({
    context,
    page
  }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await context.setOffline(true);

    await expect(page.locator("#dashboard-heartbeat")).toContainText("LOST");
    await expect(page.locator("#operational-state")).toContainText("STATUS NOT CURRENT");
    await context.setOffline(false);
  });
});

test.describe("Caesar's Palace PWA and push path", () => {
  test.skip(({ browserName }) => browserName !== "chromium");

  test("offline navigation is explicit red and never cached green", async ({
    context,
    page
  }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await page.evaluate(() => navigator.serviceWorker.ready);
    await context.setOffline(true);

    const response = await page.reload({ waitUntil: "domcontentloaded" });
    expect(response && response.status()).toBe(503);
    await expect(page.locator("body")).toContainText("OPERATIONAL RED — OFFLINE");
    await context.setOffline(false);
  });

  test("permission and PushManager subscription occur only after the explicit click", async ({
    context,
    page
  }) => {
    let enrolled = null;
    await context.grantPermissions(["notifications"]);
    await page.addInitScript(() => {
      window.__permissionRequests = 0;
      window.__subscribeRequests = 0;
      window.__fakeSubscription = null;
      Object.defineProperty(Notification, "requestPermission", {
        configurable: true,
        value: async () => {
          window.__permissionRequests += 1;
          return "granted";
        }
      });
      const manager = {
        getSubscription: async () => window.__fakeSubscription,
        subscribe: async (options) => {
          window.__subscribeRequests += 1;
          if (!options.userVisibleOnly || !(options.applicationServerKey instanceof Uint8Array)) {
            throw new Error("invalid subscription options");
          }
          window.__fakeSubscription = {
            endpoint: "https://push.example.test/device-browser",
            toJSON: () => ({
              endpoint: "https://push.example.test/device-browser",
              keys: { p256dh: "browser-key", auth: "browser-auth" }
            }),
            unsubscribe: async () => true
          };
          return window.__fakeSubscription;
        }
      };
      Object.defineProperty(ServiceWorkerRegistration.prototype, "pushManager", {
        configurable: true,
        get: () => manager
      });
    });
    await page.route("**/push/config", (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ applicationServerKey: `B${"A".repeat(86)}` })
    }));
    await page.route("**/push/subscriptions", async (route) => {
      enrolled = route.request().postDataJSON();
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ status: "subscribed" })
      });
    });

    await page.goto("/", { waitUntil: "networkidle" });
    await page.evaluate(() => navigator.serviceWorker.ready);
    await expect(page.locator("#push-card")).toBeVisible();
    await expect(page.locator("#push-status")).toContainText("off");
    expect(await page.evaluate(() => window.__permissionRequests)).toBe(0);
    expect(await page.evaluate(() => window.__subscribeRequests)).toBe(0);

    await page.locator("#push-enable").click();

    await expect(page.locator("#push-status")).toContainText("single test notification");
    expect(await page.evaluate(() => window.__permissionRequests)).toBe(1);
    expect(await page.evaluate(() => window.__subscribeRequests)).toBe(1);
    expect(enrolled.endpoint).toBe("https://push.example.test/device-browser");
    expect(enrolled.test_id).toMatch(/^[0-9a-f-]{36}$/);
  });

  test("the registered worker receives a synthetic push and focuses Sentinel", async ({
    context,
    page
  }) => {
    const registrations = new Map();
    const cdp = await context.newCDPSession(page);
    cdp.on("ServiceWorker.workerRegistrationUpdated", ({ registrations: updates }) => {
      for (const registration of updates) {
        if (registration.isDeleted) {
          registrations.delete(registration.registrationId);
        } else {
          registrations.set(registration.registrationId, registration);
        }
      }
    });
    await cdp.send("ServiceWorker.enable");
    await context.grantPermissions(["notifications"]);
    await page.goto("/", { waitUntil: "networkidle" });
    const worker = await page.evaluate(async () => {
      const registration = await navigator.serviceWorker.ready;
      return { scope: registration.scope, origin: location.origin };
    });
    expect(worker.scope).toBe(`${worker.origin}/`);

    await expect.poll(() => Array.from(registrations.values()).find(
      (registration) => registration.scopeURL === worker.scope
    ) || null).not.toBeNull();
    const registration = Array.from(registrations.values()).find(
      (candidate) => candidate.scopeURL === worker.scope
    );
    const pushed = {
      alert_id: "alert-red-1",
      title: "Caesar's Palace — action required",
      body: "automation retry budget exhausted",
      tag: "alert-red-1",
      url: "/"
    };
    await cdp.send("ServiceWorker.deliverPushMessage", {
      origin: worker.origin,
      registrationId: registration.registrationId,
      data: JSON.stringify(pushed)
    });

    await expect.poll(() => page.evaluate(async () => {
      const active = await navigator.serviceWorker.ready;
      return (await active.getNotifications({ tag: "alert-red-1" })).map(
        (notification) => ({
          title: notification.title,
          body: notification.body,
          tag: notification.tag,
          data: notification.data
        })
      );
    })).toEqual([{
      title: pushed.title,
      body: pushed.body,
      tag: pushed.tag,
      data: { url: "/", alert_id: pushed.alert_id }
    }]);

    const result = await page.evaluate(async () => {
      const source = await fetch("/service-worker.js", { cache: "no-store" }).then((r) => r.text());
      const handlers = {};
      const notifications = [];
      const actions = [];
      const client = {
        url: `${location.origin}/before`,
        navigate: async function(url) {
          actions.push(["navigate", url]);
          this.url = url;
          return this;
        },
        focus: async function() {
          actions.push(["focus", this.url]);
          return this;
        }
      };
      const worker = {
        location: { origin: location.origin },
        registration: {
          showNotification: async (title, options) => {
            notifications.push({ title, options });
          }
        },
        clients: {
          claim: async () => undefined,
          matchAll: async () => [client],
          openWindow: async (url) => actions.push(["open", url])
        },
        skipWaiting: async () => undefined,
        addEventListener: (name, handler) => { handlers[name] = handler; }
      };
      const fakeCaches = { keys: async () => [], delete: async () => true };
      new Function("self", "caches", "fetch", "Response", "URL", source)(
        worker, fakeCaches, fetch, Response, URL);

      let pushWork;
      handlers.push({
        data: { json: () => ({
          alert_id: "alert-click-1",
          title: "Caesar's Palace — action required",
          body: "automation retry budget exhausted",
          tag: "alert-click-1",
          url: "/"
        }) },
        waitUntil: (promise) => { pushWork = promise; }
      });
      await pushWork;

      let clickWork;
      handlers.notificationclick({
        notification: {
          data: notifications[0].options.data,
          close: () => actions.push(["close"])
        },
        waitUntil: (promise) => { clickWork = promise; }
      });
      await clickWork;
      return { notifications, actions };
    });

    expect(result.notifications).toHaveLength(1);
    expect(result.notifications[0].title).toContain("action required");
    expect(result.notifications[0].options.tag).toBe("alert-click-1");
    expect(result.actions[0]).toEqual(["close"]);
    expect(result.actions.some(([action]) => action === "navigate")).toBe(true);
    expect(result.actions.some(([action]) => action === "focus")).toBe(true);
    expect(result.actions.some(([action]) => action === "open")).toBe(false);
    await cdp.detach();
  });
});
