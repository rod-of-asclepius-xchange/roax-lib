use crate::commitment::{
    commit_record, issue_record, leaf_hash_ordered, Commitment, CommitmentContext, HashAlgorithm,
    Ordering, ReservedLeafSet, Salt, SaltMap, SchemaValidator,
};
use crate::error::{Error, Result};
use crate::json::JsonValue;
use crate::merkle::{audit_path, fold_inclusion_proof_untrusted, Hash};
use crate::path::{Path, Segment};
use crate::type_map::{JsonKind, TypeResolver, TypeTag};
use crate::value::{is_schema_nonnegative_integer, parse_schema_nonnegative_u64, LeafValue};
use crate::CANON_VERSION;
use std::collections::{HashMap, HashSet};
use unicode_normalization::UnicodeNormalization;

/// Profile authority supplied by the verifier, never selected authoritatively
/// from an envelope hint alone.
pub trait Profile: SchemaValidator {
    fn record_type(&self) -> &str;

    /// Validate the exact schema version, type-map descriptor, and issuer scope.
    fn validate_context(&self, context: &CommitmentContext) -> Result<()>;

    fn resolver(&self) -> &dyn TypeResolver;

    /// Profile-specific floor only. Reserved paths are added by the protocol.
    fn minimum_disclosure_paths(&self) -> Vec<Path>;
}

/// Externally authoritative root and algorithm pair.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct VerificationPolicy {
    pub anchored_root: Hash,
    pub anchored_hash_algorithm: HashAlgorithm,
    /// The leaf ordering the anchoring registry records for this root (section 9.5, H2).
    ///
    /// This is the ONLY source of the ordering on the verification path. The envelope's own
    /// `ordering` member is parsed for shape and never read, for the reason section 7.4 gives
    /// about `hashAlg` and section 9.5 repeats: a self-describing document cannot authenticate
    /// its own description.
    ///
    /// Stated as honestly as section 7.4 states H2: the anchoring registry is a requirement
    /// HANDED FORWARD rather than a mechanism this specification designs (section 2.2), so what
    /// this field models today is the verifier's own configured expectation.
    pub anchored_ordering: Ordering,
}

/// A full envelope payload after structural decoding.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FullCopy {
    context: CommitmentContext,
    root: Hash,
    leaf_count: u64,
    record: JsonValue,
    salts: SaltMap,
}

/// One revealed leaf with its own salt and no withheld salt.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DisclosedLeaf {
    path: Path,
    display_path: Option<String>,
    index: u64,
    tag: TypeTag,
    value: LeafValue,
    salt: Salt,
    audit_path: Vec<Hash>,
}

/// A selective disclosure after structural decoding.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Disclosure {
    context: CommitmentContext,
    root: Hash,
    /// An untrusted RFC 9162 proof parameter in a disclosed copy.
    claimed_leaf_count: u64,
    leaves: Vec<DisclosedLeaf>,
}

/// Strictly decoded envelope body.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ParsedEnvelope {
    Full(FullCopy),
    Disclosed(Disclosure),
}

/// Issue a full copy and retain the computed commitment for later disclosure.
pub fn issue_full_copy(
    record: &JsonValue,
    context: &CommitmentContext,
    profile: &dyn Profile,
) -> Result<(FullCopy, Commitment)> {
    if context.record_type != profile.record_type() {
        return Err(Error::ProfileUnknown);
    }
    profile.validate_context(context)?;
    let commitment = issue_record(record, context, profile, profile.resolver())?;
    let copy = FullCopy::from_commitment(record.clone(), &commitment)?;
    Ok((copy, commitment))
}

/// Issue a full copy from caller-supplied, path-addressed salts, and retain its commitment.
///
/// The deterministic twin of [`issue_full_copy`], and the ENVELOPE-level counterpart of
/// [`commit_full_copy_with_salts`], which stops at the commitment. It exists because conformance
/// corpus class 20 pins an issuance: under decision D4b a salt is an independent random draw that
/// nothing re-derives (specification section 7), so a round trip whose expected envelope bytes
/// are committed has to be issued under committed salts. Without it a runner has to assemble the
/// envelope itself, which tests the runner instead of this crate - the precise way an earlier
/// round-trip test elsewhere missed a real defect.
///
/// A caller supplying salts owns the section 7 entropy floor and the rule that no salt is reused
/// across leaves or across issuances. [`issue_full_copy`] remains the entry point for a real
/// issuance.
pub fn issue_full_copy_with_salts(
    record: &JsonValue,
    context: &CommitmentContext,
    profile: &dyn Profile,
    salts: &SaltMap,
) -> Result<(FullCopy, Commitment)> {
    let commitment = commit_full_copy_with_salts(record, context, profile, salts)?;
    let copy = FullCopy::from_commitment(record.clone(), &commitment)?;
    Ok((copy, commitment))
}

/// Rebuild a full-copy commitment from caller-supplied, path-addressed salts.
///
/// This is the deterministic construction entry point for imports and
/// conformance vectors. The profile still validates the record and binds the
/// exact context to its resolver before any leaf is built.
pub fn commit_full_copy_with_salts(
    record: &JsonValue,
    context: &CommitmentContext,
    profile: &dyn Profile,
    salts: &SaltMap,
) -> Result<Commitment> {
    if context.record_type != profile.record_type() {
        return Err(Error::ProfileUnknown);
    }
    profile.validate_context(context)?;
    commit_record(record, context, profile, profile.resolver(), salts)
}

