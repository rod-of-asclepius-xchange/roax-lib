// ROAX-CANON/1 reference implementation B, in JavaScript (Node ESM).
//
// This is corpus tooling, not roax-lib. It exists so that every expected value in
// corpus/conformance-corpus-1.0.json is computed twice, in two languages, and byte-compared.
// It was written from docs/spec/roax-canon-1.md rather than ported from roax_ref.py: the point
// of the exercise is to catch a transcription slip or a language-API divergence, and a port
// reproduces both faithfully.
//
// Deliberately plain .mjs: no package.json, no TypeScript, no dependencies. The repository does
// not host a TypeScript package and this must not look like the beginning of one.
//
// Section references are to docs/spec/roax-canon-1.md.

import { createHash } from "node:crypto";

export const CANON = "ROAX-CANON/1";

// Section 6.1.
export const TAG = {
  NULL: 0,
  BOOL: 1,
  STRING: 2,
  INTEGER: 3,
  DECIMAL: 4,
  BYTES: 5,
  EMPTY_ARRAY: 6,
  EMPTY_OBJECT: 7,
};
export const TAG_NAME = ["NULL", "BOOL", "STRING", "INTEGER", "DECIMAL", "BYTES", "EMPTY_ARRAY", "EMPTY_OBJECT"];

// Section 6.2. A fixed constant of ROAX-CANON/1, never implementation-chosen.
export const MAX_EXPANDED_DIGITS = 1024;
export const MAX_INDEX = 0xffffffff;

// Section 11.2. Each reserved path is one KEY segment carrying the literal dotted name.
export const RESERVED_PREFIX = "roax.";
export const RESERVED = {
  recordType: "roax.recordType",
  schemaVersion: "roax.schemaVersion",
  recordId: "roax.recordId",
  issuerId: "roax.issuer.id",
  issuerKeyId: "roax.issuer.keyId",
};
// Section 10.2. roax.issuer.keyId is committed but OPTIONAL to disclose and is not in the floor.
export const RESERVED_DISCLOSURE_FLOOR = [
  RESERVED.recordType,
  RESERVED.schemaVersion,
  RESERVED.recordId,
  RESERVED.issuerId,
];

export class RoaxError extends Error {
  constructor(code, detail = "") {
    super(detail ? `${code}: ${detail}` : code);
    this.code = code;
    this.detail = detail;
  }
}

// -------------------------------------------------------------------------------------------
// Hash agility (sections 7.4, 8, 9)
// -------------------------------------------------------------------------------------------

export function domain(hashAlg) {
  // Poseidon-BN254 is registered in the envelope schema, but ROAX-CANON/1 pins no field, rate,
  // capacity, round constants or byte-string-to-field-element encoding for it (section 7.4).
  if (hashAlg !== "SHA-256") throw new RoaxError("hash-alg-not-defined", hashAlg);
  return Buffer.from(`${CANON}/${hashAlg}`, "ascii");
}

export function H(hashAlg, data) {
  if (hashAlg !== "SHA-256") throw new RoaxError("hash-alg-not-defined", hashAlg);
  return createHash("sha256").update(data).digest();
}

export function u32be(n) {
  if (!Number.isInteger(n) || n < 0 || n > 0xffffffff) throw new RoaxError("u32-out-of-range", String(n));
  const b = Buffer.alloc(4);
  b.writeUInt32BE(n, 0);
  return b;
}

export function u64be(n) {
  const v = BigInt(n);
  if (v < 0n || v > 0xffffffffffffffffn) throw new RoaxError("u64-out-of-range", String(n));
  const b = Buffer.alloc(8);
  b.writeBigUInt64BE(v, 0);
  return b;
}

// -------------------------------------------------------------------------------------------
// Strings (sections 3.2, 6.1)
// -------------------------------------------------------------------------------------------

// Section 3.2 and 6.1. A JavaScript string is UTF-16 and can hold a lone surrogate, so the
// rejection is explicit here or this implementation admits input Rust cannot represent.
export function rejectUnpairedSurrogates(s) {
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff) {
      const next = i + 1 < s.length ? s.charCodeAt(i + 1) : -1;
      if (next < 0xdc00 || next > 0xdfff) throw new RoaxError("unpaired-surrogate", hexCodeUnit(c));
      i++;
    } else if (c >= 0xdc00 && c <= 0xdfff) {
      throw new RoaxError("unpaired-surrogate", hexCodeUnit(c));
    }
  }
}

