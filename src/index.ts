/**
 * `@roax/canon` - the TypeScript implementation of `ROAX-CANON/1`.
 *
 * Canonical serialization, commitment and selective disclosure for health records, written from
 * [`docs/spec/roax-canon-1.md`](../docs/spec/roax-canon-1.md).
 *
 * **The one rule that governs everything here: a number is never parsed through a float.**
 * `JSON.parse` destroys `0.010` into `0.01` before any of this code would see it, and in a medical
 * dosage that is a different statement about a drug. `readJson` in `./json.js` is a hand-written
 * scanner for that reason, and nothing in this package calls `JSON.parse` on anything it commits
 * to.
 */

export { RoaxError, type RoaxErrorCode } from './errors.js';
export {
  readJson,
  writeJson,
  fromJsValue,
  assertNoUnpairedSurrogate,
  jsonKindOf,
  type JsonValue,
  type JsonKind,
} from './json.js';
export { canonicalizeInteger, canonicalizeDecimal, MAX_TOTAL_DIGITS } from './numbers.js';
export {
  u32be,
  u64be,
  utf8,
  nfc,
  toHex,
  fromHex,
  decodeBase64Strict,
  describeUnicodeEnvironment,
} from './bytes.js';
export {
  encodePath,
  displayPath,
  compareBytes,
  isKeySegment,
  type Path,
  type PathSegment,
  type KeySegment,
  type IndexSegment,
} from './path.js';
export {
  TypeTag,
  isTypeTag,
  encodeValue,
  carrierFromJson,
  tagCarriesNoValue,
  type TypeTagValue,
  type CarrierValue,
} from './value.js';
export {
  resolveHashFunction,
  domainString,
  CANON_VERSION,
  type HashAlgName,
  type HashFunction,
} from './hash.js';
export { leafHash, SALT_LENGTH, type Leaf } from './leaf.js';
export { merkleTreeHead, inclusionProof, verifyInclusion, splitPoint } from './tree.js';
export {
  flattenRecord,
  leafSet,
  type FlatLeaf,
  type OrderedLeaf,
  type EmptyContainerPolicy,
  type FlattenOptions,
} from './flatten.js';
export {
  RESERVED_PATHS,
  RESERVED_PREFIX,
  reservedLeaves,
  mandatoryReservedPaths,
  assertRecordPathAllowed,
  type RecordIdentity,
  type ReservedLeafSpec,
} from './reserved.js';
export {
  LegacyPatternTypeMap,
  type TypeTagResolver,
} from './typemap.js';
export {
  commitRecord,
  drawSalt,
  PathKeyedSalts,
  PositionalSalts,
  FreshSalts,
  saltsFromHex,
  type SaltSource,
  type Commitment,
  type CommittedLeaf,
  type CommitOptions,
} from './commit.js';
export {
  PROFILE_FLOORS,
  REGISTERED_PROFILES,
  floorFor,
  type ProfileFloor,
} from './profiles.js';
export {
  parseEnvelope,
  verifyEnvelope,
  type Envelope,
  type DisclosedLeaf,
  type LeafSaltEntry,
  type VerifierConfig,
  type VerificationResult,
} from './envelope.js';
export {
  issueFullCopy,
  discloseFrom,
  type IssueOptions,
  type FullCopy,
  type DiscloseOptions,
} from './issue.js';
