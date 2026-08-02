import Foundation

/// The envelope fields that say what a record **is**, committed inside the root
/// as ordinary leaves (specification section 11.2).
///
/// **Each reserved path is a SINGLE `KEY` segment carrying the literal dotted
/// string.** `roax.recordType` is one segment `KEY("roax.recordType")`, not two
/// segments `KEY("roax")` then `KEY("recordType")`. Under section 5 the name
/// could otherwise legally encode three ways, and each produces a different
/// root.
public struct RecordIdentity: Equatable {
    public let recordType: String
    public let schemaVersion: String
    public let recordId: String
    public let issuerId: String
    /// The one conditional leaf: absent means no leaf, not a NULL leaf and not
    /// an empty string.
    public let issuerKeyId: String?
    /// Present under `schemas/envelope-2.0.json`, absent under 1.0.
    ///
    /// The committed corpus predates this leaf, so every corpus vector runs
    /// with it nil and the reserved set is 4 or 5. An envelope carrying a
    /// `typeMap` member raises the always-emitted set to 5 and the tree floor
    /// to 6, which is what `docs/type-maps.md` section 4 describes.
    public let typeMapId: String?
    /// The record's leaf ordering, committed at `roax.ordering` (section 11.2).
    ///
    /// The SECOND conditional reserved leaf. It is emitted only when the
    /// ordering is not the default `path`; a path-ordered record emits NO
    /// ordering leaf and must not emit `"path"`, a NULL or an empty string in
    /// its place, because those are different roots and only one can be right.
    /// The conditionality is the same `ROAX-CANON/1` compatibility rule that
    /// gives `path` an empty domain suffix, and section 11.2 argues it.
    ///
    /// THIS LEAF IS NOT AUTHORITY. It is written from the ordering supplied here
    /// and is never read back to select one: a verifier takes the ordering from
    /// the anchoring registry (section 9.5, H2). Section 11.2 argues why
    /// committing it is not section 7.4's rejected `roax.hashAlg` leaf under a
    /// new name - weak hash algorithms exist so that leaf enabled a downgrade,
    /// whereas both orderings are equally strong, so this one is redundant
    /// rather than dangerous and what it buys is committed issuer intent.
    public let ordering: Ordering

    public init(
        recordType: String,
        schemaVersion: String,
        recordId: String,
        issuerId: String,
        issuerKeyId: String? = nil,
        typeMapId: String? = nil,
        ordering: Ordering = .path
    ) {
        self.recordType = recordType
        self.schemaVersion = schemaVersion
        self.recordId = recordId
        self.issuerId = issuerId
        self.issuerKeyId = issuerKeyId
        self.typeMapId = typeMapId
        self.ordering = ordering
    }

    /// One reserved leaf: its single-segment path, its tag and its value.
    public struct ReservedLeaf {
        public let key: String
        public let value: String
        public var segments: Path { [.key(key)] }
        /// Every reserved leaf is a STRING, so every value is NFC-normalized
        /// and encoded per section 6.1 like any other string.
        public var tag: TypeTag { .string }
    }

    /// The reserved leaves this identity emits, in table order.
    ///
    /// Order is irrelevant to the root - the union is sorted by encoded path in
    /// section 9 - and is kept table-shaped so a reader can check it against
    /// specification section 11.2 line by line.
    public var reservedLeaves: [ReservedLeaf] {
        var out = [
            ReservedLeaf(key: "roax.recordType", value: recordType),
            ReservedLeaf(key: "roax.schemaVersion", value: schemaVersion),
            ReservedLeaf(key: "roax.recordId", value: recordId),
            ReservedLeaf(key: "roax.issuer.id", value: issuerId),
        ]
        if let typeMapId {
            out.append(ReservedLeaf(key: "roax.typeMap.id", value: typeMapId))
        }
        if let issuerKeyId {
            out.append(ReservedLeaf(key: "roax.issuer.keyId", value: issuerKeyId))
        }
        if ordering != .path {
            out.append(ReservedLeaf(key: "roax.ordering", value: ordering.rawValue))
        }
        return out
    }

    /// The five paths specification section 10.2 marks mandatory to disclose,
    /// restricted to the ones this identity actually emits.
    ///
    /// `roax.issuer.keyId` is deliberately absent: requiring its disclosure
    /// would permanently bind an anchored record to the key it was issued
    /// under, with no rotation path, which section 12.2 rules out.
    public var mandatoryDisclosurePaths: [Path] {
        var out: [Path] = [
            [.key("roax.recordType")],
            [.key("roax.schemaVersion")],
            [.key("roax.recordId")],
            [.key("roax.issuer.id")],
        ]
        if typeMapId != nil { out.append([.key("roax.typeMap.id")]) }
        return out
    }
}
