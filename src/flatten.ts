/**
 * Flattening (specification section 3.3) and the leaf set.
 *
 * ```
 * flatten(node, path):
 *   if node is a map and is empty:        emit (path, typeTag(path, "object"), -)
 *   if node is a map and is non-empty:    for each key k: flatten(node[k], path ‖ KEY(k))
 *   if node is an array and is empty:     emit (path, typeTag(path, "array"), -)
 *   if node is an array and is non-empty: for each index i: flatten(node[i], path ‖ INDEX(i))
 *   otherwise:                            emit (path, typeTag(path, jsonKind(node)), node)
 * ```
 *
 * A leaf is produced for every scalar AND for every EMPTY container, so removing an empty
 * container changes the root. Empty array, empty object and explicit null are three distinct
 * leaves. This is a departure from dogtag, which collapses all three to a single `TypedScalar::Null`
 * (`dogtag-mono-repo`, `crates/dogtag-standard-rs/src/flatten.rs:96-115`).
 *
 * **The leaf set is the UNION** of the reserved leaves (section 11.2) and the record's leaves.
 * A flattener that walks the record only produces a different root, so this is not an optional
 * step.
 */

import { fail } from './errors.js';
import { toHex } from './bytes.js';
import { encodePath, displayPath, type Path } from './path.js';
import { assertRecordPathAllowed, reservedLeaves, type RecordIdentity } from './reserved.js';
import { carrierFromJson, TypeTag, type CarrierValue, type TypeTagValue } from './value.js';
import type { JsonValue } from './json.js';
import type { TypeTagResolver } from './typemap.js';

export interface FlatLeaf {
  readonly path: Path;
  readonly tag: TypeTagValue;
  readonly value: CarrierValue | undefined;
  /** True for the reserved `roax.*` leaves, false for the record's own. */
  readonly reserved: boolean;
}

/**
 * How an EMPTY container gets its tag.
 *
 * **This exists because the specification and the committed corpus disagree, and the disagreement
 * is reported rather than resolved by picking a default quietly.**
 *
 * - `'map-authorized'` is what specification section 3.3 requires: "An object output is tag 7
 *   EMPTY_OBJECT and an array output is tag 6 EMPTY_ARRAY, but only when the exact selected map
 *   authorizes that structured path and observed kind under section 4.2. Assigning tags 6 or 7
 *   before map resolution would let an unknown empty issuer extension bypass decision D7's
 *   fail-closed rule."
 * - `'mechanical'` assigns tag 6 or 7 from the observed kind without consulting the map.
 *
 * The committed corpus can only be reproduced under `'mechanical'`: its class-5 vectors
 * `record-structure-empty-array` and `record-structure-empty-object` assert roots over the path
 * `a.b`, and `corpus/type-maps/org.roax.corpus.synthetic.json` declares `a.b` for `jsonKind:
 * "null"` alone. Under the specification's rule those two records fail closed and have no root at
 * all. `docs/conformance-corpus.md` class 11 names "an unknown empty array and empty object" as
 * mandatory fail-closed rows and the committed corpus carries neither, which is the same gap seen
 * from the other side.
 */
export type EmptyContainerPolicy = 'map-authorized' | 'mechanical';

export interface FlattenOptions {
  readonly resolver: TypeTagResolver;
  readonly emptyContainerPolicy?: EmptyContainerPolicy | undefined;
}

/**
 * Flattens a record into its own leaves. Does NOT add the reserved leaves; `leafSet` does.
 */
export function flattenRecord(record: JsonValue, options: FlattenOptions): FlatLeaf[] {
  const policy: EmptyContainerPolicy = options.emptyContainerPolicy ?? 'map-authorized';
  const out: FlatLeaf[] = [];
  walk(record, [], out, options.resolver, policy);
  return out;
}

function walk(
  node: JsonValue,
  path: Path,
  out: FlatLeaf[],
  resolver: TypeTagResolver,
  policy: EmptyContainerPolicy,
): void {
  switch (node.kind) {
    case 'object': {
      if (node.members.length === 0) {
        out.push(emptyContainerLeaf(path, 'object', resolver, policy));
        return;
      }
      for (const [key, child] of node.members) {
        const childPath: Path = [...path, { key }];
        // The reserved-namespace guard, at the input boundary and before any hashing
        // (specification section 11.2). It tests the FIRST segment only, so it fires here for a
        // top-level key and is a no-op deeper down.
        assertRecordPathAllowed(childPath);
        walk(child, childPath, out, resolver, policy);
      }
      return;
    }
    case 'array': {
      if (node.items.length === 0) {
        out.push(emptyContainerLeaf(path, 'array', resolver, policy));
        return;
      }
      for (let i = 0; i < node.items.length; i += 1) {
        walk(node.items[i] as JsonValue, [...path, { index: i }], out, resolver, policy);
      }
      return;
    }
    default: {
      const tag = resolver.resolve(path, node.kind);
      out.push({ path, tag, value: carrierFromJson(tag, node), reserved: false });
    }
  }
}

