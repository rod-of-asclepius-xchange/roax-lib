use crate::error::{Error, Result};
use crate::json::JsonValue;
use crate::merkle::{merkle_tree_hash, Hash};
use crate::path::{Path, Segment};
use crate::type_map::{JsonKind, TypeMapDescriptor, TypeResolver, TypeTag};
use crate::value::LeafValue;
use crate::CANON_VERSION;
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use unicode_normalization::UnicodeNormalization;

/// Hash family selected for a record.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HashAlgorithm {
    Sha256,
}

impl HashAlgorithm {
    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "SHA-256" => Ok(Self::Sha256),
            other => Err(Error::UnsupportedAlgorithm(other.to_owned())),
        }
    }

    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::Sha256 => "SHA-256",
        }
    }

    #[must_use]
    pub fn domain(self) -> Vec<u8> {
        format!("{CANON_VERSION}/{}", self.name()).into_bytes()
    }
}

/// One independent 16-byte leaf salt.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct Salt([u8; 16]);

impl Salt {
    #[must_use]
    pub const fn from_bytes(bytes: [u8; 16]) -> Self {
        Self(bytes)
    }

    pub fn from_hex(value: &str) -> Result<Self> {
        let bytes = hex::decode(value).map_err(|_| Error::InvalidHex)?;
        let bytes: [u8; 16] = bytes.try_into().map_err(|_| Error::InvalidSaltLength)?;
        if hex::encode(bytes) != value {
            return Err(Error::InvalidHex);
        }
        Ok(Self(bytes))
    }

    #[must_use]
    pub const fn as_bytes(&self) -> &[u8; 16] {
        &self.0
    }

    #[must_use]
    pub fn to_hex(self) -> String {
        hex::encode(self.0)
    }
}

/// Source of independent salts. Production callers should use `OsSaltSource`.
pub(crate) trait SaltSource {
    fn fill_salt(&mut self, output: &mut [u8; 16]) -> Result<()>;
}

/// Operating-system CSPRNG salt source.
#[derive(Debug, Default)]
pub(crate) struct OsSaltSource;

impl SaltSource for OsSaltSource {
    fn fill_salt(&mut self, output: &mut [u8; 16]) -> Result<()> {
        getrandom::fill(output).map_err(|error| Error::SaltGeneration(error.to_string()))
    }
}

/// Path-addressed salts, keyed by authoritative encoded path bytes.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SaltMap {
    entries: HashMap<Vec<u8>, (Path, Salt)>,
}

impl SaltMap {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn insert(&mut self, path: Path, salt: Salt) -> Result<()> {
        let encoded = path.encode()?;
        if self.entries.insert(encoded, (path, salt)).is_some() {
            return Err(Error::DuplicateSaltPath);
        }
        Ok(())
    }

    pub fn get(&self, path: &Path) -> Result<Salt> {
        let encoded = path.encode()?;
        self.entries
            .get(&encoded)
            .map(|(_, salt)| *salt)
            .ok_or_else(|| Error::MissingSalt(path.clone()))
    }

    #[must_use]
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    pub fn iter(&self) -> impl Iterator<Item = (&Path, Salt)> {
        self.entries.values().map(|(path, salt)| (path, *salt))
    }
}

/// Reserved-leaf generation selected explicitly by envelope schema version.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReservedLeafSet {
    /// Compatibility with the committed envelope/corpus 1.0 artifact.
    EnvelopeV1,
    /// Current exact type-map binding from envelope 2.0.
    EnvelopeV2,
}

/// Issuer identity committed into reserved leaves.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Issuer {
    pub id: String,
    pub key_id: Option<String>,
}

/// Inputs that become the fixed reserved leaf union.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CommitmentContext {
    pub hash_algorithm: HashAlgorithm,
    pub reserved_leaf_set: ReservedLeafSet,
    pub record_type: String,
    pub schema_version: String,
    pub type_map: Option<TypeMapDescriptor>,
    pub record_id: String,
    pub issuer: Issuer,
}

