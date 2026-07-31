/// Every way this library refuses an input.
///
/// The cases are the taxonomy this implementation chose; the `reason` strings
/// are this library's own codes. `corpus/README.md` records that four
/// implementations already name the fail-closed condition four different ways,
/// so a corpus `reason` is the reference implementations' spelling rather than
/// a normative code. The runner maps between the two through a declared
/// equivalence table (`ReasonEquivalence`) rather than by loosening a
/// comparison, so a rejection for the wrong reason still fails.
public enum ROAXError: Error, Equatable, CustomStringConvertible {

    // MARK: input boundary (spec section 3.2)

    /// A map carried the same key twice (spec section 3.2).
    case duplicateKey(String)
    /// `NaN`, `Infinity` or `-Infinity` appeared as a numeric literal.
    case nonFiniteNumber(String)
    /// A UTF-16 sequence carried a surrogate with no pair (spec section 6.1).
    case unpairedSurrogate
    /// The JSON text is not well-formed, or carried trailing content.
    case malformedJSON(String)

    // MARK: value encoding (spec section 6.2)

    /// The text does not match the canonical INTEGER grammar.
    case integerGrammar(String)
    /// The text does not match the canonical DECIMAL input grammar.
    case decimalGrammar(String)
    /// The expanded positional form exceeds the 1024-digit bound.
    case digitBoundExceeded(String)
    /// Base64 text outside the RFC 4648 section 4 form pinned by spec section 6.3.
    case base64NotCanonical(String)
    /// A value's Swift type does not match the tag it is being encoded under.
    case valueKindMismatch(tag: TypeTag, detail: String)
    /// Tag 8 BLOB_REF is registered and selected by no version-1 profile
    /// (spec section 6.5).
    case blobRefNotSelectable

    // MARK: paths (spec section 5)

    /// An array index at or beyond 2^32 (spec section 5).
    case indexOutOf32BitRange(UInt64)
    /// A record-supplied first segment inside the `roax.` namespace
    /// (spec section 11.2).
    case reservedNamespace(String)

    // MARK: type map (spec section 4.2)

    /// No transition or no output for the observed kind; decision D7a.
    case typeMapUncoveredPath(path: String, jsonKind: String)
    /// The map itself is unusable: an unparseable pattern, or a tag the
    /// specification forbids a map to declare.
    case typeMapInvalid(String)

    // MARK: records and trees

    /// The record contributed no leaves of its own (spec sections 3.3 and 9.1).
    case emptyRecord
    /// A salt was not 16 bytes (spec section 7).
    case saltLength(Int)
    /// No salt was supplied for a leaf the record produced.
    case saltMissingForLeaf(String)
    /// A disclosure named a path this commitment has no leaf for.
    ///
    /// Deliberately distinct from `saltMissingForLeaf`: that one names a salt
    /// carrier that failed to supply a salt for a leaf the record produced, and
    /// the corpus uses it for exactly that envelope condition. Folding the two
    /// together points a caller with a wrong path list at the salt set, and
    /// breaks the one-to-one between a reason code and a condition that
    /// `ReasonEquivalence` depends on.
    case unknownDisclosurePath(String)
    /// The salt carrier named one encoded path twice.
    case saltsDuplicatePath(String)
    /// Two leaves of one record share a complete encoded path.
    ///
    /// Specification section 9 says paths are unique by construction, so the
    /// order is total and tie-free. Two sibling keys that differ raw but agree
    /// under NFC can break that (`corpus/README.md` ambiguity 6), and a
    /// duplicate makes both the leaf order and the salt pairing ambiguous.
    case duplicateLeafPath(String)
    /// `salts.length` disagreed with the leaf count the verifier derived.
    case saltsLengthNotLeafCount(expected: Int, actual: Int)

    // MARK: envelope (spec sections 10 and 11)

    /// `record` and `disclosure` are not in exactly-one-of.
    case envelopeCopyKind(String)
    /// A disclosed copy carried a `salts` array (spec sections 7.3 and 10.1).
    case disclosedCopyCarriesSalts
    /// An envelope carried a master salt or any other seed field
    /// (spec section 7.3 rule 3).
    case masterSaltInEnvelope
    /// A disclosed leaf named a path but carried no value.
    case disclosedLeafNamedWithoutValue(String)
    /// A recomputed leaf hash, tree size or audit path did not verify.
    case inclusionProofFailed(String)
    /// The recomputed root differs from the envelope's.
    case rootMismatch
    /// An outer field disagrees with the reserved leaf that commits it
    /// (spec section 11.3).
    case outerIdentityMismatch(String)
    /// A disclosed copy omitted a non-redactable path (spec section 10.2).
    case minimumDisclosureFloor(String)
    /// The verifier has no floor table for this `recordType`.
    case profileUnknown(String)
    /// `hashAlg` is not on the verifier's allow-list (spec section 7.4, H3).
    case hashAlgNotAllowed(String)
    /// The declared `hashAlg` and the hash actually being computed disagree.
    ///
    /// `DOMAIN` is `"ROAX-CANON/1/" ‖ hashAlg` (spec sections 7 and 8), so the
    /// declared name and the digest function are two carriers of one fact. A
    /// commitment domained `ROAX-CANON/1/Poseidon-BN254` but hashed with SHA-256
    /// is the issuance spec section 7.4 says MUST NOT be made.
    case hashAlgMismatch(declared: String, computing: String)
    /// `canon` is not `ROAX-CANON/1`.
    case canonUnknown(String)

