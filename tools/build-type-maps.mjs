#!/usr/bin/env node

import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import process from "node:process";

const REFERENCE_COMMIT = "09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa";
const REFERENCE_REPOSITORY = "https://github.com/Open-Attestation/schemata.git";
const TYPE_MAP_VERSION = "1.0.0";
const FORMAT = "ROAX-TYPE-MAP/1";
const ID_DOMAIN = Buffer.from("ROAX-TYPE-MAP/1\0", "utf8");

function compareUtf8(left, right) {
  return Buffer.compare(
    Buffer.from(left.normalize("NFC"), "utf8"),
    Buffer.from(right.normalize("NFC"), "utf8"),
  );
}

const TAG = Object.freeze({
  NULL: 0,
  BOOL: 1,
  STRING: 2,
  INTEGER: 3,
  DECIMAL: 4,
  BYTES: 5,
  EMPTY_ARRAY: 6,
  EMPTY_OBJECT: 7,
  BLOB_REF: 8,
});

const PROFILE_CONFIGS = [
  {
    recordType: "hl7.fhir.bundle",
    schemaVersion: "4.0.1",
    schema: "sg/gov/moh/fhir/4.0.1/schema.json",
    rootPointer: "#",
    output: "hl7.fhir.bundle-4.0.1.json",
    extensionPoints: [],
    coverageNotes: [
      "The root is the reference schema's 146-resource union, not only #/definitions/Bundle.",
      "The concrete path language is infinite because FHIR resources and extensions recurse.",
    ],
  },
  {
    recordType: "sg.gov.moh.pdt-healthcert",
    schemaVersion: "2.0",
    schema: "sg/gov/moh/pdt-healthcert/2.0/schema.json",
    rootPointer: "#",
    output: "sg.gov.moh.pdt-healthcert-2.0.json",
    extensionPoints: [
      {
        prefix: [],
        note: "The PDT root permits additional properties, but each added path still needs an issuer extension with type evidence.",
      },
    ],
    coverageNotes: [
      "Only the PDT base schema is normative for this base map.",
      "Clinic, endorsed, OpenAttestation and Notarise fields are proposals until the profile selects those composed schemas explicitly.",
    ],
  },
  {
    recordType: "sg.gov.moh.recovery-healthcert",
    schemaVersion: "2.0",
    schema: "sg/gov/moh/recovery-healthcert/2.0/schema.json",
    rootPointer: "#",
    output: "sg.gov.moh.recovery-healthcert-2.0.json",
    extensionPoints: [
      {
        prefix: [],
        note: "The recovery root permits additional properties, but each added path still needs an issuer extension with type evidence.",
      },
    ],
    coverageNotes: [
      "The copied PDT $id is ignored and this schema is loaded by file path.",
      "The concrete path language is infinite because its lite FHIR Bundle permits recursive resources and extensions.",
    ],
  },
  {
    recordType: "sg.gov.moh.vaccination-healthcert",
    schemaVersion: "1.0",
    schema: "sg/gov/moh/vaccination-healthcert/1.0/schema.json",
    rootPointer: "#",
    output: "sg.gov.moh.vaccination-healthcert-1.0.json",
    extensionPoints: [
      {
        prefix: [{ key: "issuers" }, { anyIndex: true }],
        note: "The issuer item omits additionalProperties: false.",
      },
      {
        prefix: [{ key: "$template" }],
        note: "The renderer object omits additionalProperties: false.",
      },
      {
        prefix: [
          { key: "fhirBundle" },
          { key: "entry" },
          { anyIndex: true },
          { key: "recommendation" },
          { anyIndex: true },
        ],
        note: "The recommendation item omits additionalProperties: false.",
      },
      {
        prefix: [
          { key: "fhirBundle" },
          { key: "entry" },
          { anyIndex: true },
          { key: "recommendation" },
          { anyIndex: true },
          { key: "dateCriterion" },
          { anyIndex: true },
        ],
        note: "The dateCriterion item omits additionalProperties: false.",
      },
      {
        prefix: [{ key: "notarisationMetadata" }],
        note: "The Notarise metadata object omits additionalProperties: false.",
      },
      {
        prefix: [
          { key: "notarisationMetadata" },
          { key: "signedEuHealthCerts" },
          { anyIndex: true },
        ],
        note: "Both signed EU certificate item branches omit additionalProperties: false.",
      },
    ],
    coverageNotes: [
      "fhirBundle.entry items use the flattened pseudo-FHIR layout and never gain a resource segment.",
      "Schema nodes with properties but no explicit object type contribute exact child transitions and authorize only the object observed kind; other schema-admitted kinds remain unbound.",
    ],
  },
];

