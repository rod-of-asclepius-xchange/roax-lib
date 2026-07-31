/**
 * Unit tests for rules the specification states and no committed corpus vector exercises,
 * plus a round trip through issuance, disclosure and verification.
 *
 * The conformance runner is the primary evidence; this file covers what it cannot reach.
 * Each test names the section it discharges.
 */

import { strict as assert } from 'node:assert';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  readJson,
  carrierFromJson,
  writeJson,
  fromJsValue,
  RoaxError,
  LegacyPatternTypeMap,
  issueFullCopy,
  discloseFrom,
  parseEnvelope,
  verifyEnvelope,
  commitRecord,
  PathKeyedSalts,
  FreshSalts,
  encodeValue,
  decodeBase64Strict,
  canonicalizeDecimal,
  resolveHashFunction,
  merkleTreeHead,
  buildMerkleTree,
  inclusionProof,
  verifyInclusion,
  splitPoint,
  toHex,
  hexNibble,
  TypeTag,
  REGISTERED_PROFILES,
  type Path,
  type JsonValue,
} from '../src/index.js';

let passed = 0;
const failures: string[] = [];

function test(name: string, body: () => void): void {
  try {
    body();
    passed += 1;
  } catch (e) {
    failures.push(`${name}: ${String(e)}`);
  }
}

/**
 * The repository root, found by walking up from this module's own directory.
 *
 * The same shape `conformance/run.ts` uses and for the same reason: this file runs from `dist/`,
 * so a path relative to the source tree would not resolve. `package.json` is the marker.
 */
const REPO_ROOT = ((): string => {
  let dir = dirname(fileURLToPath(import.meta.url));
  for (let i = 0; i < 8; i += 1) {
    if (existsSync(resolve(dir, 'package.json')) && existsSync(resolve(dir, 'schemas'))) {
      return dir;
    }
    dir = resolve(dir, '..');
  }
  throw new Error('could not find the repository root from the test module');
})();

/**
 * A JSON Schema file, read with the host parser.
 *
 * `JSON.parse` is correct HERE and nowhere near a record: a schema carries no record value, so no
 * numeric literal of the protocol passes through it. Reading it with this package's own reader
 * would say the opposite of what section 6.4 means.
 */
function readJsonFile(file: string): unknown {
  return JSON.parse(readFileSync(file, 'utf8')) as unknown;
}

/**
 * The `value` pattern an envelope schema pins for tag 5, found structurally.
 *
 * A recursive search for the conditional rather than a fixed `$defs` path, so the test keeps
 * comparing against the live schema if the surrounding structure is reorganized.
 */
function tagFivePattern(node: unknown): string | undefined {
  if (node === null || typeof node !== 'object') {
    return undefined;
  }
  if (Array.isArray(node)) {
    for (const item of node) {
      const found = tagFivePattern(item);
      if (found !== undefined) {
        return found;
      }
    }
    return undefined;
  }
  const record = node as Record<string, unknown>;
  const conditionTag = (((record['if'] as Record<string, unknown>)?.['properties'] as
    | Record<string, unknown>
    | undefined)?.['tag'] as Record<string, unknown> | undefined)?.['const'];
  if (conditionTag === 5) {
    const pattern = (((record['then'] as Record<string, unknown>)?.['properties'] as
      | Record<string, unknown>
      | undefined)?.['value'] as Record<string, unknown> | undefined)?.['pattern'];
    if (typeof pattern === 'string') {
      return pattern;
    }
  }
  for (const value of Object.values(record)) {
    const found = tagFivePattern(value);
    if (found !== undefined) {
      return found;
    }
  }
  return undefined;
}

function expectCode(code: string, body: () => unknown): void {
  try {
    body();
  } catch (e) {
    assert.ok(e instanceof RoaxError, `expected a RoaxError, got ${String(e)}`);
    assert.equal(e.code, code);
    return;
  }
  assert.fail(`expected rejection ${code}, but the input was accepted`);
}

// ---------------------------------------------------------------------------------------------
// The load-bearing property: a numeric literal survives the reader.
// ---------------------------------------------------------------------------------------------

test('the reader preserves a decimal literal verbatim (section 6.4)', () => {
  const doc = readJson('{"a": 0.010, "b": 9223372036854775807, "c": 1234567890123456789.1}');
  assert.equal(doc.kind, 'object');
  const members = doc.kind === 'object' ? doc.members : [];
  assert.deepEqual(
    members.map(([k, v]) => [k, v.kind === 'number' ? v.literal : v]),
    [
      ['a', '0.010'],
      ['b', '9223372036854775807'],
      ['c', '1234567890123456789.1'],
    ],
  );
  // What JSON.parse does to the same text, for contrast. This is the disqualifying behaviour.
  assert.equal(String(JSON.parse('0.010')), '0.01');
  assert.equal(String(JSON.parse('9223372036854775807')), '9223372036854776000');
});

test('the writer emits a numeric literal verbatim, so a round trip is lossless', () => {
  const text = '{"a":0.010,"b":9223372036854775807}';
  assert.equal(writeJson(readJson(text)), text);
});

test('a JS number cannot be laundered into a commitment (section 6.4)', () => {
  expectCode('non-finite-number', () => fromJsValue({ a: 0.01 }));
});

// ---------------------------------------------------------------------------------------------
// Section 6.5: BLOB_REF is registered and selected by nothing.
// No committed typeMapVector carries expectMapRejected, so this is the only coverage.
// ---------------------------------------------------------------------------------------------

test('a type map binding any path to tag 8 BLOB_REF is rejected (section 6.5)', () => {
  expectCode('type-map-rejected', () =>
    LegacyPatternTypeMap.compile({
      typeMapVersion: '1.0.0',
      recordType: 'org.roax.corpus.synthetic',
      schemaVersion: '1.0',
      entries: [{ pattern: 'attachment', jsonKind: 'string', tag: 8 }],
    }),
  );
});