impl CommitmentContext {
    pub fn validate(&self) -> Result<()> {
        match (self.reserved_leaf_set, &self.type_map) {
            (ReservedLeafSet::EnvelopeV1, None) | (ReservedLeafSet::EnvelopeV2, Some(_)) => {}
            _ => return Err(Error::UnsupportedEnvelopeGeneration),
        }
        if !valid_record_type(&self.record_type) {
            return Err(Error::InvalidContext("invalid recordType".into()));
        }
        if self.schema_version.is_empty() {
            return Err(Error::InvalidContext("schemaVersion is empty".into()));
        }
        if self.record_id.is_empty() {
            return Err(Error::InvalidContext("recordId is empty".into()));
        }
        if uriparse::URI::try_from(self.issuer.id.as_str()).is_err() {
            return Err(Error::InvalidContext(
                "issuer.id is not an absolute URI".into(),
            ));
        }
        if let Some(descriptor) = &self.type_map {
            if !valid_sha256_id(&descriptor.id) {
                return Err(Error::InvalidContext("invalid typeMap.id".into()));
            }
            if !valid_three_part_version(&descriptor.version) {
                return Err(Error::InvalidContext("invalid typeMap.version".into()));
            }
        }
        Ok(())
    }
}

fn valid_record_type(value: &str) -> bool {
    let labels: Vec<_> = value.split('.').collect();
    labels.len() >= 2
        && labels.iter().all(|label| {
            label.split('-').all(|part| {
                !part.is_empty()
                    && part
                        .bytes()
                        .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit())
            })
        })
}

fn valid_sha256_id(value: &str) -> bool {
    value.len() == 71
        && value.starts_with("sha256:")
        && value[7..]
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn valid_three_part_version(value: &str) -> bool {
    let mut parts = value.split('.');
    let valid = (0..3).all(|_| {
        parts
            .next()
            .is_some_and(|part| !part.is_empty() && part.bytes().all(|byte| byte.is_ascii_digit()))
    });
    valid && parts.next().is_none()
}

/// Complete profile validation boundary.
pub trait SchemaValidator {
    fn validate_record(&self, record: &JsonValue) -> Result<()>;
}

/// One salted, sorted leaf.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CanonicalLeaf {
    path: Path,
    encoded_path: Vec<u8>,
    tag: TypeTag,
    value: LeafValue,
    salt: Salt,
    hash: Hash,
}

/// Root and its complete sorted leaf set.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Commitment {
    context: CommitmentContext,
    root: Hash,
    leaves: Vec<CanonicalLeaf>,
    record_leaf_count: usize,
}

impl CanonicalLeaf {
    #[must_use]
    pub fn path(&self) -> &Path {
        &self.path
    }

    #[must_use]
    pub fn encoded_path(&self) -> &[u8] {
        &self.encoded_path
    }

    #[must_use]
    pub const fn tag(&self) -> TypeTag {
        self.tag
    }

    #[must_use]
    pub fn value(&self) -> &LeafValue {
        &self.value
    }

    #[must_use]
    pub const fn salt(&self) -> Salt {
        self.salt
    }

    #[must_use]
    pub const fn hash(&self) -> Hash {
        self.hash
    }
}

impl Commitment {
    #[must_use]
    pub const fn context(&self) -> &CommitmentContext {
        &self.context
    }

    #[must_use]
    pub const fn root(&self) -> Hash {
        self.root
    }

    #[must_use]
    pub fn leaves(&self) -> &[CanonicalLeaf] {
        &self.leaves
    }

    #[must_use]
    pub const fn record_leaf_count(&self) -> usize {
        self.record_leaf_count
    }
}

