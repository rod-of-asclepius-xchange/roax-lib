#!/usr/bin/env node

import { createHash } from "node:crypto";
import { readFileSync, realpathSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { isDeepStrictEqual, TextDecoder } from "node:util";

const ID_DOMAIN = Buffer.from("ROAX-TYPE-MAP/1\0", "utf8");
const TYPE_MAP_ID = /^sha256:[0-9a-f]{64}$/;
const SEMVER = /^([0-9]+)\.([0-9]+)\.([0-9]+)$/;
const STATE_ID = /^s(?:0|[1-9][0-9]*)$/;
const GIT_COMMIT = /^[0-9a-f]{40}$/;
const JSON_NUMBER = /-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/y;
const JSON_KINDS = new Set([
  "array",
  "boolean",
  "null",
  "number",
  "object",
  "string",
]);
const BASIS = new Set([
  "fhir-element-name",
  "fhir-named-primitive",
  "profile-ruling",
  "schema-const",
  "schema-container-type",
  "schema-enum",
  "schema-type",
]);
const TAG_KINDS = new Map([
  [0, new Set(["null"])],
  [1, new Set(["boolean"])],
  [2, new Set(["string"])],
  [3, new Set(["number"])],
  [4, new Set(["number"])],
  [5, new Set(["string"])],
  [6, new Set(["array"])],
  [7, new Set(["object"])],
]);

function fail(message) {
  throw new Error(message);
}

function ensure(condition, message) {
  if (!condition) {
    fail(message);
  }
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function validateKeys(value, required, optional, label) {
  ensure(isObject(value), `${label} must be an object`);
  const allowed = new Set([...required, ...optional]);
  for (const key of required) {
    ensure(Object.hasOwn(value, key), `${label}: missing required property ${key}`);
  }
  for (const key of Object.keys(value)) {
    ensure(allowed.has(key), `${label}: unexpected property ${key}`);
  }
}

function compareUtf8(left, right) {
  return Buffer.compare(Buffer.from(left, "utf8"), Buffer.from(right, "utf8"));
}

function isSorted(values, compare = compareUtf8) {
  for (let index = 1; index < values.length; index += 1) {
    if (compare(values[index - 1], values[index]) >= 0) {
      return false;
    }
  }
  return true;
}

function artifactId(bytes) {
  return `sha256:${createHash("sha256").update(ID_DOMAIN).update(bytes).digest("hex")}`;
}

function artifactBytes(artifact) {
  return Buffer.from(`${JSON.stringify(artifact, null, 2)}\n`, "utf8");
}

function rejectDuplicateJsonMembers(text, label) {
  let index = 0;

  function syntax(message) {
    fail(`${label}: invalid JSON while checking duplicate members at offset ${index}: ${message}`);
  }

  function skipWhitespace() {
    while (
      index < text.length &&
      (text[index] === " " ||
        text[index] === "\t" ||
        text[index] === "\n" ||
        text[index] === "\r")
    ) {
      index += 1;
    }
  }

  function scanString(decode) {
    ensure(text[index] === '"', `${label}: internal JSON string scanner error`);
    const start = index;
    index += 1;
    while (index < text.length) {
      const character = text[index];
      if (character === '"') {
        index += 1;
        if (!decode) {
          return undefined;
        }
        try {
          return JSON.parse(text.slice(start, index));
        } catch (error) {
          syntax(error.message);
        }
      }
      if (character === "\\") {
        index += 1;
        if (index >= text.length) {
          syntax("unterminated escape sequence");
        }
        if (text[index] === "u") {
          index += 5;
        } else {
          index += 1;
        }
        continue;
      }
      index += 1;
    }
    syntax("unterminated string");
  }

  function scanObject() {
    index += 1;
    skipWhitespace();
    const members = new Set();
    if (text[index] === "}") {
      index += 1;
      return;
    }
    while (index < text.length) {
      if (text[index] !== '"') {
        syntax("object member name must be a string");
      }
      const member = scanString(true);
      if (members.has(member)) {
        fail(`${label}: duplicate JSON object member ${JSON.stringify(member)}`);
      }
      members.add(member);
      skipWhitespace();
      if (text[index] !== ":") {
        syntax("object member name must be followed by ':'");
      }
      index += 1;
      scanValue();
      skipWhitespace();
      if (text[index] === "}") {
        index += 1;
        return;
      }
      if (text[index] !== ",") {
        syntax("object members must be separated by ','");
      }
      index += 1;
      skipWhitespace();
    }
    syntax("unterminated object");
  }

  function scanArray() {
    index += 1;
    skipWhitespace();
    if (text[index] === "]") {
      index += 1;
      return;
    }
    while (index < text.length) {
      scanValue();
      skipWhitespace();
      if (text[index] === "]") {
        index += 1;
        return;
      }
      if (text[index] !== ",") {
        syntax("array elements must be separated by ','");
      }
      index += 1;
      skipWhitespace();
    }
    syntax("unterminated array");
  }

  function scanLiteral(literal) {
    if (!text.startsWith(literal, index)) {
      syntax(`expected ${literal}`);
    }
    index += literal.length;
  }

  function scanValue() {
    skipWhitespace();
    const character = text[index];
    if (character === "{") {
      scanObject();
      return;
    }
    if (character === "[") {
      scanArray();
      return;
    }
    if (character === '"') {
      scanString(false);
      return;
    }
    if (character === "t") {
      scanLiteral("true");
      return;
    }
    if (character === "f") {
      scanLiteral("false");
      return;
    }
    if (character === "n") {
      scanLiteral("null");
      return;
    }
    JSON_NUMBER.lastIndex = index;
    const number = JSON_NUMBER.exec(text);
    if (number !== null) {
      index = JSON_NUMBER.lastIndex;
      return;
    }
    syntax("expected a JSON value");
  }

  skipWhitespace();
  scanValue();
  skipWhitespace();
  if (index !== text.length) {
    syntax("unexpected trailing content");
  }
}

function rejectUnpairedSurrogates(value, label) {
  function validateString(text, location) {
    for (let index = 0; index < text.length; index += 1) {
      const codeUnit = text.charCodeAt(index);
      if (codeUnit >= 0xd800 && codeUnit <= 0xdbff) {
        const next = text.charCodeAt(index + 1);
        if (!(next >= 0xdc00 && next <= 0xdfff)) {
          fail(`${label}: unpaired high surrogate in ${location}`);
        }
        index += 1;
      } else if (codeUnit >= 0xdc00 && codeUnit <= 0xdfff) {
        fail(`${label}: unpaired low surrogate in ${location}`);
      }
    }
  }

  function visit(current, location) {
    if (typeof current === "string") {
      validateString(current, location);
      return;
    }
    if (Array.isArray(current)) {
      current.forEach((item, index) => visit(item, `${location}[${index}]`));
      return;
    }
    if (!isObject(current)) {
      return;
    }
    for (const [member, memberValue] of Object.entries(current)) {
      validateString(member, `object member name ${JSON.stringify(member)} at ${location}`);
      visit(memberValue, `${location}[${JSON.stringify(member)}]`);
    }
  }

  visit(value, "$");
}

function parseArtifactBytes(bytes, label) {
  let text;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch (error) {
    fail(`${label}: invalid UTF-8: ${error.message}`);
  }
  rejectDuplicateJsonMembers(text, label);
  let artifact;
  try {
    artifact = JSON.parse(text);
  } catch (error) {
    fail(`${label}: invalid JSON: ${error.message}`);
  }
  rejectUnpairedSurrogates(artifact, label);
  return artifact;
}

function parseArtifact(path) {
  const bytes = readFileSync(path);
  const artifact = parseArtifactBytes(bytes, path);
  return { artifact, bytes };
}

function parseSemver(value, label) {
  ensure(typeof value === "string", `${label}: typeMapVersion must be a string`);
  const match = SEMVER.exec(value);
  ensure(match !== null, `${label}: typeMapVersion must be three-part semver`);
  return match.slice(1).map((part) => BigInt(part));
}

function validateUri(value, label) {
  ensure(typeof value === "string" && value.length > 0, `${label}: URI must be non-empty`);
  try {
    new URL(value);
  } catch {
    fail(`${label}: URI must be absolute`);
  }
}

function validateRelativePath(value, label) {
  ensure(typeof value === "string" && value.length > 0, `${label}: path must be non-empty`);
  ensure(!value.startsWith("/"), `${label}: path must be relative`);
  ensure(!value.split("/").includes(".."), `${label}: path must not traverse a parent directory`);
}

function validateSourceSchemas(artifact, label) {
  ensure(
    Array.isArray(artifact.sourceSchemas) && artifact.sourceSchemas.length > 0,
    `${label}: sourceSchemas must be a non-empty array`,
  );
  const sources = new Map();
  for (const [index, source] of artifact.sourceSchemas.entries()) {
    const sourceLabel = `${label}: sourceSchemas[${index}]`;
    ensure(isObject(source), `${sourceLabel} must be an object`);
    ensure(
      typeof source.sourceId === "string" &&
        source.sourceId.length > 0 &&
        !source.sourceId.includes("#"),
      `${sourceLabel}: sourceId must be non-empty and contain no '#'`,
    );
    ensure(!sources.has(source.sourceId), `${label}: duplicate sourceId ${source.sourceId}`);
    if (source.kind === "git") {
      validateKeys(
        source,
        ["sourceId", "kind", "repositoryUri", "path", "commit"],
        [],
        sourceLabel,
      );
      validateUri(source.repositoryUri, `${sourceLabel}.repositoryUri`);
      validateRelativePath(source.path, `${sourceLabel}.path`);
      ensure(
        typeof source.commit === "string" && GIT_COMMIT.test(source.commit),
        `${sourceLabel}: git commit must be 40 lowercase hexadecimal characters`,
      );
    } else if (source.kind === "content") {
      validateKeys(source, ["sourceId", "kind", "uri", "digest"], [], sourceLabel);
      validateUri(source.uri, `${sourceLabel}.uri`);
      ensure(
        typeof source.digest === "string" && TYPE_MAP_ID.test(source.digest),
        `${sourceLabel}: content digest must be sha256:<64 lowercase hex>`,
      );
    } else {
      fail(`${sourceLabel}: unsupported source kind ${JSON.stringify(source.kind)}`);
    }
    sources.set(source.sourceId, source);
  }
  return sources;
}

function sourceIdFromReference(reference, label) {
  ensure(
    typeof reference === "string" && /^[^#]+(?:#(?:\/.*)?)?$/.test(reference),
    `${label}: invalid source reference`,
  );
  return reference.split("#", 1)[0];
}

function validateSourceReferences(references, sources, label, { allowEmpty = false } = {}) {
  ensure(Array.isArray(references), `${label} must be an array`);
  ensure(allowEmpty || references.length > 0, `${label} must not be empty`);
  ensure(isSorted(references), `${label} must be UTF-8 sorted with no duplicates`);
  for (const [index, reference] of references.entries()) {
    const sourceId = sourceIdFromReference(reference, `${label}[${index}]`);
    ensure(sources.has(sourceId), `${label}[${index}]: unknown sourceId ${sourceId}`);
  }
}

function validateSegment(segment, label) {
  ensure(isObject(segment), `${label}: segment must be an object`);
  const keys = Object.keys(segment);
  if (keys.length === 1 && keys[0] === "key") {
    ensure(typeof segment.key === "string", `${label}: KEY value must be a string`);
    ensure(segment.key === segment.key.normalize("NFC"), `${label}: KEY must be NFC-normalized`);
    return;
  }
  if (keys.length === 1 && keys[0] === "anyIndex") {
    ensure(segment.anyIndex === true, `${label}: anyIndex must equal true`);
    return;
  }
  fail(`${label}: segment must contain exactly one of key or anyIndex`);
}

function segmentToken(segment) {
  return Object.hasOwn(segment, "key") ? `K:${JSON.stringify(segment.key)}` : "I";
}

function renderSegments(segments) {
  return `[${segments.map((segment) => segmentToken(segment)).join(", ")}]`;
}

function sameSegments(left, right) {
  return (
    left.length === right.length &&
    left.every((segment, index) => segmentToken(segment) === segmentToken(right[index]))
  );
}

function startsWithSegments(segments, prefix) {
  return prefix.length <= segments.length && sameSegments(segments.slice(0, prefix.length), prefix);
}

function validateTagKind(tag, jsonKind, label) {
  ensure(Number.isInteger(tag) && tag >= 0 && tag <= 8, `${label}: invalid type tag`);
  ensure(tag !== 8, `${label}: BLOB_REF tag 8 is not selected by a version-1 profile`);
  ensure(JSON_KINDS.has(jsonKind), `${label}: unsupported JSON kind ${JSON.stringify(jsonKind)}`);
  ensure(
    TAG_KINDS.get(tag)?.has(jsonKind),
    `${label}: tag ${tag} is incompatible with JSON kind ${jsonKind}`,
  );
}

function stateIndex(artifact, label) {
  ensure(isObject(artifact.automaton), `${label}: automaton must be an object`);
  validateKeys(
    artifact.automaton,
    ["representation", "start", "states"],
    [],
    `${label}: automaton`,
  );
  ensure(
    artifact.automaton.representation === "structured-path-dfa/1",
    `${label}: unsupported automaton representation`,
  );
  ensure(artifact.automaton.start === "s0", `${label}: automaton start must be s0`);
  ensure(
    Array.isArray(artifact.automaton.states) && artifact.automaton.states.length > 0,
    `${label}: automaton states must be a non-empty array`,
  );
  const states = new Map();
  for (const [index, state] of artifact.automaton.states.entries()) {
    ensure(isObject(state), `${label}: state at index ${index} must be an object`);
    validateKeys(
      state,
      ["id"],
      ["keys", "anyIndex", "bindings", "unresolved", "structurallyUntypedObject"],
      `${label}: state at index ${index}`,
    );
    ensure(state.id === `s${index}`, `${label}: non-canonical state id at index ${index}`);
    ensure(STATE_ID.test(state.id), `${label}: invalid state id ${state.id}`);
    ensure(!states.has(state.id), `${label}: duplicate state ${state.id}`);
    states.set(state.id, state);
  }
  return states;
}

function bindingSortKey(binding) {
  return binding.jsonKind;
}

function unresolvedSortKey(row) {
  return JSON.stringify([row.jsonKinds, row.reason, row.sources]);
}

function validateAutomaton(artifact, sources, label) {
  const states = stateIndex(artifact, label);
  const reached = new Set(["s0"]);
  const queue = ["s0"];
  const discovered = new Set(["s0"]);
  let nextCanonicalState = 1;
  const counts = {
    states: states.size,
    keyTransitions: 0,
    indexTransitions: 0,
    resolvedOutputs: 0,
    unresolvedOutputStates: 0,
    structurallyUntypedObjectStates: 0,
    byTag: {},
    byBasis: {},
  };

  for (const state of artifact.automaton.states) {
    const keys = state.keys ?? [];
    ensure(Array.isArray(keys), `${label}: ${state.id}.keys must be an array`);
    ensure(
      state.keys === undefined || state.keys.length > 0,
      `${label}: ${state.id}.keys must be omitted rather than empty`,
    );
    const keyValues = keys.map(({ key }) => key);
    ensure(
      isSorted(keyValues),
      `${label}: ${state.id} KEY transitions must be UTF-8 sorted with no duplicates`,
    );
    for (const [index, transition] of keys.entries()) {
      const transitionLabel = `${label}: ${state.id}.keys[${index}]`;
      ensure(isObject(transition), `${transitionLabel} must be an object`);
      validateKeys(transition, ["key", "to"], [], transitionLabel);
      ensure(typeof transition.key === "string", `${transitionLabel}.key must be a string`);
      ensure(
        transition.key === transition.key.normalize("NFC"),
        `${transitionLabel}.key must be NFC-normalized`,
      );
      ensure(states.has(transition.to), `${transitionLabel}: dangling target ${transition.to}`);
      counts.keyTransitions += 1;
    }
    if (state.anyIndex !== undefined) {
      ensure(states.has(state.anyIndex), `${label}: ${state.id} has a dangling INDEX target`);
      counts.indexTransitions += 1;
    }
    if (state.structurallyUntypedObject !== undefined) {
      ensure(
        state.structurallyUntypedObject === true,
        `${label}: ${state.id}.structurallyUntypedObject must equal true when present`,
      );
      counts.structurallyUntypedObjectStates += 1;
    }

    for (const target of [
      ...keys.map(({ to }) => to),
      ...(state.anyIndex === undefined ? [] : [state.anyIndex]),
    ]) {
      if (!discovered.has(target)) {
        ensure(
          target === `s${nextCanonicalState}`,
          `${label}: DFA state numbering is not canonical breadth-first discovery order`,
        );
        discovered.add(target);
        nextCanonicalState += 1;
      }
    }

    const bindings = state.bindings ?? [];
    ensure(Array.isArray(bindings), `${label}: ${state.id}.bindings must be an array`);
    ensure(
      state.bindings === undefined || state.bindings.length > 0,
      `${label}: ${state.id}.bindings must be omitted rather than empty`,
    );
    ensure(
      isSorted(bindings.map(bindingSortKey)),
      `${label}: ${state.id} bindings must be JSON-kind sorted with no duplicates`,
    );
    const boundKinds = new Set();
    for (const [index, binding] of bindings.entries()) {
      const bindingLabel = `${label}: ${state.id}.bindings[${index}]`;
      ensure(isObject(binding), `${bindingLabel} must be an object`);
      validateKeys(binding, ["jsonKind", "tag", "basis", "sources"], [], bindingLabel);
      validateTagKind(binding.tag, binding.jsonKind, bindingLabel);
      ensure(!boundKinds.has(binding.jsonKind), `${bindingLabel}: duplicate output kind`);
      boundKinds.add(binding.jsonKind);
      ensure(
        Array.isArray(binding.basis) &&
          binding.basis.length > 0 &&
          isSorted(binding.basis) &&
          binding.basis.every((basis) => BASIS.has(basis)),
        `${bindingLabel}.basis must be a sorted non-empty set of recognized values`,
      );
      validateSourceReferences(binding.sources, sources, `${bindingLabel}.sources`);
      counts.resolvedOutputs += 1;
      counts.byTag[String(binding.tag)] = (counts.byTag[String(binding.tag)] ?? 0) + 1;
      for (const basis of binding.basis) {
        counts.byBasis[basis] = (counts.byBasis[basis] ?? 0) + 1;
      }
    }

    const unresolved = state.unresolved ?? [];
    ensure(Array.isArray(unresolved), `${label}: ${state.id}.unresolved must be an array`);
    ensure(
      state.unresolved === undefined || state.unresolved.length > 0,
      `${label}: ${state.id}.unresolved must be omitted rather than empty`,
    );
    if (unresolved.length > 0) {
      counts.unresolvedOutputStates += 1;
    }
    for (const [index, row] of unresolved.entries()) {
      const rowLabel = `${label}: ${state.id}.unresolved[${index}]`;
      ensure(isObject(row), `${rowLabel} must be an object`);
      validateKeys(row, ["jsonKinds", "reason", "sources"], [], rowLabel);
      ensure(
        Array.isArray(row.jsonKinds) &&
          row.jsonKinds.length > 0 &&
          isSorted(row.jsonKinds) &&
          row.jsonKinds.every((kind) => JSON_KINDS.has(kind)),
        `${rowLabel}.jsonKinds must be a sorted non-empty set of recognized JSON kinds`,
      );
      for (const kind of row.jsonKinds) {
        ensure(!boundKinds.has(kind), `${rowLabel}: operative and unresolved outputs overlap`);
      }
      ensure(
        typeof row.reason === "string" && row.reason.length > 0,
        `${rowLabel}.reason must be non-empty`,
      );
      validateSourceReferences(row.sources, sources, `${rowLabel}.sources`, { allowEmpty: true });
    }
    ensure(
      isSorted(unresolved.map(unresolvedSortKey)),
      `${label}: ${state.id} unresolved rows must be UTF-8 sorted with no duplicates`,
    );
  }

  while (queue.length > 0) {
    const state = states.get(queue.shift());
    for (const target of [
      ...(state.keys ?? []).map(({ to }) => to),
      ...(state.anyIndex === undefined ? [] : [state.anyIndex]),
    ]) {
      if (!reached.has(target)) {
        reached.add(target);
        queue.push(target);
      }
    }
  }
  ensure(reached.size === states.size, `${label}: automaton contains an unreachable state`);
  ensure(
    discovered.size === states.size,
    `${label}: canonical discovery did not encounter every automaton state`,
  );
  validateCoverage(artifact.coverage, counts, label);
  return states;
}

function sameCountObject(actual, expected) {
  if (!isObject(actual)) {
    return false;
  }
  const actualKeys = Object.keys(actual).sort(compareUtf8);
  const expectedKeys = Object.keys(expected).sort(compareUtf8);
  return (
    isDeepStrictEqual(actualKeys, expectedKeys) &&
    actualKeys.every((key) => actual[key] === expected[key])
  );
}

function validateCoverage(coverage, counts, label) {
  ensure(isObject(coverage), `${label}: coverage must be an object`);
  validateKeys(
    coverage,
    [
      "concretePathCardinality",
      "states",
      "keyTransitions",
      "indexTransitions",
      "resolvedOutputs",
      "unresolvedOutputStates",
      "structurallyUntypedObjectSourceNodes",
      "structurallyUntypedObjectStates",
      "byTag",
      "byBasis",
      "notes",
    ],
    [],
    `${label}: coverage`,
  );
  ensure(
    coverage.concretePathCardinality === "infinite",
    `${label}: concretePathCardinality must be infinite`,
  );
  for (const field of [
    "states",
    "keyTransitions",
    "indexTransitions",
    "resolvedOutputs",
    "unresolvedOutputStates",
    "structurallyUntypedObjectStates",
  ]) {
    ensure(coverage[field] === counts[field], `${label}: stale coverage.${field}`);
  }
  ensure(
    Number.isInteger(coverage.structurallyUntypedObjectSourceNodes) &&
      coverage.structurallyUntypedObjectSourceNodes >= 0,
    `${label}: coverage.structurallyUntypedObjectSourceNodes must be a non-negative integer`,
  );
  ensure(sameCountObject(coverage.byTag, counts.byTag), `${label}: stale coverage.byTag`);
  ensure(sameCountObject(coverage.byBasis, counts.byBasis), `${label}: stale coverage.byBasis`);
  ensure(
    Array.isArray(coverage.notes) &&
      coverage.notes.every((note) => typeof note === "string" && note.length > 0),
    `${label}: coverage.notes must contain only non-empty strings`,
  );
}

function transitionMap(state) {
  const transitions = new Map();
  for (const transition of state.keys ?? []) {
    transitions.set(`K:${JSON.stringify(transition.key)}`, transition.to);
  }
  if (state.anyIndex !== undefined) {
    transitions.set("I", state.anyIndex);
  }
  return transitions;
}

function resolveState(states, segments) {
  let state = states.get("s0");
  for (const segment of segments) {
    const target = transitionMap(state).get(segmentToken(segment));
    if (target === undefined) {
      return undefined;
    }
    state = states.get(target);
  }
  return state;
}

function extensionPointAdmits(point, selector, parentStates) {
  const prefix = point.prefix;
  if (!startsWithSegments(selector.segments, prefix)) {
    return false;
  }
  if (selector.segments.length === prefix.length) {
    return false;
  }
  const prefixState = resolveState(parentStates, prefix);
  if (prefixState === undefined) {
    return false;
  }
  const inherited = transitionMap(prefixState).get(
    segmentToken(selector.segments[prefix.length]),
  );
  if (inherited === undefined) {
    return true;
  }
  if (selector.segments.length !== prefix.length + 1) {
    return false;
  }
  const targetState = parentStates.get(inherited);
  if (targetState === undefined || bindingMap(targetState).has(selector.jsonKind)) {
    return false;
  }
  return (targetState.unresolved ?? []).some((row) =>
    row.jsonKinds.includes(selector.jsonKind),
  );
}

function validateExtensionPoints(artifact, states, label) {
  ensure(Array.isArray(artifact.extensionPoints), `${label}: extensionPoints must be an array`);
  const seen = new Set();
  for (const [index, point] of artifact.extensionPoints.entries()) {
    const pointLabel = `${label}: extensionPoints[${index}]`;
    ensure(isObject(point), `${pointLabel} must be an object`);
    validateKeys(point, ["prefix", "note"], [], pointLabel);
    ensure(Array.isArray(point.prefix), `${pointLabel}.prefix must be an array`);
    point.prefix.forEach((segment, segmentIndex) =>
      validateSegment(segment, `${pointLabel}.prefix[${segmentIndex}]`),
    );
    ensure(
      typeof point.note === "string" && point.note.length > 0,
      `${pointLabel}.note must be non-empty`,
    );
    const key = point.prefix.map(segmentToken).join("\n");
    ensure(!seen.has(key), `${pointLabel}: duplicate extension prefix`);
    seen.add(key);
    ensure(
      resolveState(states, point.prefix) !== undefined,
      `${pointLabel}: prefix is not reachable in the automaton`,
    );
  }
}

function validateSelectors(artifact, sources, label) {
  ensure(Array.isArray(artifact.addedSelectors), `${label}: addedSelectors must be an array`);
  const selectors = new Map();
  for (const [index, selector] of artifact.addedSelectors.entries()) {
    const selectorLabel = `${label}: addedSelectors[${index}]`;
    ensure(isObject(selector), `${selectorLabel} must be an object`);
    validateKeys(
      selector,
      ["segments", "jsonKind", "tag", "evidence"],
      [],
      selectorLabel,
    );
    ensure(
      Array.isArray(selector.segments) && selector.segments.length > 0,
      `${selectorLabel}.segments must be a non-empty array`,
    );
    selector.segments.forEach((segment, segmentIndex) =>
      validateSegment(segment, `${selectorLabel}.segments[${segmentIndex}]`),
    );
    validateTagKind(selector.tag, selector.jsonKind, selectorLabel);
    ensure(
      Array.isArray(selector.evidence) &&
        selector.evidence.length > 0 &&
        new Set(selector.evidence).size === selector.evidence.length,
      `${selectorLabel}.evidence must be a non-empty set`,
    );
    for (const sourceId of selector.evidence) {
      ensure(
        typeof sourceId === "string" && sources.has(sourceId),
        `${selectorLabel}.evidence: unknown sourceId ${JSON.stringify(sourceId)}`,
      );
    }
    const selectorKey = `${selector.segments.map(segmentToken).join("\n")}\n${selector.jsonKind}`;
    ensure(!selectors.has(selectorKey), `${selectorLabel}: duplicate path and JSON kind`);
    selectors.set(selectorKey, selector);
  }
  return selectors;
}

function validateScope(scope, label) {
  ensure(isObject(scope), `${label}: scope must be an object`);
  if (scope.kind === "profile") {
    validateKeys(scope, ["kind"], [], label);
    return;
  }
  ensure(scope.kind === "issuers", `${label}: unsupported scope kind`);
  validateKeys(scope, ["kind", "issuerIds"], [], label);
  ensure(
    Array.isArray(scope.issuerIds) &&
      scope.issuerIds.length > 0 &&
      scope.issuerIds.every((issuerId) => typeof issuerId === "string" && issuerId.length > 0) &&
      new Set(scope.issuerIds).size === scope.issuerIds.length,
    `${label}: issuerIds must be a non-empty set of non-empty strings`,
  );
}

function validateArtifact(artifact, label) {
  ensure(isObject(artifact), `${label}: artifact must be an object`);
  validateKeys(
    artifact,
    [
      "format",
      "typeMapVersion",
      "recordType",
      "schemaVersion",
      "scope",
      "sourceSchemas",
      "extensionPoints",
      "addedSelectors",
      "coverage",
      "automaton",
    ],
    ["parentTypeMapId"],
    label,
  );
  ensure(artifact.format === "ROAX-TYPE-MAP/1", `${label}: unsupported artifact format`);
  parseSemver(artifact.typeMapVersion, label);
  ensure(
    typeof artifact.recordType === "string" && artifact.recordType.length > 0,
    `${label}: recordType must be non-empty`,
  );
  ensure(
    typeof artifact.schemaVersion === "string" && artifact.schemaVersion.length > 0,
    `${label}: schemaVersion must be non-empty`,
  );
  if (artifact.parentTypeMapId !== undefined) {
    ensure(
      typeof artifact.parentTypeMapId === "string" && TYPE_MAP_ID.test(artifact.parentTypeMapId),
      `${label}: invalid parentTypeMapId`,
    );
  }
  validateScope(artifact.scope, `${label}: scope`);
  const sources = validateSourceSchemas(artifact, label);
  const states = validateAutomaton(artifact, sources, label);
  validateExtensionPoints(artifact, states, label);
  const selectors = validateSelectors(artifact, sources, label);
  if (artifact.parentTypeMapId === undefined) {
    ensure(artifact.scope.kind === "profile", `${label}: base artifact scope must be profile`);
    ensure(
      artifact.addedSelectors.length === 0,
      `${label}: base artifact addedSelectors must be empty`,
    );
  } else {
    ensure(artifact.scope.kind === "issuers", `${label}: child artifact scope must select issuers`);
    ensure(
      artifact.addedSelectors.length > 0,
      `${label}: child artifact must add at least one selector`,
    );
  }
  return { sources, states, selectors };
}

function validateIssuerNarrowing(parentScope, childScope) {
  ensure(childScope.kind === "issuers", "child: extension scope must select issuers");
  if (parentScope.kind === "profile") {
    return;
  }
  const parentIssuers = new Set(parentScope.issuerIds);
  for (const issuerId of childScope.issuerIds) {
    ensure(
      parentIssuers.has(issuerId),
      `child: issuer ${issuerId} is outside the parent issuer scope`,
    );
  }
}

function buildSelectorTrie(selectors) {
  const root = { children: new Map(), terminals: new Map() };
  for (const selector of selectors.values()) {
    let node = root;
    for (const segment of selector.segments) {
      const token = segmentToken(segment);
      if (!node.children.has(token)) {
        node.children.set(token, { children: new Map(), terminals: new Map() });
      }
      node = node.children.get(token);
    }
    node.terminals.set(selector.jsonKind, selector);
  }
  return root;
}

function bindingMap(state) {
  return new Map((state.bindings ?? []).map((binding) => [binding.jsonKind, binding]));
}

function unresolvedRowIdentity(row) {
  return JSON.stringify([row.reason, row.sources]);
}

function unresolvedKindsByRow(state) {
  const rows = new Map();
  for (const row of state?.unresolved ?? []) {
    const rowKey = unresolvedRowIdentity(row);
    if (!rows.has(rowKey)) {
      rows.set(rowKey, new Set());
    }
    for (const jsonKind of row.jsonKinds) {
      rows.get(rowKey).add(jsonKind);
    }
  }
  return rows;
}

function bindingEvidenceIds(binding) {
  return new Set(binding.sources.map((reference) => sourceIdFromReference(reference, "binding")));
}

function validateLogicalAdditivity(
  parentStates,
  childStates,
  selectors,
  childSources,
  parentSources,
) {
  const trie = buildSelectorTrie(selectors);
  const trieIds = new WeakMap();
  let nextTrieId = 0;
  function trieId(node) {
    if (node === undefined) {
      return "none";
    }
    if (!trieIds.has(node)) {
      trieIds.set(node, nextTrieId);
      nextTrieId += 1;
    }
    return String(trieIds.get(node));
  }

  const materialized = new Set();
  const visited = new Set();
  const queue = [{ parentId: "s0", childId: "s0", trie }];

  while (queue.length > 0) {
    const item = queue.shift();
    const visitKey = `${item.parentId ?? "none"}\0${item.childId}\0${trieId(item.trie)}`;
    if (visited.has(visitKey)) {
      continue;
    }
    visited.add(visitKey);

    const parentState =
      item.parentId === undefined ? undefined : parentStates.get(item.parentId);
    const childState = childStates.get(item.childId);
    const parentBindings = parentState === undefined ? new Map() : bindingMap(parentState);
    const childBindings = bindingMap(childState);

    if (parentState !== undefined) {
      ensure(
        childState.structurallyUntypedObject === parentState.structurallyUntypedObject,
        `child: inherited structurallyUntypedObject marker changed at logical state ${item.parentId}`,
      );
    }

    for (const [jsonKind, parentBinding] of parentBindings) {
      ensure(
        childBindings.has(jsonKind),
        `child: inherited ${jsonKind} binding is missing at logical state ${item.parentId}`,
      );
      ensure(
        isDeepStrictEqual(childBindings.get(jsonKind), parentBinding),
        `child: inherited ${jsonKind} binding changed at logical state ${item.parentId}`,
      );
    }

    const parentUnresolved = unresolvedKindsByRow(parentState);
    const childUnresolved = unresolvedKindsByRow(childState);
    for (const [rowKey, jsonKinds] of childUnresolved) {
      for (const jsonKind of jsonKinds) {
        ensure(
          parentUnresolved.get(rowKey)?.has(jsonKind) === true,
          `child: unresolved ${jsonKind} row is not inherited at child state ${item.childId}`,
        );
      }
    }
    for (const [rowKey, jsonKinds] of parentUnresolved) {
      for (const jsonKind of jsonKinds) {
        ensure(
          childUnresolved.get(rowKey)?.has(jsonKind) === true || childBindings.has(jsonKind),
          `child: inherited unresolved ${jsonKind} row is dropped without a binding at logical state ${item.parentId}`,
        );
      }
    }

    for (const [jsonKind, childBinding] of childBindings) {
      if (parentBindings.has(jsonKind)) {
        continue;
      }
      const selector = item.trie?.terminals.get(jsonKind);
      ensure(
        selector !== undefined,
        `child: undeclared ${jsonKind} binding appears at child state ${item.childId}`,
      );
      ensure(
        selector.tag === childBinding.tag,
        `child: materialized tag does not match addedSelector at ${renderSegments(selector.segments)}`,
      );
      const bindingSources = bindingEvidenceIds(childBinding);
      ensure(
        selector.evidence.every((sourceId) => bindingSources.has(sourceId)),
        `child: materialized binding at ${renderSegments(selector.segments)} does not cite every evidence source`,
      );
      materialized.add(selector);
    }

    const parentTransitions =
      parentState === undefined ? new Map() : transitionMap(parentState);
    const childTransitions = transitionMap(childState);
    for (const token of parentTransitions.keys()) {
      ensure(
        childTransitions.has(token),
        `child: inherited transition ${token} is missing at logical state ${item.parentId}`,
      );
    }
    for (const [token, childTarget] of childTransitions) {
      const parentTarget = parentTransitions.get(token);
      const trieTarget = item.trie?.children.get(token);
      if (parentTarget === undefined) {
        ensure(
          trieTarget !== undefined,
          `child: extra transition ${token} is not a prefix of an addedSelector`,
        );
      }
      queue.push({
        parentId: parentTarget,
        childId: childTarget,
        trie: trieTarget,
      });
    }
  }

  for (const selector of selectors.values()) {
    ensure(
      materialized.has(selector),
      `child: addedSelector is not materialized at ${renderSegments(selector.segments)}`,
    );
    ensure(
      selector.evidence.some((sourceId) => !parentSources.has(sourceId)),
      `child: addedSelector at ${renderSegments(selector.segments)} cites no supplemental source`,
    );
    for (const sourceId of selector.evidence) {
      ensure(childSources.has(sourceId), `child: missing selector evidence source ${sourceId}`);
    }
  }
}

function validateExtension(parent, parentBytes, child) {
  const expectedParentId = artifactId(parentBytes);
  ensure(
    child.parentTypeMapId === expectedParentId,
    `child: parentTypeMapId does not identify the exact parent bytes; expected ${expectedParentId}`,
  );
  const parentValidated = validateArtifact(parent, "parent");
  const childValidated = validateArtifact(child, "child");

  ensure(child.recordType === parent.recordType, "child: recordType differs from parent");
  ensure(child.schemaVersion === parent.schemaVersion, "child: schemaVersion differs from parent");
  ensure(
    isDeepStrictEqual(child.extensionPoints, parent.extensionPoints),
    "child: extensionPoints must remain exactly equal to the parent",
  );
  ensure(child.addedSelectors.length > 0, "child: extension must add at least one selector");
  validateIssuerNarrowing(parent.scope, child.scope);

  const [parentMajor, parentMinor] = parseSemver(parent.typeMapVersion, "parent");
  const [childMajor, childMinor] = parseSemver(child.typeMapVersion, "child");
  ensure(childMajor === parentMajor, "child: additive extension must retain the parent semver major");
  ensure(
    childMinor > parentMinor,
    "child: additive extension must increment the parent semver minor",
  );

  for (const [sourceId, parentSource] of parentValidated.sources) {
    ensure(
      childValidated.sources.has(sourceId),
      `child: inherited source ${sourceId} is missing`,
    );
    ensure(
      isDeepStrictEqual(childValidated.sources.get(sourceId), parentSource),
      `child: inherited source ${sourceId} changed`,
    );
  }

  for (const selector of childValidated.selectors.values()) {
    ensure(
      parent.extensionPoints.some((point) =>
        extensionPointAdmits(point, selector, parentValidated.states),
      ),
      `child: addedSelector ${renderSegments(selector.segments)} lies outside every parent extensionPoint; ` +
        "an added selector must introduce a segment the parent does not declare at the prefix, " +
        "or name a direct child of the prefix that the parent leaves unresolved for the observed kind",
    );
    const parentState = resolveState(parentValidated.states, selector.segments);
    const parentBinding = parentState === undefined
      ? undefined
      : bindingMap(parentState).get(selector.jsonKind);
    ensure(
      parentBinding === undefined,
      `child: addedSelector ${renderSegments(selector.segments)} overlaps an inherited output`,
    );
    ensure(
      selector.evidence.some((sourceId) => !parentValidated.sources.has(sourceId)),
      `child: addedSelector ${renderSegments(selector.segments)} cites no supplemental source`,
    );
  }

  validateLogicalAdditivity(
    parentValidated.states,
    childValidated.states,
    childValidated.selectors,
    childValidated.sources,
    parentValidated.sources,
  );
}

function summarizeAutomaton(automaton) {
  const coverage = {
    concretePathCardinality: "infinite",
    states: automaton.states.length,
    keyTransitions: 0,
    indexTransitions: 0,
    resolvedOutputs: 0,
    unresolvedOutputStates: 0,
    structurallyUntypedObjectStates: 0,
    structurallyUntypedObjectSourceNodes: 0,
    byTag: {},
    byBasis: {},
    notes: ["Self-test fixture."],
  };
  for (const state of automaton.states) {
    coverage.keyTransitions += state.keys?.length ?? 0;
    coverage.indexTransitions += state.anyIndex === undefined ? 0 : 1;
    coverage.unresolvedOutputStates += state.unresolved === undefined ? 0 : 1;
    coverage.structurallyUntypedObjectStates +=
      state.structurallyUntypedObject === true ? 1 : 0;
    for (const binding of state.bindings ?? []) {
      coverage.resolvedOutputs += 1;
      coverage.byTag[String(binding.tag)] =
        (coverage.byTag[String(binding.tag)] ?? 0) + 1;
      for (const basis of binding.basis) {
        coverage.byBasis[basis] = (coverage.byBasis[basis] ?? 0) + 1;
      }
    }
  }
  return coverage;
}

function refreshCoverage(artifact) {
  artifact.coverage = summarizeAutomaton(artifact.automaton);
}

function testFixtures() {
  const baseSource = {
    sourceId: "base",
    kind: "content",
    uri: "https://example.invalid/base.json",
    digest: `sha256:${"00".repeat(32)}`,
  };
  const extensionSource = {
    sourceId: "supplement",
    kind: "content",
    uri: "https://example.invalid/supplement.json",
    digest: `sha256:${"11".repeat(32)}`,
  };
  const inheritedBinding = {
    jsonKind: "string",
    tag: 2,
    basis: ["schema-type"],
    sources: ["base#/properties/known"],
  };
  const inheritedUnresolved = {
    jsonKinds: ["number"],
    reason: "The base schema does not choose one numeric ROAX tag.",
    sources: ["base#/properties/known"],
  };
  const parent = {
    format: "ROAX-TYPE-MAP/1",
    typeMapVersion: "1.0.0",
    recordType: "example.record",
    schemaVersion: "opaque-v1",
    scope: { kind: "profile" },
    sourceSchemas: [baseSource],
    extensionPoints: [{ prefix: [], note: "The root permits reviewed issuer additions." }],
    addedSelectors: [],
    coverage: {},
    automaton: {
      representation: "structured-path-dfa/1",
      start: "s0",
      states: [
        { id: "s0", keys: [{ key: "known", to: "s1" }] },
        {
          id: "s1",
          bindings: [inheritedBinding],
          unresolved: [inheritedUnresolved],
          structurallyUntypedObject: true,
        },
      ],
    },
  };
  refreshCoverage(parent);
  parent.coverage.structurallyUntypedObjectSourceNodes = 1;
  const child = {
    format: "ROAX-TYPE-MAP/1",
    typeMapVersion: "1.1.0",
    recordType: parent.recordType,
    schemaVersion: parent.schemaVersion,
    parentTypeMapId: artifactId(artifactBytes(parent)),
    scope: { kind: "issuers", issuerIds: ["did:example:issuer"] },
    sourceSchemas: [baseSource, extensionSource],
    extensionPoints: structuredClone(parent.extensionPoints),
    addedSelectors: [
      {
        segments: [{ key: "extra" }],
        jsonKind: "string",
        tag: 2,
        evidence: ["supplement"],
      },
      {
        segments: [{ key: "known" }],
        jsonKind: "number",
        tag: 3,
        evidence: ["supplement"],
      },
    ],
    coverage: {},
    automaton: {
      representation: "structured-path-dfa/1",
      start: "s0",
      states: [
        {
          id: "s0",
          keys: [
            { key: "extra", to: "s1" },
            { key: "known", to: "s2" },
          ],
        },
        {
          id: "s1",
          bindings: [
            {
              jsonKind: "string",
              tag: 2,
              basis: ["profile-ruling"],
              sources: ["supplement#/properties/extra"],
            },
          ],
        },
        {
          id: "s2",
          bindings: [
            {
              jsonKind: "number",
              tag: 3,
              basis: ["profile-ruling"],
              sources: ["supplement#/properties/known"],
            },
            structuredClone(inheritedBinding),
          ],
          structurallyUntypedObject: true,
        },
      ],
    },
  };
  refreshCoverage(child);
  child.coverage.structurallyUntypedObjectSourceNodes = 1;
  return { parent, child };
}

function expectReject(name, pattern, mutate, beforeParentId) {
  const fixtures = testFixtures();
  if (beforeParentId !== undefined) {
    beforeParentId(fixtures.parent, fixtures.child);
  }
  fixtures.child.parentTypeMapId = artifactId(artifactBytes(fixtures.parent));
  mutate(fixtures.parent, fixtures.child);
  try {
    validateExtension(fixtures.parent, artifactBytes(fixtures.parent), fixtures.child);
  } catch (error) {
    ensure(
      pattern.test(error.message),
      `self-test ${name}: unexpected rejection: ${error.message}`,
    );
    return;
  }
  fail(`self-test ${name}: invalid extension was accepted`);
}

function expectAccept(name, mutate, beforeParentId) {
  const fixtures = testFixtures();
  if (beforeParentId !== undefined) {
    beforeParentId(fixtures.parent, fixtures.child);
  }
  fixtures.child.parentTypeMapId = artifactId(artifactBytes(fixtures.parent));
  mutate(fixtures.parent, fixtures.child);
  try {
    validateExtension(fixtures.parent, artifactBytes(fixtures.parent), fixtures.child);
  } catch (error) {
    fail(`self-test ${name}: valid extension was rejected: ${error.message}`);
  }
}

function expectParseReject(name, bytes, pattern) {
  try {
    parseArtifactBytes(bytes, `self-test ${name}`);
  } catch (error) {
    ensure(
      pattern.test(error.message),
      `self-test ${name}: unexpected parser rejection: ${error.message}`,
    );
    return;
  }
  fail(`self-test ${name}: invalid artifact bytes were accepted`);
}

function selfTest() {
  const valid = testFixtures();
  const parentBytes = artifactBytes(valid.parent);
  const childBytes = artifactBytes(valid.child);
  validateExtension(
    parseArtifactBytes(parentBytes, "self-test parent"),
    parentBytes,
    parseArtifactBytes(childBytes, "self-test child"),
  );

  expectParseReject(
    "duplicate top-level member",
    Buffer.from('{"format":"first","format":"second"}\n', "utf8"),
    /duplicate JSON object member "format"/,
  );
  expectParseReject(
    "duplicate escaped nested member",
    Buffer.from(String.raw`{"outer":{"key":1,"\u006bey":2}}`, "utf8"),
    /duplicate JSON object member "key"/,
  );
  expectParseReject(
    "malformed UTF-8",
    Buffer.from([0x7b, 0x22, 0x78, 0x22, 0x3a, 0xc3, 0x28, 0x7d]),
    /invalid UTF-8/,
  );
  expectParseReject(
    "unpaired surrogate value",
    Buffer.from(String.raw`{"value":"\ud800"}`, "utf8"),
    /unpaired high surrogate/,
  );
  expectParseReject(
    "unpaired surrogate member name",
    Buffer.from(String.raw`{"\udc00":true}`, "utf8"),
    /unpaired low surrogate in object member name/,
  );
  const pairedSurrogates = parseArtifactBytes(
    Buffer.from(String.raw`{"\ud83d\ude00":"\ud83d\ude80"}`, "utf8"),
    "self-test paired surrogates",
  );
  ensure(
    pairedSurrogates["😀"] === "🚀",
    "self-test paired surrogates: valid surrogate pairs were not preserved",
  );

  expectReject(
    "wrong parent ID",
    /parentTypeMapId does not identify/,
    (_parent, child) => {
      child.parentTypeMapId = `sha256:${"ff".repeat(32)}`;
    },
  );
  expectReject(
    "same semver minor",
    /increment the parent semver minor/,
    (_parent, child) => {
      child.typeMapVersion = "1.0.1";
    },
  );
  expectReject(
    "profile scope",
    /child artifact scope must select issuers/,
    (_parent, child) => {
      child.scope = { kind: "profile" };
    },
  );
  expectReject(
    "issuer scope widening",
    /outside the parent issuer scope/,
    (_parent, child) => {
      child.scope = { kind: "issuers", issuerIds: ["did:example:other"] };
    },
    (parent) => {
      parent.parentTypeMapId = `sha256:${"22".repeat(32)}`;
      parent.scope = { kind: "issuers", issuerIds: ["did:example:issuer"] };
      parent.addedSelectors = [
        {
          segments: [{ key: "known" }],
          jsonKind: "string",
          tag: 2,
          evidence: ["base"],
        },
      ];
    },
  );
  expectReject(
    "parent binding override",
    /inherited string binding changed/,
    (_parent, child) => {
      child.automaton.states[2].bindings[1].basis = ["profile-ruling"];
      refreshCoverage(child);
      child.coverage.structurallyUntypedObjectSourceNodes = 1;
    },
  );
  expectReject(
    "inherited structural marker removal",
    /inherited structurallyUntypedObject marker changed/,
    (_parent, child) => {
      delete child.automaton.states[2].structurallyUntypedObject;
      refreshCoverage(child);
      child.coverage.structurallyUntypedObjectSourceNodes = 1;
    },
  );
  expectReject(
    "undeclared transition",
    /not a prefix of an addedSelector/,
    (_parent, child) => {
      child.addedSelectors = child.addedSelectors.slice(1);
    },
  );
  expectReject(
    "outside extension point",
    /outside every parent extensionPoint/,
    () => {},
    (parent, child) => {
      parent.extensionPoints = [
        { prefix: [{ key: "known" }], note: "Only the known path is extensible." },
      ];
      child.extensionPoints = structuredClone(parent.extensionPoints);
    },
  );
  expectReject(
    "descendant of a declared path",
    /outside every parent extensionPoint/,
    (parent, child) => {
      child.addedSelectors = [
        {
          segments: [{ key: "known" }, { key: "extra" }],
          jsonKind: "string",
          tag: 2,
          evidence: ["supplement"],
        },
      ];
      child.automaton.states = [
        { id: "s0", keys: [{ key: "known", to: "s1" }] },
        {
          id: "s1",
          keys: [{ key: "extra", to: "s2" }],
          bindings: structuredClone(parent.automaton.states[1].bindings),
          unresolved: structuredClone(parent.automaton.states[1].unresolved),
          structurallyUntypedObject: true,
        },
        {
          id: "s2",
          bindings: [
            {
              jsonKind: "string",
              tag: 2,
              basis: ["profile-ruling"],
              sources: ["supplement#/properties/extra"],
            },
          ],
        },
      ];
      refreshCoverage(child);
      child.coverage.structurallyUntypedObjectSourceNodes = 1;
    },
  );
  expectReject(
    "declared child with no unresolved output",
    /outside every parent extensionPoint/,
    () => {},
    (parent) => {
      delete parent.automaton.states[1].unresolved;
      refreshCoverage(parent);
      parent.coverage.structurallyUntypedObjectSourceNodes = 1;
    },
  );
  expectReject(
    "unresolved row added at an inherited state",
    /unresolved boolean row is not inherited/,
    (_parent, child) => {
      child.automaton.states[2].unresolved = [
        {
          jsonKinds: ["boolean"],
          reason: "The issuer asserts a further gap.",
          sources: ["supplement"],
        },
      ];
      refreshCoverage(child);
      child.coverage.structurallyUntypedObjectSourceNodes = 1;
    },
  );
  expectReject(
    "unresolved row added in an issuer-introduced subtree",
    /unresolved boolean row is not inherited/,
    (_parent, child) => {
      child.automaton.states[1].unresolved = [
        {
          jsonKinds: ["boolean"],
          reason: "The issuer asserts a further gap.",
          sources: ["supplement"],
        },
      ];
      refreshCoverage(child);
      child.coverage.structurallyUntypedObjectSourceNodes = 1;
    },
  );
  expectReject(
    "inherited unresolved row restated with issuer evidence",
    /unresolved number row is not inherited/,
    (_parent, child) => {
      child.automaton.states[2].bindings = [
        structuredClone(child.automaton.states[2].bindings[1]),
      ];
      child.automaton.states[2].unresolved = [
        {
          jsonKinds: ["number"],
          reason: "The base schema does not choose one numeric ROAX tag.",
          sources: ["supplement"],
        },
      ];
      child.addedSelectors = child.addedSelectors.slice(0, 1);
      refreshCoverage(child);
      child.coverage.structurallyUntypedObjectSourceNodes = 1;
    },
  );
  for (const collision of [
    {
      name: "sourceId containing a comma impersonates a two-source row",
      parentSources: ["alpha", "beta"],
      parentReason: "The base schema does not choose one numeric ROAX tag.",
      childSources: ["alpha,beta"],
      childReason: "The base schema does not choose one numeric ROAX tag.",
    },
    {
      name: "newline in a sourceId impersonates a newline in the reason",
      parentSources: ["gamma\ndelta"],
      parentReason: "The base schema does not choose one numeric ROAX tag.",
      childSources: ["delta"],
      childReason: "The base schema does not choose one numeric ROAX tag.\ngamma",
    },
  ]) {
    expectReject(
      collision.name,
      /unresolved number row is not inherited/,
      (_parent, child) => {
        child.addedSelectors = child.addedSelectors.slice(0, 1);
        child.automaton.states[2].bindings = [
          structuredClone(child.automaton.states[2].bindings[1]),
        ];
        child.automaton.states[2].unresolved = [
          {
            jsonKinds: ["number"],
            reason: collision.childReason,
            sources: collision.childSources,
          },
        ];
        refreshCoverage(child);
        child.coverage.structurallyUntypedObjectSourceNodes = 1;
      },
      (parent, child) => {
        const declare = (sourceIds, digestByte) =>
          sourceIds.map((sourceId) => ({
            sourceId,
            kind: "content",
            uri: "https://example.invalid/gap-evidence.json",
            digest: `sha256:${digestByte.repeat(32)}`,
          }));
        parent.sourceSchemas = [
          ...parent.sourceSchemas,
          ...declare(collision.parentSources, "44"),
        ];
        parent.automaton.states[1].unresolved = [
          {
            jsonKinds: ["number"],
            reason: collision.parentReason,
            sources: collision.parentSources,
          },
        ];
        refreshCoverage(parent);
        parent.coverage.structurallyUntypedObjectSourceNodes = 1;
        child.sourceSchemas = [
          ...parent.sourceSchemas,
          ...child.sourceSchemas.filter((source) => source.sourceId === "supplement"),
          ...declare(
            collision.childSources.filter(
              (sourceId) => !collision.parentSources.includes(sourceId),
            ),
            "55",
          ),
        ];
      },
    );
  }
  expectReject(
    "inherited unresolved row dropped without a binding",
    /inherited unresolved number row is dropped without a binding/,
    (_parent, child) => {
      child.automaton.states[2].bindings = [
        structuredClone(child.automaton.states[2].bindings[1]),
      ];
      child.addedSelectors = child.addedSelectors.slice(0, 1);
      refreshCoverage(child);
      child.coverage.structurallyUntypedObjectSourceNodes = 1;
    },
  );
  expectAccept("undeclared subtree descendant", (_parent, child) => {
    child.addedSelectors[0] = {
      segments: [{ key: "extra" }, { key: "deep" }],
      jsonKind: "string",
      tag: 2,
      evidence: ["supplement"],
    };
    child.automaton.states[1] = { id: "s1", keys: [{ key: "deep", to: "s3" }] };
    child.automaton.states.push({
      id: "s3",
      bindings: [
        {
          jsonKind: "string",
          tag: 2,
          basis: ["profile-ruling"],
          sources: ["supplement#/properties/extra/properties/deep"],
        },
      ],
    });
    refreshCoverage(child);
    child.coverage.structurallyUntypedObjectSourceNodes = 1;
  });
  expectReject(
    "BLOB_REF",
    /BLOB_REF tag 8/,
    (_parent, child) => {
      child.addedSelectors[0].tag = 8;
      child.automaton.states[1].bindings[0].tag = 8;
      refreshCoverage(child);
      child.coverage.structurallyUntypedObjectSourceNodes = 1;
    },
  );
  expectReject(
    "missing evidence source",
    /unknown sourceId/,
    (_parent, child) => {
      child.addedSelectors[0].evidence = ["missing"];
    },
  );
  expectReject(
    "parent-only evidence",
    /no supplemental source/,
    (_parent, child) => {
      child.addedSelectors[0].evidence = ["base"];
    },
  );
  expectReject(
    "binding evidence disconnect",
    /does not cite every evidence source/,
    (_parent, child) => {
      child.automaton.states[1].bindings[0].sources = ["base"];
    },
  );
  expectReject(
    "partially cited evidence",
    /does not cite every evidence source/,
    (_parent, child) => {
      child.sourceSchemas.push({
        sourceId: "second-supplement",
        kind: "content",
        uri: "https://example.invalid/second-supplement.json",
        digest: `sha256:${"33".repeat(32)}`,
      });
      child.addedSelectors[0].evidence.push("second-supplement");
    },
  );
  expectReject(
    "unknown carrier property",
    /unexpected property ignored/,
    (_parent, child) => {
      child.ignored = true;
    },
  );
  expectReject(
    "stale coverage",
    /stale coverage\.states/,
    (_parent, child) => {
      child.coverage.states += 1;
    },
  );
  expectReject(
    "non-canonical transitions",
    /KEY transitions must be UTF-8 sorted/,
    (_parent, child) => {
      child.automaton.states[0].keys.reverse();
    },
  );
  expectReject(
    "unreachable state",
    /unreachable state/,
    (_parent, child) => {
      child.automaton.states.push({ id: "s3" });
      refreshCoverage(child);
      child.coverage.structurallyUntypedObjectSourceNodes = 1;
    },
  );
  process.stdout.write("validated type-map extension self-tests\n");
}

function main() {
  const args = process.argv.slice(2);
  if (args.length === 1 && args[0] === "--self-test") {
    selfTest();
    return;
  }
  if (args.length !== 2) {
    fail(
      "usage: node tools/check-type-map-extension.mjs <parent-artifact.json> <child-artifact.json>\n" +
        "       node tools/check-type-map-extension.mjs --self-test",
    );
  }
  const parent = parseArtifact(args[0]);
  const child = parseArtifact(args[1]);
  validateExtension(parent.artifact, parent.bytes, child.artifact);
  process.stdout.write(
    `validated ${artifactId(child.bytes)} as an additive extension of ${artifactId(parent.bytes)}\n`,
  );
}

export { artifactBytes, artifactId, parseArtifactBytes, testFixtures, validateArtifact };

function isDirectInvocation() {
  if (process.argv[1] === undefined) {
    return false;
  }
  const modulePath = fileURLToPath(import.meta.url);
  try {
    return realpathSync(process.argv[1]) === realpathSync(modulePath);
  } catch {
    return resolve(process.argv[1]) === modulePath;
  }
}

if (isDirectInvocation()) {
  try {
    main();
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  }
}
