import Foundation

/// RFC 9162 section 2.1.1, with the one adaptation specification section 9.1
/// states.
///
/// The RFC applies the `0x00` leaf-domain byte to *raw entries*. Here that byte
/// is already inside `leafHash` (specification section 8), so this function
/// operates on already-hashed leaves and MUST NOT apply `0x00` a second time.
/// The composition `leafHash` then `MTH` is bit-identical to the RFC's `MTH`
/// over raw entries whose bytes are everything after the `0x00`.
public enum MerkleTree {

    /// `MTH(L)` of specification section 9.1.
    ///
    /// ```
    /// MTH([])     = H("")          // total function only
    /// MTH([x])    = x              // NOT H(0x00 ‖ x)
    /// MTH(L), n>1 = H(0x01 ‖ MTH(L[0:k]) ‖ MTH(L[k:n]))
    ///               k = largest power of two strictly smaller than n
    /// ```
    ///
    /// The empty branch is unreachable in a conforming implementation: the leaf
    /// set is the union of specification section 3.3, which always carries the
    /// reserved leaves, so `L` is never shorter than 6. It is kept so the
    /// function is total.
    public static func root<H: ROAXHash>(_ leaves: [[UInt8]], hash: H.Type) -> [UInt8] {
        if leaves.isEmpty { return H.hash([]) }
        if leaves.count == 1 { return leaves[0] }
        let k = largestPowerOfTwoBelow(leaves.count)
        let left = root(Array(leaves[0..<k]), hash: H.self)
        let right = root(Array(leaves[k...]), hash: H.self)
        var preimage = [UInt8]()
        preimage.reserveCapacity(1 + left.count + right.count)
        preimage.append(0x01)                               // internal-node domain byte
        preimage.append(contentsOf: left)
        preimage.append(contentsOf: right)
        return H.hash(preimage)
    }

    /// RFC 9162 section 2.1.3.1: the audit path for the leaf at `index`.
    public static func inclusionProof<H: ROAXHash>(
        leaves: [[UInt8]],
        index: Int,
        hash: H.Type
    ) throws -> [[UInt8]] {
        guard index >= 0, index < leaves.count else {
            throw ROAXError.inclusionProofFailed("index \(index) is outside a \(leaves.count)-leaf tree")
        }
        return path(index, leaves, hash: H.self)
    }

    private static func path<H: ROAXHash>(
        _ m: Int,
        _ leaves: [[UInt8]],
        hash: H.Type
    ) -> [[UInt8]] {
        if leaves.count == 1 { return [] }
        let k = largestPowerOfTwoBelow(leaves.count)
        if m < k {
            return path(m, Array(leaves[0..<k]), hash: H.self)
                + [root(Array(leaves[k...]), hash: H.self)]
        } else {
            return path(m - k, Array(leaves[k...]), hash: H.self)
                + [root(Array(leaves[0..<k]), hash: H.self)]
        }
    }

    /// RFC 9162 section 2.1.3.2, unchanged.
    ///
    /// **The tree size is an INPUT to this function and is not recovered by
    /// it.** Specification section 11.1 records the measurement: an attacker who
    /// supplies both a leaf hash and a tree size can walk an internal node to
    /// the genuine root, so `leafCount` is not self-binding in a disclosed copy.
    /// What blocks that attack is section 10 step 2 - a conforming verifier
    /// recomputes the leaf hash from the disclosed fields and never accepts a
    /// supplied one - which `EnvelopeVerifier` does. Nothing in this package
    /// calls `verifyInclusion` with a caller-supplied leaf hash except the
    /// corpus runner, whose vectors are about this function alone.
    public static func verifyInclusion<H: ROAXHash>(
        leafHash: [UInt8],
        index: Int,
        treeSize: Int,
        auditPath: [[UInt8]],
        root expectedRoot: [UInt8],
        hash: H.Type
    ) -> Bool {
        guard index >= 0, treeSize > 0, index < treeSize else { return false }

        var fn = index
        var sn = treeSize - 1
        var r = leafHash

        for sibling in auditPath {
            if sn == 0 { return false }
            if fn % 2 == 1 || fn == sn {
                var preimage: [UInt8] = [0x01]
                preimage.append(contentsOf: sibling)
                preimage.append(contentsOf: r)
                r = H.hash(preimage)
                while fn != 0 && fn % 2 == 0 { fn >>= 1; sn >>= 1 }
            } else {
                var preimage: [UInt8] = [0x01]
                preimage.append(contentsOf: r)
                preimage.append(contentsOf: sibling)
                r = H.hash(preimage)
            }
            fn >>= 1
            sn >>= 1
        }

        return sn == 0 && r == expectedRoot
    }

    @inline(__always)
    static func largestPowerOfTwoBelow(_ n: Int) -> Int {
        precondition(n > 1)
        var k = 1
        while k << 1 < n { k <<= 1 }
        return k
    }
}
