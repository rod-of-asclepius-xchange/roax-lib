/**
 * Schema binding: resolving a structured path and an observed JSON kind to a ROAX type tag
 * (specification section 4).
 *
 * **The type tag MUST come from the schema, not from the JSON literal's syntax.** Three issuers
 * writing the same logical FHIR `decimal` as `100`, `100.0` and `1e2` produce three different
 * roots under syntactic inference; with a schema-bound tag `100` and `1e2` agree and `100.0`
 * stays distinct, which is the correct FHIR outcome (section 4.1).
 *
 * **Unknown transitions and missing observed-kind outputs MUST fail closed** (section 4.2,
 * decision D7 ruled D7a). A resolver MUST NOT search another installed map, infer from JSON
 * syntax, or apply a fallback tag.
 */

import { nfc } from './bytes.js';
import { fail } from './errors.js';
import { isKeySegment, displayPath, type Path } from './path.js';
import type { JsonKind } from './json.js';
import { isTypeTag, TypeTag, type TypeTagValue } from './value.js';

/**
 * What a record needs in order to be given tags.
 *
 * Deliberately an interface rather than one concrete matcher. Specification section 4.2 makes the
 * operative matcher a STRUCTURED-PATH DFA over the published artifacts in `type-maps/`; the only
 * implementation here is over the superseded display-pattern format, because that is the format
 * the conformance corpus resolves against. See `LegacyPatternTypeMap` for the full statement of
 * that disagreement.
 */
export interface TypeTagResolver {
  /** The profile this map applies to. */
  readonly recordType: string;
  /**
   * Resolves a path and observed kind to a tag, or FAILS CLOSED.
   *
   * Never returns a default and never consults the value's syntax.
   */
  resolve(path: Path, kind: JsonKind): TypeTagValue;
}

interface KeyMatcher {
  readonly kind: 'key';
  readonly key: string;
}
interface IndexMatcher {
  readonly kind: 'index';
}
interface DescendantMatcher {
  readonly kind: 'descendant';
}
type PatternMatcher = KeyMatcher | IndexMatcher | DescendantMatcher;

interface CompiledEntry {
  readonly matchers: readonly PatternMatcher[];
  readonly jsonKind: JsonKind;
  readonly tag: TypeTagValue;
  readonly pattern: string;
}

interface LegacyMapFile {
  readonly typeMapVersion: string;
  readonly recordType: string;
  readonly schemaVersion: string;
  readonly entries: readonly {
    readonly pattern: string;
    readonly jsonKind: JsonKind;
    readonly tag: number;
  }[];
}

/**
 * A resolver over the SUPERSEDED display-pattern type-map format.
 *
 * **This format is forbidden for resolution by this repository's own schema.**
 * `schemas/type-map-1.0.json` is titled "Superseded draft ROAX display-pattern type map v1" and
 * states that it "MUST NOT be used to publish or resolve a type map because its display-pattern
 * and first-match representation conflicts with the structured-path rules in spec sections 4.2
 * and 5.2". The operative artifacts are `schemas/type-map-artifact-1.0.json` plus
 * `type-maps/registry-1.0.0.json`.
 *
 * It is implemented anyway, and only here, because the committed conformance corpus resolves
 * every one of its class-5, 7, 10, 11, 13, 15 and 19 vectors against
 * `corpus/type-maps/<recordType>.json`, which is in this format. There is no published artifact
 * for `org.roax.corpus.synthetic` at all, so no structured-path DFA can resolve a single corpus
 * record. Under specification section 1.1 that is a release-blocking corpus defect rather than a
 * wrinkle, and it is reported as a finding rather than absorbed.
 *
 * The pattern language is display notation, which is why the format was superseded: a pattern
 * cannot address a key containing `.`, `[` or `]`, and specification section 5 deliberately admits
 * such keys with no rejection rule. An ambiguous pattern is REJECTED here rather than mis-parsed.
 */
export class LegacyPatternTypeMap implements TypeTagResolver {
  readonly recordType: string;
  readonly schemaVersion: string;
  readonly typeMapVersion: string;
  private readonly entries: readonly CompiledEntry[];

  private constructor(file: LegacyMapFile, entries: readonly CompiledEntry[]) {
    this.recordType = file.recordType;
    this.schemaVersion = file.schemaVersion;
    this.typeMapVersion = file.typeMapVersion;
    this.entries = entries;
  }