function parseArgs(argv) {
  const args = {
    references: process.env.ROAX_REFERENCES,
    out: "type-maps",
    check: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--references") {
      args.references = argv[++index];
    } else if (arg === "--out") {
      args.out = argv[++index];
    } else if (arg === "--check") {
      args.check = true;
    } else if (arg === "--help") {
      process.stdout.write(
        "Usage: node tools/build-type-maps.mjs --references references/schemata [--out type-maps] [--check]\n" +
          "       node tools/build-type-maps.mjs --self-test\n",
      );
      process.exit(0);
    } else {
      throw new Error(`unknown argument: ${arg}`);
    }
  }
  if (!args.references) {
    throw new Error("--references or ROAX_REFERENCES is required");
  }
  return args;
}

function escapePointerPart(value) {
  return value.replaceAll("~", "~0").replaceAll("/", "~1");
}

function decodePointerPart(value) {
  return value.replaceAll("~1", "/").replaceAll("~0", "~");
}

function pointerGet(document, pointer) {
  if (pointer === "#" || pointer === "") {
    return document;
  }
  if (!pointer.startsWith("#/")) {
    throw new Error(`unsupported JSON Pointer: ${pointer}`);
  }
  let current = document;
  for (const encoded of pointer.slice(2).split("/")) {
    const part = decodePointerPart(encoded);
    if (current === null || typeof current !== "object" || !(part in current)) {
      throw new Error(`JSON Pointer does not resolve: ${pointer}`);
    }
    current = current[part];
  }
  return current;
}

class SchemaStore {
  constructor(referenceCheckout) {
    const checkout = resolve(referenceCheckout);
    const actualCommit = execFileSync("git", ["-C", checkout, "rev-parse", "HEAD"], {
      encoding: "utf8",
    }).trim();
    if (actualCommit !== REFERENCE_COMMIT) {
      throw new Error(
        `reference checkout is at ${actualCommit}; expected ${REFERENCE_COMMIT}`,
      );
    }
    this.srcRoot = existsSync(join(checkout, "src")) ? join(checkout, "src") : checkout;
    this.documents = new Map();
    this.nodeLocations = new WeakMap();
  }

  load(relativePath) {
    const normalized = relativePath.split("/").join(sep);
    const absolute = resolve(this.srcRoot, normalized);
    if (!absolute.startsWith(`${resolve(this.srcRoot)}${sep}`) && absolute !== resolve(this.srcRoot)) {
      throw new Error(`schema path escapes the reference checkout: ${relativePath}`);
    }
    if (!this.documents.has(absolute)) {
      const document = JSON.parse(readFileSync(absolute, "utf8"));
      this.documents.set(absolute, document);
      this.registerDocument(absolute, document);
    }
    return { absolute, document: this.documents.get(absolute) };
  }

  registerDocument(absolute, document) {
    const visit = (node, pointer) => {
      if (node === null || typeof node !== "object" || Array.isArray(node)) {
        return;
      }
      if (!this.nodeLocations.has(node)) {
        this.nodeLocations.set(node, { absolute, pointer });
      }
      for (const key of Object.keys(node).sort(compareUtf8)) {
        const value = node[key];
        if (value !== null && typeof value === "object") {
          if (Array.isArray(value)) {
            value.forEach((item, index) => visit(item, `${pointer}/${escapePointerPart(key)}/${index}`));
          } else {
            visit(value, `${pointer}/${escapePointerPart(key)}`);
          }
        }
      }
    };
    visit(document, "#");
  }

  location(node) {
    const location = this.nodeLocations.get(node);
    if (!location) {
      throw new Error("schema node has no registered location");
    }
    return location;
  }

  relativeSource(absolute, pointer = "") {
    const relativePath = relative(this.srcRoot, absolute).split(sep).join("/");
    return `references/schemata/src/${relativePath}${pointer === "#" ? "" : pointer}`;
  }