test('the BLOB_REF carrier form is still pinned, so it does not need retrofitting (section 6.5)', () => {
  // u64be(1024) ‖ u32be(32) ‖ 32 digest bytes.
  const encoded = encodeValue(TypeTag.BLOB_REF, {
    blobByteLength: '1024',
    blobDigest: 'ab'.repeat(32),
  });
  assert.equal(encoded.length, 8 + 4 + 32);
  assert.equal(toHex(encoded.subarray(0, 8)), '0000000000000400');
  assert.equal(toHex(encoded.subarray(8, 12)), '00000020');
});

// ---------------------------------------------------------------------------------------------
// Section 11.1: the full-copy derived leaf count. The nearest committed vector is caught one step
// earlier by the class-17 salts-length rule, so the comparison itself is unexercised.
// ---------------------------------------------------------------------------------------------

const SYNTHETIC_MAP = LegacyPatternTypeMap.compile({
  typeMapVersion: '1.0.0',
  recordType: 'sg.gov.moh.pdt-healthcert',
  schemaVersion: '2.0',
  entries: [
    { pattern: 'version', jsonKind: 'string', tag: 2 },
    { pattern: 'type', jsonKind: 'string', tag: 2 },
    { pattern: 'validFrom', jsonKind: 'string', tag: 2 },
    { pattern: 'dose', jsonKind: 'number', tag: 4 },
  ],
});

const IDENTITY = {
  recordType: 'sg.gov.moh.pdt-healthcert',
  schemaVersion: '2.0',
  recordId: 'urn:uuid:11111111-1111-4111-8111-111111111111',
  issuerId: 'did:web:corpus.roax.invalid',
  typeMapId: `sha256:${'0'.repeat(64)}`,
  issuerKeyId: 'did:web:corpus.roax.invalid#key-1',
};

const RECORD = readJson(
  '{"version":"pdt-healthcert-v2.0","type":"PCR","validFrom":"2026-07-28T00:00:00Z","dose":0.010}',
);

const TYPE_MAP_VERSION = '1.0.0';

function issued(): ReturnType<typeof issueFullCopy> {
  return issueFullCopy({
    record: RECORD,
    identity: IDENTITY,
    resolver: SYNTHETIC_MAP,
    typeMapVersion: TYPE_MAP_VERSION,
  });
}

const VERIFIER = {
  knownProfiles: REGISTERED_PROFILES,
  resolverFor: (t: string) => (t === IDENTITY.recordType ? SYNTHETIC_MAP : undefined),
};

test('a full copy whose declared leafCount disagrees with the rebuilt tree is rejected (11.1)', () => {
  const full = issued();
  const document = full.document as { kind: 'object'; members: [string, JsonValue][] };
  const tampered: JsonValue = {
    kind: 'object',
    members: document.members.map(([k, v]): [string, JsonValue] =>
      k === 'leafCount' ? [k, { kind: 'number', literal: '99' }] : [k, v],
    ),
  };
  // The salts-length rule fires first when the count moves, exactly as it does in the corpus, so
  // this asserts the reason ordering as well as the rule.
  expectCode('salts-length-not-leaf-count', () =>
    verifyEnvelope(parseEnvelope(tampered), VERIFIER),
  );
});

// ---------------------------------------------------------------------------------------------
// Issuance, disclosure and verification round trip.
// ---------------------------------------------------------------------------------------------

test('a full copy issued by this library verifies against itself', () => {
  const full = issued();
  const result = verifyEnvelope(parseEnvelope(full.document), VERIFIER);
  assert.equal(result.kind, 'full');
  // 4 record leaves plus 6 reserved: recordType, schemaVersion, typeMap.id, recordId, issuer.id,
  // issuer.keyId (specification section 11.2).
  assert.equal(result.leafCount, 10);
});

test('the typeMap member carries id and version together, and a version is never guessed', () => {
  // The accepting direction: both members named, and the envelope round-trips through this
  // library's own verifier carrying exactly the version the caller supplied.
  const full = issued();
  const descriptor = memberValue(full.document, 'typeMap');
  assert.deepEqual(memberValue(descriptor, 'id'), { kind: 'string', value: IDENTITY.typeMapId });
  assert.deepEqual(memberValue(descriptor, 'version'), {
    kind: 'string',
    value: TYPE_MAP_VERSION,
  });
  assert.equal(verifyEnvelope(parseEnvelope(full.document), VERIFIER).kind, 'full');

  // And the refusing direction. `schemas/envelope-1.0.json` requires both members whenever
  // `typeMap` is present, so an issuance naming the artifact without its version has nothing
  // valid to write; substituting one emits a version the caller never named into an envelope
  // that is unrecoverable once anchored. The sibling emitters refuse this too.
  expectCode('envelope-malformed', () =>
    issueFullCopy({ record: RECORD, identity: IDENTITY, resolver: SYNTHETIC_MAP }),
  );
});

test('a disclosed copy verifies, and carries the salt of no withheld leaf (sections 7.3, 10.1)', () => {
  const full = issued();
  const reveal: Path[] = [
    [{ key: 'roax.recordType' }],
    [{ key: 'roax.schemaVersion' }],
    [{ key: 'roax.typeMap.id' }],
    [{ key: 'roax.recordId' }],
    [{ key: 'roax.issuer.id' }],
    [{ key: 'version' }],
    [{ key: 'type' }],
    [{ key: 'validFrom' }],
  ];
  const disclosed = discloseFrom(full, { reveal });
  const result = verifyEnvelope(parseEnvelope(disclosed), VERIFIER);
  assert.equal(result.kind, 'disclosed');

  const text = writeJson(disclosed);
  assert.ok(!text.includes('"salts"'), 'a disclosed copy must not carry the full-copy salts array');
  // The withheld leaf is `dose`. Its salt must appear nowhere in the disclosed copy: handing it
  // over makes the value guessable by dictionary search with no cryptanalysis required.
  const doseLeaf = full.commitment.leaves.find((l) => l.path.length === 1 && 'key' in l.path[0]! && l.path[0].key === 'dose');
  assert.ok(doseLeaf !== undefined);
  assert.ok(!text.includes(toHex(doseLeaf.salt)), "a withheld leaf's salt leaked into a disclosed copy");
});

