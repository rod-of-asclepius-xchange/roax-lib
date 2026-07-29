/**
 * The envelope: issuance, selective disclosure and verification (specification sections 10 and 11).
 *
 * Two envelope schema versions exist and a verifier selects one per envelope and MUST NOT merge
 * them (section 11). `schemas/envelope-2.0.json` requires the `typeMap` member and commits
 * `roax.typeMap.id`, so its leaf and salt floors are 6; `schemas/envelope-1.0.json` predates that
 * binding, still governs every envelope issued under it, and has floors of 5. This module derives
 * the reserved-leaf set and the reserved half of the disclosure floor from the envelope in hand
 * rather than from a constant, which is what lets one verifier read both.
 */

import { fail, RoaxError } from './errors.js';
import { toHex, fromHex, nfc } from './bytes.js';
import { encodePath, displayPath, isKeySegment, type Path, type PathSegment } from './path.js';
import { resolveHashFunction, CANON_VERSION, type HashAlgName } from './hash.js';
import { leafHash } from './leaf.js';
import { verifyInclusion } from './tree.js';
import {
  RESERVED_PATHS,
  mandatoryReservedPaths,
  type RecordIdentity,
} from './reserved.js';
import {
  isTypeTag,
  tagCarriesNoValue,
  TypeTag,
  type CarrierValue,
  type TypeTagValue,
} from './value.js';
import { commitRecord, PathKeyedSalts, type SaltSource } from './commit.js';
import type { EmptyContainerPolicy } from './flatten.js';
import type { TypeTagResolver } from './typemap.js';
import type { JsonValue } from './json.js';
import { floorFor, REGISTERED_PROFILES } from './profiles.js';

export interface LeafSaltEntry {
  readonly segments: Path;
  readonly salt: string;
}

export interface DisclosedLeaf {
  readonly segments: Path;
  readonly displayPath?: string | undefined;
  readonly index: number;
  readonly tag: TypeTagValue;
  readonly value?: CarrierValue | undefined;
  readonly hasValue: boolean;
  readonly salt: string;
  readonly auditPath: readonly string[];
}

/**
 * A member the envelope schemas do not define, together with where in the envelope it sat.
 *
 * The name is carried SEPARATELY from its location rather than joined into one dotted string,
 * because a member name may itself contain a dot and the seed guard of section 7.3 rule 3 matches
 * the name exactly. Joining them would force the guard to split a display string to recover the
 * name, which is the section 5.2 trap one layer out from paths.
 */
export interface UnknownMember {
  /** Where it sat, for the rejection message alone. Never parsed and never matched against. */
  readonly where: string;
  readonly name: string;
}

export interface Envelope {
  readonly canon: string;
  readonly hashAlg: string;
  readonly recordType: string;
  readonly schemaVersion: string;
  readonly typeMap?: { readonly id: string; readonly version: string } | undefined;
  readonly recordId: string;
  readonly root: string;
  readonly leafCount: number;
  readonly issuer: { readonly id: string; readonly keyId?: string | undefined };
  readonly anchor?:
    | {
        readonly chainId: number;
        readonly registry: string;
        readonly txHash?: string | undefined;
        readonly anchoredAt?: string | undefined;
      }
    | undefined;
  readonly record?: JsonValue | undefined;
  readonly salts?: readonly LeafSaltEntry[] | undefined;
  readonly disclosure?: { readonly mode: string; readonly leaves: readonly DisclosedLeaf[] } | undefined;
  /**
   * Members the schemas do not define, at EVERY depth the envelope itself owns. Every one of them
   * is a rejection.
   *
   * `record` is deliberately not descended into: its members are the issuer's own record data,
   * governed by the record profile rather than by the envelope schema, and a record field named
   * `seed` is a clinical field rather than a salt seed.
   */
  readonly unknownMembers: readonly UnknownMember[];
}

/**
 * What the VERIFIER is configured with.
 *
 * Every one of these is the verifier's own, never the envelope's. Specification section 11.3
 * states normatively that fields outside the root are hints and never authority, and section 7.4
 * requires `hashAlg` to come from the anchoring registry (H2) and to be filtered by the verifier's
 * own allow-list (H3).
 */