  resolveRef(fromNode, ref) {
    const from = this.location(fromNode);
    const [base, fragment = ""] = ref.split("#", 2);
    let targetAbsolute = from.absolute;
    if (base) {
      // These are fixed $ref-to-file mappings. Document $id values are never registered or read.
      if (base === "https://schema.openattestation.com/2.0/schema.json") {
        targetAbsolute = join(this.srcRoot, "__schema__/com/openattestation/2.0/schema.json");
      } else if (base.startsWith("https://schemata.openattestation.com/")) {
        targetAbsolute = join(
          this.srcRoot,
          base.slice("https://schemata.openattestation.com/".length),
        );
      } else {
        targetAbsolute = resolve(dirname(from.absolute), base);
      }
      const relativePath = relative(this.srcRoot, targetAbsolute).split(sep).join("/");
      this.load(relativePath);
    }
    const document = this.documents.get(resolve(targetAbsolute));
    if (!document) {
      throw new Error(`unloaded reference target: ${ref}`);
    }
    const pointer = fragment ? `#${fragment}` : "#";
    return pointerGet(document, pointer);
  }

  sourceSchemas() {
    return [...this.documents.keys()]
      .map((absolute) => {
        const sourceId = this.relativeSource(absolute);
        return {
          sourceId,
          kind: "git",
          repositoryUri: REFERENCE_REPOSITORY,
          path: sourceId.slice("references/schemata/".length),
          commit: REFERENCE_COMMIT,
        };
      })
      .sort((left, right) => compareUtf8(left.sourceId, right.sourceId));
  }
}

function classifyNode(store, node) {
  const { absolute, pointer } = store.location(node);
  const source = store.relativeSource(absolute, pointer);
  const definition = /^#\/definitions\/([^/]+)$/.exec(pointer)?.[1];
  const field = /\/properties\/([^/]+)(?:\/items)?$/.exec(pointer)?.[1];
  const fhirSemanticSource =
    source.startsWith("references/schemata/src/sg/gov/moh/fhir/4.0.1/") ||
    source.startsWith(
      "references/schemata/src/sg/gov/moh/vaccination-healthcert/1.0/schema.json#/definitions/",
    );

  if (fhirSemanticSource && definition === "base64Binary") {
    return {
      unresolved: true,
      jsonKinds: ["string"],
      source,
      reason:
        "FHIR base64Binary does not choose ROAX STRING over the base64 text or BYTES over decoded bytes.",
    };
  }
  if (node.type === "string") {
    return {
      jsonKind: "string",
      tag: TAG.STRING,
      basis: "schema-type",
      source,
    };
  }
  if (node.type === "boolean") {
    return {
      jsonKind: "boolean",
      tag: TAG.BOOL,
      basis: "schema-type",
      source,
    };
  }
  if (node.type === "null") {
    return {
      jsonKind: "null",
      tag: TAG.NULL,
      basis: "schema-type",
      source,
    };
  }
  if (node.type === "integer") {
    return {
      jsonKind: "number",
      tag: TAG.INTEGER,
      basis: "schema-type",
      source,
    };
  }
  if (node.type === "number") {
    if (fhirSemanticSource && definition === "decimal") {
      return {
        jsonKind: "number",
        tag: TAG.DECIMAL,
        basis: "fhir-named-primitive",
        source,
      };
    }
    if (
      fhirSemanticSource &&
      ["integer", "positiveInt", "unsignedInt"].includes(definition)
    ) {
      return {
        jsonKind: "number",
        tag: TAG.INTEGER,
        basis: "fhir-named-primitive",
        source,
      };
    }
    if (fhirSemanticSource && field?.endsWith("Decimal")) {
      return {
        jsonKind: "number",
        tag: TAG.DECIMAL,
        basis: "fhir-element-name",
        source,
      };
    }
    if (
      fhirSemanticSource &&
      /(Integer|PositiveInt|UnsignedInt)$/.test(field ?? "")
    ) {
      return {
        jsonKind: "number",
        tag: TAG.INTEGER,
        basis: "fhir-element-name",
        source,
      };
    }
    return {
      unresolved: true,
      jsonKinds: ["number"],
      source,
      reason: "JSON Schema type number does not choose ROAX INTEGER or DECIMAL.",
    };
  }
  if (Object.hasOwn(node, "const")) {
    if (typeof node.const === "string") {
      return {
        jsonKind: "string",
        tag: TAG.STRING,
        basis: "schema-const",
        source,
      };
    }
    if (typeof node.const === "boolean") {
      return {
        jsonKind: "boolean",
        tag: TAG.BOOL,
        basis: "schema-const",
        source,
      };
    }
    if (node.const === null) {
      return {
        jsonKind: "null",
        tag: TAG.NULL,
        basis: "schema-const",
        source,
      };
    }
    return {
      unresolved: true,
      jsonKinds: [typeof node.const === "number" ? "number" : "string"],
      source,
      reason: "The const value does not determine one supported ROAX tag.",
    };
  }
  if (Array.isArray(node.enum) && node.enum.length > 0) {
    const kinds = [
      ...new Set(
        node.enum.map((value) => {
          if (value === null) return "null";
          if (Array.isArray(value)) return "array";
          return typeof value;
        }),
      ),
    ];
    if (kinds.length === 1 && kinds[0] === "string") {
      return {
        jsonKind: "string",
        tag: TAG.STRING,
        basis: "schema-enum",
        source,
      };
    }
    if (kinds.length === 1 && kinds[0] === "boolean") {
      return {
        jsonKind: "boolean",
        tag: TAG.BOOL,
        basis: "schema-enum",
        source,
      };
    }
    return {
      unresolved: true,
      jsonKinds: kinds.map((kind) => (kind === "object" ? "object" : kind)),
      source,
      reason: "The enum does not determine one supported ROAX tag.",
    };
  }

  const hasCombinator = ["anyOf", "oneOf"].some((keyword) =>
    Array.isArray(node[keyword]),
  );
  if (
    node.properties ||
    node.type === "object" ||
    node.type === "array" ||
    node.items ||
    hasCombinator
  ) {
    return null;
  }
  return {
    unresolved: true,
    jsonKinds: ["string", "number", "boolean", "null", "object", "array"],
    source,
    reason: "The schema node has no JSON kind or semantic type constraint.",
  };
}

