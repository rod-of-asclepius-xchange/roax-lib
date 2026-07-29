/**
 * Type tags and value encoding (specification section 6).
 */

import { fail } from './errors.js';
import { canonicalizeDecimal, canonicalizeInteger } from './numbers.js';
import { concatBytes, decodeBase64Strict, fromHex, nfc, toHex, u32be, u64be, utf8 } from './bytes.js';
import { assertNoUnpairedSurrogate, type JsonValue } from './json.js';

export const TypeTag = {
  NULL: 0,
  BOOL: 1,
  STRING: 2,
  INTEGER: 3,
  DECIMAL: 4,
  BYTES: 5,
  EMPTY_ARRAY: 6,
  EMPTY_OBJECT: 7,
  BLOB_REF: 8,
} as const;

export type TypeTagValue = (typeof TypeTag)[keyof typeof TypeTag];

export function isTypeTag(n: number): n is TypeTagValue {
  return Number.isInteger(n) && n >= 0 && n <= 8;
}

/**
 * The carrier form of a leaf value: the shape an envelope or a vector file writes it in.
 *
 * A JavaScript `number` is absent from this union deliberately, at every depth. INTEGER and
 * DECIMAL travel as strings because a JSON number in a carrier would be destroyed by the very
 * parser under test (specification section 6.4), and `BLOB_REF`'s byte length travels as a string
 * for the same reason - it is a hash-preimage input.
 *
 * **BYTES travels as lowercase hex of even length, NOT as the record's base64.** The carrier form
 * is not the record form for this one tag: both envelope schemas pin `^([0-9a-f]{2})*$` for a
 * disclosed tag-5 value, while specification section 6.3 governs the base64 a SOURCE RECORD may
 * embed. `carrierFromJson` is the single place that projection happens.
 */
export type CarrierValue =
  | boolean
  | string
  | { readonly blobByteLength: string; readonly blobDigest: string };

/** The tags that carry no value bytes at all (specification section 6.1). */
export function tagCarriesNoValue(tag: TypeTagValue): boolean {
  return tag === TypeTag.NULL || tag === TypeTag.EMPTY_ARRAY || tag === TypeTag.EMPTY_OBJECT;
}

/**
 * Encodes a value under its tag (specification section 6.1).
 *
 * | Tag | Name | Encoded value bytes |
 * |---:|---|---|
 * | 0 | `NULL` | empty |
 * | 1 | `BOOL` | `0x01` if true, `0x00` if false |
 * | 2 | `STRING` | `utf8(NFC(s))` |
 * | 3 | `INTEGER` | ASCII canonical integer |
 * | 4 | `DECIMAL` | ASCII canonical decimal |
 * | 5 | `BYTES` | the bytes themselves |
 * | 6 | `EMPTY_ARRAY` | empty |
 * | 7 | `EMPTY_OBJECT` | empty |
 * | 8 | `BLOB_REF` | `u64be(blobByteLength) ‖ u32be(len(blobDigest)) ‖ blobDigest` |
 *
 * Tag 8 encodes here but MUST NOT be issued or accepted in an envelope until a profile declares
 * the binding (specification section 6.5). The carrier form is pinned now so it does not have to
 * be retrofitted after five implementations exist; the prohibition lives at the issuance and
 * verification boundaries, which is where `schemas/conformance-corpus-1.0.json` also places it.
 *
 * Section 6.5 states the prohibition as two rejections, and BOTH are implemented rather than one:
 *
 * - a record whose map binds a path to tag 8 - `carrierFromJson` below, reached at issuance and
 *   again whenever a full copy is re-flattened, plus the explicit sweep in `issueFullCopy` for a
 *   resolver this library did not compile;
 * - an envelope carrying a tag-8 leaf - the first check in the per-leaf loop of
 *   `verifyDisclosedCopy`, because a disclosed copy is never re-flattened and would otherwise
 *   reach `encodeValue` and verify.
 */
