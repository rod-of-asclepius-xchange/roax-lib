import Foundation

#if canImport(CryptoKit)
import CryptoKit
#endif

/// The hash function named by the envelope's `hashAlg`.
///
/// Specification section 8 writes `H` rather than `SHA-256` because this is a
/// hash-agile design, so the construction takes the algorithm as a parameter
/// rather than naming one. `ROAX-CANON/1` defines `H` for `SHA-256` only:
/// `Poseidon-BN254` is registered and its parameterization is not pinned, so a
/// record MUST NOT be issued against it (specification section 7.4).
public protocol ROAXHash {
    /// The `hashAlg` identifier, which is also the tail of `DOMAIN`.
    static var identifier: String { get }
    static func hash(_ bytes: [UInt8]) -> [UInt8]
}

public enum SHA256Hash: ROAXHash {
    public static let identifier = "SHA-256"

    public static func hash(_ bytes: [UInt8]) -> [UInt8] {
        #if canImport(CryptoKit)
        return Array(CryptoKit.SHA256.hash(data: Data(bytes)))
        #else
        return ReferenceSHA256.hash(bytes)
        #endif
    }
}

/// The algorithms this verifier will run, which is the allow-list specification
/// section 7.4 H3 requires.
///
/// H3 closes the case H2 does not: an algorithm that was legitimately
/// registered and has since been retired. Without it a verifier that has
/// retired an algorithm still runs it because the envelope asked it to.
public struct HashAlgorithmAllowList: Sendable {
    public let allowed: Set<String>

    public init(allowed: Set<String>) { self.allowed = allowed }

    /// The only algorithm `ROAX-CANON/1` defines a construction for.
    public static let versionOneDefault = HashAlgorithmAllowList(allowed: ["SHA-256"])

    public func check(_ hashAlg: String) throws {
        guard allowed.contains(hashAlg) else { throw ROAXError.hashAlgNotAllowed(hashAlg) }
    }
}

/// A dependency-free SHA-256, used where CryptoKit does not exist and used as a
/// cross-check where it does.
///
/// Two implementations of the same primitive would normally be a divergence
/// risk rather than an asset. It is an asset here for one reason: the test
/// suite asserts the two agree on every corpus leaf vector, so the pair is
/// checked rather than trusted, and the package stops depending on one vendor's
/// framework for a construction the specification defines over bytes.
public enum ReferenceSHA256 {

    private static let k: [UInt32] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
        0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
        0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
        0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
        0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
        0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
        0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
        0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
    ]

    public static func hash(_ message: [UInt8]) -> [UInt8] {
        var h: [UInt32] = [
            0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
            0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
        ]

        var padded = message
        let bitLength = UInt64(message.count) * 8
        padded.append(0x80)
        while padded.count % 64 != 56 { padded.append(0) }
        padded.appendU64BE(bitLength)

        var w = [UInt32](repeating: 0, count: 64)
        var block = 0
        while block < padded.count {
            for t in 0..<16 {
                let o = block + t * 4
                w[t] = UInt32(padded[o]) << 24 | UInt32(padded[o + 1]) << 16
                    | UInt32(padded[o + 2]) << 8 | UInt32(padded[o + 3])
            }
            for t in 16..<64 {
                let s0 = rotr(w[t - 15], 7) ^ rotr(w[t - 15], 18) ^ (w[t - 15] >> 3)
                let s1 = rotr(w[t - 2], 17) ^ rotr(w[t - 2], 19) ^ (w[t - 2] >> 10)
                w[t] = w[t - 16] &+ s0 &+ w[t - 7] &+ s1
            }

            var a = h[0], b = h[1], c = h[2], d = h[3]
            var e = h[4], f = h[5], g = h[6], hh = h[7]

            for t in 0..<64 {
                let s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)
                let ch = (e & f) ^ (~e & g)
                let t1 = hh &+ s1 &+ ch &+ k[t] &+ w[t]
                let s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)
                let maj = (a & b) ^ (a & c) ^ (b & c)
                let t2 = s0 &+ maj
                hh = g; g = f; f = e; e = d &+ t1
                d = c; c = b; b = a; a = t1 &+ t2
            }

            h[0] = h[0] &+ a; h[1] = h[1] &+ b; h[2] = h[2] &+ c; h[3] = h[3] &+ d
            h[4] = h[4] &+ e; h[5] = h[5] &+ f; h[6] = h[6] &+ g; h[7] = h[7] &+ hh
            block += 64
        }

        var out = [UInt8]()
        out.reserveCapacity(32)
        for word in h { out.appendU32BE(word) }
        return out
    }

    @inline(__always)
    private static func rotr(_ x: UInt32, _ n: UInt32) -> UInt32 {
        (x >> n) | (x << (32 - n))
    }
}