test('disclosure below the minimum-disclosure floor is refused at production (section 10.2)', () => {
  const full = issued();
  expectCode('minimum-disclosure-floor', () =>
    discloseFrom(full, {
      reveal: [
        [{ key: 'roax.recordType' }],
        [{ key: 'roax.schemaVersion' }],
        [{ key: 'roax.typeMap.id' }],
        [{ key: 'roax.recordId' }],
        [{ key: 'roax.issuer.id' }],
        [{ key: 'version' }],
        [{ key: 'type' }],
        // `validFrom` withheld: a validity claim with no start is not checkable.
      ],
    }),
  );
});

test('omitting roax.issuer.keyId from a disclosed copy is ACCEPTED (sections 10.2, 12.2)', () => {
  // The upper edge of the floor. Requiring it would permanently bind an anchored record to the
  // key it was issued under and leave a rotated issuer with no path to verify.
  const full = issued();
  const disclosed = discloseFrom(full, {
    reveal: [
      [{ key: 'roax.recordType' }],
      [{ key: 'roax.schemaVersion' }],
      [{ key: 'roax.typeMap.id' }],
      [{ key: 'roax.recordId' }],
      [{ key: 'roax.issuer.id' }],
      [{ key: 'version' }],
      [{ key: 'type' }],
      [{ key: 'validFrom' }],
    ],
  });
  assert.equal(verifyEnvelope(parseEnvelope(disclosed), VERIFIER).kind, 'disclosed');
});

test('two issuances of the same record produce different roots (section 7.1)', () => {
  // Independent per-leaf salts have no shared secret, so there is nothing to reuse. A
  // deterministic reissuance reads like a feature and is the cross-record patient-linkage hazard.
  assert.notEqual(issued().root, issued().root);
});

test('an empty record is ONE leaf at the root path, not zero (section 3.3)', () => {
  // Section 3.3 says a record contributing zero leaves of its own MUST be rejected at issuance.
  // That rule is UNREACHABLE under the flatten it is stated beside, in the same way `MTH([])` is:
  // an empty map emits a leaf at the empty path, a non-empty one recurses to at least one scalar,
  // and a scalar emits itself, so every record contributes at least one leaf. `{}` is therefore a
  // one-leaf record at `encodePath([]) = 00000000`, not an empty one. The check is kept in
  // `leafSet` as a total-function guard, exactly as the specification keeps `MTH([])`.
  const commitment = commitRecord(readJson('{}'), {
    hash: resolveHashFunction('SHA-256'),
    resolver: SYNTHETIC_MAP,
    identity: IDENTITY,
    salts: new FreshSalts(),
    emptyContainerPolicy: 'mechanical',
  });
  assert.equal(commitment.leafCount, 7); // 1 record leaf plus 6 reserved.
  const rootLeaf = commitment.leaves.find((l) => l.path.length === 0);
  assert.ok(rootLeaf !== undefined);
  assert.equal(rootLeaf.tag, TypeTag.EMPTY_OBJECT);
});

// ---------------------------------------------------------------------------------------------
// Section 6.3: RFC 4648 section 4 base64, which no committed vector reaches because no profile
// binds BYTES today.
// ---------------------------------------------------------------------------------------------

test('base64 is RFC 4648 section 4: padded, standard alphabet, canonical final quantum', () => {
  assert.equal(toHex(decodeBase64Strict('AAECAw==')), '00010203');
  // The URL-safe alphabet of section 5.
  expectCode('base64-not-canonical', () => decodeBase64Strict('-_=='));
  // Absent padding.
  expectCode('base64-not-canonical', () => decodeBase64Strict('AAEC'.slice(0, 3)));
  // A final quantum whose unused bits are non-zero (RFC 4648 section 3.5): `AB==` decodes the
  // same byte as `AA==`, so accepting both would admit two encodings of one value.
  expectCode('base64-not-canonical', () => decodeBase64Strict('AB=='));
  // A line break.
  expectCode('base64-not-canonical', () => decodeBase64Strict('AA=\n'));
});

test('a BYTES carrier is lowercase hex projected from the record base64 (section 6.3)', () => {
  // **The record form and the carrier form differ for this one tag**, and this is the only place
  // the two meet. Both envelope schemas pin `^([0-9a-f]{2})*$` for a disclosed tag-5 value, so a
  // carrier that kept the base64 would be schema-invalid while still verifying against its own
  // root - valid-looking and wrong, which is the dangerous shape.
  assert.equal(carrierFromJson(TypeTag.BYTES, readJson('"AAECAw=="')), '00010203');
  // Empty bytes survive as the empty string. BYTES is not one of the tags that carries no value,
  // so the leaf keeps its `value` member and both schema patterns admit the empty match.
  assert.equal(carrierFromJson(TypeTag.BYTES, readJson('""')), '');
  // The non-canonical forms are rejected AT THE PROJECTION, because that is now the only place
  // base64 is read: the URL-safe alphabet, a non-zero final quantum, and absent padding.
  expectCode('base64-not-canonical', () => carrierFromJson(TypeTag.BYTES, readJson('"-_=="')));
  expectCode('base64-not-canonical', () => carrierFromJson(TypeTag.BYTES, readJson('"AB=="')));
  expectCode('base64-not-canonical', () => carrierFromJson(TypeTag.BYTES, readJson('"AAE"')));
  // STRING at the same observed kind keeps the text verbatim, so the two tags are genuinely
  // different projections rather than one with a cosmetic difference. The healthcert blob fields
  // bind as STRING and their base64 text is hashed as text (section 6.3).
  assert.equal(carrierFromJson(TypeTag.STRING, readJson('"AAECAw=="')), 'AAECAw==');
});