function admitsEmptyObject(node) {
  return (
    (!Array.isArray(node.required) || node.required.length === 0) &&
    (!Number.isInteger(node.minProperties) || node.minProperties === 0)
  );
}

function compileAutomaton(store, rootNode) {
  const close = (input) => {
    const stack = [...input];
    const closed = new Map();
    const expanded = new Set();
    while (stack.length > 0) {
      const node = stack.pop();
      if (node === null || typeof node !== "object" || Array.isArray(node)) {
        continue;
      }
      const { absolute, pointer } = store.location(node);
      const identity = store.relativeSource(absolute, pointer);
      if (expanded.has(identity)) {
        continue;
      }
      expanded.add(identity);
      if (typeof node.$ref === "string") {
        stack.push(store.resolveRef(node, node.$ref));
        continue;
      }
      if (Array.isArray(node.allOf)) {
        throw new Error(`${identity}: allOf requires intersection-aware compilation`);
      }
      const combinators = ["anyOf", "oneOf"].filter((keyword) =>
        Array.isArray(node[keyword]),
      );
      const hasDirectConstraint =
        node.type !== undefined ||
        node.properties !== undefined ||
        node.items !== undefined ||
        node.enum !== undefined ||
        Object.hasOwn(node, "const") ||
        node.required !== undefined ||
        node.minItems !== undefined ||
        node.minProperties !== undefined;
      if (combinators.length === 0 || hasDirectConstraint) {
        closed.set(identity, node);
      }
      for (const keyword of combinators) {
        stack.push(...node[keyword]);
      }
    }
    return [...closed.entries()].sort(([left], [right]) => compareUtf8(left, right));
  };

  const stateKey = (state) => state.map(([identity]) => identity).join("\n");
  const start = close([rootNode]);
  const queue = [start];
  const ids = new Map([[stateKey(start), 0]]);
  const built = [];
  let structurallyUntypedObjectStates = 0;
  const structurallyUntypedObjectSources = new Set();

  const intern = (state) => {
    const key = stateKey(state);
    if (!ids.has(key)) {
      ids.set(key, queue.length);
      queue.push(state);
    }
    return `s${ids.get(key)}`;
  };

  for (let index = 0; index < queue.length; index += 1) {
    const state = queue[index];
    const groups = new Map();
    const unresolved = [];
    const unresolvedKinds = new Set();

    for (const [, node] of state) {
      const classification = classifyNode(store, node);
      if (!classification) {
        continue;
      }
      if (classification.unresolved) {
        unresolved.push(classification);
        classification.jsonKinds.forEach((kind) => unresolvedKinds.add(kind));
        continue;
      }
      const groupKey = classification.jsonKind;
      if (!groups.has(groupKey)) {
        groups.set(groupKey, new Map());
      }
      const tags = groups.get(groupKey);
      if (!tags.has(classification.tag)) {
        tags.set(classification.tag, []);
      }
      tags.get(classification.tag).push(classification);
    }

    const objectSchemas = state.filter(([, node]) => node.properties);
    const structurallyUntypedObject = objectSchemas.some(
      ([, node]) => node.type !== "object",
    );
    if (structurallyUntypedObject) {
      structurallyUntypedObjectStates += 1;
      for (const [identity, node] of objectSchemas) {
        if (node.type !== "object") {
          structurallyUntypedObjectSources.add(identity);
        }
      }
    }
    const explicitArrays = state.filter(([, node]) => node.type === "array");
    const arrayEmptyPermissions = new Set(
      explicitArrays.map(
        ([, node]) => !Number.isInteger(node.minItems) || node.minItems === 0,
      ),
    );
    if (arrayEmptyPermissions.size > 1) {
      throw new Error(
        `state s${index} merges array branches that disagree on empty-array admission`,
      );
    }
    const objectEmptyPermissions = new Set(objectSchemas.map(([, node]) => admitsEmptyObject(node)));
    if (objectEmptyPermissions.size > 1) {
      throw new Error(
        `state s${index} merges object branches that disagree on empty-object admission`,
      );
    }
    const emptyObjectSchemas = objectSchemas.filter(([, node]) => admitsEmptyObject(node));
    const objectAllowsEmpty = emptyObjectSchemas.length > 0;
    const arrayAllowsEmpty =
      explicitArrays.length > 0 &&
      arrayEmptyPermissions.has(true);

    if (objectAllowsEmpty) {
      groups.set(
        "object",
        new Map([
          [
            TAG.EMPTY_OBJECT,
            emptyObjectSchemas.map(([, node]) => ({
              basis: "schema-container-type",
              source: store.relativeSource(
                store.location(node).absolute,
                store.location(node).pointer,
              ),
            })),
          ],
        ]),
      );
    }
    if (arrayAllowsEmpty) {
      groups.set(
        "array",
        new Map([
          [
            TAG.EMPTY_ARRAY,
            explicitArrays.map(([, node]) => ({
              basis: "schema-container-type",
              source: store.relativeSource(
                store.location(node).absolute,
                store.location(node).pointer,
              ),
            })),
          ],
        ]),
      );
    }

    const bindings = [];
    for (const [jsonKind, tags] of [...groups.entries()].sort(([left], [right]) =>
      compareUtf8(left, right),
    )) {
      if (unresolvedKinds.has(jsonKind)) {
        unresolved.push({
          unresolved: true,
          jsonKinds: [jsonKind],
          source: "(combined state)",
          reason: "A schema branch determines a tag while another reachable branch leaves it unresolved.",
        });
        continue;
      }
      if (tags.size !== 1) {
        const values = [...tags.keys()].join(", ");
        throw new Error(`tag conflict in state s${index} for ${jsonKind}: ${values}`);
      }
      const [tag, evidence] = [...tags.entries()][0];
      bindings.push({
        jsonKind,
        tag,
        basis: [...new Set(evidence.map((item) => item.basis))].sort(compareUtf8),
        sources: [...new Set(evidence.map((item) => item.source))].sort(compareUtf8),
      });
    }

    const propertyNodes = objectSchemas;
    const keyGroups = new Map();
    for (const [, node] of propertyNodes) {
      if (!node.properties || typeof node.properties !== "object") {
        continue;
      }
      for (const propertyName of Object.keys(node.properties)) {
        const key = propertyName.normalize("NFC");
        if (!keyGroups.has(key)) {
          keyGroups.set(key, { propertyNames: new Set(), nodes: [] });
        }
        const group = keyGroups.get(key);
        group.propertyNames.add(propertyName);
        group.nodes.push(node.properties[propertyName]);
      }
    }
    const keys = [...keyGroups.entries()]
      .sort(([left], [right]) => compareUtf8(left, right))
      .map(([key, group]) => {
        if (group.propertyNames.size > 1) {
          throw new Error(
            `state s${index} merges distinct property names that share the NFC key ` +
              `${JSON.stringify(key)}`,
          );
        }
        return { key, to: intern(close(group.nodes)) };
      });

    const itemNodes = explicitArrays
      .filter(([, node]) => node.items && typeof node.items === "object")
      .map(([, node]) => node.items);
    const anyIndex = itemNodes.length > 0 ? intern(close(itemNodes)) : undefined;

    const unresolvedRows = unresolved
      .map((item) => ({
        jsonKinds: [...new Set(item.jsonKinds)].sort(compareUtf8),
        reason: item.reason,
        sources: item.source === "(combined state)" ? [] : [item.source],
      }))
      .sort((left, right) => {
        const leftKey = `${left.jsonKinds.join(",")}\n${left.reason}\n${left.sources.join(",")}`;
        const rightKey = `${right.jsonKinds.join(",")}\n${right.reason}\n${right.sources.join(",")}`;
        return compareUtf8(leftKey, rightKey);
      });

    built.push({
      id: `s${index}`,
      ...(keys.length > 0 ? { keys } : {}),
      ...(anyIndex ? { anyIndex } : {}),
      ...(bindings.length > 0 ? { bindings } : {}),
      ...(unresolvedRows.length > 0 ? { unresolved: unresolvedRows } : {}),
      ...(structurallyUntypedObject ? { structurallyUntypedObject: true } : {}),
    });
  }

  return {
    automaton: {
      representation: "structured-path-dfa/1",
      start: "s0",
      states: built,
    },
    structurallyUntypedObjectStates,
    structurallyUntypedObjectSourceNodes: structurallyUntypedObjectSources.size,
  };
}

