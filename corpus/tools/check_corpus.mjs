#!/usr/bin/env node
// Run the ROAX conformance corpus against implementation B, and regenerate it.
//
// This file is two things at once, deliberately.
//
// As a RUNNER it is the worked example of "how do I check my implementation against the
// corpus": every vector class is consumed here, and porting this file to a new language is the
// whole job. It reports per class, and it distinguishes NOT RUN from PASSED - a runner that
// reports green with class 10 unrun is the defect docs/conformance-corpus.md exists to prevent.
//
// As a CROSS-CHECK, `--emit FILE` rewrites the corpus with every derived value this run
// recomputed and leaves every input untouched. A NOT RUN vector is copied through and explicitly
// excluded from the cross-implementation assertion.
//
// Usage:
//   node check_corpus.mjs [--corpus FILE] [--records DIR] [--salt-sets DIR]
//                         [--emit FILE] [--quiet]
//
// `--records` points at a directory holding the MOH samples already extracted to JSON text by
// `extract_reference_record.py`. Without it, class 10 reports NOT RUN and this process exits 2.
// Exit 0 is a complete pass, exit 1 is an assertion failure, and exit 2 is incomplete.

import { randomBytes } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import * as env from "./envelope.mjs";
import { parse as parseRecord } from "./json_literal.mjs";
import * as ref from "./roax_ref.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CORPUS_DIR = path.dirname(HERE);
const REPO_ROOT = path.dirname(CORPUS_DIR);

const DEFAULT_CORPUS_FILE = path.join(CORPUS_DIR, "conformance-corpus-1.0.json");
const VALUE_OPTIONS = new Map([
  ["--corpus", "corpus"],
  ["--records", "records"],
  ["--salt-sets", "saltSets"],
  ["--emit", "emit"],
]);

function usageError(message) {
  console.error(`NOT RUN: ${message}`);
  console.error("usage: node corpus/tools/check_corpus.mjs [--corpus FILE] [--records DIR]");
  console.error("       [--salt-sets DIR] [--emit FILE] [--quiet]");
  process.exit(2);
}

const parsedOptions = {
  corpus: DEFAULT_CORPUS_FILE,
  records: process.env.ROAX_EXTRACTED_RECORDS,
  saltSets: path.join(CORPUS_DIR, "fixtures", "salts"),
  emit: null,
  quiet: false,
};
const cliArgs = process.argv.slice(2);
for (let index = 0; index < cliArgs.length; index++) {
  const argument = cliArgs[index];
  if (argument === "--quiet") {
    parsedOptions.quiet = true;
    continue;
  }
  const property = VALUE_OPTIONS.get(argument);
  if (property === undefined) usageError(`unknown argument ${JSON.stringify(argument)}`);
  if (index + 1 >= cliArgs.length || cliArgs[index + 1] === ""
      || cliArgs[index + 1].startsWith("--")) {
    usageError(`${argument} requires a value`);
  }
  parsedOptions[property] = cliArgs[++index];
}

const CORPUS_FILE = parsedOptions.corpus;
const RECORDS_DIR = parsedOptions.records;
const SALT_SET_DIR = parsedOptions.saltSets;
const EMIT = parsedOptions.emit;
const QUIET = parsedOptions.quiet;

const corpus = JSON.parse(fs.readFileSync(CORPUS_FILE, "utf8"));
const committedCorpus = CORPUS_FILE === DEFAULT_CORPUS_FILE
  ? corpus
  : JSON.parse(fs.readFileSync(DEFAULT_CORPUS_FILE, "utf8"));
const HASH_ALG = corpus.hashAlg;
const V = corpus.vectors;

const typeMaps = env.loadTypeMaps(path.join(CORPUS_DIR, "type-maps"));

const results = [];
const notRun = [];

function check(vector, what, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  results.push({ cls: vector.class, name: vector.name, what, ok, got, want });
  return ok;
}

function note(cls, message) {
  notRun.push({ cls, message });
}

function carrierError(label, message) {
  throw new Error(`salt-set carrier ${label}: ${message}`);
}

function objectMembers(value, label) {
  if (!(value instanceof ref.RecordMap)) carrierError(label, "expected an object");
  const members = new Map();
  for (const [key, member] of value.entries) {
    if (members.has(key)) carrierError(label, `duplicate member ${JSON.stringify(key)}`);
    members.set(key, member);
  }
  return members;
}

