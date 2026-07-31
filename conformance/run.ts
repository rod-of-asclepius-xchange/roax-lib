/**
 * The ROAX conformance runner for this implementation.
 *
 * Written against `docs/conformance-corpus.md`, `corpus/README.md` and
 * `schemas/conformance-corpus-1.0.json`. It deliberately does not reuse
 * `corpus/tools/check_corpus.mjs`, because that runner imports one of the two reference
 * implementations and the value of a third implementation is that it agrees without having read
 * either.
 */

import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { existsSync, readFileSync } from 'node:fs';
import {
  Report,
  expectEqual,
  expectReject,
  readJsonFileLoose,
  isEscapeObject,
  decodeUtf16Escape,
} from './harness.js';
import { encodePath, displayPath, type Path, type PathSegment } from '../src/path.js';
import { encodeValue, isTypeTag, type CarrierValue } from '../src/value.js';
import { toHex, fromHex, describeUnicodeEnvironment } from '../src/bytes.js';
import { resolveHashFunction, type HashAlgName } from '../src/hash.js';
import { leafHash } from '../src/leaf.js';
import { merkleTreeHead, inclusionProof, verifyInclusion } from '../src/tree.js';
import { readJson, type JsonKind } from '../src/json.js';
import { assertRecordPathAllowed, type RecordIdentity } from '../src/reserved.js';
import { LegacyPatternTypeMap } from '../src/typemap.js';
import { flattenRecord, type EmptyContainerPolicy } from '../src/flatten.js';
import {
  commitRecord,
  drawSalt,
  PathKeyedSalts,
  PositionalSalts,
  type SaltSource,
} from '../src/commit.js';
import {
  parseEnvelope,
  verifyEnvelope,
  type VerifierConfig,
  type VerificationResult,
} from '../src/envelope.js';
import { REGISTERED_PROFILES } from '../src/profiles.js';
import { issueFullCopy, discloseFrom } from '../src/issue.js';

/**
 * The repository root.
 *
 * Resolved by walking up from the compiled module until `corpus/conformance-corpus-1.0.json` is
 * found, so the runner works both from `dist/conformance/` and from a source-level runner, and so
 * no absolute path into anyone's working tree appears in this public repository.
 *
 * The directory comes from `fileURLToPath(import.meta.url)` rather than from `import.meta.dirname`,
 * which Node added in v20.11. `package.json` declares `engines.node >= 18` because `src/` is what
 * the package ships and it needs nothing newer, so reaching for the newer accessor here would have
 * made the runner throw a bare `TypeError` out of `resolve()` on a runtime the package says it
 * supports, before a single vector ran and with nothing tying the failure to the Node version.
 */
const ROOT = findRepositoryRoot(dirname(fileURLToPath(import.meta.url)));

function findRepositoryRoot(from: string): string {
  let dir = from;
  for (let i = 0; i < 8; i += 1) {
    if (existsSync(resolve(dir, 'corpus/conformance-corpus-1.0.json'))) {
      return dir;
    }
    dir = resolve(dir, '..');
  }
  throw new Error('could not locate the repository root from ' + from);
}

interface Corpus {
  readonly corpusVersion: string;
  readonly canon: string;
  readonly hashAlg: string;
  readonly unicodeVersion: string;
  readonly vectors: Record<string, unknown[]>;
}

function segmentsOf(raw: unknown): Path {
  if (!Array.isArray(raw)) {
    throw new TypeError('segments must be an array');
  }
  return raw.map((s): PathSegment => {
    const o = s as Record<string, unknown>;
    if ('key' in o) {
      const decoded = decodeUtf16Escape(o['key']);
      return { key: decoded ?? (o['key'] as string) };
    }
    return { index: o['index'] as number };
  });
}

function carrierOf(raw: unknown): CarrierValue | undefined {
  if (raw === undefined || raw === null) {
    return undefined;
  }
  const utf16 = decodeUtf16Escape(raw);
  if (utf16 !== undefined) {
    return utf16;
  }
  return raw as CarrierValue;
}

/**
 * Every vector group this runner consumes.
 *
 * A group present in the corpus file and absent from this list is a HARD FAILURE rather than a
 * quiet skip. The quiet skip is the exact defect shape the corpus exists to prevent: a runner
 * that does not know a group reads it as zero vectors and reports the same green it reported
 * before the group was added, so extending the corpus would silently fail to extend the gate.
 */
const CONSUMED_GROUPS: readonly string[] = [
  'encodePath',
  'encodeValue',
  'reject',
  'leaf',
  'tree',
  'inclusion',
  'negativeProof',
  'typeMap',
  'record',
  'unlinkability',
  'normalization',
  'envelope',
  'roundTrip',
];

function checkEveryGroupIsConsumed(corpus: Corpus): string[] {
  return Object.keys(corpus.vectors).filter((name) => !CONSUMED_GROUPS.includes(name));
}

