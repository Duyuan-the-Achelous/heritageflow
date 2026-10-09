import http from "k6/http";
import { check } from "k6";

export const options = {
  scenarios: {
    release_spike: {
      executor: "ramping-vus",
      startVUs: 5,
      stages: [
        { duration: "30s", target: 5 },
        { duration: "5s", target: 100 },
        { duration: "90s", target: 100 },
        { duration: "15s", target: 5 },
      ],
      gracefulRampDown: "10s",
    },
  },
  thresholds: {
    http_req_duration: ["p(95)<500", "p(99)<1000"],
    http_req_failed: ["rate<0.01"],
  },
};

const baseUrl = __ENV.BASE_URL || "http://localhost:8000";
const token = __ENV.TOKEN || "demo:guanlin:visitor";
const attractionId = __ENV.ATTRACTION_ID || "guanlin-main";
const slotId = __ENV.SLOT_ID || "demo-guanlin-main-tomorrow";

export default function () {
  const response = http.post(
    `${baseUrl}/v1/reservations`,
    JSON.stringify({
      attraction_id: attractionId,
      slot_id: slotId,
      visitor_reference: `spike-${__VU}-${__ITER}`,
      quantity: 1,
    }),
    {
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "Idempotency-Key": `spike-${__VU}-${__ITER}-${Date.now()}`,
      },
    },
  );
  check(response, { "created or capacity exhausted": (r) => [201, 409].includes(r.status) });
}