function requireExactMembers(members, expected, label) {
  const allowed = new Set(expected);
  const unknown = [...members.keys()].filter((key) => !allowed.has(key));
  const missing = expected.filter((key) => !members.has(key));
  if (unknown.length) {
    carrierError(label, `unknown member(s) ${unknown.map(JSON.stringify).join(", ")}`);
  }
  if (missing.length) {
    carrierError(label, `missing member(s) ${missing.map(JSON.stringify).join(", ")}`);
  }
}

function unsignedInteger(value, label) {
  if (!(value instanceof ref.NumberLiteral) || !/^(0|[1-9][0-9]*)$/.test(value.text)) {
    carrierError(label, "expected a canonical non-negative JSON integer");
  }
  return BigInt(value.text);
}

function saltHex(value, label) {
  if (typeof value !== "string" || !/^[0-9a-f]{32}$/.test(value)) {
    carrierError(label, "salt must be exactly 16 bytes as lowercase 32-hex");
  }
}

function structuredPath(value, label) {
  if (!Array.isArray(value)) carrierError(label, "segments must be an array");
  const segments = value.map((raw, index) => {
    const segmentLabel = `${label}.segments[${index}]`;
    const members = objectMembers(raw, segmentLabel);
    if (members.has("key")) {
      requireExactMembers(members, ["key"], segmentLabel);
      const key = members.get("key");
      if (typeof key !== "string") carrierError(segmentLabel, "key must be a string");
      return { key };
    }
    requireExactMembers(members, ["index"], segmentLabel);
    const parsed = unsignedInteger(members.get("index"), `${segmentLabel}.index`);
    if (parsed > 0xffffffffn) {
      carrierError(`${segmentLabel}.index`, "index must be at most 4294967295");
    }
    return { index: Number(parsed) };
  });

  // This also rejects unpaired surrogates and gives duplicate detection the same NFC path
  // identity that section 5 hashes.
  try {
    return { segments, encoded: ref.encodePath(segments).toString("hex") };
  } catch (err) {
    carrierError(label, err instanceof Error ? err.message : String(err));
  }
}

function validatePathSaltSet(root, label) {
  requireExactMembers(root, ["pairing", "salts"], label);
  const salts = root.get("salts");
  if (!Array.isArray(salts)) carrierError(`${label}.salts`, "must be an array");
  // Path pairing is the envelope-1.0 salts carrier, whose tree floor is five.
  if (salts.length < 5) carrierError(`${label}.salts`, "must contain at least 5 entries");

  const seen = new Set();
  salts.forEach((raw, index) => {
    const entryLabel = `${label}.salts[${index}]`;
    const entry = objectMembers(raw, entryLabel);
    requireExactMembers(entry, ["segments", "salt"], entryLabel);
    saltHex(entry.get("salt"), `${entryLabel}.salt`);
    const path = structuredPath(entry.get("segments"), entryLabel);
    if (seen.has(path.encoded)) carrierError(entryLabel, "duplicates an earlier encoded path");
    seen.add(path.encoded);
  });
}

function validatePositionalSaltSet(root, label) {
  requireExactMembers(root, ["pairing", "leafCount", "salts"], label);
  const salts = root.get("salts");
  if (!Array.isArray(salts)) carrierError(`${label}.salts`, "must be an array");
  const leafCount = unsignedInteger(root.get("leafCount"), `${label}.leafCount`);
  if (leafCount < 5n) carrierError(`${label}.leafCount`, "must be at least 5");
  if (leafCount !== BigInt(salts.length)) {
    carrierError(label, `leafCount ${leafCount} does not equal ${salts.length} salts`);
  }
  salts.forEach((salt, index) => saltHex(salt, `${label}.salts[${index}]`));
}