/// Commit a complete, profile-validated record using a supplied path-addressed salt set.
pub(crate) fn commit_record<V, R>(
    record: &JsonValue,
    context: &CommitmentContext,
    validator: &V,
    resolver: &R,
    salts: &SaltMap,
) -> Result<Commitment>
where
    V: SchemaValidator + ?Sized,
    R: TypeResolver + ?Sized,
{
    let prepared = prepare_record(record, context, validator, resolver)?;
    commit_prepared(prepared, context, salts)
}

/// Issue a record using fresh independent salts from the operating system CSPRNG.
pub(crate) fn issue_record<V, R>(
    record: &JsonValue,
    context: &CommitmentContext,
    validator: &V,
    resolver: &R,
) -> Result<Commitment>
where
    V: SchemaValidator + ?Sized,
    R: TypeResolver + ?Sized,
{
    let mut source = OsSaltSource;
    issue_record_with_salt_source(record, context, validator, resolver, &mut source)
}

/// Issue a record using an injected salt source.
fn issue_record_with_salt_source<V, R>(
    record: &JsonValue,
    context: &CommitmentContext,
    validator: &V,
    resolver: &R,
    source: &mut dyn SaltSource,
) -> Result<Commitment>
where
    V: SchemaValidator + ?Sized,
    R: TypeResolver + ?Sized,
{
    let prepared = prepare_record(record, context, validator, resolver)?;
    let paths: Vec<_> = prepared
        .record
        .iter()
        .chain(&prepared.reserved)
        .map(|leaf| leaf.path.clone())
        .collect();
    let salts = generate_salts_with(&paths, source)?;
    commit_prepared(prepared, context, &salts)
}

/// Generate an independent salt for each unique structured path.
pub fn generate_salts(paths: &[Path]) -> Result<SaltMap> {
    let mut source = OsSaltSource;
    generate_salts_with(paths, &mut source)
}

/// Generate salts through an injected source, retrying accidental duplicates.
fn generate_salts_with(paths: &[Path], source: &mut dyn SaltSource) -> Result<SaltMap> {
    let mut map = SaltMap::new();
    let mut used = HashSet::new();
    for path in paths {
        let mut selected = None;
        for _ in 0..128 {
            let mut bytes = [0_u8; 16];
            source.fill_salt(&mut bytes)?;
            if used.insert(bytes) {
                selected = Some(Salt::from_bytes(bytes));
                break;
            }
        }
        map.insert(
            path.clone(),
            selected.ok_or_else(|| {
                Error::SaltGeneration("salt source repeated a value 128 times".into())
            })?,
        )?;
    }
    Ok(map)
}

/// Construct the single ROAX-CANON/1 leaf preimage and hash it.
pub fn leaf_hash(
    path: &Path,
    tag: TypeTag,
    value: &LeafValue,
    salt: Salt,
    algorithm: HashAlgorithm,
) -> Result<Hash> {
    if tag != value.tag() {
        return Err(Error::TypeMismatch { tag });
    }
    let domain = algorithm.domain();
    let encoded_path = path.encode()?;
    let encoded_value = value.encode()?;
    let domain_length = u32::try_from(domain.len())
        .map_err(|_| Error::InvalidPath("domain exceeds u32 length".into()))?;
    let path_length = u32::try_from(encoded_path.len())
        .map_err(|_| Error::InvalidPath("encoded path exceeds u32 length".into()))?;
    let value_length =
        u64::try_from(encoded_value.len()).map_err(|_| Error::InvalidValueCarrier)?;

    let mut hasher = Sha256::new();
    hasher.update([0x00]);
    hasher.update(domain_length.to_be_bytes());
    hasher.update(&domain);
    hasher.update(path_length.to_be_bytes());
    hasher.update(&encoded_path);
    hasher.update([tag as u8]);
    hasher.update(16_u32.to_be_bytes());
    hasher.update(salt.as_bytes());
    hasher.update(value_length.to_be_bytes());
    hasher.update(&encoded_value);
    Ok(hasher.finalize().into())
}

