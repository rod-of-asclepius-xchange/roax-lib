#!/usr/bin/env node
// Validate the corpus file, type maps, and envelope fixtures against the repository's JSON
// Schemas.
//
// The repository has no CI and no package manifest, and `AGENTS.md` records that the three
// schemas were checked with Ajv 8 in STRICT mode plus ajv-formats. This does the same for the
// artifacts, so "it conforms to the schema" is a measurement rather than an intention.
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
]);
for (const v of corpus.vectors.envelope ?? []) {
  const doc = readJson(path.join(REPO_ROOT, v.envelopeFile));
  const valid = validateEnvelope(doc);
  const expectValid = !SCHEMA_REJECTED.has(v.name);
  if (valid === expectValid) {
    console.log(`  ok    ${v.envelopeFile}${expectValid ? "" : "  (schema-rejected, as intended)"}`);
  } else {
    failures += 1;
    console.log(`  FAIL  ${v.envelopeFile}: schema said valid=${valid}, expected ${expectValid}`);
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

// Every value carrier makes a JSON number unrepresentable at any depth, because a JSON number in
// a vector file would be destroyed by the very parser under test (spec section 6.4).
probe("encodeValue vector carrying a bare JSON number", false,
  (doc) => { doc.vectors.encodeValue[0].input = 1.5; });

console.log(failures
  ? `FAILED: ${failures}`
  : "OK: corpus, type maps, envelope fixtures, and conditional probes validated as expected");
process.exit(failures ? 1 : 0);