function main(): number {
  const corpus = readJsonFileLoose(
    resolve(ROOT, 'corpus/conformance-corpus-1.0.json'),
  ) as Corpus;

  const unconsumed = checkEveryGroupIsConsumed(corpus);
  if (unconsumed.length > 0) {
    console.error(
      'FAILED: the corpus carries vector group(s) this runner does not consume: ' +
        unconsumed.join(', '),
    );
    console.error(
      '  A group read as absent would report the same green as before it existed.',
    );
    return 1;
  }

  const report = new Report();
  const hash = resolveHashFunction(corpus.hashAlg);

  const unicode = describeUnicodeEnvironment();
  console.log(
    `corpus ${corpus.corpusVersion} / ${corpus.canon} / ${corpus.hashAlg}; ` +
      `pinned Unicode ${corpus.unicodeVersion}, runtime tables ${unicode.runtimeProvides}`,
  );

  runEncodePath(corpus, report);
  runEncodeValue(corpus, report);
  runReject(corpus, report);
  runLeaf(corpus, report, hash);
  runTree(corpus, report, hash);
  runInclusion(corpus, report, hash);
  runNegativeProof(corpus, report, hash);
  runTypeMap(corpus, report);
  runRecord(corpus, report, hash);
  runNormalization(corpus, report, hash);
  runEnvelope(corpus, report);
  runRoundTrip(corpus, report);
  runUnlinkability(corpus, report, hash);

  printReport(report, unicode);
  return report.totalFailed === 0 ? 0 : 1;
}

function runEncodePath(corpus: Corpus, report: Report): void {
  for (const raw of corpus.vectors['encodePath'] ?? []) {
    const v = raw as { name: string; class: number; segments: unknown; encodedHex: string; displayPath?: string };
    const segments = segmentsOf(v.segments);
    expectEqual(report, v.class, v.name, toHex(encodePath(segments)), v.encodedHex);
    if (v.displayPath !== undefined) {
      expectEqual(report, v.class, `${v.name} (display)`, displayPath(segments), v.displayPath);
    }
  }
}

function runEncodeValue(corpus: Corpus, report: Report): void {
  for (const raw of corpus.vectors['encodeValue'] ?? []) {
    const v = raw as { name: string; class: number; tag: number; input?: unknown; encodedHex: string };
    if (!isTypeTag(v.tag)) {
      report.fail(v.class, `${v.name}: unknown tag ${v.tag}`);
      continue;
    }
    expectEqual(
      report,
      v.class,
      v.name,
      toHex(encodeValue(v.tag, carrierOf(v.input))),
      v.encodedHex,
    );
  }
}

function runReject(corpus: Corpus, report: Report): void {
  for (const raw of corpus.vectors['reject'] ?? []) {
    const v = raw as {
      name: string;
      class: number;
      recordType?: string;
      tag?: number;
      input?: unknown;
      segments?: unknown;
      reason: string;
    };
    expectReject(report, v.class, v.name, v.reason, () => {
      // A `recordType` makes this a WHOLE-RECORD rejection: read the record and flatten it
      // through that profile's COMMITTED map. The map has to be the committed one rather than a
      // permissive stand-in, because several of these vectors assert that a path has NO binding
      // for an observed kind, which a resolve-everything map makes unfalsifiable.
      //
      // `map-authorized` is forced here rather than taking the run's policy. Every one of these
      // vectors asserts a rejection at a SCALAR or a base64 carrier, so the empty-container
      // reading cannot change any of their outcomes, and pinning it keeps a policy sweep from
      // silently turning a rejection into a pass.
      if (v.recordType !== undefined) {
        const record = readJson((v.input as { $jsonText: string }).$jsonText);
        return flattenRecord(record, {
          resolver: resolverFor(v.recordType),
          emptyContainerPolicy: 'map-authorized',
        });
      }
      // `$jsonText` goes to the JSON reader, which is where a parser-boundary rejection lives.
      if (isEscapeObject(v.input, '$jsonText')) {
        return readJson((v.input as { $jsonText: string }).$jsonText);
      }
      // `$segments` is a path under test: an out-of-range index, or the reserved-namespace guard.
      const segmentSource = isEscapeObject(v.input, '$segments')
        ? (v.input as { $segments: unknown }).$segments
        : v.segments;
      if (segmentSource !== undefined) {
        const segments = segmentsOf(segmentSource);
        if (v.reason === 'reserved-namespace') {
          // The guard runs at the INPUT BOUNDARY, before any hashing (specification section
          // 11.2). Encoding first would reject nothing.
          assertRecordPathAllowed(segments);
        }
        return encodePath(segments);
      }
      if (v.tag !== undefined && isTypeTag(v.tag)) {
        return encodeValue(v.tag, carrierOf(v.input));
      }
      throw new TypeError(`reject vector ${v.name} names no input this runner can drive`);
    });
  }
}

function runLeaf(corpus: Corpus, report: Report, hash: ReturnType<typeof resolveHashFunction>): void {
  for (const raw of corpus.vectors['leaf'] ?? []) {
    const v = raw as {
      name: string;
      class: number;
      segments: unknown;
      tag: number;
      value?: unknown;
      saltHex: string;
      leafHash: string;
    };
    if (!isTypeTag(v.tag)) {
      report.fail(v.class, `${v.name}: unknown tag ${v.tag}`);
      continue;
    }
    const actual = toHex(
      leafHash(hash, segmentsOf(v.segments), v.tag, carrierOf(v.value), fromHex(v.saltHex)),
    );
    expectEqual(report, v.class, v.name, actual, v.leafHash);
  }
}

function runTree(corpus: Corpus, report: Report, hash: ReturnType<typeof resolveHashFunction>): void {
  for (const raw of corpus.vectors['tree'] ?? []) {
    const v = raw as { name: string; class: number; leafHashes: string[]; root: string };
    const leaves = v.leafHashes.map((h) => fromHex(h));
    expectEqual(report, v.class, v.name, toHex(merkleTreeHead(hash, leaves)), v.root);
  }
}