function expectedSaltSetNames(plan) {
  const expected = new Set();
  for (const vectors of Object.values(plan.vectors)) {
    for (const vector of vectors) {
      if (vector.saltsFile !== undefined) expected.add(path.basename(vector.saltsFile));
    }
  }

  const envelopeVectors = plan.vectors.envelope ?? [];
  const floorSources = envelopeVectors.filter((vector) =>
    (vector.class === 14 && vector.name.startsWith("floor-")
      && vector.name.endsWith("-complete"))
    || vector.name === "algorithm-sha-256-accepted");
  for (const vector of floorSources) {
    const envelope = JSON.parse(
      fs.readFileSync(path.join(REPO_ROOT, vector.envelopeFile), "utf8")
    );
    const keyMode = envelope.issuer.keyId === undefined ? "no-key-id" : "with-key-id";
    expected.add(
      `envelope-floor-${envelope.recordType}-${keyMode}-${envelope.leafCount}.json`
    );
  }

  for (const vector of envelopeVectors) {
    if (vector.name.startsWith("guard-accept-")) {
      expected.add(`envelope-guard-${vector.name}.json`);
    }
  }
  if (envelopeVectors.some((vector) => vector.name === "full-copy-complete-salts")) {
    expected.add("envelope-full-copy-typed-scalars.json");
  }
  return expected;
}

function validateSaltSetDirectory(dir, expectedNames) {
  const names = fs.readdirSync(dir).filter((name) => name.endsWith(".json")).sort();
  if (names.length === 0) carrierError(dir, "contains no JSON salt-set carriers");
  for (const name of names) {
    const label = path.join(dir, name);
    const parsed = parseRecord(fs.readFileSync(label, "utf8"));
    const root = objectMembers(parsed, label);
    const pairing = root.get("pairing");
    if (pairing === "path") validatePathSaltSet(root, label);
    else if (pairing === "positional") validatePositionalSaltSet(root, label);
    else {
      carrierError(label,
        `pairing must be "path" or "positional", got ${JSON.stringify(pairing)}`);
    }
  }
  const present = new Set(names);
  const missing = [...expectedNames].filter((name) => !present.has(name)).sort();
  const orphaned = names.filter((name) => !expectedNames.has(name));
  if (missing.length) {
    carrierError(dir, `missing committed carrier(s) ${missing.map(JSON.stringify).join(", ")}`);
  }
  if (orphaned.length) {
    carrierError(dir, `orphan carrier(s) no committed vector or fixture uses: `
      + orphaned.map(JSON.stringify).join(", "));
  }
  return names.length;
}

const validatedSaltSetCount = validateSaltSetDirectory(
  SALT_SET_DIR, expectedSaltSetNames(committedCorpus)
);

// The input escape forms documented in corpus/README.md. A lone surrogate never appears
// literally in the corpus file, because a JSON writer cannot emit one as well-formed UTF-8.
function resolveInput(value) {
  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    if ("$utf16" in value) return value.$utf16.map((u) => String.fromCharCode(parseInt(u, 16))).join("");
    if ("$segments" in value) return value.$segments.map(resolveSegment);
    if ("$jsonText" in value) return value.$jsonText;
  }
  return value;
}

function resolveSegment(seg) {
  return "key" in seg ? { key: resolveInput(seg.key) } : { index: seg.index };
}

// A type map used ONLY to drive the flattener's structural rejections in class 3's
// parser-boundary vectors. It is not a default-tag fallback, which section 4.2 forbids: every
// vector using it errors before any tag it returns is consumed.
const structuralOnlyTypeMap = { resolve: () => ref.TAG.STRING };

// ---------------------------------------------------------------------------------------------

for (const v of V.encodePath ?? []) {
  check(v, "encodedHex", ref.encodePath(v.segments).toString("hex"), v.encodedHex);
  if ("displayPath" in v) check(v, "displayPath", ref.displayPath(v.segments), v.displayPath);
}

for (const v of V.encodeValue ?? []) {
  const input = "input" in v ? resolveInput(v.input) : null;
  check(v, "encodedHex", ref.encodeValue(v.tag, input).toString("hex"), v.encodedHex);
}

for (const v of V.reject ?? []) {
  let got = null;
  try {
    runReject(v);
    got = "<accepted>";
  } catch (err) {
    got = err instanceof ref.RoaxError ? err.code : `<${err.constructor.name}>`;
  }
  check(v, "reason", got, v.reason);
}

function runReject(v) {
  const raw = v.input;
  const resolved = resolveInput(raw);
  if (raw !== null && typeof raw === "object" && "$segments" in raw) {
    ref.checkReservedNamespace(resolved);
    ref.encodePath(resolved);
    return;
  }
  if (raw !== null && typeof raw === "object" && "$jsonText" in raw) {
    ref.flatten(parseRecord(resolved), structuralOnlyTypeMap);
    return;
  }
  ref.encodeValue(v.tag, resolved);
}