function hexCodeUnit(c) {
  return "U+" + c.toString(16).toUpperCase().padStart(4, "0");
}

// Section 6.1. Surrogate rejection happens BEFORE normalization.
export function nfc(s) {
  rejectUnpairedSurrogates(s);
  return s.normalize("NFC");
}

// -------------------------------------------------------------------------------------------
// Path encoding (section 5)
// -------------------------------------------------------------------------------------------

export function encodePath(segments) {
  const parts = [u32be(segments.length)];
  for (const seg of segments) {
    if (Object.prototype.hasOwnProperty.call(seg, "key")) {
      const bytes = Buffer.from(nfc(seg.key), "utf8");
      parts.push(Buffer.from([0x01]), u32be(bytes.length), bytes);
    } else if (Object.prototype.hasOwnProperty.call(seg, "index")) {
      const i = seg.index;
      if (!Number.isInteger(i)) throw new RoaxError("index-not-integer", String(i));
      if (i < 0) throw new RoaxError("index-negative", String(i));
      // Section 5: MUST error rather than truncate.
      if (i > MAX_INDEX) throw new RoaxError("index-out-of-32-bit-range", String(i));
      parts.push(Buffer.from([0x02]), u32be(i));
    } else {
      throw new RoaxError("segment-malformed", JSON.stringify(seg));
    }
  }
  return Buffer.concat(parts);
}

// Section 5.2. Display only. Never hashed, never parsed back into segments.
export function displayPath(segments) {
  let out = "";
  for (const seg of segments) {
    if (Object.prototype.hasOwnProperty.call(seg, "key")) out += (out ? "." : "") + seg.key;
    else out += `[${seg.index}]`;
  }
  return out;
}

// -------------------------------------------------------------------------------------------
// Numbers (section 6.2)
// -------------------------------------------------------------------------------------------

const INTEGER_GRAMMAR = /^-?(0|[1-9][0-9]*)$/;
const DECIMAL_INPUT_GRAMMAR = /^(-?)(0|[1-9][0-9]*)(?:\.([0-9]+))?(?:[eE]([+-]?[0-9]+))?$/;
const DECIMAL_OUTPUT_GRAMMAR = /^-?(0|[1-9][0-9]*)(\.[0-9]+)?$/;
const HEX_BYTES = /^([0-9a-f]{2})*$/;

// Section 6.2. Arbitrary precision, held as a string, never parsed into a machine integer.
export function canonicalInteger(text) {
  if (typeof text !== "string") throw new RoaxError("integer-not-carried-as-string", String(text));
  if (!INTEGER_GRAMMAR.test(text)) throw new RoaxError("integer-grammar", text);
  const digits = text.startsWith("-") ? text.slice(1) : text;
  // The 1024-digit bound is written under the decimal subsection, but its justification counts
  // class 2's 40-digit INTEGER against it. Applied to both; no corpus vector discriminates.
  if (digits.length > MAX_EXPANDED_DIGITS) throw new RoaxError("digit-bound-exceeded", String(digits.length));
  return text === "-0" ? "0" : text;
}

// Section 6.2. Arbitrary precision, held as a string, never parsed into a float. Canonicalization
// does only two things: expand the exponent, and drop the sign of a zero-valued magnitude.
export function canonicalDecimal(text) {
  if (typeof text !== "string") throw new RoaxError("decimal-not-carried-as-string", String(text));
  const m = DECIMAL_INPUT_GRAMMAR.exec(text);
  if (!m) throw new RoaxError("decimal-grammar", text);

  const sign = m[1];
  const intDigits = m[2];
  const fracDigits = m[3] === undefined ? "" : m[3];
  const exponent = m[4] === undefined ? 0 : Number(m[4]);

  const digits = intDigits + fracDigits;
  // Shift the point right by `exponent`; `point` counts digits from the left of `digits`.
  const point = intDigits.length + exponent;

  // Section 6.2: the bound is on the expanded positional form, before the normalization below.
  // Counted arithmetically and thrown BEFORE any padding exists. The input grammar admits any
  // exponent, so building the padding first makes `1e999999999` a gigabyte string and a larger
  // exponent a RangeError, in place of the digit-bound-exceeded the reject vectors expect.
  const expanded = Math.max(point, digits.length) + Math.max(0, -point);
  if (expanded > MAX_EXPANDED_DIGITS) throw new RoaxError("digit-bound-exceeded", String(expanded));

  let intPart;
  let fracPart;
  if (point >= digits.length) {
    intPart = digits + "0".repeat(point - digits.length);
    fracPart = "";
  } else if (point <= 0) {
    intPart = "";
    fracPart = "0".repeat(-point) + digits;
  } else {
    intPart = digits.slice(0, point);
    fracPart = digits.slice(point);
  }

  intPart = intPart.replace(/^0+/, "");
  if (intPart === "") intPart = "0";
  // Only a fraction with NO digits is dropped. A fraction whose digits are all zero is kept,
  // which is why -0.00 canonicalizes to 0.00 and not to 0.
  let out = fracPart === "" ? intPart : `${intPart}.${fracPart}`;
  const magnitudeIsZero = !/[1-9]/.test(digits);
  if (sign === "-" && !magnitudeIsZero) out = `-${out}`;

  if (!DECIMAL_OUTPUT_GRAMMAR.test(out)) throw new RoaxError("decimal-output-grammar", out);
  return out;
}

