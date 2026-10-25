import { Elysia } from "elysia";
import { HttpApplicationError, type HttpApplication } from "./contracts";
import { createHttpSchemas, type HttpSchemas } from "./schemas";

export function createHttpServer(application: HttpApplication, schemas = createHttpSchemas()): Elysia {
  const server = new Elysia().onError(({ error, set }) => {
    if (error instanceof HttpApplicationError) {
      set.status = { invalid: 400, conflict: 409, unavailable: 503, upstream: 502 }[error.kind];
      return { detail: error.message };
    }
  });
  server.get("/health", () => ({ status: "ok" as const }), { response: schemas.healthResponse });
  server.post("/ingest", ({ body, headers }) => application.enqueue({
    text: body.text, hints: body.hints ?? [], source: body.source ?? "api",
    ...(headers["idempotency-key"] === undefined ? {} : { idempotency_key: headers["idempotency-key"] }),
  }), { body: schemas.ingestBody, headers: schemas.ingestHeaders, response: { 200: schemas.ingestResponse } });
  server.get("/ingest/pipeline", () => application.pipelineSnapshot(), { response: schemas.pipelineResponse });
  for (const operation of ["pause", "resume", "discard"] as const) {
    server.post(`/ingest/pipeline/:intake_id/${operation}`, async ({ params, set }) => {
      const count = await application[operation](params.intake_id);
      if (!count) return Response.json({ detail: "Intake not found" }, { status: 404 });
      return operation === "discard" ? { intake_id: params.intake_id, chunks_discarded: count } : { intake_id: params.intake_id };
    }, { params: schemas.intakeParams });
  }
  server.post("/dream", async ({ set }) => {
    const job = await application.startDream();
    set.status = 202;
    set.headers.Location = `/dream/jobs/${job.job_id}`;
    return job;
  }, { response: { 202: schemas.dreamResponse } });
  server.get("/dream/jobs/:job_id", async ({ params, set }) => {
    const job = await application.getDreamJob(params.job_id);
    if (!job) return Response.json({ detail: "Dream job not found" }, { status: 404 });
    return job;
  }, { params: schemas.dreamParams });
  server.post("/recall", ({ body }) => application.recall(body), { body: schemas.recallBody, response: schemas.recallResponse });
  server.get("/graph/:record_id", async ({ params, set }) => {
    const graph = await application.getGraph(params.record_id);
    if (!graph) return Response.json({ detail: "Node not found" }, { status: 404 });
    return graph;
  }, { params: schemas.graphParams });
  return server as unknown as Elysia;
}