function summarizeAutomaton(automaton) {
  const summary = {
    states: automaton.states.length,
    keyTransitions: 0,
    indexTransitions: 0,
    resolvedOutputs: 0,
    unresolvedOutputStates: 0,
    byTag: {},
    byBasis: {},
  };
  for (const state of automaton.states) {
    summary.keyTransitions += state.keys?.length ?? 0;
    summary.indexTransitions += state.anyIndex ? 1 : 0;
    summary.unresolvedOutputStates += state.unresolved ? 1 : 0;
    for (const binding of state.bindings ?? []) {
      summary.resolvedOutputs += 1;
      summary.byTag[String(binding.tag)] = (summary.byTag[String(binding.tag)] ?? 0) + 1;
      for (const basis of binding.basis) {
        summary.byBasis[basis] = (summary.byBasis[basis] ?? 0) + 1;
      }
    }
  }
  return summary;
}

function artifactBytes(artifact) {
  return Buffer.from(`${JSON.stringify(artifact, null, 2)}\n`, "utf8");
}

function artifactId(bytes) {
  const digest = createHash("sha256").update(ID_DOMAIN).update(bytes).digest("hex");
  return `sha256:${digest}`;
}

function buildProfile(referenceCheckout, config) {
  const store = new SchemaStore(referenceCheckout);
  const { document } = store.load(config.schema);
  const rootNode = pointerGet(document, config.rootPointer);
  const {
    automaton,
    structurallyUntypedObjectStates,
    structurallyUntypedObjectSourceNodes,
  } = compileAutomaton(store, rootNode);
  const artifact = {
    format: FORMAT,
    typeMapVersion: TYPE_MAP_VERSION,
    recordType: config.recordType,
    schemaVersion: config.schemaVersion,
    scope: { kind: "profile" },
    sourceSchemas: store.sourceSchemas(),
    extensionPoints: config.extensionPoints,
    addedSelectors: [],
    coverage: {
      concretePathCardinality: "infinite",
      ...summarizeAutomaton(automaton),
      structurallyUntypedObjectSourceNodes,
      structurallyUntypedObjectStates,
      notes: config.coverageNotes,
    },
    automaton,
  };
  return { artifact, output: config.output };
}