export interface VerifierConfig {
  /** H3: algorithms this verifier accepts, regardless of what the registry or envelope says. */
  readonly hashAlgAllowList?: readonly HashAlgName[] | undefined;
  /** The profiles this verifier is configured with. An unknown one fails closed (section 12.2). */
  readonly knownProfiles?: ReadonlySet<string> | undefined;
  /** H2: the `(root, hashAlg)` pair the verifier's OWN anchoring registry records. */
  readonly anchoredRoot?: string | undefined;
  readonly anchoredHashAlg?: HashAlgName | undefined;
  /** The registry the verifier is configured with. An envelope naming another is never read. */
  readonly registryAddress?: string | undefined;
  readonly registryChainId?: number | undefined;
  /** Resolves the exact type map for a `recordType`, when this verifier has one. */
  readonly resolverFor?: ((recordType: string) => TypeTagResolver | undefined) | undefined;
  /**
   * Whether a disclosed record leaf's tag MUST be checked against the selected map
   * (specification section 10 step 1).
   *
   * Defaults to `true`. The conformance runner sets it to `false` and reports the fact, because
   * `corpus/type-maps/` carries no `hl7.fhir.bundle` map and the eight `floor-hl7-fhir-bundle-*`
   * fixtures disclose a record leaf. See the findings document.
   */
  readonly requireTypeMapForDisclosedLeaves?: boolean | undefined;
  /**
   * Whether this verifier accepts ONLY envelopes that bind the exact type-map artifact
   * (specification section 11.2, `schemas/envelope-2.0.json`).
   *
   * **It governs BOTH copy kinds.** It is read once, beside the other allow-lists, and rejects any
   * envelope carrying no outer `typeMap` member before either copy kind is verified - because like
   * `hashAlgAllowList` and `knownProfiles` it settles whether this verifier can proceed at all
   * rather than which policy to apply.
   *
   * Defaults to `false`, which is the permissive reading and NOT an endorsement: an envelope that
   * binds no type-map artifact is reported as undischarged on every verification, full copy and
   * disclosed copy alike, rather than passed silently. The default is permissive because
   * `schemas/envelope-1.0.json` predates the binding, still governs every envelope issued under
   * it, and is legitimately verifiable - so failing closed by default would reject conforming
   * documents rather than forged ones.
   *
   * What the two copy kinds do NOT share is what is at stake, and the reports say so separately.
   * In a full copy the binding is authenticated by the rebuild: the reserved leaves come from the
   * identity, so removing the member removes a leaf and the copy fails closed on the derived leaf
   * count, on the salts length or on the root, according to what else the edit changed. What is
   * undischarged there is the absence of a binding rather than a possible holder edit. In a
   * disclosed copy nothing is re-flattened, so an absent member and an absent leaf together are
   * genuinely indistinguishable from a stripped pair.
   *
   * A deployment that issues and accepts only envelope-2.0 documents sets this to `true` and
   * closes both outright. See the findings document.
   */
  readonly requireTypeMapIdentity?: boolean | undefined;
  readonly emptyContainerPolicy?: EmptyContainerPolicy | undefined;
}

const DEFAULT_ALLOW_LIST: readonly HashAlgName[] = ['SHA-256'];

/** Top-level members `schemas/envelope-2.0.json` defines. Anything else is a rejection. */
const KNOWN_TOP_LEVEL = new Set([
  'canon',
  'hashAlg',
  'recordType',
  'schemaVersion',
  'typeMap',
  'recordId',
  'root',
  'leafCount',
  'issuer',
  'anchor',
  'disclosure',
  'record',
  'salts',
]);

/**
 * The members each NESTED object of the envelope defines.
 *
 * The top-level scan alone leaves a hole the seed guard below cannot see: `disclosure` is a known
 * top-level member, so nothing would look inside it and an envelope carrying
 * `disclosure: {mode, leaves, masterSalt}` would pass rule 3 entirely. A guard with a hole binds
 * less than it claims, so every object the envelope schemas define is scanned to the same
 * standard. `record` is the one exception and the reason is on the `unknownMembers` field.
 */
const KNOWN_TYPE_MAP = new Set(['id', 'version']);
const KNOWN_ISSUER = new Set(['id', 'keyId']);
const KNOWN_ANCHOR = new Set(['chainId', 'registry', 'txHash', 'anchoredAt']);
const KNOWN_DISCLOSURE = new Set(['mode', 'leaves']);
const KNOWN_DISCLOSED_LEAF = new Set([
  'segments',
  'displayPath',
  'index',
  'tag',
  'value',
  'salt',
  'auditPath',
]);
const KNOWN_SALT_ENTRY = new Set(['segments', 'salt']);
const KNOWN_SEGMENT = new Set(['key', 'index']);

/**
 * Member names that would carry, or look like they carry, a value from which a withheld leaf's
 * salt could be obtained.
 *
 * Specification section 7.3 rule 3 forbids any such value. The rule is VACUOUS today - decision D4
 * was ruled D4b and no derivation exists - and it is enforced anyway, because it binds any future
 * revision that reintroduces a derived salt and because a revision that added a seed would hand
 * every holder the ability to recompute every withheld leaf's salt in an envelope that still
 * verified correctly.
 */
const SEED_SHAPED_MEMBERS = new Set(['masterSalt', 'masterSaltHex', 'seed', 'saltSeed', 'kdfKey']);

function memberOf(object: JsonValue, name: string): JsonValue | undefined {
  if (object.kind !== 'object') {
    return undefined;
  }
  for (const [key, value] of object.members) {
    if (key === name) {
      return value;
    }
  }
  return undefined;
}

function requiredString(object: JsonValue, name: string): string {
  const v = memberOf(object, name);
  if (v === undefined || v.kind !== 'string') {
    fail('envelope-malformed', `the envelope member ${name} is missing or is not a string`);
  }
  return v.value;
}

const INTEGER_LITERAL = /^(?:0|[1-9][0-9]*)$/;
const MAX_SAFE = BigInt(Number.MAX_SAFE_INTEGER);

