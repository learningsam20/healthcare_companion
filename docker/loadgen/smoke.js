import http from "k6/http";
import { check, sleep } from "k6";

// This is a liveness smoke, not a capacity test. The documented load profiles
// authenticate the real Keycloak cohort through scripts/load_test.py.
export const options = {
  vus: 1,
  iterations: 3,
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<500"],
  },
};

export default function () {
  const base = __ENV.BASE_URL || "http://api:8000";
  const health = http.get(`${base}/healthz`);
  check(health, { "healthz 200": (r) => r.status === 200 });
  sleep(1);
}