impl FullCopy {
    fn from_commitment(record: JsonValue, commitment: &Commitment) -> Result<Self> {
        let mut salts = SaltMap::new();
        for leaf in commitment.leaves() {
            salts.insert(leaf.path().clone(), leaf.salt())?;
        }
        Ok(Self {
            context: commitment.context().clone(),
            root: commitment.root(),
            leaf_count: u64::try_from(commitment.leaves().len())
                .map_err(|_| Error::InvalidValueCarrier)?,
            record,
            salts,
        })
    }

    #[must_use]
    pub const fn context(&self) -> &CommitmentContext {
        &self.context
    }

    #[must_use]
    pub const fn root(&self) -> Hash {
        self.root
    }

    #[must_use]
    pub const fn leaf_count(&self) -> u64 {
        self.leaf_count
    }

    #[must_use]
    pub const fn record(&self) -> &JsonValue {
        &self.record
    }

    #[must_use]
    pub const fn salts(&self) -> &SaltMap {
        &self.salts
    }

    #[must_use]
    pub fn to_json_value(&self) -> JsonValue {
        let mut fields = common_envelope_fields(&self.context, self.root, self.leaf_count);
        fields.push(("record".into(), self.record.clone()));
        let mut salts: Vec<_> = self.salts.iter().collect();
        salts.sort_by_cached_key(|(path, _)| path.encode().unwrap_or_default());
        fields.push((
            "salts".into(),
            JsonValue::Array(
                salts
                    .into_iter()
                    .map(|(path, salt)| {
                        JsonValue::Object(vec![
                            ("segments".into(), path_json(path)),
                            ("salt".into(), JsonValue::String(salt.to_hex())),
                        ])
                    })
                    .collect(),
            ),
        ));
        JsonValue::Object(fields)
    }

    #[must_use]
    pub fn to_json_string(&self) -> String {
        self.to_json_value().to_json_string()
    }
}

impl Disclosure {
    #[must_use]
    pub const fn context(&self) -> &CommitmentContext {
        &self.context
    }

    #[must_use]
    pub const fn root(&self) -> Hash {
        self.root
    }

    #[must_use]
    pub const fn claimed_leaf_count(&self) -> u64 {
        self.claimed_leaf_count
    }

    #[must_use]
    pub fn leaves(&self) -> &[DisclosedLeaf] {
        &self.leaves
    }

    #[must_use]
    pub fn to_json_value(&self) -> JsonValue {
        let mut fields = common_envelope_fields(&self.context, self.root, self.claimed_leaf_count);
        fields.push((
            "disclosure".into(),
            JsonValue::Object(vec![
                ("mode".into(), JsonValue::String("selective".into())),
                (
                    "leaves".into(),
                    JsonValue::Array(self.leaves.iter().map(disclosed_leaf_json).collect()),
                ),
            ]),
        ));
        JsonValue::Object(fields)
    }

    #[must_use]
    pub fn to_json_string(&self) -> String {
        self.to_json_value().to_json_string()
    }
}

impl DisclosedLeaf {
    #[must_use]
    pub const fn path(&self) -> &Path {
        &self.path
    }

    /// Return the sender-supplied `displayPath` hint, when the envelope carried one.
    ///
    /// It is never compared against the authoritative `segments` and it survives
    /// verification unchanged, so it is not evidence of anything: a sender may label a
    /// genuinely included leaf with any string. Use [`Self::path`] for every decision
    /// and for any path shown to a person.
    #[must_use]
    pub fn display_path(&self) -> Option<&str> {
        self.display_path.as_deref()
    }

    #[must_use]
    pub const fn index(&self) -> u64 {
        self.index
    }

    #[must_use]
    pub const fn tag(&self) -> TypeTag {
        self.tag
    }

    #[must_use]
    pub const fn value(&self) -> &LeafValue {
        &self.value
    }

    #[must_use]
    pub const fn salt(&self) -> Salt {
        self.salt
    }

    #[must_use]
    pub fn audit_path(&self) -> &[Hash] {
        &self.audit_path
    }
}

/// Decode an envelope without passing record numbers through floating point.
///
/// The schema version is an explicit input because envelope 1.0 and 2.0 do not
/// carry an in-band discriminator and have different reserved leaf sets.
pub fn parse_envelope(input: &[u8], reserved_leaf_set: ReservedLeafSet) -> Result<ParsedEnvelope> {
    let root = JsonValue::from_slice(input)?;
    parse_envelope_value(&root, reserved_leaf_set)
}

