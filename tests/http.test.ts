import { describe, expect, test } from "bun:test";
import { createHttpServer } from "../src/http/server";
import { HttpApplicationError, type HttpApplication, type PipelineSnapshot } from "../src/http/contracts";

const snapshot: PipelineSnapshot = {
  ready: 2, leased: 1, retry_wait: 0, paused: 0,
  oldest_ready_at: null, oldest_retry_at: null, worker_count: 1, active_leases: 1,
  stuck_intakes: [], recent_errors: [],
};
function fixture(overrides: Partial<HttpApplication> = {}) {
  const requests: unknown[] = [];
  const application: HttpApplication = {
    enqueue: async request => { requests.push(request); return { chunks_stored: 2 }; },
    pipelineSnapshot: async () => snapshot,
    pause: async () => 2, resume: async () => 2, discard: async () => 2,
    startDream: async () => ({ job_id: "job-1", status: "pending", error: null }),
    getDreamJob: async () => ({ job_id: "job-1", status: "complete", error: null }),
    recall: async request => { requests.push(request); return { answer: "Found it", context: { nodes: [], edges: [], unprocessed: [{ id: "intake_chunk:1", content: "raw" }] } }; },
    getGraph: async id => ({ node: { id }, connections: [] }),
    ...overrides,
  };
  return { server: createHttpServer(application), requests };
}
function request(path: string, body?: unknown, headers?: Record<string, string>) {
  return new Request(`http://localhost${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { "content-type": "application/json", ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

describe("non-conversation HTTP routes", () => {
  test("health reports an available server", async () => {
    const response = await fixture().server.handle(request("/health"));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: "ok" });
  });
  test("ingest acknowledges synchronous staging and forwards the idempotency key", async () => {
    const { server, requests } = fixture();
    const response = await server.handle(request("/ingest", { text: "memory", hints: ["work"], source: "mobile" }, { "Idempotency-Key": "capture-1" }));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ chunks_stored: 2 });
    expect(requests).toEqual([{ text: "memory", hints: ["work"], source: "mobile", idempotency_key: "capture-1" }]);
  });
  test("ingest retries preserve the same key and staging acknowledgement", async () => {
    const { server, requests } = fixture();
    const body = { text: "memory", hints: [], source: "mobile" };
    for (let attempt = 0; attempt < 2; attempt++) {
      const response = await server.handle(request("/ingest", body, { "Idempotency-Key": "capture-1" }));
      expect(response.status).toBe(200);
      expect(await response.json()).toEqual({ chunks_stored: 2 });
    }
    expect(requests).toEqual([
      { ...body, idempotency_key: "capture-1" },
      { ...body, idempotency_key: "capture-1" },
    ]);
  });
  test("ingest supplies existing defaults when optional fields are omitted", async () => {
    const { server, requests } = fixture();
    await server.handle(request("/ingest", { text: "memory" }));
    expect(requests).toEqual([{ text: "memory", hints: [], source: "api" }]);
  });
  for (const [kind, status] of [["conflict", 409], ["invalid", 400], ["unavailable", 503]] as const) {
    test(`ingest maps ${kind} to ${status}`, async () => {
      const { server } = fixture({ enqueue: async () => { throw new HttpApplicationError(kind, "staging failed"); } });
      const response = await server.handle(request("/ingest", { text: "memory" }));
      expect(response.status).toBe(status);
      expect(await response.json()).toEqual({ detail: "staging failed" });
    });
  }
  test("dream returns 202 with a pollable Location", async () => {
    const { server } = fixture();
    const response = await server.handle(request("/dream", {}));
    expect(response.status).toBe(202);
    expect(response.headers.get("Location")).toBe("/dream/jobs/job-1");
    expect(await response.json()).toEqual({ job_id: "job-1", status: "pending", error: null });
    const poll = await server.handle(request("/dream/jobs/job-1"));
    expect(poll.status).toBe(200);
    expect(await poll.json()).toEqual({ job_id: "job-1", status: "complete", error: null });
  });
  test("unknown dream jobs return 404", async () => {
    const response = await fixture({ getDreamJob: async () => undefined }).server.handle(request("/dream/jobs/missing"));
    expect(response.status).toBe(404);
  });
  test("pipeline returns queue and worker visibility", async () => {
    const response = await fixture().server.handle(request("/ingest/pipeline"));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(snapshot);
  });
  for (const operation of ["pause", "resume", "discard"] as const) {
    test(`${operation} returns the intake identity and the documented count`, async () => {
      const ids: string[] = [];
      const { server } = fixture({ [operation]: async (id: string) => { ids.push(id); return 2; } });
      const response = await server.handle(request(`/ingest/pipeline/intake-1/${operation}`, {}));
      expect(response.status).toBe(200);
      expect(await response.json()).toEqual(operation === "discard" ? { intake_id: "intake-1", chunks_discarded: 2 } : { intake_id: "intake-1" });
      expect(ids).toEqual(["intake-1"]);
    });
    test(`${operation} returns 404 when no chunks change`, async () => {
      const response = await fixture({ [operation]: async () => 0 }).server.handle(request(`/ingest/pipeline/missing/${operation}`, {}));
      expect(response.status).toBe(404);
    });
  }
  test("recall preserves separate unprocessed evidence", async () => {
    const { server, requests } = fixture();
    const response = await server.handle(request("/recall", { question: "Where?", hints: ["work"] }));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ answer: "Found it", context: { nodes: [], edges: [], unprocessed: [{ id: "intake_chunk:1", content: "raw" }] } });
    expect(requests).toEqual([{ question: "Where?", hints: ["work"] }]);
  });
  test("graph lookup preserves canonical IDs and connections", async () => {
    const response = await fixture().server.handle(request("/graph/note:1"));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ node: { id: "note:1" }, connections: [] });
  });
  test("unknown graph nodes return 404", async () => {
    const response = await fixture({ getGraph: async () => undefined }).server.handle(request("/graph/note:missing"));
    expect(response.status).toBe(404);
  });
  for (const path of ["/converse", "/converse/stream", "/mcp", "/unknown"]) {
    test(`${path} uses the framework missing-route response`, async () => {
      const response = await fixture().server.handle(request(path, {}));
      expect(response.status).toBe(404);
    });
  }
  for (const [path, body] of [["/ingest", {}], ["/ingest", { text: 12 }], ["/recall", {}], ["/recall", { question: "hi", hints: [1] }]] as const) {
    test(`${path} rejects malformed JSON shapes before application calls: ${JSON.stringify(body)}`, async () => {
      const { server, requests } = fixture();
      const response = await server.handle(request(path, body));
      expect(response.status).toBe(422);
      expect(requests).toEqual([]);
    });
  }
});
