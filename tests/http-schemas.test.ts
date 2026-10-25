import { describe, expect, test } from "bun:test";
import { Value } from "@sinclair/typebox/value";
import { createHttpSchemas } from "../src/http/schemas";

describe("shared HTTP TypeBox schema boundaries", () => {
  test("intake bodies accept optional hints and source and reject non-string text", () => {
    const schemas = createHttpSchemas();
    expect(Value.Check(schemas.ingestBody, { text: "memory" })).toBe(true);
    expect(Value.Check(schemas.ingestBody, { text: "memory", hints: [], source: "mobile" })).toBe(true);
    expect(Value.Check(schemas.ingestBody, { text: 1 })).toBe(false);
    expect(Value.Check(schemas.ingestBody, {})).toBe(false);
  });
  test("idempotency headers accept optional string keys only", () => {
    const schema = createHttpSchemas().ingestHeaders;
    expect(Value.Check(schema, {})).toBe(true);
    expect(Value.Check(schema, { "idempotency-key": "capture-1" })).toBe(true);
    expect(Value.Check(schema, { "idempotency-key": 1 })).toBe(false);
  });
  test("recall responses keep nullable context and separate unprocessed evidence", () => {
    const schema = createHttpSchemas().recallResponse;
    expect(Value.Check(schema, { answer: "none", context: null })).toBe(true);
    expect(Value.Check(schema, { answer: "found", context: { nodes: [], edges: [], unprocessed: [{ id: "intake_chunk:1", content: "raw" }] } })).toBe(true);
    expect(Value.Check(schema, { answer: 1, context: null })).toBe(false);
  });
  test("dream responses expose only the existing job states", () => {
    const schema = createHttpSchemas().dreamResponse;
    for (const status of ["pending", "running", "complete", "failed"]) {
      expect(Value.Check(schema, { job_id: "job-1", status, error: null })).toBe(true);
    }
    expect(Value.Check(schema, { job_id: "job-1", status: "unknown", error: null })).toBe(false);
  });
  test("path schemas require named string identities", () => {
    const schemas = createHttpSchemas();
    for (const [schema, name] of [[schemas.graphParams, "record_id"], [schemas.intakeParams, "intake_id"], [schemas.dreamParams, "job_id"]] as const) {
      expect(Value.Check(schema, { [name]: "note:1" })).toBe(true);
      expect(Value.Check(schema, { [name]: 1 })).toBe(false);
      expect(Value.Check(schema, {})).toBe(false);
    }
  });
  test("ingest acknowledgements require integer chunk counts", () => {
    const schema = createHttpSchemas().ingestResponse;
    expect(Value.Check(schema, { chunks_stored: 0 })).toBe(true);
    expect(Value.Check(schema, { chunks_stored: 2 })).toBe(true);
    expect(Value.Check(schema, { chunks_stored: 0.5 })).toBe(false);
    expect(Value.Check(schema, { chunks_stored: "2" })).toBe(false);
  });
  test("graph responses retain node and edge dictionaries without embedding requirements", () => {
    const schema = createHttpSchemas().graphResponse;
    expect(Value.Check(schema, { node: { id: "note:1", content: "memory" }, connections: [{ edge: { id: "rel:1", in: "note:1", out: "entity:1", type: "mentions" }, node: { id: "entity:1", name: "Ada" } }] })).toBe(true);
    expect(Value.Check(schema, { connections: [] })).toBe(false);
  });
});