for (const v of V.leaf ?? []) {
  const value = "value" in v ? v.value : null;
  const h = ref.leafHash(HASH_ALG, v.segments, v.tag, value, Buffer.from(v.saltHex, "hex"));
  check(v, "leafHash", h.toString("hex"), v.leafHash);
}

const treesByName = new Map();
for (const v of V.tree ?? []) {
  const leaves = v.leafHashes.map((h) => Buffer.from(h, "hex"));
  treesByName.set(v.name, leaves);
  check(v, "root", ref.mth(HASH_ALG, leaves).toString("hex"), v.root);
}

// Inclusion and negative-proof vectors are derived from the tree vector of the same size, which
// is what lets this file REGENERATE them rather than merely re-verify what it was handed.
function treeOfSize(n) {
  const leaves = treesByName.get(`tree-n${n}`);
  if (leaves === undefined) throw new Error(`no tree vector of size ${n}`);
  return leaves;
}

for (const v of V.inclusion ?? []) {
  const leaves = treeOfSize(v.treeSize);
  const audit = ref.inclusionPath(HASH_ALG, v.index, leaves).map((h) => h.toString("hex"));
  const root = ref.mth(HASH_ALG, leaves);
  check(v, "leafHash", leaves[v.index].toString("hex"), v.leafHash);
  check(v, "auditPath", audit, v.auditPath);
  check(v, "root", root.toString("hex"), v.root);
  const verified = ref.verifyInclusion(HASH_ALG, Buffer.from(v.leafHash, "hex"), v.index,
    v.treeSize, v.auditPath.map((h) => Buffer.from(h, "hex")), Buffer.from(v.root, "hex"));
  check(v, "expect", verified, v.expect);
}

function flipLastByte(buf) {
  const out = Buffer.from(buf);
  out[out.length - 1] ^= 0x01;
  return out;
}

for (const v of V.negativeProof ?? []) {
  const leaves = treeOfSize(v.treeSize);
  const root = ref.mth(HASH_ALG, leaves);
  let leafHash;
  let auditPath;
  let claimedRoot = root;

  if (v.attack === "index-out-of-range") {
    leafHash = leaves[0];
    auditPath = ref.inclusionPath(HASH_ALG, 0, leaves);
  } else if (v.attack === "internal-node-as-leaf") {
    // dogtag's C1 hazard. An internal node offered as a leaf, with the audit path that would
    // carry it to the root if the tree were two leaves deep. RFC 9162 rejects it because
    // verification consumes the TRUE tree size and runs out of path before `sn` reaches 0.
    const k = ref.splitPoint(leaves.length);
    leafHash = ref.mth(HASH_ALG, leaves.slice(0, k));
    auditPath = [ref.mth(HASH_ALG, leaves.slice(k))];
  } else {
    const base = ref.inclusionPath(HASH_ALG, v.index, leaves);
    leafHash = leaves[v.index];
    if (v.attack === "wrong-root") {
      auditPath = base;
      claimedRoot = flipLastByte(root);
    } else if (v.attack === "flipped-sibling") {
      auditPath = [flipLastByte(base[0]), ...base.slice(1)];
    } else if (v.attack === "truncated-audit-path") {
      auditPath = base.slice(0, -1);
    } else if (v.attack === "extended-audit-path") {
      auditPath = [...base, root];
    } else {
      throw new Error(`unknown attack ${v.attack}`);
    }
  }

  check(v, "leafHash", leafHash.toString("hex"), v.leafHash);
  check(v, "auditPath", auditPath.map((h) => h.toString("hex")), v.auditPath);
  check(v, "root", claimedRoot.toString("hex"), v.root);
  const verified = ref.verifyInclusion(HASH_ALG, Buffer.from(v.leafHash, "hex"), v.index,
    v.treeSize, v.auditPath.map((h) => Buffer.from(h, "hex")), Buffer.from(v.root, "hex"));
  check(v, "mustNotVerify", verified, false);
}

for (const v of V.typeMap ?? []) {
  const map = typeMaps[v.recordType];
  if (map === undefined) {
    throw new Error(`corpus defect: committed type map ${v.recordType} not found`);
  }
  let tag = null;
  let failedClosed = false;
  try {
    tag = map.resolve(v.segments, v.jsonKind);
  } catch (err) {
    if (!(err instanceof ref.RoaxError)) throw err;
    failedClosed = true;
  }
  if ("expectTag" in v) check(v, "expectTag", tag, v.expectTag);
  else check(v, "expectFailClosed", failedClosed, v.expectFailClosed);
}