test('encodeValue reads a BYTES carrier as strict lowercase hex, never as base64', () => {
  assert.equal(toHex(encodeValue(TypeTag.BYTES, '00010203')), '00010203');
  assert.equal(encodeValue(TypeTag.BYTES, '').length, 0);
  // Uppercase is rejected rather than folded: the carrier is pinned to ONE spelling, and accepting
  // both would let two texts commit the same bytes.
  expectCode('envelope-malformed', () => encodeValue(TypeTag.BYTES, '00AB'));
  // Odd length, and a non-hex character.
  expectCode('envelope-malformed', () => encodeValue(TypeTag.BYTES, '000'));
  expectCode('envelope-malformed', () => encodeValue(TypeTag.BYTES, 'zz'));
  // The base64 the earlier reading decoded HERE. It is not hex, and accepting it at this boundary
  // is what let a schema-invalid disclosed copy verify against its own root.
  expectCode('envelope-malformed', () => encodeValue(TypeTag.BYTES, 'AAECAw=='));
  expectCode('value-type-mismatch', () => encodeValue(TypeTag.BYTES, true));
});

// ---------------------------------------------------------------------------------------------
// Section 6.2 edges, and the two stated ambiguities.
// ---------------------------------------------------------------------------------------------

test('the digit bound counts the padded form before normalization (stated ambiguity 2)', () => {
  // `1e1023` is 1024 digits and accepted; `1e1024` is 1025 and rejected. `0e99999` is rejected
  // under this reading and would canonicalize to `0` under the other. No vector carries it.
  assert.equal(canonicalizeDecimal('1e1023').length, 1024);
  expectCode('digit-bound-exceeded', () => canonicalizeDecimal('1e1024'));
  expectCode('digit-bound-exceeded', () => canonicalizeDecimal('0e99999'));
});

test('an exponent too large for a float is still exact, so it rejects rather than overflows', () => {
  expectCode('digit-bound-exceeded', () => canonicalizeDecimal('1e999999999999999999999'));
});

test('trailing zeros of the fraction survive and trailing zeros of the integer part do not', () => {
  assert.equal(canonicalizeDecimal('0.010'), '0.010');
  assert.equal(canonicalizeDecimal('1e2'), '100');
  assert.equal(canonicalizeDecimal('1.0e2'), '100');
  assert.equal(canonicalizeDecimal('100.0'), '100.0');
  assert.equal(canonicalizeDecimal('-0.00'), '0.00');
});

// ---------------------------------------------------------------------------------------------
// Section 3.2 input-boundary rejections that the corpus reaches only through `$jsonText`.
// ---------------------------------------------------------------------------------------------

test('a duplicate key is rejected at the input boundary at every depth (section 3.2)', () => {
  expectCode('duplicate-key', () => readJson('{"a":{"b":1,"b":2}}'));
});

test('two keys equal only after NFC are distinct members and the same leaf path', () => {
  // Not a duplicate KEY - they are different JSON members - but they encode to one path, which
  // section 9 requires to be unique. The two checks are deliberately separate.
  const record = readJson('{"\\u00e9":"a","e\\u0301":"b"}');
  const resolver = LegacyPatternTypeMap.compile({
    typeMapVersion: '1.0.0',
    recordType: 'sg.gov.moh.pdt-healthcert',
    schemaVersion: '2.0',
    entries: [
      { pattern: 'é', jsonKind: 'string', tag: 2 },
      { pattern: 'é', jsonKind: 'string', tag: 2 },
    ],
  });
  expectCode('duplicate-key', () =>
    commitRecord(record, {
      hash: resolveHashFunction('SHA-256'),
      resolver,
      identity: IDENTITY,
      salts: new FreshSalts(),
    }),
  );
});

test('a sparse-array hole has no JSON representation (section 3.2)', () => {
  const sparse: unknown[] = ['present'];
  sparse.length = 3;
  expectCode('undefined-value', () => fromJsValue(sparse));
});

test('a salt set naming one path twice is rejected (class 17)', () => {
  expectCode('salts-duplicate-path', () => {
    const salt = new Uint8Array(16);
    return new PathKeyedSalts([
      { segments: [{ key: 'a' }], salt },
      { segments: [{ key: 'a' }], salt },
    ]);
  });
});

// ---------------------------------------------------------------------------------------------
// Section 7.4: Poseidon-BN254 is registered and MUST NOT be issued against.
// ---------------------------------------------------------------------------------------------

test('Poseidon-BN254 has no defined construction and is refused (section 7.4)', () => {
  expectCode('hash-alg-unsupported', () => resolveHashFunction('Poseidon-BN254'));
});

// ---------------------------------------------------------------------------------------------
// `hexNibble` resolves ONE hexadecimal digit. Written against the code unit rather than as
// `HEX.indexOf(ch)`, because `indexOf` is a substring search: it answers 10 for the two-character
// string 'ab' and 0 for the empty string, so an `indexOf` form silently accepts input that is not
// a digit. Pinned because the function is exported and the next caller may not pre-validate.
// ---------------------------------------------------------------------------------------------

