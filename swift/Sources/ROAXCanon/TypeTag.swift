/// The ROAX type tags of specification section 6.1.
///
/// The tag is one byte in the leaf preimage and it comes from the schema, never
/// from the JSON literal's syntax (specification section 4).
public enum TypeTag: UInt8, Sendable, CaseIterable {
    case null = 0
    case bool = 1
    case string = 2
    case integer = 3
    case decimal = 4
    case bytes = 5
    case emptyArray = 6
    case emptyObject = 7
    /// Registered, and selected by no version-1 profile (specification section 6.5).
    case blobRef = 8

    public var name: String {
        switch self {
        case .null: return "NULL"
        case .bool: return "BOOL"
        case .string: return "STRING"
        case .integer: return "INTEGER"
        case .decimal: return "DECIMAL"
        case .bytes: return "BYTES"
        case .emptyArray: return "EMPTY_ARRAY"
        case .emptyObject: return "EMPTY_OBJECT"
        case .blobRef: return "BLOB_REF"
        }
    }
}

/// The observed JSON kind a type map selects an output by
/// (`docs/type-maps.md` section 3, step 5).
public enum JSONKind: String, Sendable, CaseIterable {
    case string
    case number
    case boolean
    case null
    case object
    case array
}
