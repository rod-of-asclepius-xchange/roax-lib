//! Independent Rust implementation of ROAX-CANON/1.
//!
//! The crate keeps structured paths, schema-selected type tags, empty containers,
//! and explicit nulls as different types all the way to the leaf preimage.

#![forbid(unsafe_code)]
#![allow(
    clippy::missing_errors_doc,
    clippy::missing_panics_doc,
    clippy::too_many_lines
)]

pub mod commitment;
pub mod envelope;
pub mod error;
pub mod json;
pub mod merkle;
pub mod path;
pub mod type_map;
pub mod value;

pub use commitment::{
    generate_salts, leaf_hash, CanonicalLeaf, Commitment, CommitmentContext, HashAlgorithm, Issuer,
    ReservedLeafSet, Salt, SaltMap, SchemaValidator,
};
pub use envelope::{
    commit_full_copy_with_salts, disclose, issue_full_copy, issue_full_copy_with_salts,
    parse_envelope, parse_envelope_value, reserved_leaf_set_for, verify_disclosed, verify_full,
    DisclosedLeaf, Disclosure, FullCopy, ParsedEnvelope, Profile, VerificationPolicy,
};
pub use error::{Error, Result};
pub use json::JsonValue;
pub use merkle::{audit_path, fold_inclusion_proof_untrusted, merkle_tree_hash, Hash};
pub use path::{Path, Segment};
pub use type_map::{DfaTypeMap, JsonKind, TypeMapDescriptor, TypeResolver, TypeTag};
pub use value::{BlobRef, LeafValue};

/// Canonicalization version placed in every leaf domain.
pub const CANON_VERSION: &str = "ROAX-CANON/1";

/// Unicode version required by ROAX-CANON/1.
pub const UNICODE_VERSION: &str = "15.1";

/// Unicode table version the normalization dependency must carry.
///
/// Every NFC step reachable from a leaf preimage - path segments, string
/// values, the reserved-namespace guard and outer-identity binding - depends on
/// these tables, so the crate refuses to build against any other version.
pub(crate) const REQUIRED_UNICODE_TABLES: (u8, u8, u8) = (15, 1, 0);

const _: () = assert!(
    unicode_normalization::UNICODE_VERSION.0 == REQUIRED_UNICODE_TABLES.0
        && unicode_normalization::UNICODE_VERSION.1 == REQUIRED_UNICODE_TABLES.1
        && unicode_normalization::UNICODE_VERSION.2 == REQUIRED_UNICODE_TABLES.2,
    "unicode-normalization must carry the Unicode 15.1 tables required by ROAX-CANON/1"
);

#[cfg(test)]
mod tests {
    use super::{REQUIRED_UNICODE_TABLES, UNICODE_VERSION};

    #[test]
    fn exported_unicode_version_matches_the_linked_tables() {
        assert_eq!(
            unicode_normalization::UNICODE_VERSION,
            REQUIRED_UNICODE_TABLES
        );
        let (major, minor, _) = REQUIRED_UNICODE_TABLES;
        assert_eq!(UNICODE_VERSION, format!("{major}.{minor}"));
    }
}
