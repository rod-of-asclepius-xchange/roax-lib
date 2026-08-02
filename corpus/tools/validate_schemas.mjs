#!/usr/bin/env node
// Validate the corpus file, type maps, and envelope fixtures against the repository's JSON
// Schemas.
//
// The repository has no CI, and its `package.json` is the TypeScript library's rather than a place
// for schema tooling, so Ajv stays outside the tree. `AGENTS.md` records that the seven schemas
// were checked with Ajv 8 in STRICT mode plus ajv-formats. This does the same for the artifacts,
// so "it conforms to the schema" is a measurement rather than an intention.
//
//   npm install ajv@8 ajv-formats      # anywhere; pass its node_modules with --modules
//   node validate_schemas.mjs [--modules DIR]
//
// Schemas are loaded BY FILE PATH and never registered by `$id`. That is the general rule this
// project already learned from the reference schemata, two of which carry copy-pasted `$id`
// values, and it costs nothing to keep here.

import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CORPUS_DIR = path.dirname(HERE);
const REPO_ROOT = path.dirname(CORPUS_DIR);

const args = process.argv.slice(2);
const modulesArg = args.indexOf("--modules");
const modulesDir = modulesArg >= 0 ? args[modulesArg + 1] : process.env.ROAX_NODE_MODULES;

let Ajv;
let addFormats;
try {
  const require = createRequire(modulesDir ? path.join(modulesDir, "/") : import.meta.url);
  // The 2020-12 entry point, not Ajv's default export: every schema in this repository declares
  // $schema draft/2020-12, and the default export only knows draft-07.
  Ajv = require("ajv/dist/2020").default ?? require("ajv/dist/2020");
  addFormats = require("ajv-formats").default ?? require("ajv-formats");
} catch {
  console.error("ajv 8 and ajv-formats are required. Install them and pass --modules <node_modules>.");
  process.exit(2);
}

const ajv = new Ajv({ strict: true, allErrors: true });
addFormats(ajv);

const readJson = (p) => JSON.parse(fs.readFileSync(p, "utf8"));

const corpusSchema = readJson(path.join(REPO_ROOT, "schemas/conformance-corpus-1.0.json"));
const envelopeSchema = readJson(path.join(REPO_ROOT, "schemas/envelope-1.0.json"));
const typeMapSchema = readJson(path.join(REPO_ROOT, "schemas/type-map-1.0.json"));

const validateCorpus = ajv.compile(corpusSchema);
const validateEnvelope = ajv.compile(envelopeSchema);
const validateTypeMap = ajv.compile(typeMapSchema);

let failures = 0;

function run(label, validate, doc) {
  if (validate(doc)) {
    console.log(`  ok    ${label}`);
    return;
  }
  failures += 1;
  console.log(`  FAIL  ${label}`);
  for (const e of validate.errors.slice(0, 6)) {
    console.log(`          ${e.instancePath || "/"} ${e.message}`);
  }
}

console.log("conformance corpus");
run("corpus/conformance-corpus-1.0.json", validateCorpus,
  readJson(path.join(CORPUS_DIR, "conformance-corpus-1.0.json")));

console.log("type maps");
const typeMapDir = path.join(CORPUS_DIR, "type-maps");
for (const name of fs.readdirSync(typeMapDir).sort()) {
  if (name.endsWith(".json")) {
    run(`corpus/type-maps/${name}`, validateTypeMap, readJson(path.join(typeMapDir, name)));
  }
}