test('hexNibble accepts one hexadecimal digit in either case and nothing else', () => {
  assert.equal(hexNibble('0'), 0);
  assert.equal(hexNibble('9'), 9);
  assert.equal(hexNibble('a'), 10);
  assert.equal(hexNibble('f'), 15);
  assert.equal(hexNibble('A'), 10);
  assert.equal(hexNibble('F'), 15);

  // The three shapes an `indexOf` implementation gets wrong.
  assert.equal(hexNibble('ab'), -1, "'ab' is a substring of the table, not a digit");
  assert.equal(hexNibble('0123'), -1, "'0123' is a substring of the table, not a digit");
  assert.equal(hexNibble(''), -1, 'the empty string is a substring of every string');

  assert.equal(hexNibble('g'), -1);
  assert.equal(hexNibble('G'), -1);
  assert.equal(hexNibble(' '), -1);
  // Adjacent to the accepted ranges on both sides: '/' and ':' bracket the digits, '`' and 'g'
  // bracket lowercase, '@' and 'G' bracket uppercase.
  for (const ch of ['/', ':', '`', '@']) {
    assert.equal(hexNibble(ch), -1, `${JSON.stringify(ch)} is adjacent to a range, not inside one`);
  }
});

// ---------------------------------------------------------------------------------------------
// Envelope-tree surgery, so the tests below can state what they are about rather than how they
// rebuild a document. Every helper rebuilds a fresh node: a `JsonValue` is treated as immutable
// everywhere else in this package.
// ---------------------------------------------------------------------------------------------

function memberValue(node: JsonValue, name: string): JsonValue {
  assert.equal(node.kind, 'object');
  const found = node.kind === 'object' ? node.members.find(([k]) => k === name) : undefined;
  assert.ok(found !== undefined, `no member ${name}`);
  return found[1];
}

function withMember(node: JsonValue, name: string, replacement: JsonValue): JsonValue {
  assert.equal(node.kind, 'object');
  const members = node.kind === 'object' ? node.members : [];
  assert.ok(members.some(([k]) => k === name), `no member ${name} to replace`);
  return {
    kind: 'object',
    members: members.map(([k, v]): [string, JsonValue] => (k === name ? [k, replacement] : [k, v])),
  };
}

function mapDisclosedLeaves(envelope: JsonValue, f: (leaf: JsonValue) => JsonValue): JsonValue {
  const disclosure = memberValue(envelope, 'disclosure');
  const leaves = memberValue(disclosure, 'leaves');
  assert.equal(leaves.kind, 'array');
  const mapped: JsonValue = {
    kind: 'array',
    items: leaves.kind === 'array' ? leaves.items.map(f) : [],
  };
  return withMember(envelope, 'disclosure', withMember(disclosure, 'leaves', mapped));
}

/** The single KEY a disclosed leaf sits at, or `undefined` for any other shape. */
function leafKey(leaf: JsonValue): string | undefined {
  const segments = memberValue(leaf, 'segments');
  if (segments.kind !== 'array' || segments.items.length !== 1) {
    return undefined;
  }
  const segment = segments.items[0] as JsonValue;
  if (segment.kind !== 'object') {
    return undefined;
  }
  const key = segment.members.find(([k]) => k === 'key');
  return key !== undefined && key[1].kind === 'string' ? key[1].value : undefined;
}

// The floor plus `dose`, which is the record's one NUMBER-kind leaf and therefore the only one that
// reaches the numeric half of the section 10 step 1 tag check. `roax.issuer.keyId` stays withheld,
// as it may (section 10.2).
const REVEAL_WITH_NUMERIC_LEAF: Path[] = [
  [{ key: 'roax.recordType' }],
  [{ key: 'roax.schemaVersion' }],
  [{ key: 'roax.typeMap.id' }],
  [{ key: 'roax.recordId' }],
  [{ key: 'roax.issuer.id' }],
  [{ key: 'version' }],
  [{ key: 'type' }],
  [{ key: 'validFrom' }],
  [{ key: 'dose' }],
];

// ---------------------------------------------------------------------------------------------
// Section 10 step 1: a disclosed record leaf's tag against the exact selected map, for EVERY tag a
// record leaf can carry. The corpus cannot see this - all 318 disclosed leaves in its 54 envelope
// fixtures are tag 2 STRING - so these two are the only coverage of the numeric and BYTES tags
// AGAINST THE MAP. The BYTES carrier form itself is covered separately, by the section 6.3 tests
// above and the end-to-end BYTES round trip below.
//
// Both tamper only with the tag. That is deliberate: a tag that contradicts its own value would
// also be caught downstream by `encodeValue`, so each test asserts that the MAP check fires first
// and names the map rather than the carrier.
// ---------------------------------------------------------------------------------------------

test('a disclosed DECIMAL leaf retagged INTEGER is rejected against the map (section 10 step 1)', () => {
  const disclosed = discloseFrom(issued(), { reveal: REVEAL_WITH_NUMERIC_LEAF });
  // `dose` is bound at kind `number` to tag 4 DECIMAL. Tag 3 INTEGER is the same observed kind, so
  // the map is the only thing that separates them and an uninverted check saw neither.
  const tampered = mapDisclosedLeaves(disclosed, (leaf) =>
    leafKey(leaf) === 'dose' ? withMember(leaf, 'tag', { kind: 'number', literal: '3' }) : leaf,
  );
  expectCode('type-map-fail-closed', () => verifyEnvelope(parseEnvelope(tampered), VERIFIER));
});

test('a disclosed leaf retagged BYTES at a STRING-bound path is rejected (section 10 step 1)', () => {
  const disclosed = discloseFrom(issued(), { reveal: REVEAL_WITH_NUMERIC_LEAF });
  // The asymmetry that was the whole exposure: STRING at a BYTES-bound path was caught and BYTES at
  // a STRING-bound path was not, though both are one lookup under kind `string`.
  const tampered = mapDisclosedLeaves(disclosed, (leaf) =>
    leafKey(leaf) === 'type' ? withMember(leaf, 'tag', { kind: 'number', literal: '5' }) : leaf,
  );
  expectCode('type-map-fail-closed', () => verifyEnvelope(parseEnvelope(tampered), VERIFIER));
});

test('step 1 reports nothing undischarged when a map covers every disclosed leaf', () => {
  const disclosed = discloseFrom(issued(), { reveal: REVEAL_WITH_NUMERIC_LEAF });
  const result = verifyEnvelope(parseEnvelope(disclosed), VERIFIER);
  assert.equal(result.kind, 'disclosed');
  assert.deepEqual(
    result.undischarged.filter((u) => u.includes('section 10 step 1')),
    [],
  );
});

