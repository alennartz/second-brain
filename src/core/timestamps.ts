import { InvalidInputError, type Timestamp } from "./types.ts";

const rfc3339 = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$/;

type ParsedTimestamp = {
  epochSeconds: bigint;
  fraction: string;
};

function parseTimestamp(value: string): ParsedTimestamp {
  const match = rfc3339.exec(value);
  if (!match) throw new InvalidInputError("Timestamp must be a valid RFC 3339 value with an offset");
  const [, date, hour, minute, second, fraction = "", zone] = match;
  const base = Date.parse(`${date}T${hour}:${minute}:${second}Z`);
  if (!Number.isFinite(base) || new Date(base).toISOString().slice(0, 19) !== `${date}T${hour}:${minute}:${second}`) {
    throw new InvalidInputError("Timestamp must contain a valid calendar date and time");
  }
  const offset = zone === "Z" ? 0 : Number(zone.slice(1, 3)) * 60 + Number(zone.slice(4, 6));
  if (zone !== "Z" && (Number(zone.slice(1, 3)) > 23 || Number(zone.slice(4, 6)) > 59)) {
    throw new InvalidInputError("Timestamp contains an invalid UTC offset");
  }
  const signedOffset = zone === "Z" || zone[0] === "+" ? offset : -offset;
  return { epochSeconds: BigInt(Math.trunc(base / 1000)) - BigInt(signedOffset * 60), fraction };
}

export function assertTimestamp(value: string): Timestamp {
  parseTimestamp(value);
  return value;
}

export function isTimestamp(value: unknown): value is Timestamp {
  if (typeof value !== "string") return false;
  try {
    parseTimestamp(value);
    return true;
  } catch {
    return false;
  }
}

export function compareTimestamps(left: Timestamp, right: Timestamp): number {
  const a = parseTimestamp(left);
  const b = parseTimestamp(right);
  if (a.epochSeconds !== b.epochSeconds) return a.epochSeconds > b.epochSeconds ? 1 : -1;
  const precision = Math.max(a.fraction.length, b.fraction.length);
  const leftFraction = BigInt((a.fraction || "0").padEnd(precision, "0"));
  const rightFraction = BigInt((b.fraction || "0").padEnd(precision, "0"));
  if (leftFraction !== rightFraction) return leftFraction > rightFraction ? 1 : -1;
  return 0;
}

export function maxTimestamp(values: readonly (Timestamp | null | undefined)[]): Timestamp | undefined {
  return values.filter((value): value is Timestamp => value !== null && value !== undefined).reduce<Timestamp | undefined>((current, value) => {
    if (current === undefined) return value;
    const comparison = compareTimestamps(value, current);
    return comparison > 0 || (comparison === 0 && value > current) ? value : current;
  }, undefined);
}

export const timestampPattern = rfc3339.source;