console.log("envelope fixtures");
// Every fixture is checked against the envelope schema, INCLUDING the ones the corpus expects a
// verifier to reject. Several are rejected BY the schema - a disclosed copy carrying `salts`,
// or a masterSalt field - and that is the point: the envelope schema closes those structurally
// so they are unrepresentable rather than merely forbidden (section 10.1). The expected schema
// verdict is read from the corpus vector, so a fixture that starts validating when it should
// not is a failure here.
const corpus = readJson(path.join(CORPUS_DIR, "conformance-corpus-1.0.json"));
const SCHEMA_REJECTED = new Set([
  "salt-leak-disclosed-copy-with-salts-array",
  "salt-leak-disclosed-copy-with-master-salt",
  "salt-leak-named-leaf-without-value",
  // `"salts": {}` is not an array, so the envelope schema rejects it structurally. Both halves
  // matter: the schema makes it unrepresentable in a conforming document, and the corpus vector
  // makes a VERIFIER that reads a wrong-typed member as absent fail - which is the half a schema
  // check cannot cover, because a schema validator is not what runs inside a verifier.
  "salt-leak-disclosed-copy-with-wrong-typed-salts",
]);
// Class 20's fixtures are named by roundTripVector rather than by an envelope vector, and they
// are envelopes: leaving them out would let the one class whose fixtures an implementation must
// REPRODUCE be the only class whose fixtures nothing schema-checked.
const envelopeFixtureFiles = [
  ...(corpus.vectors.envelope ?? []).map((v) => [v.name, v.envelopeFile]),
  ...(corpus.vectors.roundTrip ?? []).flatMap((v) => [
    [v.name, v.expectedFullCopyFile], [v.name, v.expectedDisclosedCopyFile],
  ]),
];
for (const [name, file] of envelopeFixtureFiles) {
  const doc = readJson(path.join(REPO_ROOT, file));
  const valid = validateEnvelope(doc);
  const expectValid = !SCHEMA_REJECTED.has(name);
  if (valid === expectValid) {
    console.log(`  ok    ${file}${expectValid ? "" : "  (schema-rejected, as intended)"}`);
  } else {
    failures += 1;
    console.log(`  FAIL  ${file}: schema said valid=${valid}, expected ${expectValid}`);
    for (const e of (validateEnvelope.errors ?? []).slice(0, 4)) {
      console.log(`          ${e.instancePath || "/"} ${e.message}`);
    }
  }
}

// A conditional that never fires compiles perfectly and asserts nothing, and validating the
// committed corpus only ever exercises the branches the committed corpus happens to reach.
// `AGENTS.md` says so and then names the probes a reader must run by hand; these run them.
//
// Each probe validates a WHOLE corpus document at root level rather than a `$defs` subschema,
// because compiling proves the `$ref` resolves and only a root-level instance proves the branch
// is reached by the path a runner takes.
console.log("schema conditionals (both directions, at root level)");

const clone = (doc) => JSON.parse(JSON.stringify(doc));
const findVector = (doc, group, pick) => doc.vectors[group].find(pick);

// A complete verifierConfig: all four members the definition requires.
const FULL_CONFIG = {
  anchoredRoot: "0".repeat(64),
  anchoredHashAlg: "SHA-256",
  hashAlgAllowList: ["SHA-256"],
  registryAddress: "roax:test:registry",
};

function probe(label, expectValid, mutate) {
  const doc = clone(corpus);
  mutate(doc);
  const valid = validateCorpus(doc);
  if (valid === expectValid) {
    console.log(`  ok    ${label}  (schema said valid=${valid})`);
    return;
  }
  failures += 1;
  console.log(`  FAIL  ${label}: schema said valid=${valid}, expected ${expectValid}`);
  for (const e of (validateCorpus.errors ?? []).slice(0, 4)) {
    console.log(`          ${e.instancePath || "/"} ${e.message}`);
  }
}

// envelopeVector's class-18 conditional. It PERMITS verifierConfig at 18 and forbids it
// everywhere else, and the `then` branch is deliberately not a `required`: a revision that
// required it rejected the committed corpus, whose four class-18 vectors are the identity rows
// the envelope alone determines. The else-branch is the half a compile check cannot see.
//
// These EXERCISE THE SCHEMA BRANCH and nothing more. They do not enforce the completeness rule
// the `then` branch describes - that a vector whose outcome turns on the verifier's configuration
// must carry a block - which no keyword can express and which that branch correctly records as
// unenforced. Every block below is synthesized here; no committed vector carries one to read.
const at18 = (doc) => findVector(doc, "envelope", (v) => v.class === 18);
const at14 = (doc) => findVector(doc, "envelope", (v) => v.class === 14);

probe("class 18 without verifierConfig", true, () => {});
probe("class 18 with a complete verifierConfig", true,
  (doc) => { at18(doc).verifierConfig = clone(FULL_CONFIG); });
probe("class 18 with an EMPTY verifierConfig", false,
  (doc) => { at18(doc).verifierConfig = {}; });
