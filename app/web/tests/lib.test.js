import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import {
  STEP, classOf, inPolygon, findProvince, provinceBounds, provinceCentroid, cellOf, cellCentre, cellRing,
  selectCells, nearestInside, countByClass, tradeoff, expandBounds, esc,
} from "../js/lib.js";

const square = (x0, y0, x1, y1) => [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]];
const feat = (name, coords, type = "Polygon") => ({ properties: { shapeName: name }, geometry: { type, coordinates: coords } });

test("class boundaries follow the FAO table", () => {
  assert.equal(classOf(10000).label, "Rất phù hợp");
  assert.equal(classOf(8000).label, "Rất phù hợp");
  assert.equal(classOf(7999).label, "Phù hợp");
  assert.equal(classOf(6000).label, "Phù hợp");
  assert.equal(classOf(4000).label, "Trung bình");
  assert.equal(classOf(3999).label, "Biên");
  assert.equal(classOf(2000).label, "Biên");
  assert.equal(classOf(1).label, "Rất biên");
  assert.equal(classOf(0).label, "Rất biên");
});

test("point in polygon respects holes", () => {
  const donut = [square(0, 0, 10, 10), square(4, 4, 6, 6)];
  assert.equal(inPolygon(1, 1, donut), true);
  assert.equal(inPolygon(5, 5, donut), false);
  assert.equal(inPolygon(11, 5, donut), false);
});

test("findProvince handles MultiPolygon, trims names and returns null outside", () => {
  const features = [feat("A\t", [[square(0, 0, 1, 1)], [square(5, 5, 6, 6)]], "MultiPolygon"), feat("B", [square(2, 0, 3, 1)])];
  assert.equal(findProvince(0.5, 0.5, features), "A");
  assert.equal(findProvince(5.5, 5.5, features), "A");
  assert.equal(findProvince(2.5, 0.5, features), "B");
  assert.equal(findProvince(1.5, 0.5, features), null);
});

test("bounds, centroid and expansion", () => {
  const features = [feat("A", [square(0, 0, 4, 2)])];
  assert.deepEqual(provinceBounds(features, "A"), [[0, 0], [4, 2]]);
  assert.equal(provinceBounds(features, "Z"), null);
  const c = provinceCentroid(features, "A");
  assert.ok(Math.abs(c.lon - 2) < 1e-9 && Math.abs(c.lat - 1) < 1e-9);
  assert.deepEqual(expandBounds([[102.1, 8.1], [109.9, 23.9]], 1), [[102, 8], [110, 24]]);   // clamped to the data grid
});

test("grid convention matches the pipeline (and the API)", () => {
  assert.deepEqual(cellOf(10.45, 105.35), { i: 162, j: 40 });
  assert.deepEqual(cellCentre(162, 40), { lat: 10.4583, lon: 105.375 });
  for (const [i, j] of [[0, 0], [191, 95], [100, 50]]) {
    const { lat, lon } = cellCentre(i, j);
    assert.deepEqual(cellOf(lat, lon), { i, j });
  }
  const ring = cellRing(10.4583, 105.375);
  assert.equal(ring.length, 5);
  assert.ok(Math.abs(ring[1][0] - ring[0][0] - STEP) < 1e-12 && Math.abs(ring[0][1] - ring[2][1] - STEP) < 1e-12);
  assert.deepEqual(ring[0], ring[4]);
});

// a province covering exactly 3 x 3 cells, in a row of 11 land cells
function rowOfCells() {
  const base = cellCentre(100, 40), cells = [];
  for (let dj = -5; dj <= 5; dj++) for (let di = -2; di <= 2; di++) {
    const c = cellCentre(100 + di, 40 + dj);
    cells.push({ lat: c.lat, lon: c.lon, index: 5000 + dj * 100 });
  }
  const w = base.lon - 1.5 * STEP, e = base.lon + 1.5 * STEP, s = base.lat - 1.5 * STEP, n = base.lat + 1.5 * STEP;
  return { cells, features: [feat("P", [square(w, s, e, n)])] };
}

test("selectCells keeps the province plus a buffer of 2 cells, drops the rest", () => {
  const { cells, features } = rowOfCells();
  // the province covers cells i 99..101 x j 39..41; the input has i 98..102 x j 35..45 (55 cells)
  const cols = (out) => [...new Set(out.map((c) => c.j))].sort((a, b) => a - b);
  const two = selectCells(cells, features, "P", 2);
  assert.equal(two.filter((c) => c.inside).length, 9);
  assert.deepEqual(cols(two), [37, 38, 39, 40, 41, 42, 43]);          // 2 buffer columns each side, 35 and 36, 44 and 45 dropped
  assert.equal(two.length, 5 * 7);                                    // all 5 available rows are within 2 of the province
  const one = selectCells(cells, features, "P", 1);
  assert.deepEqual(cols(one), [38, 39, 40, 41, 42]);
  assert.equal(one.length, 5 * 5);
  assert.equal(selectCells(cells, features, "P", 0).length, 9);       // no buffer: the province only
  assert.deepEqual(selectCells(cells, features, "Nowhere", 2), []);   // unknown province: nothing
});

test("nearestInside ignores buffer cells; countByClass counts inside cells only", () => {
  const { cells, features } = rowOfCells();
  const out = selectCells(cells, features, "P", 2);
  const centre = cellCentre(100, 40);
  const hit = nearestInside(out, centre.lat, centre.lon);
  assert.deepEqual([hit.i, hit.j], [100, 40]);
  const far = nearestInside(out, centre.lat, centre.lon + 5 * STEP);      // asks near a buffer/outside cell: still inside
  assert.equal(far.inside, true);
  const counts = countByClass(out);
  assert.equal(Object.values(counts).reduce((a, b) => a + b, 0), 9);
  assert.equal(nearestInside([], 1, 1), null);
});

test("tradeoff words", () => {
  assert.equal(tradeoff(0).dir, "same");
  assert.equal(tradeoff(-299).dir, "same");
  assert.equal(tradeoff(300).dir, "up");
  assert.equal(tradeoff(-300).text, "Mức phù hợp hơi thấp hơn giữ nguyên");
  assert.equal(tradeoff(-949).text, "Mức phù hợp hơi thấp hơn giữ nguyên");
  assert.equal(tradeoff(-1000).text, "Mức phù hợp thấp hơn giữ nguyên rõ");
});

test("esc neutralises markup", () => {
  assert.equal(esc(`<img src=x onerror="a()">&'`), "&lt;img src=x onerror=&quot;a()&quot;&gt;&amp;&#39;");
  assert.equal(esc(null), "");
});

test("the shipped province file is usable: Vietnam provinces resolve, the sea and Laos do not", () => {
  const file = fileURLToPath(new URL("../data/provinces.geojson", import.meta.url));
  const features = JSON.parse(readFileSync(file, "utf8")).features;
  assert.ok(features.length >= 60);
  assert.equal(findProvince(105.35, 10.45, features), "An Giang");
  assert.equal(findProvince(108.1, 12.7, features), "Đắk Lắk");
  assert.equal(findProvince(102.6, 17.97, features), null);               // Vientiane (DATA-14)
  assert.equal(findProvince(108.0, 9.0, features), null);                 // open sea
  assert.ok(provinceBounds(features, "Sơn La"));
  assert.ok(provinceCentroid(features, "Thái Bình"));
});
