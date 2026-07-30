use crate::type_map::JsonKind;
use crate::{Path, TypeTag};
use thiserror::Error;

/// Errors returned by the canonicalization and verification APIs.
#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum Error {
    #[error("invalid UTF-8: {0}")]
    InvalidUtf8(String),

    #[error("invalid JSON at byte {offset}: {message}")]
    InvalidJson { offset: usize, message: String },

    #[error("duplicate JSON object key {key:?}")]
    DuplicateKey { key: String },

    #[error("unpaired UTF-16 surrogate")]
    UnpairedSurrogate,

    #[error("trailing data after the JSON value")]
    TrailingJsonData,

    #[error("invalid path: {0}")]
    InvalidPath(String),

    #[error("two input paths normalize to the same encoded path")]
    DuplicateCanonicalPath,

    #[error("record path collides with the reserved roax. namespace")]
    ReservedNamespaceCollision,

    #[error("invalid integer literal")]
    InvalidInteger,

    #[error("invalid decimal literal")]
    InvalidDecimal,

    #[error("expanded number exceeds the 1024-digit ROAX-CANON/1 limit")]
    NumberExpansionLimit,

    #[error("value does not match type tag {tag:?}")]
    TypeMismatch { tag: TypeTag },

    #[error("invalid canonical RFC 4648 base64")]
    InvalidBase64,

    #[error("invalid hexadecimal value")]
    InvalidHex,

    #[error("unsupported ROAX-CANON/1 hash algorithm {0}")]
    UnsupportedAlgorithm(String),

    #[error("BLOB_REF is registered but no version-1 profile selects it")]
    BlobRefNotSelectable,

    #[error("salt must be exactly 16 bytes")]
    InvalidSaltLength,

    #[error("missing salt for path {0}")]
    MissingSalt(Path),

    #[error("duplicate salt path")]
    DuplicateSaltPath,

    #[error("salt set contains a path that is not a leaf")]
    ExtraSaltPath,

    #[error("salt generator failed: {0}")]
    SaltGeneration(String),

    #[error("record did not contribute a leaf")]
    EmptyRecordContribution,

    #[error("type map has no binding for {path} observed as {kind:?}")]
    UnknownTypeBinding { path: Path, kind: JsonKind },

    #[error("invalid type-map artifact: {0}")]
    InvalidTypeMap(String),

    #[error("type-map content ID mismatch")]
    TypeMapIdMismatch,

    #[error("type-map identity does not match the record")]
    TypeMapIdentityMismatch,

    #[error("issuer is outside the selected type-map scope")]
    TypeMapIssuerScope,

    #[error("issuer-scope comparison depends on an unspecified normalization rule")]
    IssuerScopeNormalizationUndecided,

    #[error("unsupported envelope generation")]
    UnsupportedEnvelopeGeneration,

    #[error("invalid commitment context: {0}")]
    InvalidContext(String),

    #[error("full and disclosed payloads are mutually exclusive")]
    EnvelopeModeConflict,

    #[error("envelope has neither a full record nor a disclosure")]
    EnvelopeModeMissing,

    #[error("envelope structure is invalid: {0}")]
    InvalidEnvelope(String),

    #[error("a disclosed copy carries the full-copy salts array")]
    DisclosedCopyCarriesSalts,

    #[error("an envelope carries forbidden master salt or seed material")]
    MasterSaltInEnvelope,

    #[error("a disclosed leaf is named without its required value")]
    DisclosedLeafMissingValue,

    #[error("declared leaf count does not match the derived full-copy count")]
    LeafCountMismatch,

    #[error("declared root does not match the recomputed root")]
    RootMismatch,

    #[error("leaf inclusion proof failed")]
    InvalidInclusionProof,

    #[error("disclosure contains the same path more than once")]
    DuplicateDisclosurePath,

    #[error("disclosure contains the same leaf index more than once")]
    DuplicateDisclosureIndex,

    #[error("disclosure omits a required path")]
    MinimumDisclosureFloor,

    #[error("outer envelope identity does not match committed reserved leaves")]
    OuterIdentityMismatch,

    #[error("profile is not configured")]
    ProfileUnknown,

    #[error("profile validation failed: {0}")]
    ProfileValidation(String),

    #[error("disclosure index is outside the claimed tree")]
    InvalidLeafIndex,

    #[error("disclosure value carrier is invalid")]
    InvalidValueCarrier,
}

impl Error {
    /// Stable, language-neutral reason used by conformance adapters.
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::InvalidUtf8(_) | Self::InvalidJson { .. } | Self::TrailingJsonData => {
                "invalid-json"
            }
            Self::DuplicateKey { .. } => "duplicate-key",
            Self::UnpairedSurrogate => "unpaired-surrogate",
            Self::InvalidPath(_) => "invalid-path",
            Self::DuplicateCanonicalPath => "duplicate-normalized-path",
            Self::ReservedNamespaceCollision => "reserved-namespace-collision",
            Self::InvalidInteger => "invalid-integer",
            Self::InvalidDecimal => "invalid-decimal",
            Self::NumberExpansionLimit => "number-expansion-limit",
            Self::TypeMismatch { .. } => "type-mismatch",
            Self::InvalidBase64 => "invalid-base64",
            Self::InvalidHex => "invalid-hex",
            Self::UnsupportedAlgorithm(_) => "algorithm-unsupported",
            Self::BlobRefNotSelectable => "blob-ref-unbound",
            Self::InvalidSaltLength => "invalid-salt-length",
            Self::MissingSalt(_) => "missing-salt",
            Self::DuplicateSaltPath => "duplicate-salt-path",
            Self::ExtraSaltPath => "extra-salt-path",
            Self::SaltGeneration(_) => "salt-generation",
            Self::EmptyRecordContribution => "empty-record",
            Self::UnknownTypeBinding { .. } => "type-map-fail-closed",
            Self::InvalidTypeMap(_) => "type-map-invalid",
            Self::TypeMapIdMismatch => "type-map-id-mismatch",
            Self::TypeMapIdentityMismatch => "type-map-identity-mismatch",
            Self::TypeMapIssuerScope => "type-map-issuer-scope",
            Self::IssuerScopeNormalizationUndecided => "issuer-scope-normalization-undecided",
            Self::UnsupportedEnvelopeGeneration => "envelope-version-unsupported",
            Self::InvalidContext(_) => "invalid-context",
            Self::EnvelopeModeConflict | Self::EnvelopeModeMissing => "envelope-mode",
            Self::InvalidEnvelope(_) => "invalid-envelope",
            Self::DisclosedCopyCarriesSalts => "disclosed-copy-carries-salts",
            Self::MasterSaltInEnvelope => "master-salt-in-envelope",
            Self::DisclosedLeafMissingValue => "disclosed-leaf-named-without-value",
            Self::LeafCountMismatch => "leaf-count-mismatch",
            Self::RootMismatch => "root-mismatch",
            Self::InvalidInclusionProof | Self::InvalidLeafIndex => "invalid-proof",
            Self::DuplicateDisclosurePath => "duplicate-disclosure-path",
            Self::DuplicateDisclosureIndex => "duplicate-disclosure-index",
            Self::MinimumDisclosureFloor => "minimum-disclosure-floor",
            Self::OuterIdentityMismatch => "outer-identity-mismatch",
            Self::ProfileUnknown => "profile-unknown",
            Self::ProfileValidation(_) => "profile-validation",
            Self::InvalidValueCarrier => "invalid-value-carrier",
        }
    }
}

pub type Result<T> = std::result::Result<T, Error>;
