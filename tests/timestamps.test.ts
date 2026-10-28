import { describe, expect, test } from "bun:test";
import { assertTimestamp, compareTimestamps, isTimestamp, maxTimestamp } from "../src/core/timestamps";

describe("capture timestamp values", () => {
  test("accepts RFC 3339 values with offsets and preserves their text", () => {
    const value = "2026-01-01T12:34:56.123+02:00";
    expect(assertTimestamp(value)).toBe(value);
    expect(isTimestamp(value)).toBe(true);
  });

  test("compares equivalent offsets by absolute instant", () => {
    expect(compareTimestamps("2026-01-01T12:00:00+02:00", "2026-01-01T10:00:00Z")).toBe(0);
    expect(compareTimestamps("2026-01-01T10:00:01Z", "2026-01-01T10:00:00+02:00")).toBe(1);
  });

  test("selects the latest timestamp without normalizing its representation", () => {
    expect(maxTimestamp(["2026-01-01T10:00:00+02:00", "2026-01-01T10:00:00Z"])).toBe("2026-01-01T10:00:00Z");
  });

  test("rejects malformed and impossible calendar values", () => {
    expect(isTimestamp("not-a-time")).toBe(false);
    expect(isTimestamp("2026-02-30T10:00:00Z")).toBe(false);
    expect(() => assertTimestamp("2026-01-01T10:00:00")).toThrow();
  });
});
