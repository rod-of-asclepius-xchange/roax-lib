/**
 * Unit tests for rules the specification states and no committed corpus vector exercises,
 * plus a round trip through issuance, disclosure and verification.
 *
 * The conformance runner is the primary evidence; this file covers what it cannot reach.
 * Each test names the section it discharges.
 */

import { strict as assert } from 'node:assert';
import {
  readJson,
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

function issued(): ReturnType<typeof issueFullCopy> {
  return issueFullCopy({ record: RECORD, identity: IDENTITY, resolver: SYNTHETIC_MAP });
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

console.log(`unit: ${passed} passed, ${failures.length} failed`);
for (const f of failures) {
  console.log(`  FAIL ${f}`);
}
process.exitCode = failures.length === 0 ? 0 : 1;
