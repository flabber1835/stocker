const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: ".",
  testMatch: "caesars-palace.spec.js",
  timeout: 30_000,
  expect: { timeout: 8_000 },
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "line",
  use: {
    baseURL: process.env.SENTINEL_BROWSER_BASE_URL || "http://127.0.0.1:18004",
    serviceWorkers: "allow",
    screenshot: "only-on-failure",
    trace: "retain-on-failure"
  },
  projects: [
    {
      name: "webkit-iphone",
      // Playwright can inspect service workers only in Chromium.  Blocking the
      // worker here keeps WebKit focused on the iPhone layout and page
      // lifecycle contract; the real worker path is exercised below.
      use: {
        browserName: "webkit",
        viewport: { width: 393, height: 852 },
        serviceWorkers: "block"
      }
    },
    {
      name: "chromium-pwa",
      // Full Chromium's new headless mode retains Notification permission and
      // displayed service-worker notifications. The smaller headless-shell
      // binary deliberately denies that platform surface.
      use: {
        browserName: "chromium",
        channel: process.env.SENTINEL_BROWSER_CHANNEL || "chromium",
        viewport: { width: 393, height: 852 }
      }
    }
  ]
});
