// Envelope verification for implementation B: sections 7.3, 10, 10.2, 11 and 11.2.
//
// Written from the specification text alongside envelope.py rather than ported from it. The
// reason codes are shared vocabulary and are the one thing both sides had to agree on in
// advance, because the corpus records them; everything that produces a code was derived here
// independently.

import fs from "node:fs";
import path from "node:path";

import * as ref from "./roax_ref.mjs";

// Section 10.2. Transcribed from docs/profiles/, one row per document. roax.issuer.keyId is
// committed inside the root but OPTIONAL to disclose and MUST NOT appear here: requiring it
// would permanently bind an anchored record to the key it was issued under, leaving a holder
// whose issuer has rotated keys with no path at all (section 12.2).
export const PROFILE_FLOORS = {
  "hl7.fhir.bundle": ["resourceType"],
  "sg.gov.moh.pdt-healthcert": ["version", "type", "validFrom"],
  "sg.gov.moh.recovery-healthcert": ["version", "type", "validFrom", "validUntil"],
  "sg.gov.moh.vaccination-healthcert": ["validFrom", "notarisationMetadata.reference"],
  "org.roax.corpus.synthetic": ["marker"],
};

// Section 7.4 H3. A verifier rejects any hashAlg absent from its OWN allow-list. ROAX-CANON/1
// defines a construction for SHA-256 only, so a v1 verifier allows exactly that.
export const ALLOWED_HASH_ALGS = ["SHA-256"];

export const RESERVED_FLOOR = [...ref.RESERVED_DISCLOSURE_FLOOR];

// The envelope is read with the same literal-preserving scanner a record is (section 7.3), so
// these accessors work on RecordMap/NumberLiteral rather than on plain objects.

function has(node, key) {
  if (node instanceof ref.RecordMap) return node.entries.some(([k]) => k === key);
  return node !== null && typeof node === "object" && Object.prototype.hasOwnProperty.call(node, key);
}

function get(node, key) {
  if (node instanceof ref.RecordMap) {
    for (const [k, v] of node.entries) if (k === key) return v;
    return undefined;
  }
  if (node !== null && typeof node === "object") return node[key];
  return undefined;
}

function asInt(node) {
  if (node instanceof ref.NumberLiteral) return Number.parseInt(node.text, 10);
  if (Number.isInteger(node)) return node;
  throw new ref.RoaxError("envelope-field-not-an-integer", String(node));
}

function segmentsOf(node) {
  const out = [];
  for (const seg of node || []) {
    if (has(seg, "key")) out.push({ key: get(seg, "key") });
    else if (has(seg, "index")) out.push({ index: asInt(get(seg, "index")) });
    else throw new ref.RoaxError("segment-malformed", "");
  }
  return out;
}

// A comparison key over DECODED segments. Never a rendered display string (section 5.2).
function pathKey(segments) {
  return JSON.stringify(segments.map((s) => (has(s, "key") ? ["k", ref.nfc(s.key)] : ["i", s.index])));
}

function floorFor(recordType) {
  const profile = PROFILE_FLOORS[recordType];
  if (profile === undefined) return null;
  return [...RESERVED_FLOOR, ...profile].map((p) => [{ key: p }]);
}

export function verify(envelope, typeMaps) {
  try {
    return verifyInner(envelope, typeMaps);
  } catch (err) {
    if (err instanceof ref.RoaxError) return [false, err.code];
    throw err;
  }
}

function verifyInner(envelope, typeMaps) {
  for (const field of ["canon", "hashAlg", "recordType", "schemaVersion", "recordId", "root",
    "leafCount", "issuer"]) {
    if (!has(envelope, field)) return [false, "envelope-missing-field"];
  }
  if (get(envelope, "canon") !== ref.CANON) return [false, "canon-unknown"];

  const hashAlg = get(envelope, "hashAlg");
  if (!ALLOWED_HASH_ALGS.includes(hashAlg)) return [false, "hash-alg-not-allowed"];

  // Section 7.3 rule 3.
  if (has(envelope, "masterSalt")) return [false, "master-salt-in-envelope"];

  const hasRecord = has(envelope, "record");
  const hasDisclosure = has(envelope, "disclosure");
  if (hasRecord && hasDisclosure) return [false, "record-and-disclosure-both-present"];
  if (!hasRecord && !hasDisclosure) return [false, "neither-record-nor-disclosure"];

  const recordType = get(envelope, "recordType");
  const floor = floorFor(recordType);
  // Section 12.2: an unknown profile fails closed with a stated reason, never a guess.
  if (floor === null) return [false, "profile-unknown"];

  const root = Buffer.from(get(envelope, "root"), "hex");
  const issuer = get(envelope, "issuer");
  const identity = {
    recordType,
    schemaVersion: get(envelope, "schemaVersion"),
    recordId: get(envelope, "recordId"),
    issuerId: get(issuer, "id"),
    issuerKeyId: get(issuer, "keyId"),
  };

  if (hasRecord) return verifyFull(envelope, hashAlg, root, identity, typeMaps);
  return verifyDisclosed(envelope, hashAlg, root, floor);
}

