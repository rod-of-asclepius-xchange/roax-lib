/// Leaf ordering, selected per record (specification section 9).
///
/// Two first-class options, exactly as decision B makes ZK-friendly and non-ZK
/// hashes both first-class and selectable per record; the amended decision D5
/// rules ordering the same kind of axis. `path` is the DEFAULT, and it is the
/// same default in all five libraries because section 9 makes that normative: a
/// default differing between implementations would be the silent divergence
/// this project exists to prevent.
///
/// The two differ in exactly one pair of properties and neither dominates.
/// `path` admits absence proofs and leaks gap counts; `hash` leaks nothing about
/// position and forecloses absence proofs permanently for records issued under
/// it. Section 9.4 states the trade at the point of choice.
public enum Ordering: String, Sendable, CaseIterable {
    /// Ascending `encodePath` bytes.
    case path
    /// Ascending `leafHash` bytes.
    case hash

    /// The domain suffix this ordering contributes to `DOMAIN` (sections 8, 9).
    ///
    /// The asymmetry is a stated compatibility rule rather than an accident, and
    /// section 9.5 argues it: `path` contributes the EMPTY string so that a
    /// path-ordered record's domain string is byte-identical to what
    /// `ROAX-CANON/1` specified before this axis existed. Giving `path` a
    /// non-empty suffix would change every leaf hash of every record already
    /// issued under that name. Read the suffix from here; never derive it from
    /// the case name, which is what makes the asymmetry reviewable.
    public var domainSuffix: String {
        switch self {
        case .path: return ""
        case .hash: return "/hash"
        }
    }

    /// Fail closed on an ordering this version does not define.
    ///
    /// This is H3 of specification section 9.5 at its narrowest: an unregistered
    /// ordering is refused rather than approximated by the default.
    public static func parse(_ value: String) throws -> Ordering {
        guard let ordering = Ordering(rawValue: value) else {
            throw ROAXError.orderingNotDefined(value)
        }
        return ordering
    }
}