function runInclusion(
  corpus: Corpus,
  report: Report,
  hash: ReturnType<typeof resolveHashFunction>,
): void {
  // Every inclusion vector is checked twice: the proof VERIFIES, and regenerating the audit path
  // for that index reproduces the committed one. `corpus/README.md` requires both.
  const treesBySize = new Map<number, Uint8Array[]>();
  for (const raw of corpus.vectors['tree'] ?? []) {
    const v = raw as { leafHashes: string[] };
    treesBySize.set(v.leafHashes.length, v.leafHashes.map((h) => fromHex(h)));
  }
  for (const raw of corpus.vectors['inclusion'] ?? []) {
    const v = raw as {
      name: string;
      class: number;
      leafHash: string;
      index: number;
      treeSize: number;
      auditPath: string[];
      root: string;
    };
    const ok = verifyInclusion(
      hash,
      fromHex(v.leafHash),
      v.index,
      v.treeSize,
      v.auditPath.map((h) => fromHex(h)),
      fromHex(v.root),
    );
    expectEqual(report, v.class, v.name, ok, true);
    const leaves = treesBySize.get(v.treeSize);
    if (leaves !== undefined) {
      const regenerated = inclusionProof(hash, leaves, v.index).map(toHex);
      expectEqual(
        report,
        v.class,
        `${v.name} (generated audit path)`,
        regenerated.join(','),
        v.auditPath.join(','),
      );
    } else {
      report.skip(v.class, `no tree vector of size ${v.treeSize} to regenerate an audit path from`);
    }
  }
}

function runNegativeProof(
  corpus: Corpus,
  report: Report,
  hash: ReturnType<typeof resolveHashFunction>,
): void {
  for (const raw of corpus.vectors['negativeProof'] ?? []) {
    const v = raw as {
      name: string;
      class: number;
      attack: string;
      leafHash: string;
      index: number;
      treeSize: number;
      auditPath: string[];
      root: string;
    };
    const ok = verifyInclusion(
      hash,
      fromHex(v.leafHash),
      v.index,
      v.treeSize,
      v.auditPath.map((h) => fromHex(h)),
      fromHex(v.root),
    );
    expectEqual(report, v.class, `${v.name} (${v.attack})`, ok, false);
  }
  report.note(
    9,
    'Driven through the fold primitive, not the disclosed-copy path: negativeProofVector ' +
      'carries no segments, tag, value or salt, so no leaf hash can be recomputed from it. ' +
      'See the findings note on class 9.',
  );
}

/**
 * The empty-container policy this run uses.
 *
 * `ROAX_EMPTY_CONTAINERS=map-authorized` selects the specification's rule (section 3.3), under
 * which the committed class-5 empty-array and empty-object records fail closed. The default is
 * `mechanical`, which is what reproduces the committed roots. See the `EmptyContainerPolicy`
 * documentation and the findings note.
 */
const EMPTY_CONTAINER_POLICY: EmptyContainerPolicy =
  process.env['ROAX_EMPTY_CONTAINERS'] === 'map-authorized' ? 'map-authorized' : 'mechanical';

const resolverCache = new Map<string, LegacyPatternTypeMap>();

function resolverFor(recordType: string): LegacyPatternTypeMap {
  let r = resolverCache.get(recordType);
  if (r === undefined) {
    const file = readJsonFileLoose(resolve(ROOT, `corpus/type-maps/${recordType}.json`));
    r = LegacyPatternTypeMap.compile(file as Parameters<typeof LegacyPatternTypeMap.compile>[0]);
    resolverCache.set(recordType, r);
  }
  return r;
}

/** Reads a record or envelope fixture with the LIBRARY's literal-preserving reader. */
function readFixture(relative: string): ReturnType<typeof readJson> {
  return readJson(readFileSync(resolve(ROOT, relative), 'utf8'));
}

function runTypeMap(corpus: Corpus, report: Report): void {
  for (const raw of corpus.vectors['typeMap'] ?? []) {
    const v = raw as {
      name: string;
      class: number;
      recordType: string;
      segments: unknown;
      jsonKind: JsonKind;
      expectTag?: number;
      expectFailClosed?: boolean;
      expectMapRejected?: boolean;
    };
    // `typeMapVector` names no file, so the map is resolved by the convention
    // `corpus/type-maps/<recordType>.json` that `corpus/README.md` records as a schema limit.
    if (v.expectMapRejected === true) {
      expectReject(report, v.class, v.name, 'type-map-rejected', () => resolverFor(v.recordType));
      continue;
    }
    let resolver: LegacyPatternTypeMap;
    try {
      resolver = resolverFor(v.recordType);
    } catch (e) {
      report.fail(v.class, `${v.name}: the map itself was rejected: ${String(e)}`);
      continue;
    }
    if (v.expectFailClosed === true) {
      expectReject(report, v.class, v.name, 'type-map-fail-closed', () =>
        resolver.resolve(segmentsOf(v.segments), v.jsonKind),
      );
      continue;
    }
    let tag: number | string;
    try {
      tag = resolver.resolve(segmentsOf(v.segments), v.jsonKind);
    } catch (e) {
      tag = `threw ${String(e)}`;
    }
    expectEqual(report, v.class, v.name, tag, v.expectTag);
  }
}