  static compile(file: LegacyMapFile): LegacyPatternTypeMap {
    const entries: CompiledEntry[] = [];
    for (const e of file.entries) {
      if (!isTypeTag(e.tag)) {
        fail('type-map-rejected', `type map entry ${e.pattern} names unknown tag ${e.tag}`);
      }
      // Specification section 6.5: no version-1 profile selects BLOB_REF, and an implementation
      // MUST REJECT a type map that binds any path to tag 8. That is a rejection of the MAP, not
      // a fail-closed on a path: the path IS covered, by a binding no profile has declared.
      if (e.tag === TypeTag.BLOB_REF) {
        fail(
          'type-map-rejected',
          `type map binds ${e.pattern} to tag 8 BLOB_REF, which no version-1 profile selects ` +
            '(specification section 6.5)',
        );
      }
      entries.push({
        matchers: compilePattern(e.pattern),
        jsonKind: e.jsonKind,
        tag: e.tag,
        pattern: e.pattern,
      });
    }
    return new LegacyPatternTypeMap(file, entries);
  }

  resolve(path: Path, kind: JsonKind): TypeTagValue {
    for (const entry of this.entries) {
      if (entry.jsonKind === kind && matches(entry.matchers, path, 0, 0)) {
        return entry.tag;
      }
    }
    fail(
      'type-map-fail-closed',
      `no binding in ${this.recordType} for kind ${kind} at ${displayPath(path)}`,
      { recordType: this.recordType, kind, path: displayPath(path) },
    );
  }
}

function compilePattern(pattern: string): PatternMatcher[] {
  const tokens = pattern.split('.');
  const matchers: PatternMatcher[] = [];
  for (let t = 0; t < tokens.length; t += 1) {
    const token = tokens[t] as string;
    if (token === '**') {
      if (t !== tokens.length - 1) {
        fail('type-map-rejected', `pattern ${JSON.stringify(pattern)} places ** before its end`);
      }
      matchers.push({ kind: 'descendant' });
      continue;
    }
    // Trailing `[*]` groups become INDEX matchers.
    let base = token;
    const indexers: IndexMatcher[] = [];
    while (base.endsWith('[*]')) {
      base = base.slice(0, base.length - 3);
      indexers.push({ kind: 'index' });
    }
    // Anything else containing a bracket is ambiguous under display notation. Rejecting is the
    // only safe answer: a key may legitimately contain `[` or `]` (specification section 5), so a
    // guess here would bind the wrong path silently.
    if (base.includes('[') || base.includes(']')) {
      fail(
        'type-map-rejected',
        `pattern ${JSON.stringify(pattern)} is ambiguous: a bracket appears outside a [*] index`,
      );
    }
    if (base === '') {
      // `a..b` cannot be told apart from a legitimate empty key, which section 5 admits.
      fail('type-map-rejected', `pattern ${JSON.stringify(pattern)} has an empty key token`);
    }
    // Ruled decision D14a: the lookup compares NFC-normalized keys on BOTH sides, so a pattern
    // token is normalized once at compile time rather than on every comparison.
    matchers.push({ kind: 'key', key: nfc(base) });
    matchers.push(...indexers);
  }
  return matchers;
}

/**
 * Matches compiled matchers against structured segments.
 *
 * **A key is compared under NFC on BOTH sides** (specification section 4.2, decision D14 ruled
 * D14a on 2026-07-30). The pattern token was normalized by `compilePattern`; the segment key is
 * normalized here.
 *
 * Two reasons, and the second is why the first is not merely a preference. Section 11.2's rule is
 * "check the bytes you commit, not the bytes you received", and a STRING leaf commits `utf8(NFC(s))`
 * while an encoded KEY segment commits `NFC(key)` (section 5.1), so a raw comparison checks bytes no
 * part of the record ever commits. And under a raw comparison two records that RENDER IDENTICALLY
 * diverge: the composed spelling resolves and commits while the decomposed one is refused outright
 * by the fail-closed rule of section 4.2. That is the invisible divergence decision D12 was ruled to
 * prevent, arriving one layer up, so ruling raw here would reintroduce at the type-map layer the
 * hazard already ruled out at the leaf layer.
 */
function matches(
  matchers: readonly PatternMatcher[],
  path: Path,
  mi: number,
  si: number,
): boolean {
  if (mi === matchers.length) {
    return si === path.length;
  }
  const m = matchers[mi] as PatternMatcher;
  if (m.kind === 'descendant') {
    // `**` stands for one or more remaining segments. It is unexercised by every committed
    // vector: `a.**` is the only instance and no record or type-map vector reaches it.
    return si < path.length;
  }
  const segment = path[si];
  if (segment === undefined) {
    return false;
  }
  if (m.kind === 'key') {
    if (!isKeySegment(segment) || nfc(segment.key) !== m.key) {
      return false;
    }
  } else if (isKeySegment(segment)) {
    return false;
  }
  return matches(matchers, path, mi + 1, si + 1);
}