probe("class 18 with a PARTIAL verifierConfig (no hashAlgAllowList)", false,
  (doc) => {
    const c = clone(FULL_CONFIG);
    delete c.hashAlgAllowList;
    at18(doc).verifierConfig = c;
  });
probe("class 14 carrying a complete verifierConfig", false,
  (doc) => { at14(doc).verifierConfig = clone(FULL_CONFIG); });

// recordVector's two-branch oneOf, which is what makes the D4b salts structurally unavoidable:
// a bare record file plus a root is not a reproducible assertion once nothing derives a salt.
// Every committed record vector takes the first branch, so the second is reached here by
// rewriting one - otherwise the envelope branch is a compile-time-only claim.
const bareRecord = (doc) => findVector(doc, "record", (v) => v.recordFile !== undefined);
const asEnvelopeVector = (doc) => {
  const v = bareRecord(doc);
  delete v.recordFile;
  delete v.saltsFile;
  delete v.saltPairing;
  v.envelopeFile = "corpus/fixtures/envelopes/full-copy-complete-salts.json";
  return v;
};

probe("record vector naming a record file WITHOUT its salt set", false,
  (doc) => {
    const v = bareRecord(doc);
    delete v.saltsFile;
    delete v.saltPairing;
  });
probe("record vector naming a full envelope copy alone", true,
  (doc) => { asEnvelopeVector(doc); });
probe("record vector naming BOTH an envelope and a salt set", false,
  (doc) => {
    const v = asEnvelopeVector(doc);
    v.saltsFile = "corpus/fixtures/salts/record-typed-scalars.json";
    v.saltPairing = "path";
  });

// The deleted D4a derivation must be unrepresentable, not merely unused: spec section 1.1 and
// docs/conformance-corpus.md section 1.1 require the canonicalization change to land with the
// vectors that assert it, so the carriers it needed are gone from the schema rather than ignored.
probe("record vector carrying the deleted masterSaltHex", false,
  (doc) => { bareRecord(doc).masterSaltHex = "0".repeat(32); });
probe("corpus carrying the deleted salt vector group", false,
  (doc) => {
    doc.vectors.salt = [{
      name: "derived-salt", class: 7, recordId: "urn:roax:test",
      path: "a", masterSaltHex: "0".repeat(32), saltHex: "0".repeat(32),
    }];
  });

// rejectVector's recordType conditional, added with the 2026-07-30 type rulings. A `recordType`
// makes the vector a WHOLE-RECORD rejection flattened through that profile's committed map, so the
// conditional binds the input shape: the record travels as `$jsonText`, and neither `tag` nor
// `segments` may appear, because neither the value encoder nor the path encoder consumes it.
//
// Both directions, because the else side is the half a compile check cannot see: without it a
// reader cannot tell this conditional from one that forbids `tag` on every reject vector.
const recordReject = (doc) =>
  findVector(doc, "reject", (v) => v.recordType !== undefined);
const bareReject = (doc) =>
  findVector(doc, "reject", (v) => v.recordType === undefined && v.tag !== undefined);

probe("record-shaped reject vector as committed", true, () => {});
probe("record-shaped reject vector whose input is not $jsonText", false,
  (doc) => { recordReject(doc).input = "not-a-record"; });
probe("record-shaped reject vector also carrying a tag", false,
  (doc) => { recordReject(doc).tag = 2; });
probe("record-shaped reject vector also carrying segments", false,
  (doc) => { recordReject(doc).segments = [{ key: "a" }]; });
probe("reject vector with NO recordType keeping its tag", true,
  (doc) => { bareReject(doc); });
probe("reject vector with NO recordType keeping segments", true,
  (doc) => {
    const v = bareReject(doc);
    delete v.tag;
    v.segments = [{ key: "a" }];
  });

// Every value carrier makes a JSON number unrepresentable at any depth, because a JSON number in
// a vector file would be destroyed by the very parser under test (spec section 6.4).
probe("encodeValue vector carrying a bare JSON number", false,
  (doc) => { doc.vectors.encodeValue[0].input = 1.5; });

