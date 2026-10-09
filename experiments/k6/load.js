import http from "k6/http";
import { check } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";

const bookingLatency = new Trend("booking_latency", true);
const bookingErrors = new Rate("booking_errors");
const capacityRejected = new Counter("capacity_rejected");

export const options = {
  scenarios: {
    level_1: constantVUs(1, "30s", "0s"),
    level_10: constantVUs(10, "30s", "35s"),
    level_25: constantVUs(25, "30s", "70s"),
    level_50: constantVUs(50, "30s", "105s"),
    level_100: constantVUs(100, "30s", "140s"),
  },
  thresholds: {
    booking_latency: ["p(95)<500", "p(99)<1000"],
    booking_errors: ["rate<0.01"],
  },
};

function constantVUs(vus, duration, startTime) {
  return { executor: "constant-vus", vus, duration, startTime, gracefulStop: "5s" };
}

const baseUrl = __ENV.BASE_URL || "http://localhost:8000";
const token = __ENV.TOKEN || "demo:tomb-museum:visitor";
const attractionId = __ENV.ATTRACTION_ID || "tomb-museum-main";
const slotId = __ENV.SLOT_ID || "demo-tomb-museum-main-tomorrow";

export default function () {
  const key = `load-${__VU}-${__ITER}-${Date.now()}`;
  const response = http.post(
    `${baseUrl}/v1/reservations`,
    JSON.stringify({
      attraction_id: attractionId,
      slot_id: slotId,
      visitor_reference: `visitor-${__VU}-${__ITER}`,
      quantity: 1,
    }),
    {
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "Idempotency-Key": key,
      },
      tags: { operation: "create_reservation" },
    },
  );

  bookingLatency.add(response.timings.duration);
  if (response.status === 409) {
    capacityRejected.add(1);
    return;
  }
  bookingErrors.add(response.status !== 201);
  check(response, { "reservation created": (r) => r.status === 201 });
}