    /// This library's own reason code for the failure.
    public var reason: String {
        switch self {
        case .duplicateKey: return "duplicate-key"
        case .nonFiniteNumber: return "non-finite-number"
        case .unpairedSurrogate: return "unpaired-surrogate"
        case .malformedJSON: return "malformed-json"
        case .integerGrammar: return "integer-grammar"
        case .decimalGrammar: return "decimal-grammar"
        case .digitBoundExceeded: return "digit-bound-exceeded"
        case .base64NotCanonical: return "base64-not-canonical"
        case .valueKindMismatch: return "value-kind-mismatch"
        case .blobRefNotSelectable: return "blob-ref-not-selectable"
        case .indexOutOf32BitRange: return "index-out-of-32-bit-range"
        case .reservedNamespace: return "reserved-namespace"
        case .typeMapUncoveredPath: return "type-map-fail-closed"
        case .typeMapInvalid: return "type-map-invalid"
        case .emptyRecord: return "empty-record"
        case .saltLength: return "salt-length"
        case .saltMissingForLeaf: return "salt-missing-for-leaf"
        case .unknownDisclosurePath: return "unknown-disclosure-path"
        case .saltsDuplicatePath: return "salts-duplicate-path"
        case .duplicateLeafPath: return "duplicate-leaf-path"
        case .saltsLengthNotLeafCount: return "salts-length-not-leaf-count"
        case .envelopeCopyKind: return "envelope-copy-kind"
        case .disclosedCopyCarriesSalts: return "disclosed-copy-carries-salts"
        case .masterSaltInEnvelope: return "master-salt-in-envelope"
        case .disclosedLeafNamedWithoutValue: return "disclosed-leaf-named-without-value"
        case .inclusionProofFailed: return "inclusion-proof-failed"
        case .rootMismatch: return "root-mismatch"
        case .outerIdentityMismatch: return "outer-identity-mismatch"
        case .minimumDisclosureFloor: return "minimum-disclosure-floor"
        case .profileUnknown: return "profile-unknown"
        case .hashAlgNotAllowed: return "hash-alg-not-allowed"
        case .hashAlgMismatch: return "hash-alg-mismatch"
        case .canonUnknown: return "canon-unknown"
        }
    }

    public var description: String {
        switch self {
        case .duplicateKey(let k): return "duplicate map key \(k.debugDescription)"
        case .nonFiniteNumber(let t): return "non-finite numeric literal \(t.debugDescription)"
        case .unpairedSurrogate: return "unpaired UTF-16 surrogate"
        case .malformedJSON(let d): return "malformed JSON: \(d)"
        case .integerGrammar(let t): return "not a canonical integer: \(t.debugDescription)"
        case .decimalGrammar(let t): return "not a canonical decimal: \(t.debugDescription)"
        case .digitBoundExceeded(let t): return "expanded form exceeds 1024 digits: \(t.debugDescription)"
        case .base64NotCanonical(let d): return "base64 outside RFC 4648 section 4: \(d)"
        case .valueKindMismatch(let tag, let d): return "value does not match tag \(tag.rawValue) \(tag.name): \(d)"
        case .blobRefNotSelectable: return "tag 8 BLOB_REF is selected by no version-1 profile"
        case .indexOutOf32BitRange(let i): return "array index \(i) is not below 2^32"
        case .reservedNamespace(let k): return "record key \(k.debugDescription) is in the reserved roax. namespace"
        case .typeMapUncoveredPath(let p, let k): return "type map has no binding for \(p) at kind \(k)"
        case .typeMapInvalid(let d): return "unusable type map: \(d)"
        case .emptyRecord: return "record contributed zero leaves of its own"
        case .saltLength(let n): return "salt is \(n) bytes, not 16"
        case .saltMissingForLeaf(let p): return "no salt supplied for leaf \(p)"
        case .unknownDisclosurePath(let p): return "this commitment has no leaf at \(p)"
        case .saltsDuplicatePath(let p): return "salts array names \(p) twice"
        case .duplicateLeafPath(let p): return "two leaves share the encoded path \(p)"
        case .saltsLengthNotLeafCount(let e, let a): return "salts.length \(a) != leafCount \(e)"
        case .envelopeCopyKind(let d): return "envelope copy kind: \(d)"
        case .disclosedCopyCarriesSalts: return "a disclosed copy carries a salts array"
        case .masterSaltInEnvelope: return "envelope carries a master salt or seed field"
        case .disclosedLeafNamedWithoutValue(let p): return "disclosed leaf \(p) carries no value"
        case .inclusionProofFailed(let d): return "inclusion proof failed: \(d)"
        case .rootMismatch: return "recomputed root differs from the envelope's"
        case .outerIdentityMismatch(let f): return "outer \(f) disagrees with the reserved leaf committing it"
        case .minimumDisclosureFloor(let p): return "disclosed copy omits non-redactable path \(p)"
        case .profileUnknown(let t): return "no profile registered for recordType \(t.debugDescription)"
        case .hashAlgNotAllowed(let a): return "hashAlg \(a.debugDescription) is not on the allow-list"
        case .hashAlgMismatch(let d, let c):
            return "declared hashAlg \(d.debugDescription) but the hash being computed is \(c.debugDescription)"
        case .canonUnknown(let c): return "canon \(c.debugDescription) is not ROAX-CANON/1"
        }
    }
}
