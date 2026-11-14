import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { DICT, LANGS, detectLang, getLang, setLangState, t } from "../js/i18n.js";
import { tradeoff } from "../js/lib.js";

const read = (p) => readFileSync(fileURLToPath(new URL(p, import.meta.url)), "utf8");
const VIETNAMESE = /[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]/i;
const placeholders = (s) => new Set([...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]));
const sample = (keys) => Object.fromEntries([...keys].map((k) => [k, 2]));

test("both languages have exactly the same keys", () => {
  const vi = Object.keys(DICT.vi).sort(), en = Object.keys(DICT.en).sort();
  assert.deepEqual(en.filter((k) => !vi.includes(k)), [], "keys only in English");
  assert.deepEqual(vi.filter((k) => !en.includes(k)), [], "keys only in Vietnamese");
  assert.deepEqual([...LANGS], ["vi", "en"]);
});

test("placeholders match between languages and plural functions give clean text", () => {
  for (const [key, vi] of Object.entries(DICT.vi)) {
    const en = DICT.en[key], want = placeholders(vi);
    if (typeof en === "function") {
      for (const n of [1, 2]) {
        const out = en({ ...sample(want), n, crop: "x", prov: "y" });
        assert.ok(!/undefined|NaN|\{/.test(out), `${key}: "${out}"`);
      }
    } else {
      assert.deepEqual(placeholders(en), want, `${key}: placeholders differ`);
    }
  }
});

test("English text has no Vietnamese letters (names of provinces are data, not text)", () => {
  for (const [key, v] of Object.entries(DICT.en)) {
    const text = typeof v === "function" ? v({ n: 1, crop: "x", prov: "y" }) : v;
    assert.ok(!VIETNAMESE.test(text), `${key}: ${text}`);
  }
});

test("every key used by the code and the HTML exists", () => {
  const app = read("../js/app.js"), html = read("../index.html");
  const used = new Set();
  for (const m of app.matchAll(/\bt\(\s*"([a-zA-Z0-9_.]+)"/g)) used.add(m[1]);
  for (const m of app.matchAll(/"((?:pt)\.cycle(?:Fits|NoFit))"/g)) used.add(m[1]);                 // chosen with a ternary
  for (const m of html.matchAll(/data-i18n="([^"]+)"/g)) used.add(m[1]);
  for (const m of html.matchAll(/data-i18n-attr="([^"]+)"/g)) for (const pair of m[1].split(";")) used.add(pair.split(":")[1]);
  for (const k of ["c80", "c60", "c40", "c20", "c0"]) used.add(`class.${k}`);                          // t(`class.${key}`)
  for (const k of ["water", "erosion", "income", "soil"]) used.add(`prio.name.${k}`);                  // t(`prio.name.${k}`)
  for (const a of ["show", "hide"]) for (const side of ["Left", "Right"]) used.add(`tgl.${a}${side}`);   // t(`tgl.${...}${cap}`)
  for (const side of ["Left", "Right"]) used.add(`tgl.tip${side}`);
  for (const k of [tradeoff(0).key, tradeoff(500).key, tradeoff(-500).key, tradeoff(-2000).key]) used.add(k);
  assert.ok(used.size > 100, `only ${used.size} keys found: the scan is broken`);
  const missing = [...used].filter((k) => !(k in DICT.vi) || !(k in DICT.en));
  assert.deepEqual(missing, []);
});

test("t() fills placeholders, falls back to Vietnamese, then to the key", () => {
  setLangState("en");
  assert.equal(getLang(), "en");
  assert.equal(t("onb.geoDone", { name: "Hue" }), " Location found: Hue.");
  assert.equal(t("chip.seasonsN", { n: 1 }), "1 season");
  assert.equal(t("chip.seasonsN", { n: 3 }), "3 seasons");
  assert.equal(t("res.title", { n: 1, crop: "maize", prov: "Dong Nai" }), "1 option for maize in Dong Nai");
  assert.equal(t("res.title", { n: 4, crop: "maize", prov: "Dong Nai" }), "4 options for maize in Dong Nai");
  assert.equal(t("badge.benefits", { n: 2 }), "✓ 2 benefits");
  assert.equal(t("no.such.key"), "no.such.key");
  assert.equal(t("onb.geoDone"), " Location found: {name}.");                  // a missing parameter stays visible
  setLangState("vi");
  assert.equal(t("chip.seasonsN", { n: 2 }), "2 vụ");
  assert.equal(t("hdr.detail"), "Xem chi tiết");
  setLangState("fr");                                                          // unknown languages are ignored
  assert.equal(getLang(), "vi");
});

test("language detection: a saved choice wins, otherwise the browser decides", () => {
  assert.equal(detectLang("en", "vi-VN"), "en");
  assert.equal(detectLang("vi", "en-US"), "vi");
  assert.equal(detectLang(null, "vi-VN"), "vi");
  assert.equal(detectLang(null, "vi"), "vi");
  assert.equal(detectLang(null, "en-GB"), "en");
  assert.equal(detectLang(null, "fr-FR"), "en");
  assert.equal(detectLang("xx", "vi-VN"), "vi");                               // an unknown saved value is ignored
  assert.equal(detectLang(null, undefined), "vi");
});

test("trade-off sentences have a key in the dictionary", () => {
  assert.equal(tradeoff(0).key, "trade.same");
  assert.equal(tradeoff(500).key, "trade.up");
  assert.equal(tradeoff(-500).key, "trade.slightDown");
  assert.equal(tradeoff(-2000).key, "trade.clearDown");
});
