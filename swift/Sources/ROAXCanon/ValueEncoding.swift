import Foundation

/// A value ready to be encoded under a tag.
///
/// The carrier form is deliberately narrow. A `RecordValue` is what a *record*
/// holds; `ValueEncoding` turns one into bytes under the tag the type map
/// selected, and every conversion that can fail does so here rather than
/// silently coercing.
public enum EncodableValue: Equatable {
    case none                      // NULL, EMPTY_ARRAY, EMPTY_OBJECT
    case bool(Bool)
    case text(String)              // STRING, and the source text of INTEGER/DECIMAL
    case bytes([UInt8])
    case blobRef(byteLength: UInt64, digest: [UInt8])
}

public enum ValueEncoding {

    /// The encoded value bytes of specification section 6.1.
    public static func encode(tag: TypeTag, value: EncodableValue) throws -> [UInt8] {
        switch tag {
        case .null:
            guard case .none = value else {
                throw ROAXError.valueKindMismatch(tag: tag, detail: "NULL carries no value")
            }
            return []

        case .bool:
            guard case .bool(let b) = value else {
                throw ROAXError.valueKindMismatch(tag: tag, detail: "expected a boolean")
            }
            return [b ? 0x01 : 0x00]

        case .string:
            guard case .text(let s) = value else {
                throw ROAXError.valueKindMismatch(tag: tag, detail: "expected a string")
            }
            return NFC.utf8(s)

        case .integer:
            guard case .text(let s) = value else {
                throw ROAXError.valueKindMismatch(tag: tag, detail: "expected integer source text")
            }
            return Array(try CanonicalNumber.canonicalizeInteger(s).utf8)

        case .decimal:
            guard case .text(let s) = value else {
                throw ROAXError.valueKindMismatch(tag: tag, detail: "expected decimal source text")
            }
            return Array(try CanonicalNumber.canonicalizeDecimal(s).utf8)

        case .bytes:
            switch value {
            case .bytes(let b):
                return b
            case .text(let s):
                // A record carries base64 text; the ruled FHIR `base64Binary`
                // binding commits the decoded octets, and the pinned RFC 4648
                // section 4 form is an input-admissibility condition checked
                // before the decode (`docs/type-maps.md` section 1.3).
                return try CanonicalBase64.decode(s)
            default:
                throw ROAXError.valueKindMismatch(tag: tag, detail: "expected bytes or base64 text")
            }

        case .emptyArray, .emptyObject:
            guard case .none = value else {
                throw ROAXError.valueKindMismatch(tag: tag, detail: "\(tag.name) carries no value")
            }
            return []

        case .blobRef:
            // Specification section 6.5: registered, and selected by no
            // version-1 profile. The construction is written out so it does not
            // have to be retrofitted after five implementations exist, and it
            // is unreachable because `encode` refuses the tag above the call.
            guard case .blobRef(let length, let digest) = value else {
                throw ROAXError.valueKindMismatch(tag: tag, detail: "expected a blob reference")
            }
            var out = [UInt8]()
            out.appendU64BE(length)
            out.appendU32BE(UInt32(digest.count))
            out.append(contentsOf: digest)
            return out
        }
    }

    /// Encodes a value that came out of a record, under the tag the type map
    /// selected for it.
    ///
    /// This is where the schema-bound tag meets the JSON literal, and it is the
    /// place a syntactic shortcut would be tempting. There is none: a `.number`
    /// carries its source text to whichever numeric canonicalizer the **tag**
    /// names, so `100` under a DECIMAL binding encodes as `100` and `100.0`
    /// stays a different leaf, which is the specification section 4.1 outcome.
    public static func encodeRecordValue(tag: TypeTag, value: JSONValue) throws -> [UInt8] {
        switch (tag, value) {
        case (.null, .null):
            return []
        case (.bool, .bool(let b)):
            return [b ? 0x01 : 0x00]
        case (.string, .string(let s)):
            return NFC.utf8(s)
        case (.integer, .number(let literal)):
            return Array(try CanonicalNumber.canonicalizeInteger(literal).utf8)
        case (.decimal, .number(let literal)):
            return Array(try CanonicalNumber.canonicalizeDecimal(literal).utf8)
        case (.bytes, .string(let base64)):
            return try CanonicalBase64.decode(base64)
        case (.emptyArray, .array(let items)) where items.isEmpty:
            return []
        case (.emptyObject, .object(let members)) where members.isEmpty:
            return []
        case (.blobRef, _):
            throw ROAXError.blobRefNotSelectable
        default:
            throw ROAXError.valueKindMismatch(
                tag: tag,
                detail: "observed \(value.jsonKind.rawValue)"
            )
        }
    }
}