test('the resolver-unavailable step 1 report is raised once rather than once per leaf', () => {
  const disclosed = discloseFrom(issued(), { reveal: REVEAL_WITH_NUMERIC_LEAF });
  const result = verifyEnvelope(parseEnvelope(disclosed), {
    knownProfiles: REGISTERED_PROFILES,
    requireTypeMapForDisclosedLeaves: false,
  });
  const stepOne = result.undischarged.filter((u) => u.includes('section 10 step 1'));
  // Four record leaves are revealed, and the report is about the verifier rather than about any
  // one of them.
  assert.equal(stepOne.length, 1);
});

// ---------------------------------------------------------------------------------------------
// Section 11.3: the anchoring layer is resolved from the VERIFIER's configuration, and the
// registry's identity is the address AND the chain.
// ---------------------------------------------------------------------------------------------

test('an anchor on another chain is refused even when the registry address matches (11.3)', () => {
  const anchored = issueFullCopy({
    record: RECORD,
    identity: IDENTITY,
    resolver: SYNTHETIC_MAP,
    typeMapVersion: TYPE_MAP_VERSION,
    anchor: { chainId: 137, registry: '0xregistry' },
  });
  // One contract address on two chains is two registries with two sets of contents, so comparing
  // the address alone accepts an envelope routed at a registry this verifier never configured.
  expectCode('envelope-malformed', () =>
    verifyEnvelope(parseEnvelope(anchored.document), {
      ...VERIFIER,
      registryAddress: '0xregistry',
      registryChainId: 1,
    }),
  );
  assert.equal(
    verifyEnvelope(parseEnvelope(anchored.document), {
      ...VERIFIER,
      registryAddress: '0xregistry',
      registryChainId: 137,
    }).kind,
    'full',
  );
  // A verifier configuring neither half keeps reading the anchor as the hint section 11.3 makes it.
  assert.equal(verifyEnvelope(parseEnvelope(anchored.document), VERIFIER).kind, 'full');
});

// ---------------------------------------------------------------------------------------------
// Section 7.3 rule 3: the seed guard covers every object the envelope schemas define, including the
// one reachable through a type tag rather than through a named member.
// ---------------------------------------------------------------------------------------------

test("a seed inside a disclosed leaf's value object names rule 3 rather than the carrier", () => {
  const disclosed = discloseFrom(issued(), { reveal: REVEAL_WITH_NUMERIC_LEAF });
  const tampered = mapDisclosedLeaves(disclosed, (leaf) =>
    leafKey(leaf) === 'type'
      ? withMember(leaf, 'value', {
          kind: 'object',
          members: [
            ['blobByteLength', { kind: 'string', value: '3' }],
            ['blobDigest', { kind: 'string', value: 'ab'.repeat(32) }],
            ['masterSalt', { kind: 'string', value: '00'.repeat(16) }],
          ],
        })
      : leaf,
  );
  // The envelope was already rejected without this, but under `value-type-mismatch`, which names a
  // different defect from the rule that was broken.
  expectCode('master-salt-in-envelope', () => verifyEnvelope(parseEnvelope(tampered), VERIFIER));
});

test('a present-but-non-string optional member reads as absent, at every site', () => {
  // The deliberate leniency of `optionalString`, pinned so that centralizing the three reads did
  // not widen it and cannot later narrow it by accident. These members are hints outside the root
  // (section 11.3), and `keyId` is the one conditional reserved leaf.
  const full = issued();
  const issuer = withMember(memberValue(full.document, 'issuer'), 'keyId', {
    kind: 'number',
    literal: '7',
  });
  const parsed = parseEnvelope(withMember(full.document, 'issuer', issuer));
  assert.equal(parsed.issuer.keyId, undefined);
  assert.deepEqual(parsed.unknownMembers, []);

  const anchored = issueFullCopy({
    record: RECORD,
    identity: IDENTITY,
    resolver: SYNTHETIC_MAP,
    typeMapVersion: TYPE_MAP_VERSION,
    anchor: { chainId: 1, registry: '0xregistry', txHash: '0xdead' },
  });
  const anchor = withMember(memberValue(anchored.document, 'anchor'), 'txHash', {
    kind: 'boolean',
    value: true,
  });
  assert.equal(parseEnvelope(withMember(anchored.document, 'anchor', anchor)).anchor?.txHash, undefined);
});

// ---------------------------------------------------------------------------------------------
// Section 6.5, the SECOND rejection: an envelope carrying a tag-8 leaf.
//
// The first rejection - a map that binds a path to tag 8 - is covered above, and it reaches a full
// copy transitively because re-flattening one runs `carrierFromJson`. A disclosed copy is never
// re-flattened, so this half needs its own assertion and no committed vector carries a tag-8 leaf.
// ---------------------------------------------------------------------------------------------

test('a disclosed copy carrying a tag-8 BLOB_REF leaf is rejected (section 6.5)', () => {
  const disclosed = discloseFrom(issued(), { reveal: REVEAL_WITH_NUMERIC_LEAF });
  const tampered = mapDisclosedLeaves(disclosed, (leaf) =>
    leafKey(leaf) === 'type' ? withMember(leaf, 'tag', { kind: 'number', literal: '8' }) : leaf,
  );
  expectCode('blob-ref-not-selectable', () => verifyEnvelope(parseEnvelope(tampered), VERIFIER));
  // With no map, so the tag check cannot be the thing that caught it: the rejection is the tag
  // itself, and `observedKindForTag` has no kind to look tag 8 up under in any case.
  expectCode('blob-ref-not-selectable', () =>
    verifyEnvelope(parseEnvelope(tampered), {
      knownProfiles: REGISTERED_PROFILES,
      requireTypeMapForDisclosedLeaves: false,
    }),
  );
});