export function encodeValue(tag: TypeTagValue, value: CarrierValue | undefined): Uint8Array {
  switch (tag) {
    case TypeTag.NULL:
    case TypeTag.EMPTY_ARRAY:
    case TypeTag.EMPTY_OBJECT:
      return new Uint8Array(0);
    case TypeTag.BOOL:
      if (typeof value !== 'boolean') {
        fail('value-type-mismatch', 'a BOOL leaf carries a JSON boolean');
      }
      return Uint8Array.of(value ? 0x01 : 0x00);
    case TypeTag.STRING: {
      if (typeof value !== 'string') {
        fail('value-type-mismatch', 'a STRING leaf carries a JSON string');
      }
      assertNoUnpairedSurrogate(value, 'a STRING value');
      return utf8(nfc(value));
    }
    case TypeTag.INTEGER: {
      if (typeof value !== 'string') {
        fail('value-type-mismatch', 'an INTEGER leaf carries its literal as a string');
      }
      // ASCII by construction: the grammar admits only `-` and digits.
      return utf8(canonicalizeInteger(value));
    }
    case TypeTag.DECIMAL: {
      if (typeof value !== 'string') {
        fail('value-type-mismatch', 'a DECIMAL leaf carries its literal as a string');
      }
      return utf8(canonicalizeDecimal(value));
    }
    case TypeTag.BYTES: {
      if (typeof value !== 'string') {
        fail('value-type-mismatch', 'a BYTES leaf carries lowercase hex');
      }
      // The CARRIER is lowercase hex of even length, which is what both envelope schemas pin
      // (`schemas/envelope-1.0.json:259-264`, `schemas/envelope-2.0.json:260-265`). The base64 of
      // section 6.3 is a fact about the SOURCE RECORD and is decoded once, in `carrierFromJson`
      // below; by the time a value reaches here it has already been through that projection, or it
      // arrived from an envelope that carries the hex form directly. Decoding base64 here instead
      // would emit a schema-invalid disclosed copy that still verified against its own root.
      return fromHex(value, 'a BYTES value');
    }
    case TypeTag.BLOB_REF: {
      if (typeof value !== 'object' || value === null || Array.isArray(value)) {
        fail('value-type-mismatch', 'a BLOB_REF leaf carries {blobByteLength, blobDigest}');
      }
      const { blobByteLength, blobDigest } = value;
      if (typeof blobByteLength !== 'string' || typeof blobDigest !== 'string') {
        fail('value-type-mismatch', 'BLOB_REF members are strings');
      }
      // The length travels as a decimal string and is read with BigInt, never through a float:
      // it is a hash-preimage input like any other.
      const length = BigInt(canonicalizeInteger(blobByteLength));
      const digest = fromHex(blobDigest, 'blobDigest');
      return concatBytes([u64be(length), u32be(digest.length), digest]);
    }
    default:
      return fail('value-type-mismatch', `unknown type tag ${String(tag)}`);
  }
}

/**
 * Projects a parsed JSON value onto the carrier form its resolved tag requires.
 *
 * The tag comes from the type map and the value from the record, so a disagreement between them
 * is a real error rather than something to coerce. Specification section 4 is explicit that the
 * tag is NOT inferred from the literal's syntax, so this function never picks a tag: it checks
 * that the observed value can carry the tag it was given.
 */
export function carrierFromJson(tag: TypeTagValue, value: JsonValue): CarrierValue | undefined {
  switch (tag) {
    case TypeTag.NULL:
      if (value.kind !== 'null') {
        fail('value-type-mismatch', 'a NULL leaf requires a JSON null');
      }
      return undefined;
    case TypeTag.EMPTY_ARRAY:
      if (value.kind !== 'array' || value.items.length !== 0) {
        fail('value-type-mismatch', 'an EMPTY_ARRAY leaf requires an empty JSON array');
      }
      return undefined;
    case TypeTag.EMPTY_OBJECT:
      if (value.kind !== 'object' || value.members.length !== 0) {
        fail('value-type-mismatch', 'an EMPTY_OBJECT leaf requires an empty JSON object');
      }
      return undefined;
    case TypeTag.BOOL:
      if (value.kind !== 'boolean') {
        fail('value-type-mismatch', 'a BOOL leaf requires a JSON boolean');
      }
      return value.value;
    case TypeTag.STRING:
      if (value.kind !== 'string') {
        fail('value-type-mismatch', `tag ${tag} requires a JSON string`);
      }
      return value.value;
    case TypeTag.BYTES: {
      if (value.kind !== 'string') {
        fail('value-type-mismatch', `tag ${tag} requires a JSON string`);
      }
      // **This is the one projection that changes the text, and it is where base64 stops.** The
      // record holds base64 (specification section 6.3); the carrier holds lowercase hex, because
      // that is what both envelope schemas require of a disclosed tag-5 value. Decoding here rather
      // than at `encodeValue` is what makes the two agree: a disclosed copy emits the hex, and the
      // non-canonical base64 forms section 6.3 requires rejecting are rejected once, at the
      // boundary where the record is read, rather than at every later re-encode.
      //
      // The bytes committed are unchanged by this - `fromHex(toHex(b))` is `b` - so it moves no
      // root. Empty bytes survive as the empty string, which both schema patterns admit.
      return toHex(decodeBase64Strict(value.value));
    }
    case TypeTag.INTEGER:
    case TypeTag.DECIMAL:
      if (value.kind !== 'number') {
        fail('value-type-mismatch', `tag ${tag} requires a JSON number`);
      }
      // The VERBATIM literal, straight from the scanner. This is the one hand-off in the whole
      // pipeline where a float-based reader would already have destroyed the value.
      return value.literal;
    case TypeTag.BLOB_REF:
      return fail(
        'blob-ref-not-selectable',
        'no version-1 profile selects BLOB_REF, so a record binding a path to tag 8 ' +
          'MUST be rejected (specification section 6.5)',
      );
    default:
      return fail('value-type-mismatch', `unknown type tag ${String(tag)}`);
  }
}