// -------------------------------------------------------------------------------------------
// Value encoding (section 6)
// -------------------------------------------------------------------------------------------

export function encodeValue(tag, value) {
  switch (tag) {
    case TAG.NULL:
    case TAG.EMPTY_ARRAY:
    case TAG.EMPTY_OBJECT:
      if (value !== undefined && value !== null) {
        throw new RoaxError("value-must-be-absent", TAG_NAME[tag]);
      }
      return Buffer.alloc(0);
    case TAG.BOOL:
      if (typeof value !== "boolean") throw new RoaxError("bool-carrier", String(value));
      return Buffer.from([value ? 0x01 : 0x00]);
    case TAG.STRING:
      if (typeof value !== "string") throw new RoaxError("string-carrier", String(value));
      return Buffer.from(nfc(value), "utf8");
    case TAG.INTEGER:
      return Buffer.from(canonicalInteger(value), "ascii");
    case TAG.DECIMAL:
      return Buffer.from(canonicalDecimal(value), "ascii");
    case TAG.BYTES:
      if (typeof value !== "string" || !HEX_BYTES.test(value)) {
        throw new RoaxError("bytes-carrier", String(value));
      }
      return Buffer.from(value, "hex");
    default:
      throw new RoaxError("tag-unknown", String(tag));
  }
}

// -------------------------------------------------------------------------------------------
// Salts (section 7)
// -------------------------------------------------------------------------------------------
//
// Decision D4 is ruled D4b, so there is NOTHING TO DERIVE HERE. A salt is 16 bytes drawn
// independently from a CSPRNG at issuance, with at least 128 bits of entropy; there is no key
// derivation function, no master secret and no salt preimage in this design (spec section 7).
//
// A salt is an INPUT to this implementation rather than something it computes, which is what
// makes a fixed vector file possible: the corpus build draws each salt once and commits it, and
// both implementations read the committed set. An earlier version of this file derived salts by
// HMAC-SHA-256 over a master salt and a preimage carrying the record identifier - the D4a
// construction the ruling deleted.

export const SALT_BYTES = 16;

// The committed salt of every leaf of one record, addressed by its structured path. This is the
// `salts` array of schemas/envelope-1.0.json, in memory. Pairing is by ENCODED PATH and not by
// position: a positional array would make salt-to-leaf pairing depend on reproducing the
// section 9 sort before the salts could be read at all, which is the cross-implementation
// divergence this corpus exists to prevent (spec section 7.2).
export class SaltSet {
  constructor(entries) {
    this.byPath = new Map();
    for (const entry of entries) {
      const salt = Buffer.from(entry.salt, "hex");
      if (salt.length !== SALT_BYTES) throw new RoaxError("salt-length", String(salt.length));
      const key = encodePath(entry.segments).toString("hex");
      if (this.byPath.has(key)) throw new RoaxError("duplicate-salt-path", "");
      this.byPath.set(key, salt);
    }
  }

  // Fail closed rather than draw one on demand. A drawn salt would give this implementation a
  // root no other implementation could reproduce, which is the silent divergence the corpus is
  // the enforcement mechanism against.
  forLeaf(segments) {
    const key = encodePath(segments).toString("hex");
    const salt = this.byPath.get(key);
    if (salt === undefined) throw new RoaxError("salt-missing", displayPath(segments));
    return salt;
  }