/**
 * Where a `recordVector.recordFile` was found, or WHY it was not.
 *
 * The two ways a class-10 vector cannot run are not the same problem and do not have the same
 * remedy, so they are not the same report. `ROAX_REFERENCE_RECORDS` unset means the reference
 * checkout has not been extracted at all; the variable set and the derived filename absent means it
 * has been extracted under a different name, and the only remedy is knowing which name is expected.
 * A single "set ROAX_REFERENCE_RECORDS" message told the second reader to do what they had already
 * done.
 */
type RecordFileLocation =
  | { readonly kind: 'found'; readonly path: string }
  | { readonly kind: 'unavailable'; readonly reason: string };

/**
 * Locates a `recordVector.recordFile`, or reports that it is unavailable.
 *
 * Class 10 names the three Singapore MOH samples inside a third-party checkout that this
 * repository deliberately does not vendor, as `references/schemata/src/...`. A record extracted
 * from one is placed in a scratch directory named by `ROAX_REFERENCE_RECORDS`, keyed by the
 * vector's `recordType`. Nothing is read from, or written into, this repository, and the absence
 * of the checkout is REPORTED rather than counted as a pass.
 *
 * **The filename inside that directory is a contract of this runner and not of the corpus**, since
 * `recordVector` names only the path inside the reference checkout and
 * `corpus/tools/extract_reference_record.py` writes wherever `--out` says. It is
 * `<authority>.<profile>.json`, and it is stated in `src/README.md` as well as here so it is
 * discoverable without reading this function.
 */
function resolveRecordFile(recordFile: string): RecordFileLocation {
  if (!recordFile.startsWith('references/')) {
    if (existsSync(resolve(ROOT, recordFile))) {
      return { kind: 'found', path: recordFile };
    }
    return {
      kind: 'unavailable',
      reason: `the committed fixture ${recordFile} is missing from this checkout`,
    };
  }
  // `.../<recordType>/<version>/sample-data.ts#<export>` -> `<dir>/<authority>.<profile>.json`.
  const withoutExport = recordFile.split('#')[0] as string;
  const parts = withoutExport.split('/');
  const profile = parts[parts.length - 3];
  const authority = parts.slice(3, parts.length - 3).join('.');
  const expectedName = `${authority}.${profile}.json`;

  const dir = process.env['ROAX_REFERENCE_RECORDS'];
  if (dir === undefined) {
    return {
      kind: 'unavailable',
      reason:
        `ROAX_REFERENCE_RECORDS is not set, and the reference sample ${recordFile} lives in a ` +
        'third-party checkout this repository deliberately does not vendor. Extract it with ' +
        `corpus/tools/extract_reference_record.py --out <dir>/${expectedName} and set ` +
        'ROAX_REFERENCE_RECORDS=<dir> to run this class.',
    };
  }
  const candidate = resolve(dir, expectedName);
  if (existsSync(candidate)) {
    return { kind: 'found', path: candidate };
  }
  return {
    kind: 'unavailable',
    reason:
      `ROAX_REFERENCE_RECORDS is set, and this runner probed ${candidate}, which does not exist. ` +
      `The filename inside that directory MUST be ${expectedName}, derived from the vector's ` +
      `recordFile ${recordFile}; corpus/tools/extract_reference_record.py accepts any --out path, ` +
      'so an extraction under another name is not found.',
  };
}

interface SaltsFile {
  readonly pairing?: string;
  readonly salts: unknown;
}

function saltSourceFrom(relative: string, pairing: string): SaltSource {
  const file = readJsonFileLoose(resolve(ROOT, relative)) as SaltsFile | string[];
  if (pairing === 'positional') {
    const list = Array.isArray(file) ? file : ((file as SaltsFile).salts as string[]);
    return new PositionalSalts(list.map((h) => fromHex(h, 'salt')));
  }
  const entries = ((file as SaltsFile).salts as { segments: unknown; salt: string }[]).map((e) => ({
    segments: segmentsOf(e.segments),
    salt: fromHex(e.salt, 'salt'),
  }));
  return new PathKeyedSalts(entries);
}

function identityOf(v: {
  recordType: string;
  schemaVersion: string;
  recordId: string;
  issuerId: string;
  typeMapId?: string;
  issuerKeyId?: string;
}): RecordIdentity {
  return {
    recordType: v.recordType,
    schemaVersion: v.schemaVersion,
    recordId: v.recordId,
    issuerId: v.issuerId,
    typeMapId: v.typeMapId,
    issuerKeyId: v.issuerKeyId,
  };
}

function runRecord(corpus: Corpus, report: Report, hash: ReturnType<typeof resolveHashFunction>): void {
  for (const raw of corpus.vectors['record'] ?? []) {
    const v = raw as {
      name: string;
      class: number;
      recordType: string;
      schemaVersion: string;
      recordId: string;
      issuerId: string;
      typeMapId?: string;
      issuerKeyId?: string;
      recordFile?: string;
      envelopeFile?: string;
      saltsFile?: string;
      saltPairing?: string;
      leafCount: number;
      root: string;
    };
    if (v.recordFile === undefined || v.saltsFile === undefined) {
      report.skip(v.class, `${v.name}: carried as an envelope file, which this runner does not read`);
      continue;
    }
    const located = resolveRecordFile(v.recordFile);
    if (located.kind === 'unavailable') {
      // Class 10 names the MOH samples in a checkout that lives outside this repository by
      // design. Absence is REPORTED rather than hidden, and never reported as green. The reason
      // names WHICH of the two causes fired and what to do about that one.
      report.skip(v.class, `${v.name}: NOT RUN. ${located.reason}`);
      continue;
    }
    try {
      const commitment = commitRecord(readFixture(located.path), {
        hash,
        resolver: resolverFor(v.recordType),
        identity: identityOf(v),
        salts: saltSourceFrom(v.saltsFile, v.saltPairing ?? 'path'),
        emptyContainerPolicy: EMPTY_CONTAINER_POLICY,
      });
      expectEqual(report, v.class, `${v.name} (leafCount)`, commitment.leafCount, v.leafCount);
      expectEqual(report, v.class, `${v.name} (root)`, toHex(commitment.root), v.root);
    } catch (e) {
      report.fail(v.class, `${v.name}: ${String(e)}`);
    }
  }
}