function emptyContainerLeaf(
  path: Path,
  kind: 'object' | 'array',
  resolver: TypeTagResolver,
  policy: EmptyContainerPolicy,
): FlatLeaf {
  const mechanicalTag = kind === 'array' ? TypeTag.EMPTY_ARRAY : TypeTag.EMPTY_OBJECT;
  if (policy === 'mechanical') {
    return { path, tag: mechanicalTag, value: undefined, reserved: false };
  }
  const tag = resolver.resolve(path, kind);
  if (tag !== mechanicalTag) {
    fail(
      'value-type-mismatch',
      `the map binds ${displayPath(path)} at kind ${kind} to tag ${tag}, ` +
        `but an empty ${kind} is tag ${mechanicalTag}`,
    );
  }
  return { path, tag, value: undefined, reserved: false };
}

/**
 * The union of section 3.3, ordered by ascending `encodePath` bytes (section 9).
 *
 * Reserved and record leaves are unioned BEFORE the sort, so they are ordered together and are
 * indistinguishable to the tree function.
 *
 * The order is NOT alphabetical: because the length prefix precedes the key bytes, sorting encoded
 * paths sorts by (segment count, then segment kind, then key length, then key bytes)
 * (section 5.3). A plain unsigned byte comparison over the encoding is the easiest thing to get
 * identical in five languages, which is why decision D5 was ruled D5a.
 */
export interface OrderedLeaf extends FlatLeaf {
  readonly encodedPath: Uint8Array;
  readonly index: number;
}

export function leafSet(
  recordLeaves: readonly FlatLeaf[],
  identity: RecordIdentity,
): OrderedLeaf[] {
  // Specification section 3.3: a record that contributes ZERO leaves of its own MUST be rejected
  // at issuance rather than anchored. The rejection is on the record's contribution, because the
  // union always carries the reserved leaves and the tree itself is therefore never empty.
  if (recordLeaves.length === 0) {
    fail(
      'record-contributes-no-leaves',
      'a record contributing no leaves of its own MUST be rejected at issuance ' +
        '(specification section 3.3)',
    );
  }
  const all: FlatLeaf[] = [...recordLeaves];
  for (const r of reservedLeaves(identity)) {
    all.push({ path: r.path, tag: r.tag, value: r.value, reserved: true });
  }
  const withEncoding = all.map((leaf) => ({ leaf, encodedPath: encodePath(leaf.path) }));
  withEncoding.sort((a, b) => compareBytes(a.encodedPath, b.encodedPath));

  const ordered: OrderedLeaf[] = [];
  for (let i = 0; i < withEncoding.length; i += 1) {
    const entry = withEncoding[i] as { leaf: FlatLeaf; encodedPath: Uint8Array };
    const previous = i > 0 ? (withEncoding[i - 1] as { encodedPath: Uint8Array }) : undefined;
    // Section 9 states that paths are unique by construction, so the order is total and tie-free.
    // Two members differing only in Unicode normalization form are distinct JSON keys and the
    // SAME encoded path, so the guarantee has to be enforced rather than assumed.
    if (previous !== undefined && compareBytes(previous.encodedPath, entry.encodedPath) === 0) {
      fail(
        'duplicate-key',
        `two leaves share the encoded path ${toHex(entry.encodedPath)} ` +
          `(${displayPath(entry.leaf.path)}), which section 9 requires to be unique`,
      );
    }
    ordered.push({ ...entry.leaf, encodedPath: entry.encodedPath, index: i });
  }
  return ordered;
}

function compareBytes(a: Uint8Array, b: Uint8Array): number {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i += 1) {
    const x = a[i] as number;
    const y = b[i] as number;
    if (x !== y) {
      return x < y ? -1 : 1;
    }
  }
  return a.length === b.length ? 0 : a.length < b.length ? -1 : 1;
}