for (const v of V.record ?? []) {
  const loaded = loadRecord(v);
  if (loaded === null) continue;
  const map = typeMaps[v.recordType];
  if (map === undefined) {
    throw new Error(`corpus defect: record ${v.name} names missing type map ${v.recordType}`);
  }
  const identity = {
    recordType: v.recordType,
    schemaVersion: v.schemaVersion,
    recordId: v.recordId,
    issuerId: v.issuerId,
    issuerKeyId: v.issuerKeyId,
  };
  // Under decision D4b a salt is an independent random draw that nothing can re-derive
  // (spec section 7), so the salts come from the committed set the vector names. The pairing
  // is declared rather than sniffed: guessing wrong would pair a real salt with the wrong leaf
  // and yield a plausible wrong root instead of an error.
  const ordered = ref.orderedLeaves(loaded, map, identity);
  const saltDoc = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, v.saltsFile), "utf8"));
  if (saltDoc.pairing !== v.saltPairing) {
    throw new Error(`corpus defect: record ${v.name} declares saltPairing ${v.saltPairing}, `
      + `but ${v.saltsFile} declares ${saltDoc.pairing}`);
  }
  const salts = ref.saltSetFromDocument(saltDoc, ordered);
  const { root, leaves } = ref.buildTree(HASH_ALG, loaded, map, salts, identity);
  check(v, "leafCount", leaves.length, v.leafCount);
  check(v, "root", root.toString("hex"), v.root);
}

function loadRecord(v) {
  // The corpus schema admits two carriers, and this runner consumes one of them. A full envelope
  // copy carries the record body and its salts together and is a self-sufficient carrier.
  // Failing to implement that schema-valid carrier is an implementation failure, not an
  // unavailable external input.
  if (v.recordFile === undefined) {
    throw new Error(`runner failure: record ${v.name} uses unsupported envelopeFile carrier `
      + `${v.envelopeFile}`);
  }
  // A corpus fixture lives in this repository. A MOH sample does not, by design, so it is named
  // by module and export and must be extracted first.
  if (v.recordFile.startsWith("corpus/")) {
    return parseRecord(fs.readFileSync(path.join(REPO_ROOT, v.recordFile), "utf8"));
  }
  if (!RECORDS_DIR) {
    note(v.class, `record ${v.name}: external sample ${v.recordFile} was not extracted; rerun `
      + `corpus/tools/run.sh with --references <path-to-schemata>, or pass --records `
      + `<extracted-records> to this tool`);
    return null;
  }
  const exportName = v.recordFile.split("#")[1];
  const file = path.join(RECORDS_DIR, `${exportName}.json`);
  if (!fs.existsSync(file)) {
    note(v.class, `record ${v.name}: ${file} was not extracted; rerun corpus/tools/run.sh `
      + `with --references <path-to-schemata>`);
    return null;
  }
  return parseRecord(fs.readFileSync(file, "utf8"));
}

