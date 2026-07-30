import Foundation

/// One `(path, typeTag, value, salt)` tuple and its hash.
public struct Leaf: Equatable {
    public let segments: Path
    public let tag: TypeTag
    public let encodedValue: [UInt8]
    public let salt: [UInt8]
    /// `encodePath(segments)`, kept because the sort in section 9 is over it.
    public let encodedPath: [UInt8]
    public let hash: [UInt8]

    public var displayPath: String { PathEncoding.display(segments) }
}

public enum LeafConstruction {

    /// `DOMAIN = "ROAX-CANON/1/" ‖ hashAlg` (specification sections 7 and 8).
    ///
    /// The qualification is not decoration. Section 7.4 states honestly that it
    /// buys almost nothing cryptographically - an attacker computing a record
    /// under a weak algorithm computes the domain string under it too - and what
    /// it does buy is that the same content under two algorithms cannot collide
    /// on a root by accident.
    public static func domain(hashAlg: String) -> [UInt8] {
        Array(("ROAX-CANON/1/" + hashAlg).utf8)
    }

    /// The one leaf-preimage builder in this implementation.
    ///
    /// ```
    /// leafHash = H( 0x00
    ///             ‖ u32be(len(DOMAIN)) ‖ DOMAIN
    ///             ‖ u32be(len(P))      ‖ P
    ///             ‖ tag
    ///             ‖ u32be(len(salt))   ‖ salt
    ///             ‖ u64be(len(V))      ‖ V )
    /// ```
    ///
    /// dogtag records the cost of a second one - "A second preimage builder is
    /// the drift" - and under ruled decision D4b there is no salt preimage
    /// left, so this is the only one in the design. Nothing else in this
    /// package assembles these bytes.
    public static func preimage(
        encodedPath: [UInt8],
        tag: TypeTag,
        encodedValue: [UInt8],
        salt: [UInt8],
        hashAlg: String
    ) throws -> [UInt8] {
        guard salt.count == 16 else { throw ROAXError.saltLength(salt.count) }
        let domain = domain(hashAlg: hashAlg)

        var out = [UInt8]()
        out.reserveCapacity(1 + 4 + domain.count + 4 + encodedPath.count
                            + 1 + 4 + salt.count + 8 + encodedValue.count)
        out.append(0x00)                                    // RFC 9162 leaf domain byte
        out.appendU32BE(UInt32(domain.count))
        out.append(contentsOf: domain)
        out.appendU32BE(UInt32(encodedPath.count))
        out.append(contentsOf: encodedPath)
        out.append(tag.rawValue)
        out.appendU32BE(UInt32(salt.count))
        out.append(contentsOf: salt)
        out.appendU64BE(UInt64(encodedValue.count))
        out.append(contentsOf: encodedValue)
        return out
    }

    /// `leafHash` of specification section 8.
    public static func leafHash<H: ROAXHash>(
        segments: Path,
        tag: TypeTag,
        encodedValue: [UInt8],
        salt: [UInt8],
        hash: H.Type
    ) throws -> [UInt8] {
        let encodedPath = PathEncoding.encode(segments)
        return H.hash(try preimage(
            encodedPath: encodedPath,
            tag: tag,
            encodedValue: encodedValue,
            salt: salt,
            hashAlg: H.identifier
        ))
    }

    /// Builds a `Leaf`, which is the form the tree consumes.
    public static func makeLeaf<H: ROAXHash>(
        segments: Path,
        tag: TypeTag,
        encodedValue: [UInt8],
        salt: [UInt8],
        hash: H.Type
    ) throws -> Leaf {
        let encodedPath = PathEncoding.encode(segments)
        let h = H.hash(try preimage(
            encodedPath: encodedPath,
            tag: tag,
            encodedValue: encodedValue,
            salt: salt,
            hashAlg: H.identifier
        ))
        return Leaf(
            segments: segments,
            tag: tag,
            encodedValue: encodedValue,
            salt: salt,
            encodedPath: encodedPath,
            hash: h
        )
    }
}

/// Salt generation, specification section 7.
///
/// There is no derivation, no key derivation function, no master secret and no
/// preimage. Each leaf's salt is an independent CSPRNG draw of exactly 16
/// bytes, which is the normative 128-bit entropy floor. That floor is the only
/// thing standing between a withheld low-entropy leaf and the dictionary search
/// section 10.1 describes, so a non-cryptographic generator here would remove
/// the protection while every verification still passed.
public enum SaltSource {

    /// Draws one salt from the system CSPRNG.
    ///
    /// `SystemRandomNumberGenerator` is Swift's cryptographically secure
    /// generator; on Apple platforms it is backed by `arc4random_buf` and on
    /// Linux by `getrandom`.
    public static func draw() -> [UInt8] {
        var generator = SystemRandomNumberGenerator()
        var salt = [UInt8]()
        salt.reserveCapacity(16)
        for _ in 0..<2 {
            var word = generator.next() as UInt64
            for _ in 0..<8 {
                salt.append(UInt8(truncatingIfNeeded: word))
                word >>= 8
            }
        }
        return salt
    }

    /// Draws `count` salts, independently.
    ///
    /// Specification section 7: an implementation MUST draw each salt
    /// independently, MUST NOT reuse a salt across leaves, and MUST NOT reuse a
    /// record's salts when reissuing that record.
    public static func draw(count: Int) -> [[UInt8]] {
        (0..<count).map { _ in draw() }
    }
}