test('a tag-8 leaf with no value still reports BLOB_REF rather than a missing value', () => {
  // The ORDER inside the per-leaf loop, which is the part a later edit can silently break: a leaf
  // carrying a salt and no value would otherwise surface as `disclosed-leaf-named-without-value`,
  // which names a different defect and would send a reader looking for a withheld-salt smuggle.
  const disclosed = discloseFrom(issued(), { reveal: REVEAL_WITH_NUMERIC_LEAF });
  const tampered = mapDisclosedLeaves(disclosed, (leaf) => {
    if (leafKey(leaf) !== 'type') {
      return leaf;
    }
    const retagged = withMember(leaf, 'tag', { kind: 'number', literal: '8' });
    assert.equal(retagged.kind, 'object');
    return {
      kind: 'object',
      members: retagged.kind === 'object' ? retagged.members.filter(([k]) => k !== 'value') : [],
    };
  });
  expectCode('blob-ref-not-selectable', () => verifyEnvelope(parseEnvelope(tampered), VERIFIER));
});

// ---------------------------------------------------------------------------------------------
// Section 6.3 end to end: a BYTES leaf through issuance, disclosure, parsing and verification.
//
// **No published type map selects BYTES**, so nothing in `type-maps/`, `corpus/type-maps/` or the
// committed corpus reaches this path - all 318 disclosed leaves in the 54 envelope fixtures are
// tag 2 STRING, and no vector carries a tag-5 value at all. Synthetic coverage is therefore the
// only coverage there can be, and it is required rather than optional: the carrier form is pinned
// by both envelope schemas today and would otherwise be first exercised by whichever profile
// binds `base64Binary`, long after five implementations had settled on a reading.
// ---------------------------------------------------------------------------------------------

const BYTES_MAP = LegacyPatternTypeMap.compile({
  typeMapVersion: '1.0.0',
  recordType: 'sg.gov.moh.pdt-healthcert',
  schemaVersion: '2.0',
  entries: [
    { pattern: 'version', jsonKind: 'string', tag: 2 },
    { pattern: 'type', jsonKind: 'string', tag: 2 },
    { pattern: 'validFrom', jsonKind: 'string', tag: 2 },
    { pattern: 'attachment', jsonKind: 'string', tag: 5 },
    { pattern: 'emptyAttachment', jsonKind: 'string', tag: 5 },
    { pattern: 'lettersAttachment', jsonKind: 'string', tag: 5 },
  ],
});

// The record carries BASE64, as a source record does. `attachment` is the `AAECAw==` of the
// section 6.3 test above; `emptyAttachment` is the empty-bytes case, which has to travel the whole
// way rather than only through `encodeValue`, because `value: ""` is what interacts with the
// disclosed-leaf `hasValue` rule.
//
// **`lettersAttachment` is `0xAB 0xCD 0xEF`, and it is here because every other BYTES value in
// this file spells out to letter-free hex.** `00010203` and `""` are identical under
// `toUpperCase`, so a `toHex` that emitted uppercase nibbles would satisfy both assertions below
// and the live tag-5 schema pattern as well. `hexNibble` has already been wrong once, so the
// emitted carrier needs at least one value whose spelling can distinguish the two cases.
const BYTES_RECORD = readJson(
  '{"version":"pdt-healthcert-v2.0","type":"PCR","validFrom":"2026-07-28T00:00:00Z",' +
    '"attachment":"AAECAw==","emptyAttachment":"","lettersAttachment":"q83v"}',
);

// The pdt floor - `version`, `type`, `validFrom` plus the reserved paths - and the three BYTES
// leaves. Revealing less would be rejected for the floor rather than for anything about BYTES.
const REVEAL_WITH_BYTES: Path[] = [
  [{ key: 'roax.recordType' }],
  [{ key: 'roax.schemaVersion' }],
  [{ key: 'roax.typeMap.id' }],
  [{ key: 'roax.recordId' }],
  [{ key: 'roax.issuer.id' }],
  [{ key: 'version' }],
  [{ key: 'type' }],
  [{ key: 'validFrom' }],
  [{ key: 'attachment' }],
  [{ key: 'emptyAttachment' }],
  [{ key: 'lettersAttachment' }],
];

const BYTES_VERIFIER = {
  knownProfiles: REGISTERED_PROFILES,
  resolverFor: (t: string) => (t === IDENTITY.recordType ? BYTES_MAP : undefined),
};

/** The `value` of the single-KEY disclosed leaf at `key`, as text, or `undefined`. */
function disclosedValueAt(envelope: JsonValue, key: string): string | undefined {
  const leaves = memberValue(memberValue(envelope, 'disclosure'), 'leaves');
  assert.equal(leaves.kind, 'array');
  const leaf = (leaves.kind === 'array' ? leaves.items : []).find((l) => leafKey(l) === key);
  assert.ok(leaf !== undefined, `no disclosed leaf at ${key}`);
  const value = memberValue(leaf, 'value');
  return value.kind === 'string' ? value.value : undefined;
}

