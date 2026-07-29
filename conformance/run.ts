/**
 * The ROAX conformance runner for this implementation.
 *
 * Written against `docs/conformance-corpus.md`, `corpus/README.md` and
 * `schemas/conformance-corpus-1.0.json`. It deliberately does not reuse
 * `corpus/tools/check_corpus.mjs`, because that runner imports one of the two reference
 * implementations and the value of a third implementation is that it agrees without having read
 * either.
 */

import { resolve } from 'node:path';
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
import type { EmptyContainerPolicy } from '../src/flatten.js';
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

/**
 * The repository root.
 *
 * Resolved by walking up from the compiled module until `corpus/conformance-corpus-1.0.json` is
 * found, so the runner works both from `dist/conformance/` and from a source-level runner, and so
 * no absolute path into anyone's working tree appears in this public repository.
 */
const ROOT = findRepositoryRoot(import.meta.dirname);

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

function main(): number {
  const corpus = readJsonFileLoose(
    resolve(ROOT, 'corpus/conformance-corpus-1.0.json'),
  ) as Corpus;
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
      tag?: number;
      input?: unknown;
      segments?: unknown;
      reason: string;
    };
    expectReject(report, v.class, v.name, v.reason, () => {
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
 * Locates a `recordVector.recordFile`, or reports that it is unavailable.
 *
 * Class 10 names the three Singapore MOH samples inside a third-party checkout that this
 * repository deliberately does not vendor, as `references/schemata/src/...`. A record extracted
 * from one is placed in a scratch directory named by `ROAX_REFERENCE_RECORDS`, keyed by the
 * vector's `recordType`. Nothing is read from, or written into, this repository, and the absence
 * of the checkout is REPORTED rather than counted as a pass.
 */
function resolveRecordFile(recordFile: string): string | undefined {
  if (!recordFile.startsWith('references/')) {
    return existsSync(resolve(ROOT, recordFile)) ? recordFile : undefined;
  }
  const dir = process.env['ROAX_REFERENCE_RECORDS'];
  if (dir === undefined) {
    return undefined;
  }
  // `.../<recordType>/<version>/sample-data.ts#<export>` -> `<dir>/<recordType>.json`.
  const withoutExport = recordFile.split('#')[0] as string;
  const parts = withoutExport.split('/');
  const profile = parts[parts.length - 3];
  const authority = parts.slice(3, parts.length - 3).join('.');
  const candidate = resolve(dir, `${authority}.${profile}.json`);
  return existsSync(candidate) ? candidate : undefined;
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
    const recordPath = resolveRecordFile(v.recordFile);
    if (recordPath === undefined) {
      // Class 10 names the MOH samples in a checkout that lives outside this repository by
      // design. Absence is REPORTED rather than hidden, and never reported as green.
      report.skip(
        v.class,
        `${v.name}: the reference sample ${v.recordFile} is outside this repository. ` +
          'Set ROAX_REFERENCE_RECORDS to a directory of extracted records to run it.',
      );
      continue;
    }
    try {
      const commitment = commitRecord(readFixture(recordPath), {
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
    // `corpus/type-maps/` carries no `hl7.fhir.bundle` map, so section 10 step 1 cannot be
    // discharged for the eight `floor-hl7-fhir-bundle-*` fixtures. Reported, not hidden.
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
  if (!unicode.matchesPin) {
    console.log(
      `DECLARED: ROAX-CANON/1 pins Unicode ${unicode.pinnedByCanon}; this runtime's NFC tables ` +
        `are Unicode ${unicode.runtimeProvides}. Specification section 6.1 requires this to be ` +
        'stated rather than claimed as conformance.',
    );
  }
}

process.exitCode = main();