  get size() {
    return this.byPath.size;
  }
}

// -------------------------------------------------------------------------------------------
// Leaf construction (section 8)
// -------------------------------------------------------------------------------------------

export function leafHash(hashAlg, segments, tag, value, salt) {
  if (salt.length !== 16) throw new RoaxError("salt-length", String(salt.length));
  const dom = domain(hashAlg);
  const p = encodePath(segments);
  const v = encodeValue(tag, value);
  return H(hashAlg, Buffer.concat([
    Buffer.from([0x00]),
    u32be(dom.length), dom,
    u32be(p.length), p,
    Buffer.from([tag]),
    u32be(salt.length), salt,
    u64be(v.length), v,
  ]));
}

// -------------------------------------------------------------------------------------------
// Tree construction (section 9), RFC 9162 section 2.1.1 over already-hashed leaves
// -------------------------------------------------------------------------------------------

// The largest power of two STRICTLY smaller than n, for n > 1.
export function splitPoint(n) {
  let k = 1;
  while (k * 2 < n) k *= 2;
  return k;
}

// Section 9.1. The 0x00 leaf-domain byte is applied inside leafHash and MUST NOT be reapplied.
export function mth(hashAlg, leaves) {
  if (leaves.length === 0) return H(hashAlg, Buffer.alloc(0)); // total function only
  if (leaves.length === 1) return leaves[0];
  const k = splitPoint(leaves.length);
  return H(hashAlg, Buffer.concat([
    Buffer.from([0x01]),
    mth(hashAlg, leaves.slice(0, k)),
    mth(hashAlg, leaves.slice(k)),
  ]));
}

// RFC 9162 section 2.1.3 PATH(m, D[n]). Deepest sibling first, root-ward last.
export function inclusionPath(hashAlg, index, leaves) {
  const n = leaves.length;
  if (index < 0 || index >= n) throw new RoaxError("leaf-index-out-of-range", `${index} of ${n}`);
  if (n === 1) return [];
  const k = splitPoint(n);
  if (index < k) {
    return [...inclusionPath(hashAlg, index, leaves.slice(0, k)), mth(hashAlg, leaves.slice(k))];
  }
  return [...inclusionPath(hashAlg, index - k, leaves.slice(k)), mth(hashAlg, leaves.slice(0, k))];
}

// RFC 9162 section 2.1.3.2, unchanged, over already-hashed leaves.
export function verifyInclusion(hashAlg, leaf, index, treeSize, path, root) {
  if (treeSize <= 0 || index < 0 || index >= treeSize) return false;
  let fn = index;
  let sn = treeSize - 1;
  let r = leaf;
  for (const p of path) {
    if (p.length !== leaf.length) return false;
    if (sn === 0) return false;
    if ((fn & 1) === 1 || fn === sn) {
      r = H(hashAlg, Buffer.concat([Buffer.from([0x01]), p, r]));
      while ((fn & 1) === 0 && fn !== 0) {
        fn >>>= 1;
        sn >>>= 1;
      }
    } else {
      r = H(hashAlg, Buffer.concat([Buffer.from([0x01]), r, p]));
    }
    fn >>>= 1;
    sn >>>= 1;
  }
  return sn === 0 && r.equals(root);
}

// -------------------------------------------------------------------------------------------
// Flattening and the reserved leaf set (sections 3.3, 11.2)
// -------------------------------------------------------------------------------------------

// A JSON number captured as its verbatim source text (section 6.4). Never touched by a float.
export class NumberLiteral {
  constructor(text) {
    this.text = text;
  }
}

// An ordered map preserving duplicate keys, so the flattener can reject them rather than let a
// plain object silently drop one (section 3.2).
export class RecordMap {
  constructor(entries) {
    this.entries = entries;
  }
}

// Section 11.2. The guard tests the NFC-normalized key of the FIRST segment only, and is not a
// display-path test: reconstructing a.b[0].c to run it is what section 5.2 forbids.
export function checkReservedNamespace(segments) {
  if (segments.length === 0) return;
  const first = segments[0];
  if (!Object.prototype.hasOwnProperty.call(first, "key")) return;
  if (nfc(first.key).startsWith(RESERVED_PREFIX)) throw new RoaxError("reserved-namespace", first.key);
}