test('a BYTES leaf issues, discloses as hex, parses and verifies (sections 6.3, 10)', () => {
  const full = issueFullCopy({
    record: BYTES_RECORD,
    identity: IDENTITY,
    resolver: BYTES_MAP,
    typeMapVersion: TYPE_MAP_VERSION,
  });
  // The full copy verifies, which is what proves the two halves agree: verification re-flattens
  // the record, so the base64 goes through `carrierFromJson` a second time and the hex it yields
  // goes through `encodeValue`. A projection and a decoder that disagreed would not close here.
  assert.equal(verifyEnvelope(parseEnvelope(full.document), BYTES_VERIFIER).kind, 'full');

  const disclosed = discloseFrom(full, { reveal: REVEAL_WITH_BYTES });
  // The assertion the finding is about: `00010203`, not `AAECAw==`.
  assert.equal(disclosedValueAt(disclosed, 'attachment'), '00010203');
  assert.equal(disclosedValueAt(disclosed, 'emptyAttachment'), '');
  // The one carrier here whose hex has letters, so it is the only assertion in this file that
  // fails if the emitted spelling is uppercase. `q83v` is `0xAB 0xCD 0xEF`.
  assert.equal(disclosedValueAt(disclosed, 'lettersAttachment'), 'abcdef');

  // And the disclosed copy verifies against the root of the full copy, so the hex carrier
  // reconstructs the same leaf hash the base64 record committed.
  const result = verifyEnvelope(parseEnvelope(disclosed), BYTES_VERIFIER);
  assert.equal(result.kind, 'disclosed');
  assert.equal(result.root, full.root);
});

test('the disclosed BYTES carrier matches the tag-5 pattern of both live envelope schemas', () => {
  // Read the pattern OUT OF THE SCHEMA rather than restating it here. A hardcoded copy would keep
  // agreeing with itself after the schema moved, which is the whole failure mode: this test exists
  // because the code and the schema had drifted apart with nothing comparing them.
  const disclosed = discloseFrom(
    issueFullCopy({
      record: BYTES_RECORD,
      identity: IDENTITY,
      resolver: BYTES_MAP,
      typeMapVersion: TYPE_MAP_VERSION,
    }),
    { reveal: REVEAL_WITH_BYTES },
  );
  // `lettersAttachment` is in this list for the reason given at the fixture: the schema pattern is
  // case-sensitive, and the other two carriers cannot tell the two cases apart.
  const values = ['attachment', 'emptyAttachment', 'lettersAttachment'].map((k) =>
    disclosedValueAt(disclosed, k),
  );

  for (const schema of ['schemas/envelope-1.0.json', 'schemas/envelope-2.0.json']) {
    const file = resolve(REPO_ROOT, schema);
    // Never silently skipped: the schemas are committed to this repository, so an absent one is a
    // defect to report rather than a check to drop.
    assert.ok(existsSync(file), `${schema} is missing, so the live carrier check cannot run`);
    const pattern = tagFivePattern(readJsonFile(file));
    assert.ok(pattern !== undefined, `${schema} pins no tag-5 value pattern`);
    for (const value of values) {
      assert.ok(typeof value === 'string', 'a BYTES carrier is a string');
      assert.match(value, new RegExp(pattern), `${schema} rejects the carrier ${value}`);
    }
    // The base64 the code used to emit is rejected by that same live pattern, so the check has
    // teeth rather than passing for any string.
    assert.ok(!new RegExp(pattern).test('AAECAw=='), `${schema} would have accepted base64`);
  }
});

// ---------------------------------------------------------------------------------------------
// Section 9: sharing the subtree heads across audit paths changes no byte.
//
// The naive forms below are the ones this package computed before the heads were shared, kept here
// as the oracle. `docs/conformance-corpus.md` class 8 mandates the sizes: the RFC 9162 split rule
// goes wrong only away from powers of two.
// ---------------------------------------------------------------------------------------------

test('shared subtree heads reproduce a per-proof recomputation at every index (section 9)', () => {
  const hash = resolveHashFunction('SHA-256');
  const node = (left: Uint8Array, right: Uint8Array): Uint8Array => {
    const preimage = new Uint8Array(1 + left.length + right.length);
    preimage[0] = 0x01;
    preimage.set(left, 1);
    preimage.set(right, 1 + left.length);
    return hash.hash(preimage);
  };
  const naiveHead = (leaves: readonly Uint8Array[]): Uint8Array => {
    if (leaves.length === 1) {
      return leaves[0] as Uint8Array;
    }
    const k = splitPoint(leaves.length);
    return node(naiveHead(leaves.slice(0, k)), naiveHead(leaves.slice(k)));
  };
  const naiveProof = (leaves: readonly Uint8Array[], index: number): Uint8Array[] => {
    if (leaves.length === 1) {
      return [];
    }
    const k = splitPoint(leaves.length);
    if (index < k) {
      const path = naiveProof(leaves.slice(0, k), index);
      path.push(naiveHead(leaves.slice(k)));
      return path;
    }
    const path = naiveProof(leaves.slice(k), index - k);
    path.push(naiveHead(leaves.slice(0, k)));
    return path;
  };

  for (const size of [1, 2, 3, 5, 7, 8, 9, 130]) {
    const leaves = Array.from({ length: size }, (_, i) =>
      hash.hash(Uint8Array.of(i & 0xff, (i >> 8) & 0xff)),
    );
    const tree = buildMerkleTree(hash, leaves);
    const expectedRoot = toHex(naiveHead(leaves));
    assert.equal(toHex(tree.root), expectedRoot, `root at size ${size}`);
    assert.equal(toHex(merkleTreeHead(hash, leaves)), expectedRoot, `MTH at size ${size}`);
    for (let i = 0; i < size; i += 1) {
      const shared = tree.auditPath(i).map(toHex);
      assert.deepEqual(shared, naiveProof(leaves, i).map(toHex), `path ${i} of ${size}`);
      assert.deepEqual(inclusionProof(hash, leaves, i).map(toHex), shared);
      assert.ok(
        verifyInclusion(hash, leaves[i] as Uint8Array, i, size, tree.auditPath(i), tree.root),
        `proof ${i} of ${size} verifies`,
      );
    }
    // Still a `RangeError` and still raised before anything is hashed (`src/errors.js`).
    assert.throws(() => inclusionProof(hash, leaves, size), RangeError);
    assert.throws(() => tree.auditPath(-1), RangeError);
  }
});

console.log(`unit: ${passed} passed, ${failures.length} failed`);
for (const f of failures) {
  console.log(`  FAIL ${f}`);
}
process.exitCode = failures.length === 0 ? 0 : 1;
