import { Surreal, RecordId, StringRecordId } from "surrealdb";
import { createNodeEngines } from "@surrealdb/node";
import { createHash, randomUUID } from "node:crypto";
import type { Embedder } from "../embeddings/embedder.ts";
import type { Storage, StorageTransaction } from "./storage.ts";
import type { NewNode, NodeFields, NewEdge, IntakeChunkDraft, NodeRecord, IntakeChunkRecord } from "../core/types.ts";
import { schema, vectorSchema } from "./schema.ts";
export interface EmbeddedStorageOptions { dbPath: string; embeddingDimensions: number; embedder: Embedder; clock?: () => Date }
type Row = Record<string, any>;
function table(value: string): string { if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(value)) throw new Error("Invalid table"); return value; }
function rid(value: string): StringRecordId { const split = value.indexOf(":"); if (split < 1 || !value.slice(split + 1)) throw new Error("Invalid record ID"); table(value.slice(0, split)); return new StringRecordId(value); }
function plain(value: any): any { if (value == null) return null; if (value instanceof RecordId) return value.toString(); if (value instanceof Date) return value.toISOString(); if (Array.isArray(value)) return value.map(plain); if (typeof value === "object") { if (typeof value.toISOString === "function") return value.toISOString(); return Object.fromEntries(Object.entries(value).map(([k,v]) => [k,plain(v)])); } return value; }
function node(row: Row): NodeRecord { const { embedding, dream_age, created_at, updated_at, ...rest } = row; return { ...rest, table: row.id.split(":")[0], kind: row.id.split(":")[0], dreamAge: dream_age ?? 0, ...(created_at ? { createdAt: created_at } : {}), ...(updated_at ? { updatedAt: updated_at } : {}) } as NodeRecord; }
function edge(row: Row): any { return { id: row.id, from: row.in, to: row.out, edgeType: row.id.split(":")[0], ...(row.context != null ? { context: row.context } : {}) }; }
type EmbeddableNode = { kind?: string; id?: string; content?: string; description?: string; name?: string };
function embeddingText(value: EmbeddableNode): string {
 const kind = value.kind ?? value.id?.split(":")[0];
 return kind === "note" ? value.content ?? "" : value.description || value.name || "";
}
function chunk(row: Row): IntakeChunkRecord {  const { embedding, worker_id, paused, ...rest } = row; return { ...rest, state: paused ? "paused" : row.state, next_attempt_at: row.next_attempt_at ?? null, lease_token: row.lease_token ?? null, lease_expires_at: row.lease_expires_at ?? null, last_error: row.last_error ?? null, idempotency_key: row.idempotency_key ?? null } as IntakeChunkRecord; }
const evidence = (r: Row) => Object.fromEntries(["id","intake_id","chunk_index","total_chunks","content","source","hints","created_at"].filter(k => r[k] != null).map(k => [k,r[k]]));
function cosine(a: number[], b: number[]): number { const dot = a.reduce((sum,v,i) => sum + v * (b[i] ?? 0),0); return dot / (Math.hypot(...a) * Math.hypot(...b) || 1); }
export function createEmbeddedStorage(options: EmbeddedStorageOptions): Storage {
 const db = new Surreal({ engines: createNodeEngines() });
 const clock = options.clock ?? (() => new Date());
 const now = () => clock().toISOString();
 const scope = (driver: any) => {
  const query = async (sql: string, vars: Row = {}): Promise<Row[]> => plain((await driver.query(sql, vars))[0] ?? []);
  const rows = async (name: string): Promise<Row[]> => {
   table(name);
   const info: any = plain((await driver.query("INFO FOR DB"))[0]);
   if (!(name in (info.tables ?? {}))) return [];
   return query(`SELECT * FROM ${name}`);
  };
  const get = async (id: string) => (await query("SELECT * FROM $id", { id: rid(id) }))[0];
  const merge = async (id: string, fields: Row) => (await query("UPDATE $id MERGE $fields RETURN AFTER", { id: rid(id), fields }))[0];
  const remove = async (id: string) => { await query("DELETE $id", { id: rid(id) }); };
  const allEdges = async () => { const info: any = plain((await driver.query("INFO FOR DB"))[0]); const names = Object.keys(info.tables ?? {}).filter(k => !["note","entity","intake_chunk","intake_key"].includes(k)); return (await Promise.all(names.map(rows))).flat().filter(r => r.in && r.out); };
  const create = async (name: string, fields: Row) => (await query(`CREATE ${table(name)} CONTENT $fields RETURN AFTER`, { fields }))[0]!;
  const createNode = async (input: NewNode) => { const { kind, ...fields } = input; const timestamp = new Date(now()); return node(await create(kind, { ...fields, ...(kind === "note" ? { source: input.source ?? "api" } : {}), embedding: [...await options.embedder.embed(embeddingText(input))], dream_age: 0, created_at: timestamp, updated_at: timestamp })); };
  const updateNodeFields = async (id: string, fields: NodeFields) => {
   const old = await get(id); if (!old) return undefined;
   const data: Row = { ...fields };
   if (fields.dreamAge !== undefined) { data.dream_age = fields.dreamAge; delete data.dreamAge; }
   if (fields.content !== undefined || fields.description !== undefined || fields.name !== undefined) data.embedding = [...await options.embedder.embed(embeddingText({ ...old, ...fields }))];
   data.updated_at = new Date(now());
   return node(await merge(id, data));
  };
  const createIntakeChunks = async (intakeId: string, drafts: readonly IntakeChunkDraft[], key?: string) => {
   const fingerprint = createHash("sha256").update(JSON.stringify(drafts.map(d => ({ content: d.content, source: d.source ?? "api", hints: d.hints ?? [] })))).digest("hex");
   if (key) { const prior = (await query("SELECT * FROM $id", { id: new RecordId("intake_key", key) }))[0]; if (prior) { if (prior.fingerprint !== fingerprint) throw new Error("Idempotency content conflict"); return 0; } }
   const vectors = await options.embedder.embedBatch(drafts.map(d => d.content));
   for (const [i,d] of drafts.entries()) await create("intake_chunk", { ...d, source: d.source ?? "api", hints: [...(d.hints ?? [])], intake_id: intakeId, embedding: [...vectors[i]!], state: "ready", attempt_count: 0, paused: false, idempotency_key: key, created_at: new Date(now()), updated_at: new Date(now()) });
   if (key) await query("CREATE $id CONTENT $fields", { id: new RecordId("intake_key", key), fields: { intake_id: intakeId, fingerprint, chunk_count: drafts.length } });
   return drafts.length;
  };
  const owned = async (token: string) => (await rows("intake_chunk")).filter(r => r.lease_token === token && r.state === "leased" && r.lease_expires_at > now());
  const cleanup = async () => { const remaining = await rows("intake_chunk"); for (const key of await rows("intake_key")) if (!remaining.some(r => r.intake_id === key.intake_id)) await remove(key.id); };
  const search = async (names: readonly string[], text: string, vector: readonly number[], limit: number): Promise<Row[]> => {
   if (!Number.isInteger(limit) || limit < 0) throw new Error("Invalid search limit");
   if (limit === 0) return [];
   const candidates = await Promise.all(names.map(async name => {
    const field = name === "entity" ? "name" : "content";
    const lexical = await query(`SELECT *, search::score(1) AS score FROM ${table(name)} WHERE ${field} @1@ $text ORDER BY score DESC LIMIT $limit`, { text, limit: limit * 3 });
    const semantic = await query(`SELECT *, vector::similarity::cosine(embedding, $vector) AS score FROM ${table(name)} WHERE embedding != NONE ORDER BY score DESC LIMIT $limit`, { vector: [...vector], limit: limit * 3 });
    return [lexical, semantic.filter(r => r.score > 0)];
   }));
   const records = new Map<string,Row>(); const scores = new Map<string,number>();
   for (const lists of candidates) for (const list of lists) list.forEach((r,i) => { const { score, ...record } = r; records.set(r.id,record); scores.set(r.id,(scores.get(r.id) ?? 0)+1/(60+i+1)); });
   return [...records.values()].sort((a,b) => scores.get(b.id)!-scores.get(a.id)!).slice(0,limit);
  };
  return {
   createNode, updateNodeFields, createIntakeChunks,
   async getNode(id: string) { const r = await get(id); return r ? node(r) : undefined; }, deleteNode: remove,
   async createEdge(input: NewEdge) { table(input.edgeType); return edge((await query(`RELATE $from->${input.edgeType}->$to CONTENT $fields RETURN AFTER`, { from: rid(input.fromId), to: rid(input.toId), fields: { ...(input.context !== undefined ? {context: input.context} : {}) } }))[0]!); },
   async getEdge(id: string) { const r = await get(id); return r ? edge(r) : undefined; }, deleteEdge: remove,
   async updateEdgeFields(id: string, fields: Row) { const old = await get(id); if (!old) return undefined; const targetType = fields.edgeType ?? fields.edge_type ?? id.split(":")[0]; const from = fields.fromId ?? fields.in ?? old.in; const to = fields.toId ?? fields.out ?? old.out; table(targetType); rid(from); rid(to);
    if (targetType !== id.split(":")[0] || from !== old.in || to !== old.out) {
     const created = (await query(`RELATE $from->${table(targetType)}->$to CONTENT $fields RETURN AFTER`, { from: rid(from), to: rid(to), fields: { ...(fields.context !== undefined ? { context: fields.context } : old.context !== undefined ? { context: old.context } : {}) } }))[0]!;
     await remove(id); return edge(created);
    }
    const data: Row = { ...(fields.context !== undefined ? { context: fields.context } : {}) }; return edge(await merge(id,data)); },
   async getIncomingEdges(id: string) { rid(id); return (await allEdges()).filter(r => r.out === id).map(edge); },
   async getOutgoingEdges(id: string) { rid(id); return (await allEdges()).filter(r => r.in === id).map(edge); },
   async getEdgesByType(type: string) { return (await rows(type)).filter(r => r.in && r.out).map(edge); },
   async findEdges(from: string, type: string, to: string) { rid(from); rid(to); return (await rows(type)).filter(r => r.in === from && r.out === to).map(edge); },
   async searchCandidates(text: string, limit: number) { const vector = await options.embedder.embed(text); return { nodes: (await search(["note", "entity"],text,vector,limit)).map(node), unprocessed: (await search(["intake_chunk"],text,vector,limit)).map(evidence) as any }; },
   async searchIntakeChunks(text: string, limit: number) { return (await search(["intake_chunk"],text,await options.embedder.embed(text),limit)).map(chunk); },
   async findSimilarCandidates(id: string, limit: number) { const source = await get(id); if (!source?.embedding) return []; return [...await rows("note"),...await rows("entity")].filter(r => r.id !== id && r.embedding).sort((a,b) => cosine(b.embedding,source.embedding)-cosine(a.embedding,source.embedding)).slice(0,limit).map(node); },
   async findUnlinkedCooccurrenceCandidates(limit: number) { const edges = await allEdges(); const refs = edges.filter(r => r.id.startsWith("references:") && r.in.startsWith("note:") && r.out.startsWith("entity:")); const pairs = new Map<string,any>(); for (const a of refs) for (const b of refs) if (a.in === b.in && a.out < b.out && !edges.some(e => (e.in === a.out && e.out === b.out) || (e.in === b.out && e.out === a.out))) { const key = `${a.out}|${b.out}`; const pair = pairs.get(key) ?? { fromId: a.out, toId: b.out, sharedNoteIds: [] }; if (!pair.sharedNoteIds.includes(a.in)) pair.sharedNoteIds.push(a.in); pairs.set(key,pair); } return [...pairs.values()].slice(0,limit); },
   async getIntakeChunks(ids: readonly string[]) { return (await Promise.all(ids.map(get))).filter(Boolean).map(r => chunk(r!)); },
   async claimIntakeBatch(worker: string, maxChars: number, leaseSeconds: number) { const records = (await rows("intake_chunk")).sort((a,b) => String(a.created_at).localeCompare(String(b.created_at)) || a.chunk_index-b.chunk_index); if (maxChars < 0) return undefined; const current = now(); const eligible = (r: Row) => !r.paused && (r.state === "ready" || (r.state === "retry_wait" && (!r.next_attempt_at || r.next_attempt_at <= current)) || (r.state === "leased" && r.lease_expires_at <= current)); const intakeBlocked = (intakeId: string) => records.some(row => row.intake_id === intakeId && (row.paused === true || (row.state === "leased" && row.lease_expires_at > current))); const head = records.find(r => !intakeBlocked(r.intake_id) && eligible(r) && !records.some(p => p.intake_id === r.intake_id && p.chunk_index < r.chunk_index && !eligible(p))); if (!head) return undefined; const chosen: Row[] = []; let size = 0; for (const r of records.filter(r => r.intake_id === head.intake_id).sort((a,b) => a.chunk_index-b.chunk_index)) { if (!eligible(r) || (chosen.length && size+r.content.length > maxChars)) break; chosen.push(r); size += r.content.length; } const token = randomUUID(); const updated = []; for (const r of chosen) { const row = await merge(r.id, { state: "leased", worker_id: worker, lease_token: token, lease_expires_at: new Date(clock().getTime()+leaseSeconds*1000), updated_at: new Date(now()) }); if (row) updated.push(chunk(row)); } return updated.length ? { lease_token: token, intake_id: head.intake_id, chunks: updated } : undefined; },
   async renewIntakeBatch(token: string, seconds: number) { const list = await owned(token); for (const r of list) await merge(r.id,{ lease_expires_at: new Date(clock().getTime()+seconds*1000) }); return list.length; },
   async deleteIntakeBatch(token: string) { const list = await owned(token); for (const r of list) await remove(r.id); await cleanup(); return list.length; },
   async releaseIntakeBatch(token: string, error: string, next?: string) { for (const r of await owned(token)) { const paused = r.paused === true; await merge(r.id,{ state: paused ? "paused" : "retry_wait", updated_at: new Date(now()), last_error: error, next_attempt_at: paused ? undefined : (next ? new Date(next) : new Date(now())), attempt_count: (r.attempt_count ?? 0) + 1, lease_token: undefined, lease_expires_at: undefined, worker_id: undefined }); } },
   async setIntakePaused(id: string, paused: boolean) { const list = (await rows("intake_chunk")).filter(r => r.intake_id === id); for (const r of list) { const fields: Row = { paused, updated_at: new Date(now()) }; if (paused && r.state !== "leased") fields.state = "paused"; if (!paused && r.state === "paused") { fields.state = "ready"; fields.next_attempt_at = undefined; } await merge(r.id, fields); } return list.length; },
   async deleteIntake(id: string) { const list = (await rows("intake_chunk")).filter(r => r.intake_id === id); for (const r of list) await remove(r.id); await cleanup(); return list.length; },
   async intakeQueueSnapshot() { const list = (await rows("intake_chunk")).map(chunk); const count = (state: string) => list.filter(r => r.state === state).length; const errors = new Map<string,any>(); const stuck = new Map<string,any>();
    for (const r of list) {
     if (r.last_error && (!errors.has(r.intake_id) || (r.updated_at ?? now()) >= errors.get(r.intake_id).at)) errors.set(r.intake_id,{ intake_id: r.intake_id, error: r.last_error, at: r.updated_at ?? now() });
     if (["retry_wait", "paused"].includes(r.state)) { const previous = stuck.get(r.intake_id); stuck.set(r.intake_id,{ intake_id: r.intake_id, state: r.state, attempt_count: Math.max(previous?.attempt_count ?? 0,r.attempt_count), last_error: r.last_error, since: [previous?.since, r.updated_at ?? now()].filter(Boolean).sort()[0] }); }
    }
    const oldest = (state: string, field: "created_at" | "next_attempt_at") => list.filter(r => r.state === state).map(r => r[field]).filter((v): v is string => !!v).sort()[0] ?? null;
    return { ready: count("ready"), leased: count("leased"), retry_wait: count("retry_wait"), paused: count("paused"), oldest_ready_at: oldest("ready","created_at"), oldest_retry_at: oldest("retry_wait","next_attempt_at"), worker_count: 0, active_leases: new Set(list.filter(r => r.state === "leased" && r.lease_expires_at && r.lease_expires_at > now()).map(r => r.lease_token)).size, stuck_intakes: [...stuck.values()].sort((a,b) => a.since.localeCompare(b.since)), recent_errors: [...errors.values()].sort((a,b) => a.at.localeCompare(b.at)).slice(-20) }; },
   async countNodes() { return (await rows("note")).length+(await rows("entity")).length; },
   async selectDreamBatch(kind: "entity" | "all", limit: number) { return [...await rows("entity"),...(kind === "all" ? await rows("note") : [])].sort((a,b) => (a.dream_age ?? 0)-(b.dream_age ?? 0)).slice(0,limit).map(node); },
   async incrementDreamAge(ids: readonly string[]) { for (const id of ids) { const r = await get(id); if (r) await merge(id,{dream_age: (r.dream_age ?? 0)+1}); } },
  };
 };
 const transact = async <T>(callback: (tx: StorageTransaction) => Promise<T>): Promise<T> => { const tx = await db.beginTransaction(); try { const result = await callback(scope(tx)); await tx.commit(); return result; } catch (error) { await tx.cancel(); throw error; } };
 const base = scope(db);
 const mutations = new Set(["createNode","updateNodeFields","deleteNode","createEdge","updateEdgeFields","deleteEdge","createIntakeChunks","claimIntakeBatch","renewIntakeBatch","deleteIntakeBatch","releaseIntakeBatch","setIntakePaused","deleteIntake","incrementDreamAge"]);
 const api: any = Object.fromEntries(Object.entries(base).map(([name,method]) => [name, mutations.has(name) ? (...args: any[]) => transact(tx => (tx as any)[name](...args)) : method]));
 api.withTransaction = transact;
 api.init = async () => { await db.connect(`surrealkv://${options.dbPath}`); await db.use({ namespace: "brain", database: "brain" }); try { await db.query(schema); } catch (error) { if (!(error instanceof Error) || !error.message.includes("SEARCH")) throw error; await db.query(schema.replaceAll("SEARCH ANALYZER", "FULLTEXT ANALYZER")); } await db.query(vectorSchema(options.embeddingDimensions)); };
 api.close = async () => { await db.close(); };
 return api as Storage;
}