export function jsonKind(node) {
  if (node === null) return "null";
  if (typeof node === "boolean") return "boolean";
  if (node instanceof NumberLiteral) return "number";
  if (typeof node === "string") return "string";
  if (Array.isArray(node)) return "array";
  if (node instanceof RecordMap) return "object";
  throw new RoaxError("value-kind-unknown", String(node));
}

// Convert a parsed record node into the carrier form encodeValue expects. Every mismatch fails
// closed: coercing a JSON number into a schema-declared STRING would be syntactic inference
// arriving through the back door (section 4).
export function carrier(tag, node) {
  switch (tag) {
    case TAG.NULL:
    case TAG.EMPTY_ARRAY:
    case TAG.EMPTY_OBJECT:
      if (node !== null) throw new RoaxError("tag-value-mismatch", `${TAG_NAME[tag]} at a non-null value`);
      return null;
    case TAG.BOOL:
      if (typeof node !== "boolean") throw new RoaxError("tag-value-mismatch", "BOOL");
      return node;
    case TAG.STRING:
      if (node instanceof NumberLiteral) throw new RoaxError("tag-value-mismatch", "STRING at a JSON number");
      if (typeof node !== "string") throw new RoaxError("tag-value-mismatch", "STRING");
      return node;
    case TAG.INTEGER:
    case TAG.DECIMAL:
      if (node instanceof NumberLiteral) return node.text;
      if (typeof node === "string") {
        throw new RoaxError("tag-value-mismatch", `${TAG_NAME[tag]} at a JSON string`);
      }
      throw new RoaxError("tag-value-mismatch", TAG_NAME[tag]);
    case TAG.BYTES:
      throw new RoaxError("bytes-binding-unsupported", "v1 binds base64 fields as STRING");
    default:
      throw new RoaxError("tag-unknown", String(tag));
  }
}

// Section 3.3. A leaf for every scalar and for every EMPTY container. There is no syntactic
// fallback: an uncovered path raises, which is the fail-closed rule of section 4.2.
export function flatten(node, typeMap, segments = []) {
  checkReservedNamespace(segments);

  if (node instanceof RecordMap) {
    if (node.entries.length === 0) return [{ segments, tag: TAG.EMPTY_OBJECT, value: null }];
    const out = [];
    const seen = new Set();
    for (const [k, v] of node.entries) {
      if (seen.has(k)) throw new RoaxError("duplicate-key", k);
      seen.add(k);
      out.push(...flatten(v, typeMap, [...segments, { key: k }]));
    }
    return out;
  }
  if (Array.isArray(node)) {
    if (node.length === 0) return [{ segments, tag: TAG.EMPTY_ARRAY, value: null }];
    const out = [];
    node.forEach((v, i) => out.push(...flatten(v, typeMap, [...segments, { index: i }])));
    return out;
  }
  const tag = typeMap.resolve(segments, jsonKind(node));
  return [{ segments, tag, value: carrier(tag, node) }];
}

// Section 11.2. Four reserved leaves always; roax.issuer.keyId only when issuer.keyId is
// present. An absent issuer.keyId emits NO leaf - not a NULL leaf and not an empty string.
export function reservedLeaves({ recordType, schemaVersion, recordId, issuerId, issuerKeyId }) {
  const out = [
    { segments: [{ key: RESERVED.recordType }], tag: TAG.STRING, value: recordType },
    { segments: [{ key: RESERVED.schemaVersion }], tag: TAG.STRING, value: schemaVersion },
    { segments: [{ key: RESERVED.recordId }], tag: TAG.STRING, value: recordId },
    { segments: [{ key: RESERVED.issuerId }], tag: TAG.STRING, value: issuerId },
  ];
  if (issuerKeyId !== undefined && issuerKeyId !== null) {
    out.push({ segments: [{ key: RESERVED.issuerKeyId }], tag: TAG.STRING, value: issuerKeyId });
  }
  return out;
}