/**
 * Reads a STRUCTURAL integer - a count, an index, a chain identifier or a type tag.
 *
 * A structural integer is not a record value, so reading one is not the section 6.4 hazard. **It is
 * not therefore uncommitted:** a `tag` is written into the leaf preimage as `Uint8Array.of(tag)`
 * and an INDEX segment is written into `encodePath` as `u32be(i)`, so two of the four reach a hash.
 * What makes that safe is exactness rather than irrelevance.
 *
 * The literal is checked against the integer grammar, converted with `BigInt`, which is exact for
 * a digit string of any length, and only then narrowed - so the range check happens BEFORE any
 * machine number exists rather than after one has already rounded. `Number(exact)` below is
 * therefore lossless by construction, which `Number(literal)` followed by `Number.isSafeInteger`
 * is not: the latter rounds a 20-digit literal first and asks afterwards.
 *
 * ONE function reads all four sites. They were four hand-rolled copies, and the copy that read a
 * disclosed leaf's `tag` had neither the grammar check nor the range check, so `2.0`, `2e0` and
 * `-0` were silently accepted as tags.
 */
function structuralInteger(literal: string, where: string): number {
  if (!INTEGER_LITERAL.test(literal)) {
    fail('envelope-malformed', `${where} is not a non-negative integer literal`);
  }
  const exact = BigInt(literal);
  if (exact > MAX_SAFE) {
    fail('envelope-malformed', `${where} is outside the safe integer range`);
  }
  return Number(exact);
}

function requiredCount(object: JsonValue, name: string): number {
  const v = memberOf(object, name);
  if (v === undefined || v.kind !== 'number') {
    fail('envelope-malformed', `the envelope member ${name} is missing or is not a number`);
  }
  return structuralInteger(v.literal, `the envelope member ${name}`);
}

/** Records every member of `node` that `known` does not define. Names only; values are not read. */
function collectUnknown(
  node: JsonValue | undefined,
  where: string,
  known: ReadonlySet<string>,
  out: UnknownMember[],
): void {
  if (node === undefined || node.kind !== 'object') {
    return;
  }
  for (const [name] of node.members) {
    if (!known.has(name)) {
      out.push({ where, name });
    }
  }
}

function segmentsFrom(
  node: JsonValue | undefined,
  where: string,
  unknown: UnknownMember[],
): Path {
  if (node === undefined || node.kind !== 'array') {
    fail('envelope-malformed', `${where} is missing or is not an array of segments`);
  }
  return node.items.map((item): PathSegment => {
    collectUnknown(item, `${where} path segment`, KNOWN_SEGMENT, unknown);
    const key = memberOf(item, 'key');
    if (key !== undefined) {
      if (key.kind !== 'string') {
        fail('envelope-malformed', `${where} carries a non-string key`);
      }
      return { key: key.value };
    }
    const index = memberOf(item, 'index');
    if (index === undefined || index.kind !== 'number') {
      fail('envelope-malformed', `${where} carries a segment that is neither a key nor an index`);
    }
    return { index: structuralInteger(index.literal, `${where} index`) };
  });
}

function carrierFrom(node: JsonValue, where: string): CarrierValue {
  switch (node.kind) {
    case 'string':
      return node.value;
    case 'boolean':
      return node.value;
    case 'number':
      // A DECIMAL or INTEGER value inside an envelope travels as a STRING, exactly as it does in
      // a corpus vector, for the reason section 6.4 gives. A bare JSON number here is a malformed
      // envelope rather than something to coerce.
      fail(
        'envelope-malformed',
        `${where} carries a bare JSON number; INTEGER and DECIMAL values travel as strings`,
      );
      break;
    case 'object': {
      const length = memberOf(node, 'blobByteLength');
      const digest = memberOf(node, 'blobDigest');
      if (length?.kind === 'string' && digest?.kind === 'string') {
        return { blobByteLength: length.value, blobDigest: digest.value };
      }
      fail('envelope-malformed', `${where} is not a value any type tag carries`);
      break;
    }
    default:
      fail('envelope-malformed', `${where} is not a value any type tag carries`);
  }
}