function runNormalization(
  corpus: Corpus,
  report: Report,
  hash: ReturnType<typeof resolveHashFunction>,
): void {
  for (const raw of corpus.vectors['normalization'] ?? []) {
    const v = raw as {
      name: string;
      class: number;
      recordFileNFD: string;
      recordFileNFC: string;
      saltsFile: string;
      recordType: string;
      schemaVersion: string;
      recordId: string;
      issuerId: string;
      issuerKeyId?: string;
      expectSameRoot: boolean;
      root?: string;
    };
    try {
      const shared = {
        hash,
        resolver: resolverFor(v.recordType),
        identity: identityOf(v),
        // Both forms are computed under ONE shared salt set. Under decision D4b two issuances
        // would produce different roots for a reason that has nothing to do with normalization,
        // and the equality assertion would then hold nothing.
        salts: saltSourceFrom(v.saltsFile, 'path'),
        emptyContainerPolicy: EMPTY_CONTAINER_POLICY,
      };
      const nfd = toHex(commitRecord(readFixture(v.recordFileNFD), shared).root);
      const nfcRoot = toHex(commitRecord(readFixture(v.recordFileNFC), shared).root);
      expectEqual(report, v.class, `${v.name} (both forms agree)`, nfd === nfcRoot, v.expectSameRoot);
      if (v.root !== undefined) {
        expectEqual(report, v.class, `${v.name} (root)`, nfd, v.root);
      }
    } catch (e) {
      report.fail(v.class, `${v.name}: ${String(e)}`);
    }
  }
}

/**
 * Class 12: cross-record unlinkability under independent per-leaf salts.
 *
 * Behavioural rather than pinned. Under decision D4b the salts are independently random, so no
 * fixed hexadecimal expectation can exist: the vector describes an issuance to perform with THIS
 * implementation's own generator and the relations the results MUST satisfy.
 *
 * The leaves are hashed directly with the vector's authored tag and NOTHING is resolved. That is
 * not a shortcut: class 12 issues no record, and two of the three committed vectors name the
 * reserved paths `roax.recordId` and `roax.issuer.id`, whose tag is fixed at STRING by
 * specification section 11.2 and which no type map binds at all. Routing this class through a
 * resolver would fail closed on them.
 *
 * **Honest limit, restated here because a passing class must not read as a guarantee it is not.**
 * This detects a DETERMINISTIC or REUSED salt. It does NOT detect a weak or predictable CSPRNG: an
 * implementation drawing 16 bytes from a poorly seeded generator passes every trial while
 * providing far less than the 128 bits specification section 7 requires. No fixed vector file can
 * test a randomness source.
 */
function runUnlinkability(
  corpus: Corpus,
  report: Report,
  hash: ReturnType<typeof resolveHashFunction>,
): void {
  for (const raw of corpus.vectors['unlinkability'] ?? []) {
    const v = raw as {
      name: string;
      class: number;
      paths: unknown[];
      tag: number;
      value?: unknown;
      trials: number;
      expectDistinctSaltsWithinIssuance: boolean;
      expectDistinctSaltsAcrossIssuances: boolean;
      expectDistinctLeafHashesAcrossIssuances: boolean;
    };
    if (!isTypeTag(v.tag)) {
      report.fail(v.class, `${v.name}: unknown tag ${v.tag}`);
      continue;
    }
    const paths = v.paths.map(segmentsOf);
    // Two keys differing only in Unicode normalization form are unequal as JSON text and equal as
    // paths once NFC is applied, so `uniqueItems` in the schema cannot reach them. Comparing
    // ENCODED paths does, and such a pair is a corpus defect rather than a vector to run.
    const encoded = new Set(paths.map((p) => toHex(encodePath(p))));
    if (encoded.size !== paths.length) {
      report.fail(v.class, `${v.name}: two paths are equal once encoded, which disables the ` +
        'within-issuance distinctness assertion');
      continue;
    }

    const trials: { salt: string; leaf: string }[][] = [];
    for (let t = 0; t < v.trials; t += 1) {
      trials.push(
        paths.map((path) => {
          const salt = drawSalt();
          return {
            salt: toHex(salt),
            leaf: toHex(leafHash(hash, path, v.tag as never, carrierOf(v.value), salt)),
          };
        }),
      );
    }

    // 1. Within each issuance the salts at the `paths` entries are all distinct. This is the only
    //    assertion in the corpus that fails an implementation drawing one salt per RECORD and
    //    reusing it across that record's leaves.
    let withinOk = true;
    for (const trial of trials) {
      if (new Set(trial.map((x) => x.salt)).size !== trial.length) {
        withinOk = false;
      }
    }
    expectEqual(report, v.class, `${v.name} (distinct salts within an issuance)`, withinOk,
      v.expectDistinctSaltsWithinIssuance);

    // 2. At each path, the salt drawn in every trial differs from the salt at that path in every
    //    other trial. Catches a deterministic salt and a salt reused across records.
    // 3. At each path, the leaf hash differs likewise.
    let acrossSaltsOk = true;
    let acrossLeavesOk = true;
    for (let p = 0; p < paths.length; p += 1) {
      const salts = trials.map((t) => (t[p] as { salt: string }).salt);
      const hashes = trials.map((t) => (t[p] as { leaf: string }).leaf);
      if (new Set(salts).size !== salts.length) {
        acrossSaltsOk = false;
      }
      if (new Set(hashes).size !== hashes.length) {
        acrossLeavesOk = false;
      }
    }
    expectEqual(report, v.class, `${v.name} (distinct salts across issuances)`, acrossSaltsOk,
      v.expectDistinctSaltsAcrossIssuances);
    expectEqual(report, v.class, `${v.name} (distinct leaf hashes across issuances)`,
      acrossLeavesOk, v.expectDistinctLeafHashesAcrossIssuances);
  }
  report.note(
    12,
    'Detects a deterministic or reused salt. It CANNOT detect a weak CSPRNG, and no fixed ' +
      'vector file can.',
  );
}