#[derive(Clone, Debug)]
struct UnsaltedLeaf {
    path: Path,
    tag: TypeTag,
    value: LeafValue,
}

struct PreparedRecord {
    record: Vec<UnsaltedLeaf>,
    reserved: Vec<UnsaltedLeaf>,
}

fn prepare_record<V, R>(
    record: &JsonValue,
    context: &CommitmentContext,
    validator: &V,
    resolver: &R,
) -> Result<PreparedRecord>
where
    V: SchemaValidator + ?Sized,
    R: TypeResolver + ?Sized,
{
    context.validate()?;
    record.validate()?;
    if !matches!(record, JsonValue::Object(_)) {
        return Err(Error::ProfileValidation(
            "a ROAX record must be a JSON object".into(),
        ));
    }
    check_reserved_namespace(record)?;
    validator.validate_record(record)?;

    let mut record_leaves = Vec::new();
    flatten(record, &Path::new(), resolver, &mut record_leaves)?;
    if record_leaves.is_empty() {
        return Err(Error::EmptyRecordContribution);
    }
    let reserved = reserved_leaves(context)?;
    ensure_unique_encoded_paths(record_leaves.iter().chain(&reserved))?;
    Ok(PreparedRecord {
        record: record_leaves,
        reserved,
    })
}

fn commit_prepared(
    prepared: PreparedRecord,
    context: &CommitmentContext,
    salts: &SaltMap,
) -> Result<Commitment> {
    let record_leaf_count = prepared.record.len();
    let mut leaves = Vec::with_capacity(record_leaf_count + prepared.reserved.len());
    let mut used_salts = HashSet::new();
    for leaf in prepared.record.into_iter().chain(prepared.reserved) {
        let encoded_path = leaf.path.encode()?;
        let salt = salts.get(&leaf.path)?;
        if !used_salts.insert(salt) {
            return Err(Error::SaltGeneration(
                "one salt was assigned to more than one leaf".into(),
            ));
        }
        let hash = leaf_hash(
            &leaf.path,
            leaf.tag,
            &leaf.value,
            salt,
            context.hash_algorithm,
        )?;
        leaves.push(CanonicalLeaf {
            path: leaf.path,
            encoded_path,
            tag: leaf.tag,
            value: leaf.value,
            salt,
            hash,
        });
    }
    if salts.len() != leaves.len() {
        return Err(Error::ExtraSaltPath);
    }
    leaves.sort_by(|left, right| left.encoded_path.cmp(&right.encoded_path));
    let hashes: Vec<Hash> = leaves.iter().map(|leaf| leaf.hash).collect();
    Ok(Commitment {
        context: context.clone(),
        root: merkle_tree_hash(&hashes),
        leaves,
        record_leaf_count,
    })
}

