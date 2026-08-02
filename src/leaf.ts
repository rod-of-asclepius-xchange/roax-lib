/**
 * Leaf construction (specification section 8).
 *
 * ```
 * leafHash(path, tag, value, salt) = H(
 *       0x00                              // RFC 9162 leaf domain byte
 *     ‖ u32be(len(DOMAIN)) ‖ DOMAIN       // DOMAIN = "ROAX-CANON/1/" ‖ hashAlg
 *     ‖ u32be(len(P))      ‖ P            // P = encodePath(path)
 *     ‖ tag                               // one byte
 *     ‖ u32be(len(salt))   ‖ salt         // 16 bytes
 *     ‖ u64be(len(V))      ‖ V            // V = encoded value bytes (section 6)
 * )
 * ```
 *
 * **There is exactly one leaf-preimage builder in this library and this is it.** dogtag records
 * the cost of the alternative plainly - "A second preimage builder is the drift"
 * (`dogtag-mono-repo`, `AGENTS.md:1747-1751`). Since decision D4 was ruled D4b there is no salt
 * preimage either, so this is the only preimage in the design.
 */

import { concatBytes, u32be, u64be } from './bytes.js';
import {
  domainString,
  ORDERING_DEFAULT,
  type HashFunction,
  type Ordering,
} from './hash.js';
import { encodePath, type Path } from './path.js';
import { encodeValue, type CarrierValue, type TypeTagValue } from './value.js';
import { fail } from './errors.js';

/** `ROAX-CANON/1` pins the salt length at exactly 16 bytes (specification section 7). */
export const SALT_LENGTH = 16;

export interface Leaf {
  readonly path: Path;
  readonly tag: TypeTagValue;
  readonly value: CarrierValue | undefined;
  readonly salt: Uint8Array;
}

/**
 * Specification section 8.
 *
 * `ordering` reaches this preimage ONLY through `DOMAIN` (section 9.5, H1), which is why a leaf
 * is ordering-sensitive even though it carries no tree: a copy issued under one ordering and
 * verified under the other fails here rather than at the tree.
 */
export function leafHash(
  hash: HashFunction,
  path: Path,
  tag: TypeTagValue,
  value: CarrierValue | undefined,
  salt: Uint8Array,
  ordering: Ordering = ORDERING_DEFAULT,
): Uint8Array {
  if (salt.length !== SALT_LENGTH) {
    fail('salt-length', `a salt is exactly ${SALT_LENGTH} bytes, got ${salt.length}`);
  }
  const domain = domainString(hash.name, ordering);
  const encodedPath = encodePath(path);
  const encodedValue = encodeValue(tag, value);
  const preimage = concatBytes([
    Uint8Array.of(0x00), // RFC 9162 leaf domain byte, applied HERE and not again in the tree.
    u32be(domain.length),
    domain,
    u32be(encodedPath.length),
    encodedPath,
    Uint8Array.of(tag),
    u32be(salt.length),
    salt,
    // u64be rather than u32be: a value may exceed 4 GiB in principle, and every variable-length
    // component is length-prefixed so no two distinct tuples share a preimage.
    u64be(encodedValue.length),
    encodedValue,
  ]);
  return hash.hash(preimage);
}
