package io.roax.canon

/**
 * RFC 9162 section 2.1.1, **with the one adaptation ROAX-CANON/1 section 9.1 states**.
 *
 * The RFC applies its `0x00` leaf-domain byte to raw entries. Here that byte is already applied
 * inside [leafHash], so this tree function operates on **already-hashed leaves** and MUST NOT
 * apply `0x00` a second time. `MTH([x])` is therefore `x`, not `H(0x00 ‖ x)`.
 *
 * The composition [leafHash] then [merkleTreeHash] is bit-identical to RFC 9162's `MTH` over raw
 * entries whose entry bytes are everything after the `0x00` in section 8.
 */
object Merkle {

    /**
     * `MTH(L)`.
     *
     * `MTH([])` is `H("")`, and is **unreachable in a conforming implementation**: the leaf set is
     * the union of section 3.3, which always carries the reserved leaves, so `L` is never empty
     * and its length is never below the floor. The branch exists so the function is total, which
     * is easier to port than one with an undefined case.
     */
    fun merkleTreeHash(leaves: List<ByteArray>, hash: HashAlgorithm = Sha256): ByteArray =
        mth(leaves, 0, leaves.size, hash)

    private fun mth(l: List<ByteArray>, from: Int, to: Int, hash: HashAlgorithm): ByteArray {
        val n = to - from
        if (n == 0) return hash.digest(ByteArray(0))
        if (n == 1) return l[from]
        val k = largestPowerOfTwoStrictlyBelow(n)
        val left = mth(l, from, from + k, hash)
        val right = mth(l, from + k, to, hash)
        return hash.digest(ByteSink(1 + left.size + right.size).byte(0x01).bytes(left).bytes(right).toByteArray())
    }

    /** The largest power of two strictly smaller than [n], for `n > 1`. */
    internal fun largestPowerOfTwoStrictlyBelow(n: Int): Int {
        require(n > 1) { "split rule needs n > 1, got $n" }
        return Integer.highestOneBit(n - 1)
    }

    /**
     * RFC 9162 section 2.1.3, `PATH(m, D[n])`, over already-hashed leaves.
     */
    fun inclusionPath(leaves: List<ByteArray>, index: Int, hash: HashAlgorithm = Sha256): List<ByteArray> {
        require(index in leaves.indices) { "index $index outside [0, ${leaves.size})" }
        val out = ArrayList<ByteArray>()
        path(leaves, 0, leaves.size, index, out, hash)
        return out
    }

    private fun path(
        l: List<ByteArray>,
        from: Int,
        to: Int,
        m: Int,
        out: MutableList<ByteArray>,
        hash: HashAlgorithm,
    ) {
        val n = to - from
        if (n == 1) return
        val k = largestPowerOfTwoStrictlyBelow(n)
        if (m < k) {
            path(l, from, from + k, m, out, hash)
            out.add(mth(l, from + k, to, hash))
        } else {
            path(l, from + k, to, m - k, out, hash)
            out.add(mth(l, from, from + k, hash))
        }
    }

    /**
     * RFC 9162 section 2.1.3.2, unchanged.
     *
     * **The tree size is an INPUT here, not something this function recovers**, and that is the
     * measured correction ROAX-CANON/1 section 11.1 records. An attacker who controls the tree
     * size controls the shape the verifier rebuilds and can walk an internal node to the genuine
     * root: on an 8-leaf tree, `MTH(L[0:4])` presented at index 0 with a forged size of 2 verifies.
     *
     * So this function is a **fold primitive and not a membership check**. What makes a membership
     * check sound is section 10 step 2 - the caller recomputes the leaf hash from the disclosed
     * path, tag, value and salt and never accepts a supplied one - which [Envelope.verify] does.
     * A recomputed leaf hash is `0x00`-domained by construction and an internal node is
     * `0x01`-domained, so it cannot equal one except by defeating second-preimage resistance.
     */
    fun verifyInclusion(
        leafHash: ByteArray,
        leafIndex: Long,
        treeSize: Long,
        auditPath: List<ByteArray>,
        root: ByteArray,
        hash: HashAlgorithm = Sha256,
    ): Boolean {
        if (leafIndex < 0 || treeSize < 0) return false
        if (leafIndex >= treeSize) return false

        var fn = leafIndex
        var sn = treeSize - 1
        var r = leafHash

        for (p in auditPath) {
            if (sn == 0L) return false
            if ((fn and 1L) == 1L || fn == sn) {
                r = hash.digest(ByteSink(1 + p.size + r.size).byte(0x01).bytes(p).bytes(r).toByteArray())
                if ((fn and 1L) == 0L) {
                    while (fn != 0L && (fn and 1L) == 0L) {
                        fn = fn shr 1
                        sn = sn shr 1
                    }
                }
            } else {
                r = hash.digest(ByteSink(1 + r.size + p.size).byte(0x01).bytes(r).bytes(p).toByteArray())
            }
            fn = fn shr 1
            sn = sn shr 1
        }

        return sn == 0L && Bytes.constantTimeEquals(r, root)
    }
}