/// Select the reserved-leaf generation an envelope belongs to, from what it COMMITS.
///
/// [`parse_envelope`] takes the generation as an INPUT, which is right: it is the verifier's own
/// decision and never the document's. But a verifier that accepts BOTH generations still has to
/// choose one per envelope, and the obvious choice - "2.0 when the outer `typeMap` member is
/// there" - hands that choice to the party the binding constrains. A holder deletes the member,
/// withholds the leaf, and a verifier reading only the member drops to the 1.0 generation where
/// `roax.typeMap.id` is not in the floor and nothing asks for it, while every remaining inclusion
/// proof stays genuine. **A check whose execution is controlled by the party it constrains is not
/// a check** (specification section 11.3; `roax.typeMap.id` is mandatory to disclose by
/// arithmetic under section 11.2, because it selects and authenticates the exact map).
///
/// So this reads the COMMITTED evidence as well: any disclosed leaf, or any `salts` entry,
/// addressing the single segment `roax.typeMap.id` selects the 2.0 generation regardless of what
/// the outer member says. A copy that then presents no member fails with
/// [`Error::TypeMapNotNamed`], and a copy presenting a different one fails the binding with
/// [`Error::OuterIdentityMismatch`].
///
/// The one case no envelope can evidence is a copy that drops BOTH. It is byte-indistinguishable
/// from a legitimate 1.0 copy issued before the binding existed, because the only signal that a
/// further reserved leaf was committed is `leafCount`, which specification section 11.1 measured
/// is NOT authenticated in a disclosed copy. A verifier that requires the binding regardless
/// passes [`ReservedLeafSet::EnvelopeV2`] here instead of calling this.
#[must_use]
pub fn reserved_leaf_set_for(value: &JsonValue) -> ReservedLeafSet {
    let JsonValue::Object(members) = value else {
        return ReservedLeafSet::EnvelopeV1;
    };
    let member = |name: &str| {
        members
            .iter()
            .find(|(key, _)| key == name)
            .map(|(_, entry)| entry)
    };
    if member("typeMap").is_some() {
        return ReservedLeafSet::EnvelopeV2;
    }
    let commits_type_map_id = |entries: Option<&JsonValue>| {
        let Some(JsonValue::Array(rows)) = entries else {
            return false;
        };
        rows.iter().any(|row| {
            let JsonValue::Object(fields) = row else {
                return false;
            };
            fields
                .iter()
                .find(|(key, _)| key == "segments")
                .is_some_and(|(_, segments)| is_type_map_id_path(segments))
        })
    };
    let disclosure_leaves = member("disclosure").and_then(|disclosure| {
        let JsonValue::Object(fields) = disclosure else {
            return None;
        };
        fields
            .iter()
            .find(|(key, _)| key == "leaves")
            .map(|(_, leaves)| leaves)
    });
    if commits_type_map_id(disclosure_leaves) || commits_type_map_id(member("salts")) {
        return ReservedLeafSet::EnvelopeV2;
    }
    ReservedLeafSet::EnvelopeV1
}

fn is_type_map_id_path(segments: &JsonValue) -> bool {
    let JsonValue::Array(items) = segments else {
        return false;
    };
    let [JsonValue::Object(fields)] = items.as_slice() else {
        return false;
    };
    fields.iter().any(|(key, entry)| {
        key == "key" && matches!(entry, JsonValue::String(name) if name == "roax.typeMap.id")
    })
}

/// Decode an already strict-parsed envelope value.
pub fn parse_envelope_value(
    value: &JsonValue,
    reserved_leaf_set: ReservedLeafSet,
) -> Result<ParsedEnvelope> {
    value.validate()?;
    let envelope_object = object(value, "envelope")?;
    reject_forbidden_seed_fields(envelope_object)?;
    reject_unknown_keys(
        envelope_object,
        &[
            "canon",
            "hashAlg",
            // ACCEPTED FOR SHAPE AND DELIBERATELY NOT READ. Both envelope schemas permit this
            // member, so rejecting it would refuse a conforming envelope; using it would violate
            // specification section 9.5 H2, which requires a verifier to take the ordering from
            // the anchoring registry and never from the envelope.
            // `VerificationPolicy::anchored_ordering` is where it comes from.
            "ordering",
            "recordType",
            "schemaVersion",
            "typeMap",
            "recordId",
            "root",
            "leafCount",
            "issuer",
            "anchor",
            "record",
            "disclosure",
            "salts",
        ],
        "envelope",
    )?;

    if string_field(envelope_object, "canon")? != CANON_VERSION {
        return Err(Error::InvalidEnvelope(
            "unsupported canonicalization version".into(),
        ));
    }
    let hash_algorithm = HashAlgorithm::parse(string_field(envelope_object, "hashAlg")?)?;
    let record_type = string_field(envelope_object, "recordType")?.to_owned();
    let schema_version = string_field(envelope_object, "schemaVersion")?.to_owned();
    let record_id = string_field(envelope_object, "recordId")?.to_owned();
    let root_hash = hash_field(envelope_object, "root")?;
    let leaf_count = u64_field(envelope_object, "leafCount")?;
    let issuer = parse_issuer(required_field(envelope_object, "issuer")?)?;
    if let Some(anchor) = optional_field(envelope_object, "anchor") {
        validate_anchor(anchor)?;
    }

    let type_map_hint = optional_field(envelope_object, "typeMap")
        .map(parse_type_map_descriptor)
        .transpose()?;
    let type_map = match reserved_leaf_set {
        ReservedLeafSet::EnvelopeV1 => None,
        // `TypeMapNotNamed` rather than a bare `InvalidEnvelope`, so a caller can tell "this
        // verifier requires the binding and the copy has none" apart from "the two sides name
        // different artifacts". `reserved_leaf_set_for` reaches this generation only for a copy
        // that COMMITS `roax.typeMap.id`, so under that selector this code means the presenter
        // dropped the outer member while the root still commits the identifier.
        ReservedLeafSet::EnvelopeV2 => Some(type_map_hint.ok_or(Error::TypeMapNotNamed)?),
    };
    let context = CommitmentContext {
        hash_algorithm,
        reserved_leaf_set,
        record_type,
        schema_version,
        type_map,
        record_id,
        issuer,
        // NOT taken from the envelope (section 9.5, H2). Parsing cannot know the authoritative
        // ordering, so the context is built under the default and the verification entry points
        // replace it with the registry's before anything is rebuilt.
        ordering: Ordering::default(),
    };
    context.validate()?;
    validate_carrier_floor(&context, leaf_count)?;

    let record = optional_field(envelope_object, "record");
    let disclosure = optional_field(envelope_object, "disclosure");
    match (record, disclosure) {
        (Some(_), Some(_)) => Err(Error::EnvelopeModeConflict),
        (None, None) => Err(Error::EnvelopeModeMissing),
        (Some(record), None) => {
            if !matches!(record, JsonValue::Object(_)) {
                return Err(Error::InvalidEnvelope("record must be an object".into()));
            }
            let salts = optional_field(envelope_object, "salts")
                .ok_or_else(|| Error::InvalidEnvelope("full copy requires salts".into()))?;
            let salt_values = array(salts, "salts")?;
            if salt_values.len() < usize::try_from(carrier_floor(&context)).unwrap_or(usize::MAX) {
                return Err(Error::InvalidEnvelope(
                    "salts is below the envelope-version floor".into(),
                ));
            }
            Ok(ParsedEnvelope::Full(FullCopy {
                context,
                root: root_hash,
                leaf_count,
                record: record.clone(),
                salts: parse_salt_map(salts)?,
            }))
        }
        (None, Some(disclosure)) => {
            if optional_field(envelope_object, "salts").is_some() {
                return Err(Error::DisclosedCopyCarriesSalts);
            }
            Ok(ParsedEnvelope::Disclosed(parse_disclosure(
                disclosure, context, root_hash, leaf_count,
            )?))
        }
    }
}

