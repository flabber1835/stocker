const { test, expect } = require("@playwright/test");

async function openSystemDetails(page) {
  const details = page.locator("#system-details");
  await expect(details).not.toHaveAttribute("open", "");
  await expect(page.locator("#operational-state")).toBeVisible();
  await details.locator(":scope > summary").click();
  await expect(details).toHaveAttribute("open", "");
}

async function waitForActiveWorker(page, observe) {
  await expect.poll(async () => {
    const snapshot = await page.evaluate(async () => {
      const registration = await navigator.serviceWorker.getRegistration();
      return {
        activated: registration?.active?.state === "activated",
        controlsPage: Boolean(registration?.active &&
          navigator.serviceWorker.controller === registration.active)
      };
    });
    observe?.(snapshot);
    return snapshot;
  }).toEqual({ activated: true, controlsPage: true });
}

const REQUIRED_AUTOMATION_STEPS = [
  "automation_step_discovery",
  "automation_step_data",
  "automation_step_prepare",
  "automation_step_open",
  "automation_step_transport",
  "automation_step_reconcile",
  "automation_step_complete"
];

test.describe('App resume presentation', () => {
  // Hold the foreground HTML read deterministically. Worker delivery and
  // offline navigation are qualified separately by the PWA tests below.
  test.use({serviceWorkers:'block'});
  for (const expires of [false, true]) {
    test(`a saved positive view is amber during reconnect${expires ? ' and red on timeout' : ''}`, async ({ page }) => {
      // CI's unconfigured server is deliberately red. Only this client-display
      // fixture supplies a positive headline; it is not financial evidence.
      let release;
      const held = new Promise(resolve => { release = resolve; });
      await page.route('**/', async route => {
        if (!route.request().isNavigationRequest()) await held;
        try {
          const response = await route.fetch();
          const source = await response.text();
          const body = source.replace(
            /(<span id="operational-state" class=")state [^"]+("[^>]*>)[\s\S]*?(<\/span>)/,
            '$1state ok$2CLIENT PRESENTATION FIXTURE$3');
          expect(body).not.toBe(source);
          expect(body).toContain('CLIENT PRESENTATION FIXTURE');
          await route.fulfill({response,body});
        } catch (error) {
          if (!expires) throw error; // The expected timeout can abort this request.
        }
      });
      try {
        await page.clock.install();
        await page.goto('/', {waitUntil:'domcontentloaded'});
        await openSystemDetails(page);
        await page.locator('[data-detail-key="mode-guide"] summary').click();
        const generated = await page.locator('body').getAttribute('data-generated-at');
        await page.evaluate(() => {
          window.__resumeRealNow = Date.now;
          const clock = Date.now() + 120000;
          Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});
          document.dispatchEvent(new Event('visibilitychange'));
          Date.now = () => clock;
          Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'});
          document.dispatchEvent(new Event('visibilitychange'));
          window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}));
        });
        await expect(page.locator('#operational-state')).toHaveClass('state warn');
        await expect(page.locator('#operational-state')).toContainText('REFRESHING STATUS');
        await expect(page.locator('html')).toHaveClass('refreshing-status');
        expect(await page.locator('body').getAttribute('data-generated-at')).toBe(generated);
        if (expires) {
          await page.clock.runFor(15001);
          await expect(page.locator('#operational-state')).toHaveClass('state fail');
          await expect(page.locator('#operational-state')).toContainText('STATUS NOT CURRENT');
        } else {
          await page.evaluate(() => { Date.now = window.__resumeRealNow; });
          release();
          await expect(page.locator('#operational-state')).toContainText('CLIENT PRESENTATION FIXTURE');
          await expect(page.locator('html')).not.toHaveClass('refreshing-status');
        }
        await expect(page.locator('#system-details')).toHaveAttribute('open','');
        await expect(page.locator('[data-detail-key="mode-guide"]')).toHaveAttribute('open','');
      } finally { release(); }
    });
  }
});

