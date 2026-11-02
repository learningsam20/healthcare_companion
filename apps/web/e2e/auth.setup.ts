import { test } from "@playwright/test";
import { mkdirSync } from "node:fs";

import {
  AUTH_DIR,
  DEMO_USERS,
  authFile,
  signInThroughKeycloak,
  type DemoRole,
} from "./support";

const roles = Object.keys(DEMO_USERS) as DemoRole[];

for (const role of roles) {
  test(`authenticate ${role} (${DEMO_USERS[role]}) and store session`, async ({ page }) => {
    mkdirSync(AUTH_DIR, { recursive: true });
    await signInThroughKeycloak(page, DEMO_USERS[role]);
    await page.context().storageState({ path: authFile(role) });
  });
}