/// Verify a full copy by rebuilding its complete leaf set and tree.
pub fn verify_full(
    copy: &FullCopy,
    profile: &dyn Profile,
    policy: VerificationPolicy,
) -> Result<Commitment> {
    check_policy(&copy.context, copy.root, profile, policy)?;
    profile.validate_context(&copy.context)?;
    // The ordering comes from the REGISTRY and never from the envelope (section 9.5, H2). A full
    // copy is the case that genuinely needs it structurally: this rebuilds the whole tree, so
    // the ordering decides both leaf placement and every leaf preimage through DOMAIN.
    let rebuild_context = CommitmentContext {
        ordering: policy.anchored_ordering,
        ..copy.context.clone()
    };
    let commitment = commit_record(
        &copy.record,
        &rebuild_context,
        profile,
        profile.resolver(),
        &copy.salts,
    )?;
    if u64::try_from(commitment.leaves().len()).map_err(|_| Error::InvalidValueCarrier)?
        != copy.leaf_count
    {
        return Err(Error::LeafCountMismatch);
    }
    if commitment.root() != copy.root {
        return Err(Error::RootMismatch);
    }
    Ok(commitment)
}

/// Produce a selective disclosure from a complete commitment.
///
/// The protocol and profile floors are included even when the caller did not
/// request them. Only the disclosed leaves' own salts enter the result.
pub fn disclose(
    commitment: &Commitment,
    profile: &dyn Profile,
    requested_paths: &[Path],
) -> Result<Disclosure> {
    let context = commitment.context();
    context.validate()?;
    if context.record_type != profile.record_type() {
        return Err(Error::ProfileUnknown);
    }
    profile.validate_context(context)?;

    let mut selected = HashSet::new();
    for path in requested_paths {
        selected.insert(path.encode()?);
    }
    for path in disclosure_floor(context.reserved_leaf_set, profile)? {
        selected.insert(path.encode()?);
    }

    let hashes: Vec<Hash> = commitment
        .leaves()
        .iter()
        .map(crate::CanonicalLeaf::hash)
        .collect();
    let mut leaves = Vec::with_capacity(selected.len());
    for encoded_path in selected {
        let (index, leaf) = commitment
            .leaves()
            .iter()
            .enumerate()
            .find(|(_, leaf)| leaf.encoded_path() == encoded_path)
            .ok_or_else(|| Error::InvalidPath("requested path is not a leaf".into()))?;
        leaves.push(DisclosedLeaf {
            path: leaf.path().normalized(),
            display_path: Some(leaf.path().display()),
            index: u64::try_from(index).map_err(|_| Error::InvalidLeafIndex)?,
            tag: leaf.tag(),
            value: leaf.value().clone(),
            salt: leaf.salt(),
            audit_path: audit_path(&hashes, index)?,
        });
    }
    leaves.sort_by_key(|leaf| leaf.index);
    Ok(Disclosure {
        context: context.clone(),
        root: commitment.root(),
        claimed_leaf_count: u64::try_from(commitment.leaves().len())
            .map_err(|_| Error::InvalidLeafIndex)?,
        leaves,
    })
}

/// Verify a selective disclosure without trusting caller-supplied leaf hashes.
pub fn verify_disclosed(
    disclosure: &Disclosure,
    profile: &dyn Profile,
    policy: VerificationPolicy,
) -> Result<()> {
    check_policy(&disclosure.context, disclosure.root, profile, policy)?;
    if disclosure.claimed_leaf_count == 0 {
        return Err(Error::InvalidLeafIndex);
    }

    let mut disclosed_by_path = HashMap::new();
    let mut disclosed_indices = HashSet::new();
    for leaf in &disclosure.leaves {
        if leaf.tag == TypeTag::BlobRef {
            return Err(Error::BlobRefNotSelectable);
        }
        leaf.value.validate_disclosure_canonicality()?;
        validate_disclosed_namespace(leaf, disclosure.context.reserved_leaf_set)?;
        let encoded_path = leaf.path.encode()?;
        if disclosed_by_path.insert(encoded_path, leaf).is_some() {
            return Err(Error::DuplicateDisclosurePath);
        }
        if !disclosed_indices.insert(leaf.index) {
            return Err(Error::DuplicateDisclosureIndex);
        }
        if leaf.index >= disclosure.claimed_leaf_count {
            return Err(Error::InvalidLeafIndex);
        }
        // Section 10 step 2, and the ONE place a disclosed copy needs the ordering at all.
        //
        // It is needed for the LEAF PREIMAGE, exactly as `hashAlg` already is, and for nothing
        // structural: the index and audit path are carried and the tree is never rebuilt
        // (section 9.6). It comes from the policy rather than the envelope, per section 9.5 H2.
        let recomputed = leaf_hash_ordered(
            &leaf.path,
            leaf.tag,
            &leaf.value,
            leaf.salt,
            disclosure.context.hash_algorithm,
            policy.anchored_ordering,
        )?;
        if !fold_inclusion_proof_untrusted(
            &recomputed,
            leaf.index,
            disclosure.claimed_leaf_count,
            &leaf.audit_path,
            &disclosure.root,
        ) {
            return Err(Error::InvalidInclusionProof);
        }
        validate_fixed_reserved_leaf(leaf, disclosure.context.reserved_leaf_set)?;
    }

    // Establish committed identity before using it to select a type map or floor.
    bind_outer_identity(disclosure, &disclosed_by_path)?;
    profile.validate_context(&disclosure.context)?;

    for leaf in &disclosure.leaves {
        if reserved_leaf_name(&leaf.path, disclosure.context.reserved_leaf_set).is_none() {
            let kind = observed_kind_from_tag(leaf.tag)?;
            let expected = profile.resolver().resolve(&leaf.path, kind)?;
            if expected != leaf.tag {
                return Err(Error::TypeMismatch { tag: leaf.tag });
            }
        }
    }

    for path in disclosure_floor(disclosure.context.reserved_leaf_set, profile)? {
        if !disclosed_by_path.contains_key(&path.encode()?) {
            return Err(Error::MinimumDisclosureFloor);
        }
    }
    Ok(())
}