// Class 12 ASSERTS RATHER THAN COMPARES. Under decision D4b salts are independent random draws,
// so there is no pinned value for a runner to reproduce: it performs the issuances the vector
// describes, with its OWN generator, and checks the relations. That is also why these vectors
// contribute no bytes to --emit - there is nothing derived to write back.
//
// The within-issuance assertion is the one that catches an implementation drawing ONE salt per
// record and reusing it across that record's leaves; a single-path vector cannot see that,
// because such an implementation still varies the path's salt between trials.
//
// There is deliberately no within-issuance LEAF HASH check: two different paths carry different
// encoded paths into the section 8 preimage, so their hashes differ whatever the salts do.
for (const v of V.unlinkability ?? []) {
  // Two entries that are different JSON text and the SAME path once NFC is applied pass the
  // schema's uniqueItems (spec section 6.1), and the within-issuance assertion below would then
  // compare a path a record can hold only once. encodePath normalizes, so comparing encoded forms
  // is the duplicate-path rejection orderedLeaves makes over a record's union; this class issues
  // no record and never reaches that one. A corpus carrying such a pair is defective rather than
  // failing, so this throws instead of recording an assertion.
  const encodedPaths = new Set(v.paths.map((p) => ref.encodePath(p).toString("hex")));
  if (encodedPaths.size !== v.paths.length) {
    throw new Error(`corpus defect: unlinkability vector ${v.name} names two paths that are `
      + `equal once NFC is applied`);
  }

  const saltsSeen = new Map();
  const hashesSeen = new Map();
  let withinOk = true;
  let acrossSaltsOk = true;
  let acrossHashesOk = true;

  for (let trial = 0; trial < v.trials; trial++) {
    const drawn = v.paths.map(() => randomBytes(ref.SALT_BYTES));
    if (new Set(drawn.map((b) => b.toString("hex"))).size !== drawn.length) withinOk = false;

    v.paths.forEach((segments, i) => {
      const pathKey = ref.encodePath(segments).toString("hex");
      const saltHex = drawn[i].toString("hex");
      const hashHex = ref.leafHash(HASH_ALG, segments, v.tag, v.value ?? null, drawn[i]).toString("hex");

      const salts = saltsSeen.get(pathKey) ?? new Set();
      if (salts.has(saltHex)) acrossSaltsOk = false;
      salts.add(saltHex);
      saltsSeen.set(pathKey, salts);

      const hashes = hashesSeen.get(pathKey) ?? new Set();
      if (hashes.has(hashHex)) acrossHashesOk = false;
      hashes.add(hashHex);
      hashesSeen.set(pathKey, hashes);
    });
  }

  check(v, "expectDistinctSaltsWithinIssuance", withinOk, v.expectDistinctSaltsWithinIssuance);
  check(v, "expectDistinctSaltsAcrossIssuances", acrossSaltsOk, v.expectDistinctSaltsAcrossIssuances);
  check(v, "expectDistinctLeafHashesAcrossIssuances", acrossHashesOk,
    v.expectDistinctLeafHashesAcrossIssuances);
}

// Class 19. The two forms share ONE salt set, so any root difference is normalization and
// nothing else. Only the value case exists: whether the TYPE-MAP LOOKUP matches over normalized
// keys is an open question (docs/decisions.md), and a key-case vector would settle it.
for (const v of V.normalization ?? []) {
  const map = typeMaps[v.recordType];
  if (map === undefined) {
    throw new Error(`corpus defect: normalization ${v.name} names missing type map `
      + `${v.recordType}`);
  }
  const identity = {
    recordType: v.recordType,
    schemaVersion: v.schemaVersion,
    recordId: v.recordId,
    issuerId: v.issuerId,
    issuerKeyId: v.issuerKeyId,
  };
  const saltDoc = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, v.saltsFile), "utf8"));
  const roots = [v.recordFileNFD, v.recordFileNFC].map((file) => {
    const record = parseRecord(fs.readFileSync(path.join(REPO_ROOT, file), "utf8"));
    const ordered = ref.orderedLeaves(record, map, identity);
    const salts = ref.saltSetFromDocument(saltDoc, ordered);
    return ref.buildTree(HASH_ALG, record, map, salts, identity).root.toString("hex");
  });
  check(v, "expectSameRoot", roots[0] === roots[1], v.expectSameRoot);
  if ("root" in v) check(v, "root", roots[0], v.root);
}

for (const v of V.envelope ?? []) {
  const file = path.join(REPO_ROOT, v.envelopeFile);
  const envelope = parseRecord(fs.readFileSync(file, "utf8"));
  const [accepted, reason] = env.verify(envelope, typeMaps);
  check(v, "expectAccept", accepted, v.expectAccept);
  // The reason is asserted, not just the verdict. Several fixtures are rejectable for more
  // than one cause - `guard-reject-reserved-collision` carries a placeholder root because a
  // record colliding with a reserved path cannot be hashed at all - so a boolean alone would
  // pass an implementation that never ran the check the vector is about.
  check(v, "reason", reason, v.reason);
}

// ---------------------------------------------------------------------------------------------
// Reporting
// ---------------------------------------------------------------------------------------------

const CLASS_COUNT = 19;
const byClass = new Map();
for (const r of results) {
  const bucket = byClass.get(r.cls) ?? { pass: 0, fail: 0, failures: [] };
  if (r.ok) bucket.pass += 1;
  else {
    bucket.fail += 1;
    bucket.failures.push(r);
  }
  byClass.set(r.cls, bucket);
}