// Sections 3.3 and 9. The leaf set in encodePath order, WITHOUT any salt.
//
// Split out of buildTree when decision D4 was ruled D4b. Leaf order is a function of the path
// set alone (spec section 9), so it is computable before a salt exists - which is what lets a
// caller draw a salt set for a record, and what lets the envelope verifier recover leaf order
// without inventing salt values to get it.
//
// The union of the reserved leaves and the record's own is formed BEFORE the sort, so the two
// are ordered together and are indistinguishable to the tree function.
export function orderedLeaves(record, typeMap, identity) {
  const recordLeaves = flatten(record, typeMap);
  if (recordLeaves.length === 0) throw new RoaxError("record-contributes-no-leaves", "");

  const all = [...reservedLeaves(identity), ...recordLeaves];
  const encoded = all.map((leaf) => ({ enc: encodePath(leaf.segments), leaf }));

  const seen = new Set();
  for (const { enc } of encoded) {
    const key = enc.toString("hex");
    if (seen.has(key)) throw new RoaxError("duplicate-path", "");
    seen.add(key);
  }

  encoded.sort((a, b) => Buffer.compare(a.enc, b.enc));
  return encoded.map((e) => e.leaf);
}

// Sections 3.3, 7, 8 and 9. `salts` is a SaltSet and is an INPUT: under decision D4b nothing
// here derives a salt (spec section 7), and a leaf with no committed salt is an error rather
// than a fresh draw.
export function buildTree(hashAlg, record, typeMap, salts, identity) {
  const ordered = orderedLeaves(record, typeMap, identity);
  const leafSalts = ordered.map((leaf) => salts.forLeaf(leaf.segments));
  const hashes = ordered.map((leaf, i) => leafHash(hashAlg, leaf.segments, leaf.tag, leaf.value, leafSalts[i]));
  return { root: mth(hashAlg, hashes), leaves: ordered, salts: leafSalts, hashes };
}

// -------------------------------------------------------------------------------------------
// Type map (section 4)
// -------------------------------------------------------------------------------------------

// Section 4. Keyed by (path pattern, observed JSON kind); first matching entry wins. Unknown
// paths fail closed: there is no default tag and no fallback to the observed JSON kind, because
// either would let two libraries with different maps produce different roots silently.
export class TypeMap {
  constructor(doc) {
    this.doc = doc;
    this.recordType = doc.recordType;
    this.schemaVersion = doc.schemaVersion;
    this.version = doc.typeMapVersion;
    this.entries = doc.entries.map((e) => ({ pattern: parsePattern(e.pattern), entry: e }));
  }

  resolve(segments, kind) {
    for (const { pattern, entry } of this.entries) {
      if (entry.jsonKind !== undefined && entry.jsonKind !== kind) continue;
      if (matchPattern(pattern, segments)) return entry.tag;
    }
    throw new RoaxError("type-map-uncovered-path", displayPath(segments));
  }
}

// `*` matches one array index, `**` matches any run of segments. Because the pattern is written
// in display notation it cannot address a key containing `.`, `[` or `]`, which section 5
// deliberately admits; those are rejected here rather than silently mis-parsed.
export function parsePattern(pattern) {
  const out = [];
  let i = 0;
  while (i < pattern.length) {
    if (pattern[i] === "[") {
      const j = pattern.indexOf("]", i);
      if (j < 0) throw new RoaxError("type-map-pattern", pattern);
      const body = pattern.slice(i + 1, j);
      if (body === "*") out.push({ kind: "index", value: null });
      else if (/^[0-9]+$/.test(body)) out.push({ kind: "index", value: Number(body) });
      else throw new RoaxError("type-map-pattern", pattern);
      i = j + 1;
      if (pattern[i] === ".") i++;
      continue;
    }
    let j = i;
    while (j < pattern.length && pattern[j] !== "." && pattern[j] !== "[") j++;
    const token = pattern.slice(i, j);
    if (token === "**") out.push({ kind: "any", value: null });
    else if (token === "" || token.includes("]")) throw new RoaxError("type-map-pattern", pattern);
    else out.push({ kind: "key", value: token });
    i = j;
    if (pattern[i] === ".") i++;
  }
  return out;
}

export function matchPattern(pattern, segments) {
  const step = (pi, si) => {
    while (pi < pattern.length) {
      const { kind, value } = pattern[pi];
      if (kind === "any") {
        for (let skip = si; skip <= segments.length; skip++) if (step(pi + 1, skip)) return true;
        return false;
      }
      if (si >= segments.length) return false;
      const seg = segments[si];
      if (kind === "key") {
        if (!Object.prototype.hasOwnProperty.call(seg, "key") || seg.key !== value) return false;
      } else {
        if (!Object.prototype.hasOwnProperty.call(seg, "index")) return false;
        if (value !== null && seg.index !== value) return false;
      }
      pi++;
      si++;
    }
    return si === segments.length;
  };
  return step(0, 0);
}