/**
 * The verifier configuration the corpus is run under.
 *
 * `org.roax.corpus.synthetic` is added to this verifier's profile registry because the corpus
 * defines it as a corpus-only `recordType` that is deliberately NOT in `docs/profiles/`. The
 * profile allow-list is the verifier's OWN under specification section 12.2, so configuring one
 * that knows the corpus profile is the correct way to run corpus fixtures - not a widening of the
 * registry.
 */
function corpusVerifierConfig(): VerifierConfig {
  return {
    knownProfiles: new Set([...REGISTERED_PROFILES, 'org.roax.corpus.synthetic']),
    resolverFor: (recordType: string) => {
      if (!existsSync(resolve(ROOT, `corpus/type-maps/${recordType}.json`))) {
        return undefined;
      }
      return resolverFor(recordType);
    },
    // The corpus-only profile's floor. `org.roax.corpus.synthetic` is not in `docs/profiles/`
    // and MUST NEVER be issued against, so the library's registry rightly does not carry it -
    // but class 20 verifies a DISCLOSED copy under it, and a floor has to come from somewhere.
    // `marker` is the corpus's own declaration, matching `PROFILE_FLOORS` in
    // `corpus/tools/envelope.py` and `envelope.mjs`.
    floorFor: (recordType: string) =>
      recordType === 'org.roax.corpus.synthetic'
        ? {
            recordType,
            profilePaths: [[{ key: 'marker' }]],
            citation: 'corpus/README.md, the synthetic profile',
          }
        : undefined,
    // `corpus/type-maps/` carries no `hl7.fhir.bundle` map, so section 10 step 1 cannot be
    // discharged for the 8 of the 9 class-14 `hl7.fhir.bundle` fixtures that disclose a record leaf.
    // Reported, not hidden.
    requireTypeMapForDisclosedLeaves: false,
    emptyContainerPolicy: EMPTY_CONTAINER_POLICY,
  };
}

function runEnvelope(corpus: Corpus, report: Report): void {
  const config = corpusVerifierConfig();
  const undischargedSeen = new Set<string>();
  for (const raw of corpus.vectors['envelope'] ?? []) {
    const v = raw as {
      name: string;
      class: number;
      envelopeFile: string;
      expectAccept: boolean;
      reason?: string;
      verifierConfig?: {
        anchoredRoot: string;
        anchoredHashAlg: string;
        hashAlgAllowList: string[];
        registryAddress: string;
        registryChainId?: number;
      };
    };
    const vectorConfig: VerifierConfig =
      v.verifierConfig === undefined
        ? config
        : {
            ...config,
            anchoredRoot: v.verifierConfig.anchoredRoot,
            anchoredHashAlg: v.verifierConfig.anchoredHashAlg as HashAlgName,
            hashAlgAllowList: v.verifierConfig.hashAlgAllowList as HashAlgName[],
            registryAddress: v.verifierConfig.registryAddress,
            registryChainId: v.verifierConfig.registryChainId,
          };
    const run = (): VerificationResult =>
      verifyEnvelope(parseEnvelope(readFixture(v.envelopeFile)), vectorConfig);

    if (v.expectAccept) {
      try {
        const result = run();
        report.pass(v.class);
        for (const u of result.undischarged) {
          if (!undischargedSeen.has(u)) {
            undischargedSeen.add(u);
            report.note(v.class, `undischarged: ${u}`);
          }
        }
      } catch (e) {
        report.fail(v.class, `${v.name}: expected accept, got ${String(e)}`);
      }
      continue;
    }
    // The reason is load-bearing rather than decoration: several fixtures are rejectable for more
    // than one cause, so a boolean alone would pass an implementation that never ran the check
    // the vector is about (`corpus/README.md`).
    expectReject(report, v.class, v.name, v.reason ?? '', run);
  }
}

