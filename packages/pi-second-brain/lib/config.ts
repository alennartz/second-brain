import { execSync } from "node:child_process";
import { Type, type Static } from "@sinclair/typebox";
import { Value } from "@sinclair/typebox/value";

export const embeddingConfigSchema = Type.Object({
  baseUrl: Type.Optional(Type.String({ minLength: 1 })),
  model: Type.String({ minLength: 1 }),
  dimensions: Type.Integer({ minimum: 1 }),
  apiKey: Type.String({ minLength: 1 }),
});
export const secondBrainConfigSchema = Type.Object({
  dbPath: Type.String({ minLength: 1 }),
  embedding: embeddingConfigSchema,
});
export type EmbeddingConfig = Static<typeof embeddingConfigSchema>;
export type SecondBrainConfig = Static<typeof secondBrainConfigSchema>;

export function parseSecondBrainConfig(value: unknown): SecondBrainConfig {
  if (!Value.Check(secondBrainConfigSchema, value)) throw new Error("Invalid secondBrain configuration: expected dbPath and embedding { model, dimensions, apiKey }");
  return value;
}

export function resolveSecret(value: string, env: Record<string, string | undefined> = process.env): string {
  if (value.startsWith("$")) {
    const name = value.slice(1);
    const resolved = env[name];
    if (!resolved) throw new Error(`Missing environment variable ${name}`);
    return resolved;
  }
  if (value.startsWith("!")) return execSync(value.slice(1), { encoding: "utf8", timeout: 10000 }).trim();
  return value;
}