let failed = 0;
let incomplete = 0;
if (!QUIET) {
  console.log(`corpus ${CORPUS_FILE}`);
  console.log(`  corpusVersion ${corpus.corpusVersion}  canon ${corpus.canon}  hashAlg ${corpus.hashAlg}`);
  console.log(`  corpus pins Unicode ${corpus.unicodeVersion}; this runtime's NFC tables are Unicode ${process.versions.unicode}`);
  console.log(`  validated ${validatedSaltSetCount} committed salt-set carriers`);
}
for (let cls = 1; cls <= CLASS_COUNT; cls++) {
  const bucket = byClass.get(cls);
  const notes = notRun.filter((s) => s.cls === cls);
  if (bucket === undefined && notes.length === 0) {
    const message = `  class ${String(cls).padStart(2)}: NO VECTORS - coverage gap`;
    if (QUIET) console.error(message);
    else console.log(message);
    incomplete += 1;
    continue;
  }
  const pass = bucket?.pass ?? 0;
  const fail = bucket?.fail ?? 0;
  failed += fail;
  incomplete += notes.length;
  // Any class with a NOT RUN vector is incomplete, even when its other assertions pass.
  // Reporting PASS when work was not run is the failure docs/conformance-corpus.md guards against.
  let status;
  if (fail) status = notes.length ? "FAIL (also incomplete)" : "FAIL";
  else if (notes.length) status = pass === 0 ? "NOT RUN" : "INCOMPLETE - some vectors NOT RUN";
  else status = pass === 0 ? "NOT RUN" : "PASS";
  if (!QUIET || fail || notes.length) {
    const log = QUIET ? console.error : console.log;
    log(`  class ${String(cls).padStart(2)}: ${status}  ${pass} assertions` +
      (fail ? `, ${fail} FAILED` : "") + (notes.length ? `, ${notes.length} NOT RUN` : ""));
    for (const n of notes) log(`      NOT RUN: ${n.message}`);
    for (const f of (bucket?.failures ?? []).slice(0, 8)) {
      log(`      FAIL ${f.name} ${f.what}: got ${JSON.stringify(f.got)} want `
        + `${JSON.stringify(f.want)}`);
    }
  }
}

if (EMIT) {
  // Rewrite fields backed by this run's results. Inputs and NOT RUN vectors are copied through,
  // so the caller must exclude those vectors from any byte-comparison claim.
  const out = JSON.parse(fs.readFileSync(CORPUS_FILE, "utf8"));
  const byName = new Map(results.map((r) => [`${r.name} ${r.what}`, r.got]));
  const put = (vec, field, key = field) => {
    const got = byName.get(`${vec.name} ${key}`);
    if (got !== undefined) vec[field] = got;
  };
  for (const v of out.vectors.encodePath ?? []) { put(v, "encodedHex"); put(v, "displayPath"); }
  for (const v of out.vectors.encodeValue ?? []) put(v, "encodedHex");
  for (const v of out.vectors.reject ?? []) put(v, "reason");
  for (const v of out.vectors.leaf ?? []) put(v, "leafHash");
  for (const v of out.vectors.tree ?? []) put(v, "root");
  for (const v of out.vectors.inclusion ?? []) {
    put(v, "leafHash"); put(v, "auditPath"); put(v, "root"); put(v, "expect");
  }
  for (const v of out.vectors.negativeProof ?? []) {
    put(v, "leafHash"); put(v, "auditPath"); put(v, "root");
  }
  for (const v of out.vectors.typeMap ?? []) {
    if ("expectTag" in v) put(v, "expectTag");
    else put(v, "expectFailClosed");
  }
  for (const v of out.vectors.record ?? []) { put(v, "leafCount"); put(v, "root"); }
  // Class 12 and class 19 are absent from this list deliberately. Class 12 derives nothing to
  // write back, and class 19's root is asserted above rather than recomputed into the file.
  for (const v of out.vectors.envelope ?? []) { put(v, "expectAccept"); put(v, "reason"); }
  fs.writeFileSync(EMIT, JSON.stringify(out, null, 2) + "\n");
  if (!QUIET) console.log(`  emitted ${EMIT}`);
}

if (failed) {
  const log = QUIET ? console.error : console.log;
  log(`FAILED: ${failed} assertions`);
} else if (incomplete) {
  const log = QUIET ? console.error : console.log;
  log(`INCOMPLETE: ${results.length} assertions passed; ${incomplete} vector(s) or `
    + `class(es) NOT RUN`);
} else if (!QUIET) {
  console.log(`OK: ${results.length} assertions passed`);
}
process.exit(failed ? 1 : incomplete ? 2 : 0);