/**
 * Class 20: issue, disclose, then verify the copy THIS library produced.
 *
 * Every other class runs `verifyEnvelope` against bytes the corpus generator wrote. That is the
 * gap this class closes: a library can emit a disclosed copy its own verifier refuses and still
 * pass every other vector, because no other vector asks it to PRODUCE one.
 *
 * So this drives the real issuance and disclosure entry points - `issueFullCopy` and
 * `discloseFrom` - rather than assembling an envelope here. Assembling it here would test this
 * file instead of the library, which is exactly how an earlier round-trip test elsewhere missed
 * the defect: it checked inclusion proofs directly instead of driving the verifier.
 */
function runRoundTrip(corpus: Corpus, report: Report): void {
  const config = corpusVerifierConfig();
  for (const raw of corpus.vectors['roundTrip'] ?? []) {
    const v = raw as {
      name: string;
      class: number;
      recordType: string;
      schemaVersion: string;
      recordId: string;
      issuerId: string;
      issuerKeyId?: string;
      typeMap?: { id: string; version: string };
      recordFile: string;
      saltsFile: string;
      saltPairing: string;
      leafCount: number;
      root: string;
      disclosePaths: unknown[];
      expectedFullCopyFile: string;
      expectedDisclosedCopyFile: string;
      expectSelfVerifies: boolean;
    };
    try {
      const identity: RecordIdentity = {
        recordType: v.recordType,
        schemaVersion: v.schemaVersion,
        recordId: v.recordId,
        issuerId: v.issuerId,
        typeMapId: v.typeMap?.id,
        issuerKeyId: v.issuerKeyId,
      };
      const full = issueFullCopy({
        record: readFixture(v.recordFile),
        identity,
        resolver: resolverFor(v.recordType),
        typeMapVersion: v.typeMap?.version,
        salts: saltSourceFrom(v.saltsFile, v.saltPairing),
        emptyContainerPolicy: EMPTY_CONTAINER_POLICY,
      });
      expectEqual(report, v.class, `${v.name} (leafCount)`, full.commitment.leafCount, v.leafCount);
      expectEqual(report, v.class, `${v.name} (root)`, full.root, v.root);

      const disclosed = discloseFrom(full, {
        reveal: v.disclosePaths.map(segmentsOf),
        includeDisplayPath: true,
      });

      // Compared SEMANTICALLY: JSON member order, whether `displayPath` is emitted, the order of
      // `disclosure.leaves` and the order of a full copy's `salts` are not fixed by the
      // specification, so asserting any of them would fail a conforming implementation.
      // A number keeps its SOURCE TEXT through `comparableJson`, which is the one thing that must
      // survive - the full copy carries the record's literals (specification sections 6.4, 7.3).
      for (const [produced, expectedFile] of [
        [full.document, v.expectedFullCopyFile],
        [disclosed, v.expectedDisclosedCopyFile],
      ] as const) {
        const difference = firstDifference(
          normalizedForComparison(comparableJson(produced)),
          normalizedForComparison(comparableJson(readFixture(expectedFile))),
        );
        if (difference === undefined) {
          report.pass(v.class);
        } else {
          report.fail(
            v.class,
            `${v.name} (${expectedFile.split('/').pop() ?? expectedFile}): ${difference}`,
          );
        }
        // And the half no static fixture can assert: this library's verifier over this library's
        // own output. A producer that omitted a per-leaf value carrier fails HERE, on
        // `disclosed-leaf-named-without-value`, even though every leaf hash it computed was right.
        try {
          verifyEnvelope(parseEnvelope(produced), config);
          report.pass(v.class);
        } catch (e) {
          report.fail(
            v.class,
            `${v.name}: this library issued an envelope its own verifier refused: ${String(e)}`,
          );
        }
      }
    } catch (e) {
      report.fail(v.class, `${v.name}: ${String(e)}`);
    }
  }
}

/**
 * The first place two comparable forms differ, or `undefined` when they agree.
 *
 * A whole envelope printed twice is not a readable failure, and what this class catches is one
 * missing member on one leaf.
 */
function firstDifference(got: unknown, want: unknown, at = ''): string | undefined {
  if (got === want) {
    return undefined;
  }
  if (Array.isArray(got) && Array.isArray(want)) {
    if (got.length !== want.length) {
      return `${at || '/'}: ${got.length} entries, expected ${want.length}`;
    }
    for (let i = 0; i < got.length; i += 1) {
      const d = firstDifference(got[i], want[i], `${at}/${i}`);
      if (d !== undefined) {
        return d;
      }
    }
    return undefined;
  }
  if (isPlainObject(got) && isPlainObject(want)) {
    for (const key of new Set([...Object.keys(got), ...Object.keys(want)])) {
      if (!(key in got)) {
        return `${at}/${key}: ABSENT, expected ${JSON.stringify(want[key])}`;
      }
      if (!(key in want)) {
        return `${at}/${key}: ${JSON.stringify(got[key])}, expected ABSENT`;
      }
      const d = firstDifference(got[key], want[key], `${at}/${key}`);
      if (d !== undefined) {
        return d;
      }
    }
    return undefined;
  }
  return `${at || '/'}: ${JSON.stringify(got)}, expected ${JSON.stringify(want)}`;
}