/** Reads a parsed JSON document as an envelope, without yet judging it. */
export function parseEnvelope(document: JsonValue): Envelope {
  if (document.kind !== 'object') {
    fail('envelope-malformed', 'an envelope is a JSON object');
  }
  const unknownMembers: UnknownMember[] = [];
  collectUnknown(document, 'the envelope', KNOWN_TOP_LEVEL, unknownMembers);

  const typeMapNode = memberOf(document, 'typeMap');
  collectUnknown(typeMapNode, 'typeMap', KNOWN_TYPE_MAP, unknownMembers);
  const issuerNode = memberOf(document, 'issuer');
  if (issuerNode === undefined || issuerNode.kind !== 'object') {
    fail('envelope-malformed', 'the envelope member issuer is missing or is not an object');
  }
  collectUnknown(issuerNode, 'issuer', KNOWN_ISSUER, unknownMembers);
  const issuerKeyId = memberOf(issuerNode, 'keyId');
  const anchorNode = memberOf(document, 'anchor');
  collectUnknown(anchorNode, 'anchor', KNOWN_ANCHOR, unknownMembers);
  const saltsNode = memberOf(document, 'salts');
  const disclosureNode = memberOf(document, 'disclosure');

  const salts =
    saltsNode === undefined
      ? undefined
      : saltsNode.kind === 'array'
        ? saltsNode.items.map((item) => {
            collectUnknown(item, 'a salts entry', KNOWN_SALT_ENTRY, unknownMembers);
            return {
              segments: segmentsFrom(memberOf(item, 'segments'), 'a salts entry', unknownMembers),
              salt: requiredString(item, 'salt'),
            };
          })
        : fail('envelope-malformed', 'salts is not an array');

  const disclosure =
    disclosureNode === undefined ? undefined : parseDisclosure(disclosureNode, unknownMembers);

  return {
    canon: requiredString(document, 'canon'),
    hashAlg: requiredString(document, 'hashAlg'),
    recordType: requiredString(document, 'recordType'),
    schemaVersion: requiredString(document, 'schemaVersion'),
    typeMap:
      typeMapNode === undefined
        ? undefined
        : {
            id: requiredString(typeMapNode, 'id'),
            version: requiredString(typeMapNode, 'version'),
          },
    recordId: requiredString(document, 'recordId'),
    root: requiredString(document, 'root'),
    leafCount: requiredCount(document, 'leafCount'),
    issuer: {
      id: requiredString(issuerNode, 'id'),
      keyId: issuerKeyId?.kind === 'string' ? issuerKeyId.value : undefined,
    },
    anchor:
      anchorNode === undefined
        ? undefined
        : {
            chainId: requiredCount(anchorNode, 'chainId'),
            registry: requiredString(anchorNode, 'registry'),
            txHash: memberOf(anchorNode, 'txHash')?.kind === 'string'
              ? (memberOf(anchorNode, 'txHash') as { value: string }).value
              : undefined,
            anchoredAt: memberOf(anchorNode, 'anchoredAt')?.kind === 'string'
              ? (memberOf(anchorNode, 'anchoredAt') as { value: string }).value
              : undefined,
          },
    record: memberOf(document, 'record'),
    salts,
    disclosure,
    unknownMembers,
  };
}

function parseDisclosure(
  node: JsonValue,
  unknown: UnknownMember[],
): { mode: string; leaves: DisclosedLeaf[] } {
  collectUnknown(node, 'disclosure', KNOWN_DISCLOSURE, unknown);
  const leavesNode = memberOf(node, 'leaves');
  if (leavesNode === undefined || leavesNode.kind !== 'array') {
    fail('envelope-malformed', 'disclosure.leaves is missing or is not an array');
  }
  const leaves = leavesNode.items.map((item): DisclosedLeaf => {
    collectUnknown(item, 'a disclosed leaf', KNOWN_DISCLOSED_LEAF, unknown);
    const tagNode = memberOf(item, 'tag');
    if (tagNode === undefined || tagNode.kind !== 'number') {
      fail('envelope-malformed', 'a disclosed leaf carries no valid tag');
    }
    const tag = structuralInteger(tagNode.literal, "a disclosed leaf's tag");
    if (!isTypeTag(tag)) {
      fail('envelope-malformed', 'a disclosed leaf carries no valid tag');
    }
    const valueNode = memberOf(item, 'value');
    const displayNode = memberOf(item, 'displayPath');
    const auditNode = memberOf(item, 'auditPath');
    if (auditNode === undefined || auditNode.kind !== 'array') {
      fail('envelope-malformed', 'a disclosed leaf carries no auditPath array');
    }
    return {
      segments: segmentsFrom(memberOf(item, 'segments'), 'a disclosed leaf', unknown),
      // Display only, and never an input to anything the verifier computes (section 5.2).
      displayPath: displayNode?.kind === 'string' ? displayNode.value : undefined,
      index: requiredCount(item, 'index'),
      tag,
      value: valueNode === undefined ? undefined : carrierFrom(valueNode, 'a disclosed value'),
      hasValue: valueNode !== undefined,
      salt: requiredString(item, 'salt'),
      auditPath: auditNode.items.map((h) => {
        if (h.kind !== 'string') {
          fail('envelope-malformed', 'an auditPath entry is not a string');
        }
        return h.value;
      }),
    };
  });
  return { mode: requiredString(node, 'mode'), leaves };
}

export interface VerificationResult {
  readonly kind: 'full' | 'disclosed';
  readonly root: string;
  readonly leafCount: number;
  /**
   * Steps the specification requires that this verifier could not discharge, each with its reason.
   * An empty array means every applicable step ran.
   */
  readonly undischarged: readonly string[];
}

