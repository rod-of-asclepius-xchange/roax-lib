#!/usr/bin/env node

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  artifactBytes,
  artifactId,
  parseArtifactBytes,
  testFixtures,
  validateArtifact,
} from "./check-type-map-extension.mjs";

const REFERENCE_COMMIT = "09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa";
const REFERENCE_REPOSITORY = "https://github.com/Open-Attestation/schemata.git";
const SOURCE_PREFIX = "references/schemata/src/";
const toolDirectory = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(toolDirectory, "..");
const EXPECTED_UNTYPED_OBJECT_SOURCE_NODES = new Map([
  ["hl7.fhir.bundle", 659],
  ["sg.gov.moh.pdt-healthcert", 65],
  ["sg.gov.moh.recovery-healthcert", 65],
  ["sg.gov.moh.vaccination-healthcert", 33],
]);

const USAGE =
  "Usage: node tools/check-type-maps.mjs [type-map-directory] [--skip-schema-validation]\n";

function parseArgs(argv) {
  const args = { out: undefined, schemaValidation: true };
  for (const arg of argv) {
    if (arg === "--skip-schema-validation") {
      args.schemaValidation = false;
    } else if (arg === "--help") {
      process.stdout.write(USAGE);
      process.exit(0);
    } else if (arg.startsWith("--") || args.out !== undefined) {
      throw new Error(`unknown argument: ${arg}\n${USAGE}`);
    } else {
      args.out = arg;
    }
  }
  return {
    outputRoot: resolve(args.out ?? join(repositoryRoot, "type-maps")),
    schemaValidation: args.schemaValidation,
  };
}

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function loadSchemaValidators() {
  const bases = [];
  if (process.env.ROAX_AJV) {
    bases.push(resolve(process.env.ROAX_AJV));
  }
  bases.push(process.cwd(), toolDirectory);
  const failures = [];
  for (const base of bases) {
    let compile;
    try {
      const require = createRequire(join(base, "roax-schema-resolution.cjs"));
      const ajvModule = require("ajv/dist/2020.js");
      const formatsModule = require("ajv-formats");
      const Ajv2020 = ajvModule.default ?? ajvModule;
      const addFormats = formatsModule.default ?? formatsModule;
      const ajv = new Ajv2020({ strict: true });
      addFormats(ajv);
      compile = (name) => ajv.compile(readJson(join(repositoryRoot, "schemas", name)));
    } catch (error) {
      failures.push(`  ${base}: ${error.message.split("\n")[0]}`);
      continue;
    }
    return {
      base,
      artifact: compile("type-map-artifact-1.0.json"),
      registry: compile("type-map-registry-1.0.json"),
    };
  }
  throw new Error(
    "ajv 8 and ajv-formats are required to validate the artifacts against their JSON Schemas.\n" +
      "Install them outside this tree and name that directory with ROAX_AJV:\n" +
      "  npm install --prefix /tmp/roax-ajv ajv ajv-formats\n" +
      "  ROAX_AJV=/tmp/roax-ajv node tools/check-type-maps.mjs\n" +
      "Pass --skip-schema-validation to run only the dependency-free carrier and binding checks.\n" +
      `Resolution attempts:\n${failures.join("\n")}`,
  );
}

function expectSchemaValid(validate, instance, label) {
  assert(
    validate(instance),
    `${label}: ${JSON.stringify(validate.errors?.slice(0, 3) ?? [])}`,
  );
}

function expectSchemaInvalid(validate, instance, label) {
  assert(!validate(instance), `${label}: the schema accepted an instance it must reject`);
}

function validateConditionalCarrierRules(schemas, parent, child) {
  expectSchemaValid(schemas.artifact, parent, "base artifact fixture");
  expectSchemaValid(schemas.artifact, child, "child artifact fixture");

  const profileScopedChild = structuredClone(child);
  profileScopedChild.scope = { kind: "profile" };
  expectSchemaInvalid(schemas.artifact, profileScopedChild, "child artifact with profile scope");

  const emptyChild = structuredClone(child);
  emptyChild.addedSelectors = [];
  expectSchemaInvalid(schemas.artifact, emptyChild, "child artifact with no added selector");

  const issuerScopedBase = structuredClone(parent);
  issuerScopedBase.scope = { kind: "issuers", issuerIds: ["did:example:issuer"] };
  expectSchemaInvalid(schemas.artifact, issuerScopedBase, "base artifact with issuer scope");

  const extendingBase = structuredClone(parent);
  extendingBase.addedSelectors = structuredClone(child.addedSelectors);
  expectSchemaInvalid(schemas.artifact, extendingBase, "base artifact with an added selector");
}

function validateProvenance(artifact) {
  const sourceIds = new Set();
  for (const source of artifact.sourceSchemas) {
    assert(!sourceIds.has(source.sourceId), `${artifact.recordType}: duplicate sourceId`);
    sourceIds.add(source.sourceId);
    assert(source.sourceId.startsWith(SOURCE_PREFIX));
    assert.equal(source.kind, "git");
    assert.equal(source.repositoryUri, REFERENCE_REPOSITORY);
    assert(source.path.startsWith("src/"));
    assert.equal(source.sourceId, `references/schemata/${source.path}`);
    assert.equal(source.commit, REFERENCE_COMMIT);
  }
  for (const state of artifact.automaton.states) {
    for (const binding of state.bindings ?? []) {
      for (const source of binding.sources) {
        assert(
          source.startsWith(SOURCE_PREFIX),
          `${artifact.recordType}: binding cites a source outside the pinned checkout`,
        );
      }
    }
  }
  assert.equal(
    artifact.coverage.structurallyUntypedObjectSourceNodes,
    EXPECTED_UNTYPED_OBJECT_SOURCE_NODES.get(artifact.recordType),
    `${artifact.recordType}: stale structurallyUntypedObjectSourceNodes`,
  );
}