function verifyFull(envelope, hashAlg, root, identity, typeMaps) {
  // Section 7.3 rule 1. Without it a full copy has no route to any leaf hash.
  if (!has(envelope, "salts")) return [false, "full-copy-without-salts"];

  const typeMap = typeMaps[identity.recordType];
  if (typeMap === undefined) return [false, "type-map-missing"];

  const leafCount = asInt(get(envelope, "leafCount"));
  const saltEntries = get(envelope, "salts");

  // The reserved-namespace guard, duplicate-key rejection and fail-closed type-map lookup all
  // live inside buildTree, so this call is what makes class 15's reject row fire before
  // anything is compared against the root.
  const { leaves } = ref.buildTree(hashAlg, get(envelope, "record"), typeMap,
    Buffer.alloc(32), identity);

  // Section 11.1: a derived count disagreeing with the declared one MUST be a rejection.
  if (saltEntries.length !== leafCount) return [false, "salts-length-not-leaf-count"];
  if (leaves.length !== leafCount) return [false, "leaf-count-mismatch"];

  const supplied = new Map();
  for (const entry of saltEntries) {
    supplied.set(pathKey(segmentsOf(get(entry, "segments"))), Buffer.from(get(entry, "salt"), "hex"));
  }
  if (supplied.size !== leaves.length) return [false, "salts-duplicate-path"];

  const rebuilt = [];
  for (const leaf of leaves) {
    const salt = supplied.get(pathKey(leaf.segments));
    if (salt === undefined) return [false, "salt-missing-for-leaf"];
    rebuilt.push(ref.leafHash(hashAlg, leaf.segments, leaf.tag, leaf.value, salt));
  }
  if (!ref.mth(hashAlg, rebuilt).equals(root)) return [false, "root-mismatch"];
  return [true, "ok"];
}

function verifyDisclosed(envelope, hashAlg, root, floor) {
  // Sections 7.3 and 10.1: `salts` alongside `disclosure` is what would make a withheld leaf's
  // salt representable at all. Reject rather than repair.
  if (has(envelope, "salts")) return [false, "disclosed-copy-carries-salts"];

  const disclosure = get(envelope, "disclosure");
  if (get(disclosure, "mode") !== "selective") return [false, "disclosure-mode-unknown"];
  const leaves = get(disclosure, "leaves");
  if (!leaves || leaves.length === 0) return [false, "disclosure-empty"];

  const treeSize = asInt(get(envelope, "leafCount"));
  const seenPaths = new Set();
  const seenIndex = new Set();

  for (const entry of leaves) {
    for (const field of ["segments", "index", "tag", "salt", "auditPath"]) {
      if (!has(entry, field)) return [false, "disclosed-leaf-missing-field"];
    }
    const tag = asInt(get(entry, "tag"));
    const emptyTag = tag === ref.TAG.NULL || tag === ref.TAG.EMPTY_ARRAY || tag === ref.TAG.EMPTY_OBJECT;
    if (emptyTag && has(entry, "value")) return [false, "disclosed-leaf-value-present-for-empty-tag"];
    // A leaf NAMED with its value withheld, while its salt ships anyway: the class 17 leak
    // wearing a disclosure's clothes.
    if (!emptyTag && !has(entry, "value")) return [false, "disclosed-leaf-named-without-value"];

    const segments = segmentsOf(get(entry, "segments"));
    const key = pathKey(segments);
    if (seenPaths.has(key)) return [false, "disclosed-leaf-duplicate-path"];
    seenPaths.add(key);
    const index = asInt(get(entry, "index"));
    if (seenIndex.has(index)) return [false, "disclosed-leaf-duplicate-index"];
    seenIndex.add(index);

    const value = get(entry, "value");
    // A numeric carrier is a canonical numeric STRING, never a JSON number (section 6.4).
    if (value instanceof ref.NumberLiteral) return [false, "disclosed-leaf-numeric-carrier"];

    // Section 10 step 1: recompute the leaf from its fields. Never trust a supplied leaf hash.
    const leaf = ref.leafHash(hashAlg, segments, tag, value === undefined ? null : value,
      Buffer.from(get(entry, "salt"), "hex"));
    const auditPath = get(entry, "auditPath").map((h) => Buffer.from(h, "hex"));
    if (!ref.verifyInclusion(hashAlg, leaf, index, treeSize, auditPath, root)) {
      return [false, "inclusion-proof-failed"];
    }
  }

  // Section 10.2, the minimum-disclosure floor.
  for (const required of floor) {
    if (!seenPaths.has(pathKey(required))) return [false, "minimum-disclosure-floor"];
  }
  return [true, "ok"];
}

export function loadTypeMaps(dir) {
  const out = {};
  if (!fs.existsSync(dir)) return out;
  for (const name of fs.readdirSync(dir)) {
    if (!name.endsWith(".json")) continue;
    const doc = JSON.parse(fs.readFileSync(path.join(dir, name), "utf8"));
    out[doc.recordType] = new ref.TypeMap(doc);
  }
  return out;
}
