import { Elysia } from "elysia";
import { Type } from "@sinclair/typebox";
import { HttpApplicationError, type HttpApplication } from "./contracts";
import { createHttpSchemas, type HttpSchemas } from "./schemas";
import { InvalidInputError } from "../core/types";

function applicationError(error: unknown): HttpApplicationError {
  if (error instanceof HttpApplicationError) return error;
  const message = error instanceof Error ? error.message : String(error);
  if (error instanceof InvalidInputError) return new HttpApplicationError("invalid", message);
  return new HttpApplicationError("unavailable", message);
}
function callApplication<T>(operation: () => Promise<T>): Promise<T> {
  return Promise.resolve().then(operation).catch(error => { throw applicationError(error); });
}

export function createHttpServer(application: HttpApplication, schemas = createHttpSchemas()): Elysia {
  const notFoundResponse = Type.Object({ detail: Type.String() });
  const server = new Elysia().onError(({ error, set }) => {
    if (error instanceof HttpApplicationError) {
      set.status = { invalid: 400, conflict: 409, unavailable: 503, upstream: 502 }[error.kind];
      return { detail: error.message };
    }
  });
  server.get("/health", () => ({ status: "ok" as const }), { response: schemas.healthResponse });
  server.post("/ingest", ({ body, headers }) => callApplication(() => application.enqueue({
    text: body.text, hints: body.hints ?? [], source: body.source ?? "api", captured_at: body.captured_at,
    ...(headers["idempotency-key"] === undefined ? {} : { idempotency_key: headers["idempotency-key"] }),
  })), { body: schemas.ingestBody, headers: schemas.ingestHeaders, response: { 200: schemas.ingestResponse } });
  server.get("/ingest/pipeline", () => callApplication(() => application.pipelineSnapshot()), { response: schemas.pipelineResponse });
  for (const operation of ["pause", "resume", "discard"] as const) {
    server.post(`/ingest/pipeline/:intake_id/${operation}`, async ({ params, status }) => {
      const count = await callApplication(() => application[operation](params.intake_id));
      if (!count) return status(404, { detail: "Intake not found" });
      return operation === "discard" ? { intake_id: params.intake_id, chunks_discarded: count } : { intake_id: params.intake_id };
    }, { params: schemas.intakeParams, response: { 200: operation === "discard" ? schemas.discardResponse : schemas.intakeResponse, 404: notFoundResponse } });
  }
  server.post("/dream", async ({ set }) => {
    const job = await callApplication(() => application.startDream());
    set.status = 202;
    set.headers.Location = `/dream/jobs/${job.job_id}`;
    return job;
  }, { response: { 202: schemas.dreamResponse } });
  server.get("/dream/jobs/:job_id", async ({ params, status }) => {
    const job = await callApplication(() => application.getDreamJob(params.job_id));
    if (!job) return status(404, { detail: "Dream job not found" });
    return job;
  }, { params: schemas.dreamParams, response: { 200: schemas.dreamResponse, 404: notFoundResponse } });
  server.post("/recall", ({ body }) => callApplication(() => application.recall(body)), { body: schemas.recallBody, response: schemas.recallResponse });
  server.get("/graph/:record_id", async ({ params, status }) => {
    const graph = await callApplication(() => application.getGraph(params.record_id));
    if (!graph) return status(404, { detail: "Node not found" });
    return graph;
  }, { params: schemas.graphParams, response: { 200: schemas.graphResponse, 404: notFoundResponse } });
  return server as unknown as Elysia;
}