function resolveBinding(artifact, segments, jsonKind) {
  const states = new Map(artifact.automaton.states.map((state) => [state.id, state]));
  let state = states.get(artifact.automaton.start);
  for (const segment of segments) {
    const next =
      typeof segment === "number"
        ? state.anyIndex
        : state.keys?.find(({ key }) => key === segment.normalize("NFC"))?.to;
    if (next === undefined) {
      return undefined;
    }
    state = states.get(next);
  }
  return state.bindings?.find((binding) => binding.jsonKind === jsonKind);
}

function expectTag(artifact, segments, jsonKind, tag) {
  assert.equal(
    resolveBinding(artifact, segments, jsonKind)?.tag,
    tag,
    `${artifact.recordType}: expected tag ${tag} at ${JSON.stringify(segments)}`,
  );
}

function expectUnbound(artifact, segments, jsonKind) {
  assert.equal(
    resolveBinding(artifact, segments, jsonKind),
    undefined,
    `${artifact.recordType}: expected fail-closed at ${JSON.stringify(segments)}`,
  );
}

function validateBindings(artifacts) {
  const fhir = artifacts.get("hl7.fhir.bundle");
  expectTag(fhir, ["resourceType"], "string", 2);
  expectTag(fhir, ["multipleBirthInteger"], "number", 3);
  expectTag(fhir, ["valueQuantity", "value"], "number", 4);
  expectTag(fhir, ["extension", 0, "extension", 1, "valueDecimal"], "number", 4);
  expectUnbound(fhir, ["text", "div"], "string");
  expectUnbound(fhir, ["data"], "string");
  expectUnbound(fhir, ["notInSchema"], "string");

  const pdt = artifacts.get("sg.gov.moh.pdt-healthcert");
  expectTag(pdt, ["id"], "string", 2);
  expectTag(pdt, ["type", 0], "string", 2);
  expectUnbound(pdt, ["type"], "array");
  expectTag(
    pdt,
    ["fhirBundle", "entry", 0, "resource", "valueQuantity", "value"],
    "number",
    4,
  );
  expectUnbound(pdt, ["$template", "name"], "string");
  expectUnbound(pdt, ["notarisationMetadata", "reference"], "string");
  expectUnbound(pdt, ["issuerAddedEmptyArray"], "array");
  expectUnbound(pdt, ["issuerAddedEmptyObject"], "object");

  const recovery = artifacts.get("sg.gov.moh.recovery-healthcert");
  expectTag(recovery, ["validUntil"], "string", 2);
  expectUnbound(recovery, ["type", 0], "string");
  expectUnbound(recovery, ["issuerAdded"], "string");

  const vaccination = artifacts.get("sg.gov.moh.vaccination-healthcert");
  expectTag(vaccination, ["attachments"], "array", 6);
  expectTag(vaccination, ["attachments", 0], "object", 7);
  expectTag(vaccination, ["fhirBundle", "entry", 0, "birthDate"], "string", 2);
  expectUnbound(
    vaccination,
    ["fhirBundle", "entry", 0, "resource", "birthDate"],
    "string",
  );
  expectUnbound(
    vaccination,
    ["notarisationMetadata", "signedEuHealthCerts", 0, "dose"],
    "number",
  );
  expectUnbound(
    vaccination,
    ["notarisationMetadata", "signedEuHealthCerts", 0, "expiryDateTime"],
    "string",
  );
  expectUnbound(vaccination, ["notarisationMetadata", "issuerAdded"], "string");
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const schemas = args.schemaValidation ? loadSchemaValidators() : undefined;

  const fixtures = testFixtures();
  assert.equal(
    fixtures.child.parentTypeMapId,
    artifactId(artifactBytes(fixtures.parent)),
    "the extension fixture does not identify its own parent bytes",
  );

  const registryPath = join(args.outputRoot, "registry-1.0.0.json");
  const registry = readJson(registryPath);
  assert.equal(registry.maps.length, 4, "registry must contain exactly four base maps");
  if (schemas !== undefined) {
    expectSchemaValid(schemas.registry, registry, registryPath);
    validateConditionalCarrierRules(schemas, fixtures.parent, fixtures.child);
  }

  const artifacts = new Map();
  for (const row of registry.maps) {
    const path = join(args.outputRoot, basename(row.path));
    const bytes = readFileSync(path);
    assert.equal(artifactId(bytes), row.id, `${row.recordType}: incorrect content ID`);
    const artifact = parseArtifactBytes(bytes, path);
    assert.equal(artifact.recordType, row.recordType);
    assert.equal(artifact.schemaVersion, row.schemaVersion);
    assert.equal(artifact.typeMapVersion, row.typeMapVersion);
    assert.deepEqual(artifact.scope, row.scope);
    assert.equal(
      artifact.parentTypeMapId,
      undefined,
      `${row.recordType}: a published base map must not name a parent`,
    );
    if (schemas !== undefined) {
      expectSchemaValid(schemas.artifact, artifact, path);
    }
    validateArtifact(artifact, row.recordType);
    validateProvenance(artifact);
    artifacts.set(row.recordType, artifact);
  }

  validateBindings(artifacts);
  process.stdout.write(
    `validated ${artifacts.size} type-map artifacts and the registry` +
      `${schemas === undefined ? " without JSON Schema validation" : ""}\n`,
  );
}

try {
  main();
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
}