/**
 * Verifies an envelope, throwing a `RoaxError` naming the exact reason on rejection.
 *
 * The ORDER below is derived rather than chosen, and the derivation is specification section 11.3:
 * a field outside the root is never authority, so authority is established before an outer field
 * SELECTS anything. Choosing the disclosure floor from the envelope's `recordType` and validating
 * it afterwards is trust-then-verify, which is the same shape as the dogtag `documentStore` scar
 * that section records.
 *
 *  1. structural rules, including the copy-kind and salt-carriage rules of section 7.3;
 *  2. the verifier's own allow-lists - `hashAlg` under section 7.4 H3, and the profile registry
 *     under section 12.2 - which settle whether this verifier can proceed at all;
 *  3. the anchoring layer, read from the verifier's own configuration (section 7.4 H2);
 *  4. every disclosed leaf recomputed from its own fields and its inclusion proof checked;
 *  5. the outer identity bound to the reserved leaves the root commits;
 *  6. the minimum-disclosure floor, selected from the COMMITTED `roax.recordType` leaf.
 *
 * Steps 4 and 5 in that order are pinned by the corpus: `corpus/README.md` measures that enforcing
 * the floor before the binding fails exactly 16 of 54 envelope vectors, because the binding
 * subsumes the reserved half of the floor and those 16 therefore reject with
 * `outer-identity-mismatch` rather than `minimum-disclosure-floor`. Step 6's SOURCE of floor is
 * not corpus-observable - by then the outer field has been proved NFC-equal to the committed leaf,
 * so both sources yield the same table - and it is written this way so the structural claim is
 * visible where a reader of the code will find it.
 */
export function verifyEnvelope(envelope: Envelope, config: VerifierConfig = {}): VerificationResult {
  const undischarged: string[] = [];

  // ---- 1. Structural -------------------------------------------------------------------------
  if (envelope.canon !== CANON_VERSION) {
    fail('envelope-malformed', `canon is ${JSON.stringify(envelope.canon)}, not ${CANON_VERSION}`);
  }
  // The seed guard runs over every unknown member at every depth the envelope owns, and it runs
  // BEFORE the generic rejection so a seed keeps its own reason rather than being absorbed into
  // "unknown member".
  for (const member of envelope.unknownMembers) {
    if (SEED_SHAPED_MEMBERS.has(member.name)) {
      fail(
        'master-salt-in-envelope',
        `${member.where} carries ${member.name}, and no envelope may carry any value from which ` +
          'the salt of an undisclosed leaf could be obtained (specification section 7.3 rule 3)',
      );
    }
  }
  if (envelope.unknownMembers.length > 0) {
    fail(
      'envelope-malformed',
      `unknown members: ${envelope.unknownMembers
        .map((m) => `${m.name} in ${m.where}`)
        .join(', ')}`,
    );
  }
  const hasRecord = envelope.record !== undefined;
  const hasDisclosure = envelope.disclosure !== undefined;
  if (hasRecord === hasDisclosure) {
    fail(
      'envelope-copy-kind',
      'exactly one of record and disclosure MUST be present (specification section 11.1)',
    );
  }
  if (hasDisclosure && envelope.salts !== undefined) {
    // The load-bearing half of section 7.3 rule 2. An envelope carrying `salts` alongside
    // `disclosure` MUST be rejected rather than repaired: extra salts change no leaf hash, so it
    // would verify correctly against the root while leaking every withheld field to a dictionary
    // search (section 10.1).
    fail(
      'disclosed-copy-carries-salts',
      'a disclosed copy carries the salt of every leaf it reveals and of no other leaf, so the ' +
        'full-copy salts array MUST NOT appear (specification section 7.3)',
    );
  }
  if (hasRecord && envelope.salts === undefined) {
    fail(
      'envelope-malformed',
      'a full copy MUST carry the salt of every leaf; without them it is not verifiable at all',
    );
  }

  // ---- 2. The verifier's own allow-lists ------------------------------------------------------
  const allowList = config.hashAlgAllowList ?? DEFAULT_ALLOW_LIST;
  if (!allowList.includes(envelope.hashAlg as HashAlgName)) {
    // H3 closes the case H2 does not: an algorithm legitimately registered and since retired.
    // Without it a verifier that has retired an algorithm still runs it because the envelope asked.
    fail(
      'hash-alg-not-allowed',
      `hashAlg ${JSON.stringify(envelope.hashAlg)} is not on this verifier's allow-list`,
      { allowList: [...allowList] },
    );
  }
  const knownProfiles = config.knownProfiles ?? REGISTERED_PROFILES;
  if (!knownProfiles.has(envelope.recordType)) {
    // An unknown profile MUST fail closed with a stated reason and MUST NEVER default to a guess
    // (section 12.2). This fires on the OUTER recordType and ahead of everything below, because it
    // settles whether this verifier can proceed at all rather than which policy to apply.
    fail(
      'profile-unknown',
      `recordType ${JSON.stringify(envelope.recordType)} is not a profile this verifier knows`,
    );
  }
  if (config.requireTypeMapIdentity === true && envelope.typeMap === undefined) {
    // Read HERE rather than inside either copy-kind path, so that the option governs both. It is
    // the verifier's own policy in the same sense the two allow-lists above are, and a policy that
    // held for a disclosed copy and not for a full copy would tell a deployment it had opted out
    // of `schemas/envelope-1.0.json` while it was still accepting one.
    fail(
      'outer-identity-mismatch',
      'this verifier accepts only envelopes that bind the exact type-map artifact, and this ' +
        'envelope carries no typeMap member',
    );
  }
  const hash = resolveHashFunction(envelope.hashAlg);

  // ---- 3. The anchoring layer, from the verifier's own configuration ---------------------------
  if (config.anchoredHashAlg !== undefined) {
    // H2: authority for which hash to run comes from the same place authority for the root comes
    // from. A self-describing document cannot authenticate its own description.
    if (config.anchoredHashAlg !== envelope.hashAlg) {
      fail(
        'hash-alg-not-allowed',
        `the anchoring registry records ${config.anchoredHashAlg} against this root, ` +
          `not ${envelope.hashAlg}`,
      );
    }
  } else {
    undischarged.push(
      'section 7.4 H2: no anchoring registry is configured, so hashAlg was taken from the ' +
        'envelope. The registry is deliberately undesigned (specification section 2.2).',
    );
  }
  if (config.anchoredRoot !== undefined && config.anchoredRoot !== envelope.root) {
    fail('root-mismatch', 'the root is not the one the anchoring registry records');
  }
  if (
    config.registryAddress !== undefined &&
    envelope.anchor !== undefined &&
    envelope.anchor.registry !== config.registryAddress
  ) {
    // The dogtag `documentStore` bug in this design's shape: an attacker-supplied address that
    // answers "valid". The registry named in the envelope is NEVER read.
    fail(
      'envelope-malformed',
      'the anchor block names a registry this verifier is not configured with; ' +
        'a verifier resolves the anchoring layer from its own configuration',
    );
  }

  const identity: RecordIdentity = {
    recordType: envelope.recordType,
    schemaVersion: envelope.schemaVersion,
    recordId: envelope.recordId,
    issuerId: envelope.issuer.id,
    typeMapId: envelope.typeMap?.id,
    issuerKeyId: envelope.issuer.keyId,
  };
  const resolver = config.resolverFor?.(envelope.recordType);

  if (hasRecord) {
    return verifyFullCopy(envelope, identity, hash, resolver, config, undischarged);
  }
  return verifyDisclosedCopy(envelope, identity, hash, resolver, config, undischarged);
}