class FixtureStore {
  constructor(document) {
    this.pointers = new WeakMap();
    const visit = (node, pointer) => {
      if (node === null || typeof node !== "object") {
        return;
      }
      if (Array.isArray(node)) {
        node.forEach((item, index) => visit(item, `${pointer}/${index}`));
        return;
      }
      if (!this.pointers.has(node)) {
        this.pointers.set(node, pointer);
      }
      for (const key of Object.keys(node)) {
        visit(node[key], `${pointer}/${escapePointerPart(key)}`);
      }
    };
    visit(document, "#");
  }

  location(node) {
    const pointer = this.pointers.get(node);
    if (pointer === undefined) {
      throw new Error("fixture node has no registered location");
    }
    return { absolute: "fixture", pointer };
  }

  relativeSource(absolute, pointer = "") {
    return `${absolute}${pointer === "#" ? "" : pointer}`;
  }

  resolveRef() {
    throw new Error("fixture schemas do not use $ref");
  }
}

function objectBranches(first, second) {
  return { properties: { value: { anyOf: [first, second] } } };
}

function expectCompileRejects(name, document, pattern) {
  try {
    compileAutomaton(new FixtureStore(document), document);
  } catch (error) {
    if (!pattern.test(error.message)) {
      throw new Error(`self-test ${name}: unexpected rejection: ${error.message}`);
    }
    return;
  }
  throw new Error(`self-test ${name}: disagreeing branches were accepted`);
}

