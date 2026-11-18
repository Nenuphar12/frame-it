// The Timeline's periods (`period.ts`): what a link may carry, and the days a month spans — the
// artworks link turns them into a `taken_at` "between" chip. Run by Node: `pnpm test`.
import assert from "node:assert/strict";
import { test } from "node:test";

import { isPeriod, periodDays, periodOf } from "./period.ts";

test("a period is a year or a month, nothing else", () => {
  for (const value of ["2024", "2024-01", "2024-12", "1999-07"]) assert.ok(isPeriod(value), value);
  for (const value of ["", "24", "2024-1", "2024-00", "2024-13", "0000", "2024-03-01", 2024]) {
    assert.ok(!isPeriod(value), String(value));
  }
});

test("periodOf pads like the server's ISO prefixes", () => {
  assert.equal(periodOf(2024), "2024");
  assert.equal(periodOf(2024, 3), "2024-03");
  assert.equal(periodOf(2024, 12), "2024-12");
});

test("periodDays spans the whole year or month, leap years included", () => {
  assert.deepEqual(periodDays("2024"), ["2024-01-01", "2024-12-31"]);
  assert.deepEqual(periodDays("2024-03"), ["2024-03-01", "2024-03-31"]);
  assert.deepEqual(periodDays("2024-04"), ["2024-04-01", "2024-04-30"]);
  assert.deepEqual(periodDays("2024-02"), ["2024-02-01", "2024-02-29"]);
  assert.deepEqual(periodDays("2023-02"), ["2023-02-01", "2023-02-28"]);
  assert.deepEqual(periodDays("1900-02"), ["1900-02-01", "1900-02-28"]);
  assert.deepEqual(periodDays("2000-02"), ["2000-02-01", "2000-02-29"]);
});