fn check_policy(
    context: &CommitmentContext,
    root: Hash,
    profile: &dyn Profile,
    policy: VerificationPolicy,
) -> Result<()> {
    context.validate()?;
    if context.record_type != profile.record_type() {
        return Err(Error::ProfileUnknown);
    }
    if context.hash_algorithm != policy.anchored_hash_algorithm {
        return Err(Error::UnsupportedAlgorithm(
            context.hash_algorithm.name().into(),
        ));
    }
    if root != policy.anchored_root {
        return Err(Error::RootMismatch);
    }
    Ok(())
}

fn bind_outer_identity(
    disclosure: &Disclosure,
    disclosed_by_path: &HashMap<Vec<u8>, &DisclosedLeaf>,
) -> Result<()> {
    let mut expected = vec![
        ("roax.recordType", disclosure.context.record_type.as_str()),
        (
            "roax.schemaVersion",
            disclosure.context.schema_version.as_str(),
        ),
        ("roax.recordId", disclosure.context.record_id.as_str()),
        ("roax.issuer.id", disclosure.context.issuer.id.as_str()),
    ];
    if disclosure.context.reserved_leaf_set == ReservedLeafSet::EnvelopeV2 {
        expected.push((
            "roax.typeMap.id",
            disclosure
                .context
                .type_map
                .as_ref()
                .ok_or(Error::OuterIdentityMismatch)?
                .id
                .as_str(),
        ));
    }

    for (key, outer_value) in expected {
        let path = reserved_path(key);
        let leaf = disclosed_by_path
            .get(&path.encode()?)
            .ok_or(Error::OuterIdentityMismatch)?;
        let LeafValue::String(committed_value) = &leaf.value else {
            return Err(Error::OuterIdentityMismatch);
        };
        if committed_value.nfc().ne(outer_value.nfc()) {
            return Err(Error::OuterIdentityMismatch);
        }
    }
    Ok(())
}

fn validate_fixed_reserved_leaf(
    leaf: &DisclosedLeaf,
    reserved_leaf_set: ReservedLeafSet,
) -> Result<()> {
    let Some(_) = reserved_leaf_name(&leaf.path, reserved_leaf_set) else {
        return Ok(());
    };
    if leaf.tag != TypeTag::String || !matches!(leaf.value, LeafValue::String(_)) {
        return Err(Error::TypeMismatch { tag: leaf.tag });
    }
    Ok(())
}

fn validate_disclosed_namespace(
    leaf: &DisclosedLeaf,
    reserved_leaf_set: ReservedLeafSet,
) -> Result<()> {
    let Some(Segment::Key(first)) = leaf.path.segments().first() else {
        return Ok(());
    };
    let normalized: String = first.nfc().collect();
    if normalized.starts_with("roax.")
        && reserved_leaf_name(&leaf.path, reserved_leaf_set).is_none()
    {
        return Err(Error::ReservedNamespaceCollision);
    }
    Ok(())
}

fn observed_kind_from_tag(tag: TypeTag) -> Result<JsonKind> {
    match tag {
        TypeTag::Null => Ok(JsonKind::Null),
        TypeTag::Bool => Ok(JsonKind::Boolean),
        TypeTag::String | TypeTag::Bytes => Ok(JsonKind::String),
        TypeTag::Integer | TypeTag::Decimal => Ok(JsonKind::Number),
        TypeTag::EmptyArray => Ok(JsonKind::Array),
        TypeTag::EmptyObject => Ok(JsonKind::Object),
        TypeTag::BlobRef => Err(Error::BlobRefNotSelectable),
    }
}

fn disclosure_floor(reserved: ReservedLeafSet, profile: &dyn Profile) -> Result<Vec<Path>> {
    let mut paths = vec![
        reserved_path("roax.recordType"),
        reserved_path("roax.schemaVersion"),
        reserved_path("roax.recordId"),
        reserved_path("roax.issuer.id"),
    ];
    if reserved == ReservedLeafSet::EnvelopeV2 {
        paths.push(reserved_path("roax.typeMap.id"));
    }
    for path in profile.minimum_disclosure_paths() {
        if let Some(Segment::Key(first)) = path.segments().first() {
            let normalized: String = first.nfc().collect();
            if normalized.starts_with("roax.") {
                return Err(Error::ReservedNamespaceCollision);
            }
        }
        paths.push(path);
    }
    Ok(paths)
}