function expectCompiles(name, document, expectedTag) {
  const { automaton } = compileAutomaton(new FixtureStore(document), document);
  const state = automaton.states.find(
    (candidate) => candidate.id === automaton.states[0].keys[0].to,
  );
  const tags = (state.bindings ?? []).map((binding) => binding.tag);
  if (!tags.includes(expectedTag)) {
    throw new Error(
      `self-test ${name}: expected tag ${expectedTag}, got ${JSON.stringify(tags)}`,
    );
  }
}

function selfTest() {
  expectCompileRejects(
    "object branches disagree on empty admission",
    objectBranches(
      { type: "object", properties: { a: { type: "string" } }, required: ["a"] },
      { type: "object", properties: { b: { type: "string" } } },
    ),
    /merges object branches that disagree on empty-object admission/,
  );
  expectCompileRejects(
    "object branches disagree through minProperties",
    objectBranches(
      { type: "object", properties: { a: { type: "string" } }, minProperties: 1 },
      { type: "object", properties: { b: { type: "string" } } },
    ),
    /merges object branches that disagree on empty-object admission/,
  );
  expectCompileRejects(
    "array branches disagree on empty admission",
    {
      properties: {
        value: {
          anyOf: [
            { type: "array", items: { type: "string" } },
            { type: "array", minItems: 1, items: { type: "string" } },
          ],
        },
      },
    },
    /merges array branches that disagree on empty-array admission/,
  );
  expectCompiles(
    "object branches agree that empty is admitted",
    objectBranches(
      { type: "object", properties: { a: { type: "string" } } },
      { type: "object", properties: { b: { type: "string" } } },
    ),
    TAG.EMPTY_OBJECT,
  );
  process.stdout.write("validated type-map generator self-tests\n");
}

function compareOrWrite(path, bytes, check) {
  if (check) {
    if (!existsSync(path)) {
      throw new Error(`missing generated file: ${path}`);
    }
    const current = readFileSync(path);
    if (!current.equals(bytes)) {
      throw new Error(`generated file is stale: ${path}`);
    }
    return;
  }
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, bytes);
}

function main() {
  const argv = process.argv.slice(2);
  if (argv.length === 1 && argv[0] === "--self-test") {
    selfTest();
    return;
  }
  const args = parseArgs(argv);
  const outputRoot = resolve(args.out);
  const registryRows = [];

  for (const config of PROFILE_CONFIGS) {
    const { artifact, output } = buildProfile(args.references, config);
    const bytes = artifactBytes(artifact);
    const path = join(outputRoot, output);
    compareOrWrite(path, bytes, args.check);
    registryRows.push({
      id: artifactId(bytes),
      path: `type-maps/${output}`,
      typeMapVersion: artifact.typeMapVersion,
      recordType: artifact.recordType,
      schemaVersion: artifact.schemaVersion,
      scope: artifact.scope,
    });
    process.stdout.write(
      `${args.check ? "checked" : "wrote"} ${path}: ${artifact.coverage.states} states, ` +
        `${artifact.coverage.resolvedOutputs} resolved outputs, ${registryRows.at(-1).id}\n`,
    );
  }

  registryRows.sort((left, right) => compareUtf8(left.recordType, right.recordType));
  const registry = {
    format: "ROAX-TYPE-MAP-REGISTRY/1",
    registryVersion: "1.0.0",
    idAlgorithm: {
      name: "sha256",
      preimage: "utf8(\"ROAX-TYPE-MAP/1\\u0000\") || exactArtifactBytes",
    },
    maps: registryRows,
  };
  compareOrWrite(
    join(outputRoot, "registry-1.0.0.json"),
    Buffer.from(`${JSON.stringify(registry, null, 2)}\n`, "utf8"),
    args.check,
  );
}

try {
  main();
} catch (error) {
  process.stderr.write(`${error.stack ?? error.message}\n`);
  process.exit(1);
}