// roundTripVector. It carries no if/then, so what these probe are the pins that keep the class
// from becoming vacuous: an implementation "passing" it by declaring that its own output need
// not verify, or by dropping the assertion the class exists for.
const roundTrip = (doc) => doc.vectors.roundTrip[0];
probe("round-trip vector as committed", true, () => {});
probe("round-trip vector declaring its own output need not verify", false,
  (doc) => { roundTrip(doc).expectSelfVerifies = false; });
probe("round-trip vector without expectSelfVerifies at all", false,
  (doc) => { delete roundTrip(doc).expectSelfVerifies; });
probe("round-trip vector without the disclosed copy it must reproduce", false,
  (doc) => { delete roundTrip(doc).expectedDisclosedCopyFile; });
// The class const, which is what stops a mislabelled vector marking another class covered while
// leaving this one reading as a gap.
probe("round-trip vector labelled as another class", false,
  (doc) => { roundTrip(doc).class = 14; });
// disclosePaths is SEGMENTS. A dotted display string is the section 5.2 trap one level up: it
// would name a leaf no record has, so the produced copy would silently omit that path.
probe("round-trip vector naming a disclose path in display notation", false,
  (doc) => { roundTrip(doc).disclosePaths = ["counts.integer"]; });

// orderingVector and the `ordering` declaration (spec section 9). The declaration is REQUIRED on
// every ordering-sensitive vector, which is the half a compile check cannot see: a schema that
// merely PERMITTED the field would accept the corpus unchanged today and would still accept a
// future `hash`-ordered vector that forgot to say so, which is the silent-divergence shape the
// whole file exists to prevent.
probe("leaf vector without its ordering declaration", false,
  (doc) => { delete doc.vectors.leaf[0].ordering; });
probe("record vector without its ordering declaration", false,
  (doc) => { delete doc.vectors.record[0].ordering; });
probe("envelope vector without its ordering declaration", false,
  (doc) => { delete doc.vectors.envelope[0].ordering; });
probe("leaf vector declaring an unregistered ordering", false,
  (doc) => { doc.vectors.leaf[0].ordering = "document"; });
// The registered non-default value must be ACCEPTED by the schema even though no committed
// vector in these groups uses it, or the schema would forbid the very thing the amendment added.
probe("leaf vector declaring the non-default hash ordering", true,
  (doc) => { doc.vectors.leaf[0].ordering = "hash"; });

const ordering = (doc) => doc.vectors.ordering[0];
probe("ordering vector as committed", true, () => {});
// A class-21 vector carrying one side asserts nothing about the axis it exists to test.
probe("ordering vector carrying only the path side", false,
  (doc) => { delete ordering(doc).orderings.hash; });
probe("ordering vector carrying only the hash side", false,
  (doc) => { delete ordering(doc).orderings.path; });
probe("ordering vector carrying an unregistered third ordering", false,
  (doc) => { ordering(doc).orderings.document = clone(ordering(doc).orderings.path); });
// The leaf hashes are what prove tree PLACEMENT rather than only the root.
probe("ordering vector without its per-side leaf hashes", false,
  (doc) => { delete ordering(doc).orderings.hash.leafHashes; });
probe("ordering vector labelled as another class", false,
  (doc) => { ordering(doc).class = 10; });
// A class-21 vector must not ALSO carry a single top-level ordering: it would contradict the two
// it declares inside `orderings`.
probe("ordering vector also carrying a top-level ordering stamp", false,
  (doc) => { ordering(doc).ordering = "path"; });
// A positional salt set cannot serve both sides, whose leaf counts differ by the roax.ordering
// leaf, so the enum admits `path` alone here where recordVector admits both.
probe("ordering vector declaring a positional salt set", false,
  (doc) => { ordering(doc).saltPairing = "positional"; });

// The file-level default is pinned to the specification's default rather than left free. A corpus
// declaring the other one would make every vector that declares nothing wrong at once, which no
// single vector could reveal.
probe("corpus declaring hash as its default ordering", false,
  (doc) => { doc.defaultOrdering = "hash"; });
probe("corpus declaring no default ordering at all", false,
  (doc) => { delete doc.defaultOrdering; });

console.log(failures
  ? `FAILED: ${failures}`
  : "OK: corpus, type maps, envelope fixtures, and conditional probes validated as expected");
process.exit(failures ? 1 : 0);
