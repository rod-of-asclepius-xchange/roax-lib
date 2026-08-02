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
 *
 * **What this package throws.** Every rejection of input is a `RoaxError` carrying a
 * `RoaxErrorCode`, which is the conformance corpus's own reason string. The one exception is a
 * precondition violation by the caller: drawing an audit path for a leaf index outside the tree
 * throws a `RangeError`, whether through `inclusionProof`, `MerkleTree.auditPath` or
 * `Commitment.auditPathFor`. See `./errors.js` for why that one is deliberately outside the
 * taxonomy.
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
  hexNibble,
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
  resolveOrdering,
  ORDERING_DEFAULT,
  ORDERING_DOMAIN_SUFFIX,
  type HashAlgName,
  type Ordering,
  type HashFunction,
} from './hash.js';
export { leafHash, SALT_LENGTH, type Leaf } from './leaf.js';
export {
  merkleTreeHead,
  buildMerkleTree,
  inclusionProof,
  verifyInclusion,
  splitPoint,
  type MerkleTree,
} from './tree.js';
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
  type UnknownMember,
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