fn reserved_path(key: &str) -> Path {
    Path::from_segments(vec![Segment::Key(key.into())])
}

fn single_key(path: &Path) -> Option<&str> {
    match path.segments() {
        [Segment::Key(key)] => Some(key),
        _ => None,
    }
}

fn reserved_leaf_name(path: &Path, reserved_leaf_set: ReservedLeafSet) -> Option<&str> {
    let key = single_key(path)?;
    let allowed = matches!(
        key,
        "roax.recordType"
            | "roax.schemaVersion"
            | "roax.recordId"
            | "roax.issuer.id"
            | "roax.issuer.keyId"
    ) || (reserved_leaf_set == ReservedLeafSet::EnvelopeV2
        && key == "roax.typeMap.id");
    allowed.then_some(key)
}

fn parse_disclosure(
    value: &JsonValue,
    context: CommitmentContext,
    root: Hash,
    leaf_count: u64,
) -> Result<Disclosure> {
    let object = object(value, "disclosure")?;
    reject_unknown_keys(object, &["mode", "leaves"], "disclosure")?;
    if string_field(object, "mode")? != "selective" {
        return Err(Error::InvalidEnvelope(
            "disclosure mode must be selective".into(),
        ));
    }
    let JsonValue::Array(values) = required_field(object, "leaves")? else {
        return Err(Error::InvalidEnvelope(
            "disclosure leaves must be an array".into(),
        ));
    };
    if values.is_empty() {
        return Err(Error::InvalidEnvelope(
            "disclosure must reveal at least one leaf".into(),
        ));
    }
    let leaves = values
        .iter()
        .map(parse_disclosed_leaf)
        .collect::<Result<Vec<_>>>()?;
    Ok(Disclosure {
        context,
        root,
        claimed_leaf_count: leaf_count,
        leaves,
    })
}

fn parse_disclosed_leaf(value: &JsonValue) -> Result<DisclosedLeaf> {
    let object = object(value, "disclosed leaf")?;
    reject_unknown_keys(
        object,
        &[
            "segments",
            "displayPath",
            "index",
            "tag",
            "value",
            "salt",
            "auditPath",
        ],
        "disclosed leaf",
    )?;
    let path = parse_path(required_field(object, "segments")?)?;
    let index = u64_field(object, "index")?;
    let tag_number =
        u8::try_from(usize_field(object, "tag")?).map_err(|_| Error::InvalidValueCarrier)?;
    let tag = TypeTag::try_from(tag_number).map_err(|_| Error::InvalidValueCarrier)?;
    let carrier = optional_field(object, "value");
    if !matches!(
        tag,
        TypeTag::Null | TypeTag::EmptyArray | TypeTag::EmptyObject
    ) && carrier.is_none()
    {
        return Err(Error::DisclosedLeafMissingValue);
    }
    if matches!(
        tag,
        TypeTag::Null | TypeTag::EmptyArray | TypeTag::EmptyObject
    ) && carrier.is_some()
    {
        return Err(Error::InvalidValueCarrier);
    }
    let leaf_value = LeafValue::from_disclosure_carrier(tag, carrier)?;
    let salt = Salt::from_hex(string_field(object, "salt")?)?;
    let display_path = optional_field(object, "displayPath")
        .map(|value| {
            let JsonValue::String(value) = value else {
                return Err(Error::InvalidEnvelope(
                    "displayPath must be a string".into(),
                ));
            };
            Ok(value.clone())
        })
        .transpose()?;
    let JsonValue::Array(proof_values) = required_field(object, "auditPath")? else {
        return Err(Error::InvalidEnvelope("auditPath must be an array".into()));
    };
    let audit_path = proof_values
        .iter()
        .map(parse_hash_value)
        .collect::<Result<Vec<_>>>()?;
    Ok(DisclosedLeaf {
        path,
        display_path,
        index,
        tag,
        value: leaf_value,
        salt,
        audit_path,
    })
}

fn parse_salt_map(value: &JsonValue) -> Result<SaltMap> {
    let JsonValue::Array(entries) = value else {
        return Err(Error::InvalidEnvelope("salts must be an array".into()));
    };
    let mut salts = SaltMap::new();
    for entry in entries {
        let object = object(entry, "salt entry")?;
        reject_unknown_keys(object, &["segments", "salt"], "salt entry")?;
        salts.insert(
            parse_path(required_field(object, "segments")?)?,
            Salt::from_hex(string_field(object, "salt")?)?,
        )?;
    }
    Ok(salts)
}

fn parse_path(value: &JsonValue) -> Result<Path> {
    let JsonValue::Array(values) = value else {
        return Err(Error::InvalidPath("segments must be an array".into()));
    };
    let mut segments = Vec::with_capacity(values.len());
    for value in values {
        let object = object(value, "path segment")?;
        match object {
            [(key, JsonValue::String(value))] if key == "key" => {
                segments.push(Segment::Key(value.clone()));
            }
            [(key, value)] if key == "index" => {
                let index = parse_usize_value(value)?;
                segments.push(Segment::Index(u32::try_from(index).map_err(|_| {
                    Error::InvalidPath("array index is outside the 32-bit range".into())
                })?));
            }
            _ => {
                return Err(Error::InvalidPath(
                    "a path segment must contain exactly one key or index".into(),
                ))
            }
        }
    }
    Ok(Path::from_segments(segments))
}