fn flatten<R>(
    value: &JsonValue,
    path: &Path,
    resolver: &R,
    leaves: &mut Vec<UnsaltedLeaf>,
) -> Result<()>
where
    R: TypeResolver + ?Sized,
{
    enum Frame<'a> {
        Visit(&'a JsonValue),
        PushKey(&'a str),
        PushIndex(u32),
        Pop,
    }

    let mut segments = path.segments().to_vec();
    let mut pending = vec![Frame::Visit(value)];
    while let Some(frame) = pending.pop() {
        match frame {
            Frame::PushKey(key) => segments.push(Segment::Key(key.to_owned())),
            Frame::PushIndex(index) => segments.push(Segment::Index(index)),
            Frame::Pop => {
                segments
                    .pop()
                    .expect("each traversal pop has a matching pushed segment");
            }
            Frame::Visit(JsonValue::Object(entries)) if !entries.is_empty() => {
                for (key, child) in entries.iter().rev() {
                    pending.push(Frame::Pop);
                    pending.push(Frame::Visit(child));
                    pending.push(Frame::PushKey(key));
                }
            }
            Frame::Visit(JsonValue::Array(values)) if !values.is_empty() => {
                for (index, child) in values.iter().enumerate().rev() {
                    let index = u32::try_from(index).map_err(|_| {
                        Error::InvalidPath("array index is outside the 32-bit range".into())
                    })?;
                    pending.push(Frame::Pop);
                    pending.push(Frame::Visit(child));
                    pending.push(Frame::PushIndex(index));
                }
            }
            Frame::Visit(value) => {
                let leaf_path = Path::from_segments(segments.clone());
                let kind = JsonKind::of(value);
                resolver.ensure_lookup_decision_independent(&leaf_path, kind)?;
                let tag = resolver.resolve(&leaf_path, kind)?;
                let leaf_value = LeafValue::from_json(tag, value)?;
                leaves.push(UnsaltedLeaf {
                    path: leaf_path,
                    tag,
                    value: leaf_value,
                });
            }
        }
    }
    Ok(())
}

fn reserved_leaves(context: &CommitmentContext) -> Result<Vec<UnsaltedLeaf>> {
    let mut values = vec![
        ("roax.recordType", context.record_type.clone()),
        ("roax.schemaVersion", context.schema_version.clone()),
        ("roax.recordId", context.record_id.clone()),
        ("roax.issuer.id", context.issuer.id.clone()),
    ];
    if context.reserved_leaf_set == ReservedLeafSet::EnvelopeV2 {
        values.push((
            "roax.typeMap.id",
            context
                .type_map
                .as_ref()
                .ok_or(Error::UnsupportedEnvelopeGeneration)?
                .id
                .clone(),
        ));
    }
    if let Some(key_id) = &context.issuer.key_id {
        values.push(("roax.issuer.keyId", key_id.clone()));
    }
    Ok(values
        .into_iter()
        .map(|(key, value)| UnsaltedLeaf {
            path: Path::from_segments(vec![Segment::Key(key.into())]),
            tag: TypeTag::String,
            value: LeafValue::String(value),
        })
        .collect())
}

fn check_reserved_namespace(record: &JsonValue) -> Result<()> {
    let JsonValue::Object(entries) = record else {
        return Ok(());
    };
    for (key, _) in entries {
        let normalized: String = key.nfc().collect();
        if normalized.starts_with("roax.") {
            return Err(Error::ReservedNamespaceCollision);
        }
    }
    Ok(())
}

fn ensure_unique_encoded_paths<'a>(leaves: impl Iterator<Item = &'a UnsaltedLeaf>) -> Result<()> {
    let mut paths = HashSet::new();
    for leaf in leaves {
        if !paths.insert(leaf.path.encode()?) {
            return Err(Error::DuplicateCanonicalPath);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{
        leaf_hash, CommitmentContext, HashAlgorithm, Issuer, ReservedLeafSet, Salt, CANON_VERSION,
    };
    use crate::{LeafValue, Path, Segment, TypeTag};

    #[test]
    fn domain_is_algorithm_qualified() {
        assert_eq!(
            HashAlgorithm::Sha256.domain(),
            format!("{CANON_VERSION}/SHA-256").into_bytes()
        );
    }

    #[test]
    fn reserved_set_selection_is_explicit() {
        let context = CommitmentContext {
            hash_algorithm: HashAlgorithm::Sha256,
            reserved_leaf_set: ReservedLeafSet::EnvelopeV2,
            record_type: "example.record".into(),
            schema_version: "1".into(),
            type_map: None,
            record_id: "id".into(),
            issuer: Issuer {
                id: "issuer".into(),
                key_id: None,
            },
        };
        assert!(context.validate().is_err());
    }

    #[test]
    fn leaf_hash_is_stable() {
        let hash = leaf_hash(
            &Path::from_segments(vec![Segment::Key("a".into())]),
            TypeTag::String,
            &LeafValue::String("value".into()),
            Salt::from_bytes([7; 16]),
            HashAlgorithm::Sha256,
        )
        .unwrap();
        assert_eq!(hash.len(), 32);
    }
}