/**
 * An envelope's comparison form with the aspects the specification does not fix removed. Applied
 * to BOTH sides, so what survives is what the specification actually says.
 *
 * Three things are relaxed, and nothing else. `disclosure.leaves` is ordered by leaf index and a
 * full copy's `salts` by its entry's structured path, because every leaf carries its own index and
 * every salt entry its own path, so neither array order carries anything. `displayPath` is
 * DROPPED: it is display only and never hashed (specification section 5.2), and
 * `schemas/envelope-1.0.json` leaves it out of `disclosedLeaf.required`, so a conforming producer
 * may omit it and a comparison that noticed would fail conforming work.
 *
 * Everything else stays exact, which is the half that matters: both array LENGTHS, every leaf's
 * segments, index, tag, value carrier, salt and audit path, and every scalar identity field. A
 * producer that omitted a per-leaf value carrier - the defect this class exists for - still fails.
 */
function normalizedForComparison(envelope: unknown): unknown {
  if (!isPlainObject(envelope)) {
    return envelope;
  }
  const out: Record<string, unknown> = { ...envelope };
  const salts = out['salts'];
  if (Array.isArray(salts)) {
    out['salts'] = [...salts].sort(bySortKey((entry) =>
      JSON.stringify(isPlainObject(entry) ? (entry['segments'] ?? null) : null),
    ));
  }
  const disclosure = out['disclosure'];
  if (isPlainObject(disclosure) && Array.isArray(disclosure['leaves'])) {
    const leaves = disclosure['leaves'].map((leaf) => {
      if (!isPlainObject(leaf)) {
        return leaf;
      }
      const copy: Record<string, unknown> = { ...leaf };
      delete copy['displayPath'];
      return copy;
    });
    leaves.sort(bySortKey((leaf) => (isPlainObject(leaf) ? numberLiteralOf(leaf['index']) : '')));
    out['disclosure'] = { ...disclosure, leaves };
  }
  return out;
}

function isPlainObject(x: unknown): x is Record<string, unknown> {
  return x !== null && typeof x === 'object' && !Array.isArray(x);
}

/** The digits `comparableJson` kept for a number, left-padded so a string sort orders them. */
function numberLiteralOf(node: unknown): string {
  const literal = isPlainObject(node) ? node['$numberLiteral'] : undefined;
  return typeof literal === 'string' ? literal.padStart(20, '0') : '';
}

function bySortKey(key: (x: unknown) => string): (a: unknown, b: unknown) => number {
  return (a, b) => {
    const ka = key(a);
    const kb = key(b);
    return ka < kb ? -1 : ka > kb ? 1 : 0;
  };
}

/** A comparison form for a parsed JSON tree: members sorted, numbers kept as source text. */
function comparableJson(node: unknown): unknown {
  const n = node as { kind?: string; members?: [string, unknown][]; items?: unknown[]; value?: unknown; literal?: string };
  if (n?.kind === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, val] of [...(n.members ?? [])].sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))) {
      out[k] = comparableJson(val);
    }
    return out;
  }
  if (n?.kind === 'array') {
    return (n.items ?? []).map(comparableJson);
  }
  if (n?.kind === 'number') {
    return { $numberLiteral: n.literal };
  }
  if (n?.kind === 'null') {
    return null;
  }
  return n?.value;
}

function printReport(report: Report, unicode: ReturnType<typeof describeUnicodeEnvironment>): void {
  console.log('');
  console.log('class   pass   fail   skip');
  for (const [cls, r] of report.entries()) {
    console.log(
      `${String(cls).padStart(5)} ${String(r.passed).padStart(6)} ${String(r.failed).padStart(6)} ${String(r.skipped).padStart(6)}`,
    );
    for (const f of r.failures.slice(0, 8)) {
      console.log(`        FAIL ${f}`);
    }
    if (r.failures.length > 8) {
      console.log(`        ... and ${r.failures.length - 8} more failures`);
    }
    for (const n of r.notes) {
      console.log(`        note ${n}`);
    }
  }
  console.log('');
  console.log(
    `total: ${report.totalPassed} passed, ${report.totalFailed} failed, ${report.totalSkipped} skipped`,
  );
  // Declared on EVERY run, beside the Unicode declaration and for the same reason: a total line a
  // consumer reads on its own must not stand for a conformance claim the run did not make.
  if (EMPTY_CONTAINER_POLICY === 'mechanical') {
    console.log(
      "DECLARED: this run used the empty-container policy 'mechanical', which takes tag 6 " +
        'EMPTY_ARRAY or tag 7 EMPTY_OBJECT from the observed kind WITHOUT consulting the type ' +
        "map. That is the committed corpus's rule and it is NOT specification section 3.3's, " +
        'which requires the exact selected map to authorize the path and kind first. A green ' +
        'total above is therefore evidence of agreement with the committed vectors and is NOT ' +
        'evidence of conformance to section 3.3. Run ROAX_EMPTY_CONTAINERS=map-authorized for ' +
        'the other reading; the two are mutually exclusive against this corpus, and the ' +
        'measurement is in docs/typescript-implementation-findings.md finding 2.',
    );
  } else {
    console.log(
      "DECLARED: this run used the empty-container policy 'map-authorized', which is " +
        'specification section 3.3. The committed class-5 empty-array and empty-object records ' +
        'fail closed under it, so failures there are the documented corpus divergence rather ' +
        'than a regression. See docs/typescript-implementation-findings.md finding 2.',
    );
  }
  if (!unicode.matchesPin) {
    console.log(
      `DECLARED: ROAX-CANON/1 pins Unicode ${unicode.pinnedByCanon}; this runtime's NFC tables ` +
        `are Unicode ${unicode.runtimeProvides}. Specification section 6.1 requires this to be ` +
        'stated rather than claimed as conformance.',
    );
  }
}

process.exitCode = main();