fn parse_type_map_descriptor(value: &JsonValue) -> Result<crate::TypeMapDescriptor> {
    let object = object(value, "typeMap")?;
    reject_unknown_keys(object, &["id", "version"], "typeMap")?;
    let id = string_field(object, "id")?;
    if !id.starts_with("sha256:")
        || id.len() != 71
        || !id[7..]
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(Error::InvalidEnvelope("invalid typeMap.id".into()));
    }
    let version = string_field(object, "version")?;
    if !is_three_part_version(version) {
        return Err(Error::InvalidEnvelope("invalid typeMap.version".into()));
    }
    Ok(crate::TypeMapDescriptor {
        id: id.to_owned(),
        version: version.to_owned(),
    })
}

fn parse_issuer(value: &JsonValue) -> Result<crate::Issuer> {
    let object = object(value, "issuer")?;
    reject_unknown_keys(object, &["id", "keyId"], "issuer")?;
    let id = string_field(object, "id")?;
    if uriparse::URI::try_from(id).is_err() {
        return Err(Error::InvalidEnvelope(
            "issuer.id must be an absolute URI".into(),
        ));
    }
    Ok(crate::Issuer {
        id: id.to_owned(),
        key_id: optional_field(object, "keyId")
            .map(|value| match value {
                JsonValue::String(value) => Ok(value.clone()),
                _ => Err(Error::InvalidEnvelope(
                    "issuer.keyId must be a string".into(),
                )),
            })
            .transpose()?,
    })
}

fn validate_anchor(value: &JsonValue) -> Result<()> {
    let object = object(value, "anchor")?;
    reject_unknown_keys(
        object,
        &["chainId", "registry", "txHash", "anchoredAt"],
        "anchor",
    )?;
    let JsonValue::Number(chain_id) = required_field(object, "chainId")? else {
        return Err(Error::InvalidEnvelope(
            "anchor.chainId must be a non-negative integer".into(),
        ));
    };
    if !is_schema_nonnegative_integer(chain_id) {
        return Err(Error::InvalidEnvelope(
            "anchor.chainId must be a non-negative integer".into(),
        ));
    }
    let registry = string_field(object, "registry")?;
    if !is_prefixed_hex(registry, 40, true) {
        return Err(Error::InvalidEnvelope("invalid anchor.registry".into()));
    }
    if let Some(value) = optional_field(object, "txHash") {
        let JsonValue::String(value) = value else {
            return Err(Error::InvalidEnvelope(
                "anchor.txHash must be a string".into(),
            ));
        };
        if !is_prefixed_hex(value, 64, true) {
            return Err(Error::InvalidEnvelope("invalid anchor.txHash".into()));
        }
    }
    if let Some(value) = optional_field(object, "anchoredAt") {
        let JsonValue::String(value) = value else {
            return Err(Error::InvalidEnvelope(
                "anchor.anchoredAt must be a string".into(),
            ));
        };
        value
            .parse::<jiff::Timestamp>()
            .map_err(|_| Error::InvalidEnvelope("invalid anchor.anchoredAt".into()))?;
    }
    Ok(())
}

fn validate_carrier_floor(context: &CommitmentContext, leaf_count: u64) -> Result<()> {
    if leaf_count < carrier_floor(context) {
        Err(Error::InvalidEnvelope(
            "leafCount is below the envelope-version floor".into(),
        ))
    } else {
        Ok(())
    }
}

fn carrier_floor(context: &CommitmentContext) -> u64 {
    match context.reserved_leaf_set {
        ReservedLeafSet::EnvelopeV1 if context.issuer.key_id.is_some() => 6,
        ReservedLeafSet::EnvelopeV1 => 5,
        ReservedLeafSet::EnvelopeV2 => 6,
    }
}

fn is_prefixed_hex(value: &str, digits: usize, mixed_case: bool) -> bool {
    value.len() == digits + 2
        && value.starts_with("0x")
        && value[2..].bytes().all(|byte| {
            byte.is_ascii_digit()
                || (b'a'..=b'f').contains(&byte)
                || (mixed_case && (b'A'..=b'F').contains(&byte))
        })
}

fn is_three_part_version(value: &str) -> bool {
    let mut parts = value.split('.');
    let valid = (0..3).all(|_| {
        parts
            .next()
            .is_some_and(|part| !part.is_empty() && part.bytes().all(|byte| byte.is_ascii_digit()))
    });
    valid && parts.next().is_none()
}

fn reject_forbidden_seed_fields(object: &[(String, JsonValue)]) -> Result<()> {
    if object.iter().any(|(key, _)| {
        matches!(
            key.as_str(),
            "masterSalt" | "masterSaltHex" | "saltSeed" | "seed" | "derivationKey"
        )
    }) {
        Err(Error::MasterSaltInEnvelope)
    } else {
        Ok(())
    }
}

fn reject_unknown_keys(
    object: &[(String, JsonValue)],
    allowed: &[&str],
    location: &str,
) -> Result<()> {
    if let Some((key, _)) = object
        .iter()
        .find(|(key, _)| !allowed.contains(&key.as_str()))
    {
        Err(Error::InvalidEnvelope(format!(
            "unknown {location} member {key}"
        )))
    } else {
        Ok(())
    }
}

fn object<'a>(value: &'a JsonValue, location: &str) -> Result<&'a [(String, JsonValue)]> {
    value
        .as_object()
        .ok_or_else(|| Error::InvalidEnvelope(format!("{location} must be an object")))
}

fn array<'a>(value: &'a JsonValue, location: &str) -> Result<&'a [JsonValue]> {
    let JsonValue::Array(values) = value else {
        return Err(Error::InvalidEnvelope(format!(
            "{location} must be an array"
        )));
    };
    Ok(values)
}

