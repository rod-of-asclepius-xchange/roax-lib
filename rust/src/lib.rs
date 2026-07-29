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
    commit_full_copy_with_salts, disclose, issue_full_copy, parse_envelope, parse_envelope_value,
    verify_disclosed, verify_full, DisclosedLeaf, Disclosure, FullCopy, ParsedEnvelope, Profile,
    VerificationPolicy,
};
pub use error::{Error, Result};
pub use json::JsonValue;
pub use merkle::{audit_path, fold_inclusion_proof_untrusted, merkle_tree_hash, Hash};
pub use path::{Path, Segment};
pub use type_map::{DfaTypeMap, JsonKind, LookupKeyMode, TypeMapDescriptor, TypeResolver, TypeTag};
pub use value::{BlobRef, LeafValue};

/// Canonicalization version placed in every leaf domain.
pub const CANON_VERSION: &str = "ROAX-CANON/1";

/// Unicode version required by ROAX-CANON/1.
pub const UNICODE_VERSION: &str = "15.1";
