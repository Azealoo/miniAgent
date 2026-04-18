import { defineConfig } from "@playwright/test";

const condaBin = "/gpfs/home/yininz6/.conda/envs/miniAgent/bin";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  outputDir: "/tmp/bioapex-playwright-results",
  use: {
    baseURL: "http://127.0.0.1:3100",
    headless: true,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `${condaBin}/npm run start:e2e -- --hostname 127.0.0.1 --port 3100`,
    url: "http://127.0.0.1:3100",
    timeout: 120_000,
    reuseExistingServer: false,
    env: {
      ...process.env,
      PATH: `${condaBin}:${process.env.PATH ?? ""}`,
      PLAYWRIGHT_BROWSERS_PATH: "0",
    },
  },
});
