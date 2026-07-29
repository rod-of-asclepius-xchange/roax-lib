#!/usr/bin/env node
// Validate every artifact this corpus ships against the repository's JSON Schemas.
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

console.log(failures ? `FAILED: ${failures}` : "OK: every artifact validates as expected");
process.exit(failures ? 1 : 0);