function verifyFullCopy(
  envelope: Envelope,
  identity: RecordIdentity,
  hash: ReturnType<typeof resolveHashFunction>,
  resolver: TypeTagResolver | undefined,
  config: VerifierConfig,
  undischarged: string[],
): VerificationResult {
  const saltEntries = envelope.salts as readonly LeafSaltEntry[];
  if (identity.typeMapId === undefined) {
    // The full-copy half of the section 11.2 residue, reported on the same footing as the
    // disclosed-copy half so that neither copy kind passes an unbound envelope silently. What is
    // at stake differs and the wording says which: the rebuild below takes the reserved leaves
    // from the identity, so a member a holder removed removes a leaf with it and the copy fails
    // closed further down. Nothing is waivable here; the binding is simply absent.
    undischarged.push(
      'section 11.2: this full copy carries no typeMap member, so it commits no roax.typeMap.id ' +
        'leaf and the exact type-map artifact it was issued against is not authenticated by the ' +
        'root. It was issued under schemas/envelope-1.0.json, which predates the binding. Unlike ' +
        'a disclosed copy the member cannot be removed silently, because the rebuild would emit a ' +
        'different leaf set. Set requireTypeMapIdentity to reject such an envelope outright.',
    );
  }
  // Checked BEFORE the tree is rebuilt, so a copy whose salts array simply has the wrong length is
  // rejected for that rather than for the derived-count disagreement it also causes.
  if (saltEntries.length !== envelope.leafCount) {
    fail(
      'salts-length-not-leaf-count',
      `salts carries ${saltEntries.length} entries against a leafCount of ${envelope.leafCount}`,
    );
  }
  // Duplicate paths are caught by the salt source's own constructor, which is the earliest point
  // at which two entries can be seen to name one leaf.
  const salts: SaltSource = new PathKeyedSalts(
    saltEntries.map((e) => ({ segments: e.segments, salt: fromHex(e.salt, 'a salt') })),
  );
  if (resolver === undefined) {
    fail(
      'type-map-fail-closed',
      `a full copy is re-flattened, which needs the exact type map for ${envelope.recordType}`,
    );
  }
  const commitment = commitRecord(envelope.record as JsonValue, {
    hash,
    resolver,
    identity,
    salts,
    emptyContainerPolicy: config.emptyContainerPolicy,
  });
  // Section 11.1: in a full copy the verifier derives the leaf count itself, and a derived count
  // that disagrees with the field MUST be a rejection - not a warning, and not a silent preference
  // for either value.
  if (commitment.leafCount !== envelope.leafCount) {
    fail(
      'leaf-count-mismatch',
      `the rebuilt tree has ${commitment.leafCount} leaves against a declared ${envelope.leafCount}`,
    );
  }
  if (toHex(commitment.root) !== envelope.root) {
    fail('root-mismatch', 'the rebuilt root does not equal the envelope root');
  }
  return {
    kind: 'full',
    root: envelope.root,
    leafCount: commitment.leafCount,
    undischarged,
  };
}