fn required_field<'a>(object: &'a [(String, JsonValue)], key: &str) -> Result<&'a JsonValue> {
    optional_field(object, key)
        .ok_or_else(|| Error::InvalidEnvelope(format!("missing required member {key}")))
}

fn optional_field<'a>(object: &'a [(String, JsonValue)], key: &str) -> Option<&'a JsonValue> {
    object
        .iter()
        .find_map(|(candidate, value)| (candidate == key).then_some(value))
}

fn string_field<'a>(object: &'a [(String, JsonValue)], key: &str) -> Result<&'a str> {
    match required_field(object, key)? {
        JsonValue::String(value) => Ok(value),
        _ => Err(Error::InvalidEnvelope(format!("{key} must be a string"))),
    }
}

fn usize_field(object: &[(String, JsonValue)], key: &str) -> Result<usize> {
    parse_usize_value(required_field(object, key)?)
}

fn u64_field(object: &[(String, JsonValue)], key: &str) -> Result<u64> {
    parse_u64_value(required_field(object, key)?)
}

fn parse_usize_value(value: &JsonValue) -> Result<usize> {
    let maximum = u64::try_from(usize::MAX).unwrap_or(u64::MAX);
    let value = parse_bounded_schema_integer(value, maximum)?;
    usize::try_from(value)
        .map_err(|_| Error::InvalidEnvelope("integer exceeds platform range".into()))
}

fn parse_u64_value(value: &JsonValue) -> Result<u64> {
    parse_bounded_schema_integer(value, u64::MAX)
}

fn parse_bounded_schema_integer(value: &JsonValue, maximum: u64) -> Result<u64> {
    let JsonValue::Number(value) = value else {
        return Err(Error::InvalidEnvelope(
            "expected a non-negative integer".into(),
        ));
    };
    parse_schema_nonnegative_u64(value, maximum)
        .ok_or_else(|| Error::InvalidEnvelope("expected an in-range non-negative integer".into()))
}

fn hash_field(object: &[(String, JsonValue)], key: &str) -> Result<Hash> {
    parse_hash_text(string_field(object, key)?)
}

fn parse_hash_value(value: &JsonValue) -> Result<Hash> {
    let JsonValue::String(value) = value else {
        return Err(Error::InvalidHex);
    };
    parse_hash_text(value)
}

fn parse_hash_text(value: &str) -> Result<Hash> {
    let decoded = hex::decode(value).map_err(|_| Error::InvalidHex)?;
    if hex::encode(&decoded) != value {
        return Err(Error::InvalidHex);
    }
    decoded.try_into().map_err(|_| Error::InvalidHex)
}

fn common_envelope_fields(
    context: &CommitmentContext,
    root: Hash,
    leaf_count: u64,
) -> Vec<(String, JsonValue)> {
    let mut fields = vec![
        ("canon".into(), JsonValue::String(CANON_VERSION.into())),
        (
            "hashAlg".into(),
            JsonValue::String(context.hash_algorithm.name().into()),
        ),
        (
            "recordType".into(),
            JsonValue::String(context.record_type.clone()),
        ),
        (
            "schemaVersion".into(),
            JsonValue::String(context.schema_version.clone()),
        ),
    ];
    if let Some(descriptor) = &context.type_map {
        fields.push((
            "typeMap".into(),
            JsonValue::Object(vec![
                ("id".into(), JsonValue::String(descriptor.id.clone())),
                (
                    "version".into(),
                    JsonValue::String(descriptor.version.clone()),
                ),
            ]),
        ));
    }
    fields.extend([
        (
            "recordId".into(),
            JsonValue::String(context.record_id.clone()),
        ),
        ("root".into(), JsonValue::String(hex::encode(root))),
        (
            "leafCount".into(),
            JsonValue::Number(leaf_count.to_string()),
        ),
        (
            "issuer".into(),
            JsonValue::Object({
                let mut issuer = vec![("id".into(), JsonValue::String(context.issuer.id.clone()))];
                if let Some(key_id) = &context.issuer.key_id {
                    issuer.push(("keyId".into(), JsonValue::String(key_id.clone())));
                }
                issuer
            }),
        ),
    ]);
    fields
}

fn path_json(path: &Path) -> JsonValue {
    JsonValue::Array(
        path.segments()
            .iter()
            .map(|segment| match segment {
                Segment::Key(key) => {
                    JsonValue::Object(vec![("key".into(), JsonValue::String(key.clone()))])
                }
                Segment::Index(index) => {
                    JsonValue::Object(vec![("index".into(), JsonValue::Number(index.to_string()))])
                }
            })
            .collect(),
    )
}

fn disclosed_leaf_json(leaf: &DisclosedLeaf) -> JsonValue {
    let mut fields = vec![
        ("segments".into(), path_json(&leaf.path)),
        ("index".into(), JsonValue::Number(leaf.index.to_string())),
        (
            "tag".into(),
            JsonValue::Number((leaf.tag as u8).to_string()),
        ),
    ];
    if let Some(display_path) = &leaf.display_path {
        fields.push((
            "displayPath".into(),
            JsonValue::String(display_path.clone()),
        ));
    }
    if let Some(value) = leaf.value.disclosure_carrier() {
        fields.push(("value".into(), value));
    }
    fields.extend([
        ("salt".into(), JsonValue::String(leaf.salt.to_hex())),
        (
            "auditPath".into(),
            JsonValue::Array(
                leaf.audit_path
                    .iter()
                    .map(|hash| JsonValue::String(hex::encode(hash)))
                    .collect(),
            ),
        ),
    ]);
    JsonValue::Object(fields)
}