test.describe("Caesar's Palace on iPhone WebKit", () => {
  test.skip(({ browserName }) => browserName !== "webkit");

  for (const appearance of ["light", "dark"]) {
    for (const viewport of [
      { name: "portrait", width: 393, height: 852 },
      { name: "landscape", width: 852, height: 393 }
    ]) {
      test(`${viewport.name} ${appearance} opens every status from the compact view`, async ({ page }) => {
        await page.setViewportSize(viewport);
        await page.emulateMedia({ colorScheme: appearance });
        await page.goto("/", { waitUntil: "domcontentloaded" });

        await expect(page.locator("#operational-state")).toBeVisible();
        await expect(page.locator("#dashboard-heartbeat")).toContainText(
          "DASHBOARD HEARTBEAT");
        await expect(page.locator('[data-key="automation_step_discovery"]')).toBeHidden();
        await openSystemDetails(page);
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
        await page.locator("#system-details > summary").click();
        await expect(page.locator("#system-details")).not.toHaveAttribute("open", "");
        await expect(page.locator('[data-key="automation_step_discovery"]')).toBeHidden();
        await expect(page.locator("#operational-state")).toBeVisible();
      });
    }
  }

  test("dynamic text, long errors, and wide detail tables stay contained", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await openSystemDetails(page);
    await page.addStyleTag({ content: "body{font-size:24px!important}" });
    await page.locator(".detail").first().evaluate((node) => {
      node.textContent = "BROKER_ACCOUNT_RUNTIME_FAILURE_".repeat(80);
    });
    // Help and technical text can precede the financial table sections.
    // Require real tables and stress every section instead of depending on
    // the first disclosure or silently skipping the overflow check.
    const tableSections = page.locator("details").filter({
      has: page.locator("table")
    });
    expect(await tableSections.count()).toBeGreaterThan(0);
    for (const details of await tableSections.all()) {
      // DOM order opens ancestors before their children. Never toggle an
      // already-open ancestor closed or match a descendant's summary.
      if (await details.getAttribute("open") === null) {
        await details.locator(":scope > summary").click();
      }
      await expect(details).toHaveAttribute("open", "");
    }
    for (const table of await page.locator("table").all()) {
      await expect(table).toBeVisible();
      await table.evaluate((node) => {
        const row = node.insertRow();
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

  test("PWA readiness waits for activation and page control", async ({ context, page }) => {
    let releaseActivation;
    let gateArrived;
    let preparation;
    const gate = new Promise((resolve) => { releaseActivation = resolve; });
    const gateReached = new Promise((resolve) => { gateArrived = resolve; });
    await context.route("**/service-worker.js", async (route) => {
      const response = await route.fetch();
      const source = await response.text();
      expect(source).toContain("var names = await caches.keys();");
      await route.fulfill({
        response,
        body: source.replace("var names = await caches.keys();",
          'await fetch("/__activation_gate__"); var names = await caches.keys();')
      });
    });
    await context.route("**/__activation_gate__", async (route) => {
      gateArrived();
      await gate;
      await route.fulfill({ status: 204 });
    });
    try {
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await gateReached;
      expect(await page.evaluate(async () => {
        const registration = await navigator.serviceWorker.ready;
        return { state: registration.active.state, controller: navigator.serviceWorker.controller };
      })).toEqual({ state: "activating", controller: null });
      const snapshots = [];
      let finished = false;
      preparation = waitForActiveWorker(page, (snapshot) => snapshots.push(snapshot))
        .then(() => { finished = true; });
      await expect.poll(() => snapshots.length).toBeGreaterThan(0);
      expect(snapshots[0]).toEqual({ activated: false, controlsPage: false });
      expect(finished).toBe(false);
      releaseActivation();
      await preparation;
      expect(finished).toBe(true);
    } finally {
      releaseActivation();
      await preparation?.catch(() => undefined);
    }
  });

  test("offline navigation is explicit red and never cached green", async ({
    context,
    page
  }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await waitForActiveWorker(page);
    await context.setOffline(true);

    const [response] = await Promise.all([
      page.waitForResponse((candidate) => candidate.request().isNavigationRequest() &&
        candidate.request().frame() === page.mainFrame() && candidate.fromServiceWorker()),
      page.reload({ waitUntil: "domcontentloaded" })
    ]);
    expect(response.status()).toBe(503);
    expect(response.headers()["cache-control"]).toBe("no-store");
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
        body: JSON.stringify({ status: "subscribed", delivery_status: "QUEUED",
          sender_available: true })
      });
    });

    await page.goto("/", { waitUntil: "networkidle" });
    await waitForActiveWorker(page);
    await expect(page.locator("#push-card")).toBeHidden();
    expect(await page.evaluate(() => window.__permissionRequests)).toBe(0);
    expect(await page.evaluate(() => window.__subscribeRequests)).toBe(0);
    await openSystemDetails(page);
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

  for (const outcome of ["unavailable", "accepted", "failed", "unreadable"]) {
    test(`test notification shows ${outcome} rather than assuming delivery`, async ({ context, page }) => {
      await context.grantPermissions(["notifications"]);
      await page.addInitScript(() => {
        Object.defineProperty(ServiceWorkerRegistration.prototype, "pushManager", {
          configurable: true,
          get: () => ({ getSubscription: async () => ({
            toJSON: () => ({endpoint: "https://push.example.test/current",
              keys: {p256dh: "fixture", auth: "fixture"}}),
            unsubscribe: async () => true
          }) })
        });
      });
      const alert_id = "a".repeat(64);
      let submissions = 0;
      await page.route("**/push/subscriptions", async route => {
        submissions++;
        await route.fulfill({status: 201, contentType: "application/json",
          body: JSON.stringify({alert_id, delivery_status: "QUEUED",
            sender_available: outcome !== "unavailable"})});
      });
      await page.route("**/push/tests/*", route => route.fulfill({
        status: outcome === "unreadable" ? 503 : 200, contentType: "application/json",
        body: JSON.stringify({alert_id,
          delivery_status: outcome === "accepted" ? "ACCEPTED" : outcome === "failed" ? "FAILED" : "QUEUED",
          sender_available: outcome !== "unavailable"})
      }));
      await page.goto("/", {waitUntil: "networkidle"});
      await waitForActiveWorker(page);
      expect(submissions).toBe(0);
      await openSystemDetails(page);
      expect(submissions).toBe(0);
      await page.locator("#push-enable").click();
      await expect(page.locator("#push-status")).toContainText(
        outcome === "accepted" ? "accepted by the push service"
          : outcome === "failed" ? "notification failed"
          : outcome === "unreadable" ? "status could not be read" : "sender is unavailable");
      expect(submissions).toBe(1);
      if (outcome === "unavailable") {
        await expect(page.locator("#push-status")).not.toContainText("accepted");
      }
    });
  }

  test("the registered worker receives a synthetic push and focuses Sentinel", async ({
    context,
    page
  }) => {
    const registrations = new Map();
    const cdp = await context.newCDPSession(page);
    cdp.on("ServiceWorker.workerErrorReported", (error) => {
      console.error("PWA_WORKER_ERROR", JSON.stringify(error));
    });
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
    await waitForActiveWorker(page);
    const worker = await page.evaluate(async () => {
      const registration = await navigator.serviceWorker.getRegistration();
      return { scope: registration.scope, origin: location.origin };
    });
    expect(worker.scope).toBe(`${worker.origin}/`);
    const actor = context.serviceWorkers().find(
      (candidate) => candidate.url() === `${worker.origin}/service-worker.js`);
    expect(actor).toBeTruthy();
    await actor.evaluate(() => {
      self.__pushEvidence = { stage: "awaiting_push", notifications: [], error: null };
      const original = self.registration.showNotification.bind(self.registration);
      self.registration.showNotification = async (title, options) => {
        self.__pushEvidence.stage = "native_delivery";
        try {
          await original(title, options);
          self.__pushEvidence.notifications =
            (await self.registration.getNotifications({ tag: options.tag })).map(
              (notification) => ({
                title: notification.title, body: notification.body,
                tag: notification.tag, data: notification.data
              }));
          self.__pushEvidence.stage = "retained_at_delivery";
        } catch (error) {
          self.__pushEvidence.stage = "native_delivery_failed";
          self.__pushEvidence.error = { name: error.name, message: error.message };
          throw error;
        }
      };
    });

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

    try {
      await expect.poll(() => actor.evaluate(() => self.__pushEvidence.notifications)).toEqual([{
        title: pushed.title,
        body: pushed.body,
        tag: pushed.tag,
        data: { url: "/", alert_id: pushed.alert_id }
      }]);
    } catch (error) {
      console.error("PWA_PUSH_FAILURE", JSON.stringify(
        await actor.evaluate(() => self.__pushEvidence)));
      throw error;
    }

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