function verifyDisclosedCopy(
  envelope: Envelope,
  identity: RecordIdentity,
  hash: ReturnType<typeof resolveHashFunction>,
  resolver: TypeTagResolver | undefined,
  config: VerifierConfig,
  undischarged: string[],
): VerificationResult {
  const disclosure = envelope.disclosure as { mode: string; leaves: readonly DisclosedLeaf[] };
  if (disclosure.mode !== 'selective') {
    fail('envelope-malformed', `disclosure.mode is ${JSON.stringify(disclosure.mode)}`);
  }
  const root = fromHex(envelope.root, 'root');
  const requireMap = config.requireTypeMapForDisclosedLeaves ?? true;

  // ---- 4. Recompute every leaf, then check its proof ------------------------------------------
  //
  // Step 2 of specification section 10, and it is not optional. `verifyInclusion` is a fold
  // primitive that trusts the leaf hash it is handed, so a verifier that accepted one could be
  // walked from an internal node to the genuine root under a forged tree size (section 11.1).
  // A recomputed leaf hash is `0x00`-domained by construction and an internal node is
  // `0x01`-domained, so the substitution needs a second preimage.
  const committedByPath = new Map<string, DisclosedLeaf>();
  for (const leaf of disclosure.leaves) {
    // Section 6.5 states TWO rejections and this is the second: an implementation MUST reject a
    // record whose type map binds any path to tag 8, AND MUST reject an envelope carrying a tag-8
    // leaf. A full copy is covered by the first through `carrierFromJson`, which fails with this
    // same code while re-flattening; a disclosed copy is never re-flattened, so without this the
    // MUST held for one copy kind and not the other.
    //
    // It is the FIRST check in the loop deliberately. A tag-8 leaf carrying no value would
    // otherwise surface as `disclosed-leaf-named-without-value`, which names a different defect.
    if (leaf.tag === TypeTag.BLOB_REF) {
      fail(
        'blob-ref-not-selectable',
        `the disclosed leaf at ${displayPath(leaf.segments)} carries tag 8 BLOB_REF, which no ` +
          'version-1 profile selects (specification section 6.5)',
      );
    }
    if (!tagCarriesNoValue(leaf.tag) && !leaf.hasValue) {
      // A leaf named with a salt and no value is a withheld leaf's salt smuggled into a disclosed
      // copy. Nothing about the root check would notice.
      fail(
        'disclosed-leaf-named-without-value',
        `the disclosed leaf at ${displayPath(leaf.segments)} carries a salt and no value`,
      );
    }
    if (tagCarriesNoValue(leaf.tag) && leaf.hasValue) {
      fail(
        'envelope-malformed',
        `tag ${leaf.tag} carries no value, but the leaf at ${displayPath(leaf.segments)} has one`,
      );
    }
    const isReserved = isReservedPath(leaf.segments);
    if (!isReserved && resolver !== undefined) {
      // Step 1 of section 10: a record leaf's tag is checked against the exact selected map.
      const observed = observedKindForTag(leaf.tag);
      if (observed !== undefined) {
        const bound = resolver.resolve(leaf.segments, observed);
        if (bound !== leaf.tag) {
          fail(
            'type-map-fail-closed',
            `the map binds ${displayPath(leaf.segments)} to tag ${bound}, not ${leaf.tag}`,
          );
        }
      }
    } else if (!isReserved && requireMap) {
      fail(
        'type-map-fail-closed',
        `no type map is available for ${envelope.recordType}, so the tag of the record leaf at ` +
          `${displayPath(leaf.segments)} cannot be checked (specification section 10 step 1)`,
      );
    } else if (!isReserved) {
      undischarged.push(
        `section 10 step 1: no type map for ${envelope.recordType}, so disclosed record-leaf ` +
          'tags were not checked against one.',
      );
    }

    const computed = leafHash(
      hash,
      leaf.segments,
      leaf.tag,
      leaf.value,
      fromHex(leaf.salt, 'a disclosed salt'),
    );
    const ok = verifyInclusion(
      hash,
      computed,
      leaf.index,
      envelope.leafCount,
      leaf.auditPath.map((h) => fromHex(h, 'an auditPath entry')),
      root,
    );
    if (!ok) {
      fail(
        'inclusion-proof-failed',
        `the inclusion proof for ${displayPath(leaf.segments)} at index ${leaf.index} does not ` +
          'verify against the root',
      );
    }
    committedByPath.set(toHex(encodePath(leaf.segments)), leaf);
  }

  // ---- 5. Bind the outer identity to the reserved leaves the root commits ----------------------
  //
  // The outer fields are hints (section 11.3); the leaves are inside the root (section 11.2).
  // Without this a holder of a recovery copy relabels the envelope as PDT - whose floor is a
  // strict SUBSET of recovery's - withholds `validUntil`, and every inclusion proof still verifies
  // against the genuine recovery root.
  const bindings: [Path, string, string][] = [
    [[{ key: RESERVED_PATHS.recordType }], envelope.recordType, 'recordType'],
    [[{ key: RESERVED_PATHS.schemaVersion }], envelope.schemaVersion, 'schemaVersion'],
    [[{ key: RESERVED_PATHS.recordId }], envelope.recordId, 'recordId'],
    [[{ key: RESERVED_PATHS.issuerId }], envelope.issuer.id, 'issuer.id'],
  ];
  // **The type-map identity is decided from the COMMITTED side, in both directions.**
  //
  // Taking only its MEMBERSHIP from the outer `typeMap` member would be the trust-then-verify
  // shape this function is otherwise written to avoid: the floor TABLE comes from the committed
  // `roax.recordType` leaf at step 6 precisely so an outer field selects nothing before it has
  // been authenticated, and a binding whose presence an outer field decides is the same defect one
  // level down. A holder who deleted the outer member and withheld the leaf would otherwise waive
  // a binding section 11.2 marks mandatory to disclose, on a copy that still verified.
  const typeMapIdPath: Path = [{ key: RESERVED_PATHS.typeMapId }];
  const committedTypeMapId = committedByPath.get(toHex(encodePath(typeMapIdPath)));
  if (identity.typeMapId !== undefined) {
    bindings.push([typeMapIdPath, identity.typeMapId, 'typeMap.id']);
  } else if (committedTypeMapId !== undefined) {
    // The other direction, and the half that was missing: the root authenticates a map identity
    // and the envelope names none, so nothing outside the root can be checked against it.
    fail(
      'outer-identity-mismatch',
      'the disclosed copy commits roax.typeMap.id inside the root while the envelope carries no ' +
        'typeMap member, so the map identity the root authenticates is unbound',
    );
  } else {
    // **The residue, and it is reported on every affected verification rather than waived.**
    // Both halves absent is the one case the two directions above cannot separate, because
    // specification section 11.1's envelope shape carries no discriminator for which schema
    // version a document was issued under: `canon` is `ROAX-CANON/1` under both, and the outer
    // `schemaVersion` is the RECORD profile's version rather than the envelope schema's.
    //
    // A verifier that has set `requireTypeMapIdentity` never reaches here: the option is read
    // beside the allow-lists in step 2, so it rejects both copy kinds ahead of this.
    undischarged.push(
      'section 11.2: this copy carries neither an outer typeMap member nor a committed ' +
        'roax.typeMap.id leaf, so it was either issued under schemas/envelope-1.0.json, which ' +
        'predates the binding, or had the binding stripped - and the envelope carries no ' +
        'discriminator that separates the two. Set requireTypeMapIdentity to reject the pair.',
    );
  }
  // `roax.issuer.keyId` is deliberately NOT bound. It is the one conditional leaf, and requiring
  // its disclosure would permanently bind an anchored record to the key it was issued under.
  for (const [path, outerValue, label] of bindings) {
    const leaf = committedByPath.get(toHex(encodePath(path)));
    if (leaf === undefined) {
      fail(
        'outer-identity-mismatch',
        `the disclosed copy does not commit ${label}, so its outer value is unbound`,
      );
    }
    // Compared under NFC on BOTH sides: a STRING leaf commits its normalized form, so an
    // unnormalized outer field naming the same string must still bind.
    if (typeof leaf.value !== 'string' || nfc(leaf.value) !== nfc(outerValue)) {
      fail(
        'outer-identity-mismatch',
        `the outer ${label} disagrees with the ${displayPath(path)} leaf committed inside the root`,
      );
    }
  }

  // ---- 6. The floor, selected from the COMMITTED recordType leaf -------------------------------
  const committedRecordType = committedByPath.get(
    toHex(encodePath([{ key: RESERVED_PATHS.recordType }])),
  )?.value as string;
  const floor = floorFor(committedRecordType);
  if (floor === undefined) {
    // Unreachable in practice: step 2 already rejected an unknown profile on the outer field, and
    // step 5 has just proved that field equal to this leaf. Kept so that a later edit cannot
    // quietly restore the trust-then-verify shape.
    fail('profile-unknown', `no floor is registered for ${JSON.stringify(committedRecordType)}`);
  }
  // `mandatoryReservedPaths` is keyed on the identity's `typeMapId`, and step 5 has just settled
  // that member against the root in both directions: present means proved equal to the committed
  // leaf, absent means the leaf is proved absent too. So the reserved half of this floor is
  // selected from an authenticated fact rather than from an outer hint, exactly as its other half
  // is selected from the committed `recordType` leaf above.
  const floorPaths: Path[] = [...mandatoryReservedPaths(identity), ...floor.profilePaths];
  for (const path of floorPaths) {
    if (!committedByPath.has(toHex(encodePath(path)))) {
      fail(
        'minimum-disclosure-floor',
        `the disclosed copy omits the non-redactable path ${displayPath(path)} ` +
          `(${floor.citation})`,
      );
    }
  }

  return {
    kind: 'disclosed',
    root: envelope.root,
    leafCount: envelope.leafCount,
    undischarged,
  };
}

function isReservedPath(path: Path): boolean {
  const first = path[0];
  return path.length === 1 && first !== undefined && isKeySegment(first) && first.key.startsWith('roax.');
}

/**
 * The observed JSON kind a tag implies, for the section 10 step 1 tag check.
 *
 * `undefined` where the mapping is not one-to-one: kind `number` covers INTEGER and DECIMAL and
 * kind `string` covers STRING and BYTES, so checking those would need the value's own kind, which
 * a disclosed copy does not carry separately from its tag.
 */
function observedKindForTag(tag: TypeTagValue): 'string' | 'boolean' | 'null' | 'object' | 'array' | undefined {
  switch (tag) {
    case 0:
      return 'null';
    case 1:
      return 'boolean';
    case 2:
      return 'string';
    case 6:
      return 'array';
    case 7:
      return 'object';
    default:
      return undefined;
  }
}

export { RoaxError };
