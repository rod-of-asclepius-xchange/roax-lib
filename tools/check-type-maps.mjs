#!/usr/bin/env node

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { basename, join, resolve } from "node:path";

const ID_DOMAIN = Buffer.from("ROAX-TYPE-MAP/1\0", "utf8");
const REFERENCE_COMMIT = "09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa";
const REFERENCE_REPOSITORY = "https://github.com/Open-Attestation/schemata.git";
const outputRoot = resolve(process.argv[2] ?? "type-maps");
const EXPECTED_UNTYPED_OBJECT_SOURCE_NODES = new Map([
  ["hl7.fhir.bundle", 659],
  ["sg.gov.moh.pdt-healthcert", 65],
  ["sg.gov.moh.recovery-healthcert", 65],
  ["sg.gov.moh.vaccination-healthcert", 33],
]);

function compareUtf8(left, right) {
  return Buffer.compare(Buffer.from(left, "utf8"), Buffer.from(right, "utf8"));
}

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function artifactId(bytes) {
  return `sha256:${createHash("sha256").update(ID_DOMAIN).update(bytes).digest("hex")}`;
}

function stateIndex(artifact) {
  const index = new Map();
  for (const state of artifact.automaton.states) {
    assert(!index.has(state.id), `${artifact.recordType}: duplicate state ${state.id}`);
    index.set(state.id, state);
  }
  assert(index.has(artifact.automaton.start), `${artifact.recordType}: missing start state`);
  return index;
}

function validateAutomaton(artifact) {
  const states = stateIndex(artifact);
  assert.equal(artifact.format, "ROAX-TYPE-MAP/1");
  assert.equal(artifact.automaton.representation, "structured-path-dfa/1");
  assert.equal(artifact.automaton.start, "s0");
  assert.deepEqual(artifact.scope, { kind: "profile" });
  assert.equal(artifact.parentTypeMapId, undefined);
  assert.deepEqual(artifact.addedSelectors, []);
  assert.equal(artifact.coverage.states, states.size);

  const sourceIds = new Set();
  for (const source of artifact.sourceSchemas) {
    assert(!sourceIds.has(source.sourceId), `${artifact.recordType}: duplicate sourceId`);
    sourceIds.add(source.sourceId);
    assert(source.sourceId.startsWith("references/schemata/src/"));
    assert.equal(source.kind, "git");
    assert.equal(source.repositoryUri, REFERENCE_REPOSITORY);
    assert(source.path.startsWith("src/"));
    assert(!source.path.startsWith("/"));
    assert(!source.path.split("/").includes(".."));
    assert.equal(source.sourceId, `references/schemata/${source.path}`);
    assert.equal(source.commit, REFERENCE_COMMIT);
  }
  for (const point of artifact.extensionPoints) {
    let state = states.get(artifact.automaton.start);
    for (const segment of point.prefix) {
      if (segment.key !== undefined) {
        assert.equal(segment.key, segment.key.normalize("NFC"));
        const next = state.keys?.find(({ key }) => key === segment.key)?.to;
        assert(next !== undefined, `${artifact.recordType}: invalid extension-point KEY`);
        state = states.get(next);
      } else {
        assert(state.anyIndex !== undefined, `${artifact.recordType}: invalid extension-point INDEX`);
        state = states.get(state.anyIndex);
      }
    }
  }

  const reached = new Set([artifact.automaton.start]);
  const queue = [artifact.automaton.start];
  const totals = {
    keyTransitions: 0,
    indexTransitions: 0,
    resolvedOutputs: 0,
    unresolvedOutputStates: 0,
    structurallyUntypedObjectStates: 0,
  };
  for (const [position, state] of artifact.automaton.states.entries()) {
    assert.equal(state.id, `s${position}`, `${artifact.recordType}: non-canonical state order`);
    const keys = new Set();
    const keyOrder = (state.keys ?? []).map(({ key }) => key);
    assert.deepEqual(keyOrder, [...keyOrder].sort(compareUtf8));
    for (const transition of state.keys ?? []) {
      assert.equal(transition.key, transition.key.normalize("NFC"));
      assert(!keys.has(transition.key), `${state.id}: duplicate KEY transition`);
      keys.add(transition.key);
      assert(states.has(transition.to), `${state.id}: dangling KEY transition`);
      totals.keyTransitions += 1;
    }
    if (state.anyIndex !== undefined) {
      assert(states.has(state.anyIndex), `${state.id}: dangling INDEX transition`);
      totals.indexTransitions += 1;
    }
    const kinds = new Set();
    for (const binding of state.bindings ?? []) {
      assert(!kinds.has(binding.jsonKind), `${state.id}: duplicate output kind`);
      kinds.add(binding.jsonKind);
      assert.notEqual(binding.tag, 8, `${state.id}: version-1 base map emits BLOB_REF`);
      totals.resolvedOutputs += 1;
      for (const source of binding.sources) {
        assert(source.startsWith("references/schemata/src/"));
        assert(
          sourceIds.has(source.split("#", 1)[0]),
          `${artifact.recordType}: binding cites an unknown sourceId`,
        );
      }
    }
    if (state.unresolved !== undefined) {
      totals.unresolvedOutputStates += 1;
      for (const row of state.unresolved) {
        for (const source of row.sources) {
          assert(
            sourceIds.has(source.split("#", 1)[0]),
            `${artifact.recordType}: unresolved row cites an unknown sourceId`,
          );
        }
        for (const kind of row.jsonKinds) {
          assert(!kinds.has(kind), `${state.id}: operative and unresolved output overlap`);
        }
      }
    }
    if (state.structurallyUntypedObject === true) {
      totals.structurallyUntypedObjectStates += 1;
    }
  }
  while (queue.length > 0) {
    const state = states.get(queue.shift());
    for (const next of [
      ...(state.keys ?? []).map(({ to }) => to),
      ...(state.anyIndex === undefined ? [] : [state.anyIndex]),
    ]) {
      if (!reached.has(next)) {
        reached.add(next);
        queue.push(next);
      }
    }
  }
  assert.equal(reached.size, states.size, `${artifact.recordType}: unreachable DFA state`);
  for (const [field, total] of Object.entries(totals)) {
    assert.equal(artifact.coverage[field], total, `${artifact.recordType}: stale ${field}`);
  }
  assert.equal(
    artifact.coverage.structurallyUntypedObjectSourceNodes,
    EXPECTED_UNTYPED_OBJECT_SOURCE_NODES.get(artifact.recordType),
    `${artifact.recordType}: stale structurallyUntypedObjectSourceNodes`,
  );
}

function resolveBinding(artifact, segments, jsonKind) {
  const states = stateIndex(artifact);
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

const registry = readJson(join(outputRoot, "registry-1.0.0.json"));
assert.equal(registry.maps.length, 4, "registry must contain exactly four base maps");
const artifacts = new Map();
for (const row of registry.maps) {
  const path = join(outputRoot, basename(row.path));
  const bytes = readFileSync(path);
  assert.equal(artifactId(bytes), row.id, `${row.recordType}: incorrect content ID`);
  const artifact = JSON.parse(bytes);
  assert.equal(artifact.recordType, row.recordType);
  assert.equal(artifact.schemaVersion, row.schemaVersion);
  assert.equal(artifact.typeMapVersion, row.typeMapVersion);
  assert.deepEqual(artifact.scope, row.scope);
  validateAutomaton(artifact);
  artifacts.set(row.recordType, artifact);
}

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

process.stdout.write(`validated ${artifacts.size} type-map artifacts\n`);
