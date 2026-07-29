use crate::error::{Error, Result};
use crate::json::JsonValue;
use crate::path::{Path, Segment};
use crate::value::parse_schema_nonnegative_u64;
use serde::de::Error as SerdeError;
use serde::{Deserialize, Deserializer};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet, VecDeque};
use unicode_normalization::{UnicodeNormalization, UNICODE_VERSION};

const TYPE_MAP_DOMAIN: &[u8] = b"ROAX-TYPE-MAP/1\0";

/// JSON kind observed before schema-selected tagging.
#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq, Hash, PartialOrd, Ord)]
#[serde(rename_all = "lowercase")]
pub enum JsonKind {
    String,
    Number,
    Boolean,
    Null,
    Object,
    Array,
}

impl JsonKind {
    #[must_use]
    pub const fn of(value: &JsonValue) -> Self {
        match value {
            JsonValue::Object(_) => Self::Object,
            JsonValue::Array(_) => Self::Array,
            JsonValue::String(_) => Self::String,
            JsonValue::Number(_) => Self::Number,
            JsonValue::Bool(_) => Self::Boolean,
            JsonValue::Null => Self::Null,
        }
    }
}

/// ROAX-CANON/1 type tags.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[repr(u8)]
pub enum TypeTag {
    Null = 0,
    Bool = 1,
    String = 2,
    Integer = 3,
    Decimal = 4,
    Bytes = 5,
    EmptyArray = 6,
    EmptyObject = 7,
    BlobRef = 8,
}

impl TryFrom<u8> for TypeTag {
    type Error = Error;

    fn try_from(value: u8) -> Result<Self> {
        match value {
            0 => Ok(Self::Null),
            1 => Ok(Self::Bool),
            2 => Ok(Self::String),
            3 => Ok(Self::Integer),
            4 => Ok(Self::Decimal),
            5 => Ok(Self::Bytes),
            6 => Ok(Self::EmptyArray),
            7 => Ok(Self::EmptyObject),
            8 => Ok(Self::BlobRef),
            _ => Err(Error::InvalidTypeMap(format!("unknown tag {value}"))),
        }
    }
}

/// Explicit selection for open decision D14.
///
/// There is intentionally no `Default` implementation.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LookupKeyMode {
    Raw,
    Nfc15_1,
}

/// Exact descriptor carried by a current envelope.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TypeMapDescriptor {
    pub id: String,
    pub version: String,
}

/// Fail-closed schema-selected tag resolver.
pub trait TypeResolver {
    fn resolve(&self, path: &Path, kind: JsonKind) -> Result<TypeTag>;

    /// Refuse a lookup whose result changes across the two open D14 readings.
    fn ensure_lookup_decision_independent(&self, path: &Path, kind: JsonKind) -> Result<()>;
}

/// Validated structured-path DFA over exact immutable artifact bytes.
#[derive(Clone, Debug)]
pub struct DfaTypeMap {
    id: String,
    version: String,
    record_type: String,
    schema_version: String,
    states: Vec<CompiledState>,
    lookup_key_mode: LookupKeyMode,
}

#[derive(Clone, Debug)]
struct CompiledState {
    keys: HashMap<String, usize>,
    any_index: Option<usize>,
    bindings: HashMap<JsonKind, TypeTag>,
}

impl DfaTypeMap {
    /// Identify, decode, validate, and compile exact artifact bytes.
    pub fn from_exact_bytes(
        bytes: &[u8],
        expected_id: &str,
        lookup_key_mode: LookupKeyMode,
    ) -> Result<Self> {
        assert_unicode_version()?;
        let actual_id = content_id(bytes);
        if actual_id != expected_id {
            return Err(Error::TypeMapIdMismatch);
        }

        // The strict parser establishes a single JSON interpretation before serde
        // decodes the closed artifact carrier.
        JsonValue::from_slice(bytes)?;
        let artifact: Artifact = serde_json::from_slice(bytes)
            .map_err(|error| Error::InvalidTypeMap(error.to_string()))?;
        validate_artifact(&artifact)?;

        if artifact.parent_type_map_id.is_some()
            || matches!(artifact.scope, ArtifactScope::Issuers { .. })
        {
            return Err(Error::InvalidTypeMap(
                "issuer child artifacts require parent and additivity validation".into(),
            ));
        }
        let states = compile_states(&artifact.automaton.states)?;

        Ok(Self {
            id: actual_id,
            version: artifact.type_map_version,
            record_type: artifact.record_type,
            schema_version: artifact.schema_version,
            states,
            lookup_key_mode,
        })
    }

    #[must_use]
    pub fn id(&self) -> &str {
        &self.id
    }

    #[must_use]
    pub fn version(&self) -> &str {
        &self.version
    }

    #[must_use]
    pub fn record_type(&self) -> &str {
        &self.record_type
    }

    #[must_use]
    pub fn schema_version(&self) -> &str {
        &self.schema_version
    }

    /// Check the exact record, descriptor, and issuer selection tuple.
    pub fn select(
        &self,
        record_type: &str,
        schema_version: &str,
        descriptor: &TypeMapDescriptor,
        _issuer_id: &str,
    ) -> Result<()> {
        if self.id != descriptor.id
            || self.version != descriptor.version
            || self.record_type != record_type
            || self.schema_version != schema_version
        {
            return Err(Error::TypeMapIdentityMismatch);
        }
        Ok(())
    }
}

impl TypeResolver for DfaTypeMap {
    fn resolve(&self, path: &Path, kind: JsonKind) -> Result<TypeTag> {
        self.resolve_with_mode(path, kind, self.lookup_key_mode)
    }

    fn ensure_lookup_decision_independent(&self, path: &Path, kind: JsonKind) -> Result<()> {
        let raw = self.resolve_with_mode(path, kind, LookupKeyMode::Raw);
        let nfc = self.resolve_with_mode(path, kind, LookupKeyMode::Nfc15_1);
        match (raw, nfc) {
            (Ok(left), Ok(right)) if left == right => Ok(()),
            (Err(Error::UnknownTypeBinding { .. }), Err(Error::UnknownTypeBinding { .. })) => {
                Ok(())
            }
            _ => Err(Error::LookupNormalizationUndecided(path.clone())),
        }
    }
}

impl DfaTypeMap {
    fn resolve_with_mode(
        &self,
        path: &Path,
        kind: JsonKind,
        lookup_key_mode: LookupKeyMode,
    ) -> Result<TypeTag> {
        let mut state_index = 0_usize;
        for segment in path.segments() {
            let state = self.states.get(state_index).ok_or_else(|| {
                Error::InvalidTypeMap("transition reached a missing state".into())
            })?;
            state_index = match segment {
                Segment::Key(key) => {
                    let lookup = match lookup_key_mode {
                        LookupKeyMode::Raw => key.clone(),
                        LookupKeyMode::Nfc15_1 => key.nfc().collect(),
                    };
                    *state
                        .keys
                        .get(&lookup)
                        .ok_or_else(|| Error::UnknownTypeBinding {
                            path: path.clone(),
                            kind,
                        })?
                }
                Segment::Index(_) => state.any_index.ok_or_else(|| Error::UnknownTypeBinding {
                    path: path.clone(),
                    kind,
                })?,
            };
        }
        self.states[state_index]
            .bindings
            .get(&kind)
            .copied()
            .ok_or_else(|| Error::UnknownTypeBinding {
                path: path.clone(),
                kind,
            })
    }
}

#[must_use]
pub fn content_id(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(TYPE_MAP_DOMAIN);
    hasher.update(bytes);
    format!("sha256:{}", hex::encode(hasher.finalize()))
}

fn assert_unicode_version() -> Result<()> {
    if UNICODE_VERSION == (15, 1, 0) {
        Ok(())
    } else {
        Err(Error::InvalidTypeMap(format!(
            "unicode-normalization tables are {UNICODE_VERSION:?}, expected (15, 1, 0)"
        )))
    }
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Artifact {
    format: String,
    type_map_version: String,
    record_type: String,
    schema_version: String,
    #[serde(default)]
    parent_type_map_id: OptionalField<String>,
    scope: ArtifactScope,
    source_schemas: Vec<SourceSchema>,
    extension_points: Vec<ExtensionPoint>,
    added_selectors: Vec<SelectorBinding>,
    coverage: Coverage,
    automaton: ArtifactAutomaton,
}

#[derive(Debug)]
struct OptionalField<T>(Option<T>);

impl<T> Default for OptionalField<T> {
    fn default() -> Self {
        Self(None)
    }
}

impl<T> OptionalField<T> {
    fn as_ref(&self) -> Option<&T> {
        self.0.as_ref()
    }

    fn as_deref(&self) -> Option<&T::Target>
    where
        T: std::ops::Deref,
    {
        self.0.as_deref()
    }

    fn is_some(&self) -> bool {
        self.0.is_some()
    }
}

impl<'de, T> Deserialize<'de> for OptionalField<T>
where
    T: Deserialize<'de>,
{
    fn deserialize<D>(deserializer: D) -> std::result::Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        T::deserialize(deserializer).map(|value| Self(Some(value)))
    }
}

#[derive(Clone, Copy, Debug)]
struct ArtifactTag(u8);

impl ArtifactTag {
    const fn value(self) -> u8 {
        self.0
    }
}

impl<'de> Deserialize<'de> for ArtifactTag {
    fn deserialize<D>(deserializer: D) -> std::result::Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = deserialize_bounded_integer(deserializer, u64::from(TypeTag::BlobRef as u8))?;
        u8::try_from(value)
            .map(Self)
            .map_err(|_| invalid_schema_integer::<D::Error>())
    }
}

#[derive(Clone, Copy, Debug)]
struct CoverageCount(usize);

impl CoverageCount {
    const fn value(self) -> usize {
        self.0
    }
}

impl<'de> Deserialize<'de> for CoverageCount {
    fn deserialize<D>(deserializer: D) -> std::result::Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let maximum = u64::try_from(usize::MAX).unwrap_or(u64::MAX);
        let value = deserialize_bounded_integer(deserializer, maximum)?;
        usize::try_from(value)
            .map(Self)
            .map_err(|_| invalid_schema_integer::<D::Error>())
    }
}

fn deserialize_bounded_integer<'de, D>(
    deserializer: D,
    maximum: u64,
) -> std::result::Result<u64, D::Error>
where
    D: Deserializer<'de>,
{
    let number = serde_json::Number::deserialize(deserializer)?;
    parse_schema_nonnegative_u64(&number.to_string(), maximum)
        .ok_or_else(invalid_schema_integer::<D::Error>)
}

fn invalid_schema_integer<E>() -> E
where
    E: SerdeError,
{
    E::custom("expected a non-negative mathematical integer within range")
}

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", deny_unknown_fields)]
enum ArtifactScope {
    #[serde(rename = "profile")]
    Profile,
    #[serde(rename = "issuers")]
    #[serde(rename_all = "camelCase")]
    Issuers { issuer_ids: Vec<String> },
}

#[derive(Debug, Deserialize, PartialEq, Eq, Hash)]
#[serde(tag = "kind", deny_unknown_fields)]
enum SourceSchema {
    #[serde(rename = "git")]
    Git {
        #[serde(rename = "sourceId")]
        source_id: String,
        #[serde(rename = "repositoryUri")]
        repository_uri: String,
        path: String,
        commit: String,
    },
    #[serde(rename = "content")]
    Content {
        #[serde(rename = "sourceId")]
        source_id: String,
        uri: String,
        digest: String,
    },
}

impl SourceSchema {
    fn source_id(&self) -> &str {
        match self {
            Self::Git { source_id, .. } | Self::Content { source_id, .. } => source_id,
        }
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Eq, Hash)]
#[serde(untagged)]
enum SegmentPattern {
    Key(KeySegmentPattern),
    AnyIndex(AnyIndexSegmentPattern),
}

#[derive(Clone, Debug, Deserialize, PartialEq, Eq, Hash)]
#[serde(deny_unknown_fields)]
struct KeySegmentPattern {
    key: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct AnyIndexSegmentPattern {
    any_index: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ExtensionPoint {
    prefix: Vec<SegmentPattern>,
    note: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SelectorBinding {
    segments: Vec<SegmentPattern>,
    json_kind: JsonKind,
    tag: ArtifactTag,
    evidence: Vec<String>,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "kebab-case")]
enum BindingBasis {
    SchemaType,
    SchemaConst,
    SchemaEnum,
    SchemaContainerType,
    FhirNamedPrimitive,
    FhirElementName,
    ProfileRuling,
}

impl BindingBasis {
    const fn name(self) -> &'static str {
        match self {
            Self::SchemaType => "schema-type",
            Self::SchemaConst => "schema-const",
            Self::SchemaEnum => "schema-enum",
            Self::SchemaContainerType => "schema-container-type",
            Self::FhirNamedPrimitive => "fhir-named-primitive",
            Self::FhirElementName => "fhir-element-name",
            Self::ProfileRuling => "profile-ruling",
        }
    }

    const fn index(self) -> usize {
        match self {
            Self::SchemaType => 0,
            Self::SchemaConst => 1,
            Self::SchemaEnum => 2,
            Self::SchemaContainerType => 3,
            Self::FhirNamedPrimitive => 4,
            Self::FhirElementName => 5,
            Self::ProfileRuling => 6,
        }
    }
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Coverage {
    concrete_path_cardinality: String,
    states: CoverageCount,
    key_transitions: CoverageCount,
    index_transitions: CoverageCount,
    resolved_outputs: CoverageCount,
    unresolved_output_states: CoverageCount,
    structurally_untyped_object_source_nodes: CoverageCount,
    structurally_untyped_object_states: CoverageCount,
    by_tag: TagCounts,
    by_basis: BasisCounts,
    notes: Vec<String>,
}

#[derive(Debug, Default, Deserialize)]
#[serde(default, deny_unknown_fields)]
struct TagCounts {
    #[serde(rename = "0")]
    zero: OptionalField<CoverageCount>,
    #[serde(rename = "1")]
    one: OptionalField<CoverageCount>,
    #[serde(rename = "2")]
    two: OptionalField<CoverageCount>,
    #[serde(rename = "3")]
    three: OptionalField<CoverageCount>,
    #[serde(rename = "4")]
    four: OptionalField<CoverageCount>,
    #[serde(rename = "5")]
    five: OptionalField<CoverageCount>,
    #[serde(rename = "6")]
    six: OptionalField<CoverageCount>,
    #[serde(rename = "7")]
    seven: OptionalField<CoverageCount>,
    #[serde(rename = "8")]
    eight: OptionalField<CoverageCount>,
}

impl TagCounts {
    fn values(&self) -> [Option<usize>; 9] {
        [
            self.zero.as_ref().copied().map(CoverageCount::value),
            self.one.as_ref().copied().map(CoverageCount::value),
            self.two.as_ref().copied().map(CoverageCount::value),
            self.three.as_ref().copied().map(CoverageCount::value),
            self.four.as_ref().copied().map(CoverageCount::value),
            self.five.as_ref().copied().map(CoverageCount::value),
            self.six.as_ref().copied().map(CoverageCount::value),
            self.seven.as_ref().copied().map(CoverageCount::value),
            self.eight.as_ref().copied().map(CoverageCount::value),
        ]
    }
}

#[derive(Debug, Default, Deserialize)]
#[serde(default, rename_all = "kebab-case", deny_unknown_fields)]
struct BasisCounts {
    schema_type: OptionalField<CoverageCount>,
    schema_const: OptionalField<CoverageCount>,
    schema_enum: OptionalField<CoverageCount>,
    schema_container_type: OptionalField<CoverageCount>,
    fhir_named_primitive: OptionalField<CoverageCount>,
    fhir_element_name: OptionalField<CoverageCount>,
    profile_ruling: OptionalField<CoverageCount>,
}

impl BasisCounts {
    fn values(&self) -> [Option<usize>; 7] {
        [
            self.schema_type.as_ref().copied().map(CoverageCount::value),
            self.schema_const
                .as_ref()
                .copied()
                .map(CoverageCount::value),
            self.schema_enum.as_ref().copied().map(CoverageCount::value),
            self.schema_container_type
                .as_ref()
                .copied()
                .map(CoverageCount::value),
            self.fhir_named_primitive
                .as_ref()
                .copied()
                .map(CoverageCount::value),
            self.fhir_element_name
                .as_ref()
                .copied()
                .map(CoverageCount::value),
            self.profile_ruling
                .as_ref()
                .copied()
                .map(CoverageCount::value),
        ]
    }
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ArtifactAutomaton {
    representation: String,
    start: String,
    states: Vec<ArtifactState>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ArtifactState {
    id: String,
    #[serde(default)]
    keys: OptionalField<Vec<KeyTransition>>,
    #[serde(default)]
    any_index: OptionalField<String>,
    #[serde(default)]
    bindings: OptionalField<Vec<Binding>>,
    #[serde(default)]
    unresolved: OptionalField<Vec<Unresolved>>,
    #[serde(default)]
    structurally_untyped_object: OptionalField<bool>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct KeyTransition {
    key: String,
    to: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Binding {
    #[serde(rename = "jsonKind")]
    json_kind: JsonKind,
    tag: ArtifactTag,
    basis: Vec<BindingBasis>,
    sources: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Unresolved {
    json_kinds: Vec<JsonKind>,
    reason: String,
    sources: Vec<String>,
}

#[derive(Debug)]
struct AutomatonCounts {
    states: usize,
    key_transitions: usize,
    index_transitions: usize,
    resolved_outputs: usize,
    unresolved_output_states: usize,
    structurally_untyped_object_states: usize,
    by_tag: [usize; 9],
    by_basis: [usize; 7],
}

fn validate_artifact(artifact: &Artifact) -> Result<()> {
    if artifact.format != "ROAX-TYPE-MAP/1"
        || artifact.automaton.representation != "structured-path-dfa/1"
        || artifact.automaton.start != "s0"
        || artifact.record_type.is_empty()
        || artifact.schema_version.is_empty()
        || !is_three_part_version(&artifact.type_map_version)
        || artifact.source_schemas.is_empty()
    {
        return Err(Error::InvalidTypeMap(
            "artifact header or metadata is invalid".into(),
        ));
    }

    if let Some(parent_id) = artifact.parent_type_map_id.as_ref() {
        if !is_sha256_id(parent_id) {
            return Err(Error::InvalidTypeMap(
                "parentTypeMapId is not a SHA-256 content ID".into(),
            ));
        }
    }

    let is_child = artifact.parent_type_map_id.is_some();
    match (&artifact.scope, is_child) {
        (ArtifactScope::Profile, false) if artifact.added_selectors.is_empty() => {}
        (ArtifactScope::Issuers { issuer_ids }, true)
            if nonempty_unique(issuer_ids) && !artifact.added_selectors.is_empty() => {}
        _ => {
            return Err(Error::InvalidTypeMap(
                "parent, scope, and addedSelectors conditional is invalid".into(),
            ))
        }
    }

    let source_ids = source_ids(&artifact.source_schemas)?;
    let counts = validate_states(&artifact.automaton.states, &source_ids)?;
    validate_extension_points(&artifact.extension_points, &artifact.automaton.states)?;
    validate_selectors(&artifact.added_selectors, &source_ids)?;
    validate_coverage(&artifact.coverage, &counts)?;
    Ok(())
}

fn source_ids(sources: &[SourceSchema]) -> Result<HashSet<String>> {
    let mut ids = HashSet::new();
    let mut unique_sources = HashSet::new();
    for source in sources {
        if !unique_sources.insert(source) {
            return Err(Error::InvalidTypeMap("duplicate sourceSchema".into()));
        }
        let id = source.source_id();
        if id.is_empty() || id.contains('#') {
            return Err(Error::InvalidTypeMap("invalid sourceId".into()));
        }
        if !ids.insert(id.to_owned()) {
            return Err(Error::InvalidTypeMap("duplicate sourceId".into()));
        }
        match source {
            SourceSchema::Git {
                repository_uri,
                path,
                commit,
                ..
            } => {
                if !is_absolute_uri(repository_uri)
                    || !is_relative_source_path(path)
                    || !is_lower_hex(commit, 40)
                {
                    return Err(Error::InvalidTypeMap("invalid git sourceSchema".into()));
                }
            }
            SourceSchema::Content { uri, digest, .. } => {
                if !is_absolute_uri(uri) || !is_sha256_id(digest) {
                    return Err(Error::InvalidTypeMap("invalid content sourceSchema".into()));
                }
            }
        }
    }
    Ok(ids)
}

fn validate_states(
    states: &[ArtifactState],
    source_ids: &HashSet<String>,
) -> Result<AutomatonCounts> {
    if states.is_empty() {
        return Err(Error::InvalidTypeMap("automaton has no states".into()));
    }
    let mut counts = AutomatonCounts {
        states: states.len(),
        key_transitions: 0,
        index_transitions: 0,
        resolved_outputs: 0,
        unresolved_output_states: 0,
        structurally_untyped_object_states: 0,
        by_tag: [0; 9],
        by_basis: [0; 7],
    };
    let mut discovered = vec![false; states.len()];
    discovered[0] = true;
    let mut next_canonical_state = 1;

    for (index, state) in states.iter().enumerate() {
        if state.id != format!("s{index}") {
            return Err(Error::InvalidTypeMap(
                "state IDs must be contiguous and ordered".into(),
            ));
        }
        if state.structurally_untyped_object.as_ref() == Some(&false) {
            return Err(Error::InvalidTypeMap(
                "structurallyUntypedObject may only be true".into(),
            ));
        }
        if state.structurally_untyped_object.as_ref() == Some(&true) {
            counts.structurally_untyped_object_states += 1;
        }

        let mut last_key: Option<&[u8]> = None;
        let mut key_set = HashSet::new();
        let keys = state.keys.as_deref().unwrap_or(&[]);
        if state.keys.as_ref().is_some_and(Vec::is_empty) {
            return Err(Error::InvalidTypeMap(
                "empty keys arrays must be omitted".into(),
            ));
        }
        for transition in keys {
            if transition.key.nfc().ne(transition.key.chars()) {
                return Err(Error::InvalidTypeMap("transition key is not NFC".into()));
            }
            if !key_set.insert(&transition.key) {
                return Err(Error::InvalidTypeMap("duplicate KEY transition".into()));
            }
            if last_key.is_some_and(|previous| previous >= transition.key.as_bytes()) {
                return Err(Error::InvalidTypeMap(
                    "KEY transitions are not in UTF-8 byte order".into(),
                ));
            }
            last_key = Some(transition.key.as_bytes());
            parse_state_id(&transition.to, states.len())?;
            counts.key_transitions += 1;
        }
        if let Some(target) = state.any_index.as_ref() {
            parse_state_id(target, states.len())?;
            counts.index_transitions += 1;
        }
        for target in keys
            .iter()
            .map(|transition| transition.to.as_str())
            .chain(state.any_index.as_deref())
        {
            let target = parse_state_id(target, states.len())?;
            if !discovered[target] {
                if target != next_canonical_state {
                    return Err(Error::InvalidTypeMap(
                        "DFA state numbering is not canonical breadth-first order".into(),
                    ));
                }
                discovered[target] = true;
                next_canonical_state += 1;
            }
        }

        let mut binding_kinds = HashSet::new();
        let bindings = state.bindings.as_deref().unwrap_or(&[]);
        if state.bindings.as_ref().is_some_and(Vec::is_empty) {
            return Err(Error::InvalidTypeMap(
                "empty bindings arrays must be omitted".into(),
            ));
        }
        let mut last_binding_kind = None;
        for binding in bindings {
            let kind_name = json_kind_name(binding.json_kind);
            if last_binding_kind.is_some_and(|previous| previous >= kind_name.as_bytes()) {
                return Err(Error::InvalidTypeMap(
                    "bindings are not in JSON-kind order".into(),
                ));
            }
            last_binding_kind = Some(kind_name.as_bytes());
            if !binding_kinds.insert(binding.json_kind) {
                return Err(Error::InvalidTypeMap("duplicate binding kind".into()));
            }
            if binding.basis.is_empty() || binding.sources.is_empty() {
                return Err(Error::InvalidTypeMap(
                    "binding lacks basis or sources".into(),
                ));
            }
            validate_sorted_source_references(&binding.sources, source_ids, false)?;
            validate_sorted_basis(&binding.basis)?;
            let tag = TypeTag::try_from(binding.tag.value())?;
            if tag == TypeTag::BlobRef {
                return Err(Error::BlobRefNotSelectable);
            }
            if !tag_matches_kind(tag, binding.json_kind) {
                return Err(Error::InvalidTypeMap(
                    "binding tag is incompatible with observed kind".into(),
                ));
            }
            counts.resolved_outputs += 1;
            counts.by_tag[usize::from(binding.tag.value())] += 1;
            for basis in &binding.basis {
                counts.by_basis[basis.index()] += 1;
            }
        }

        let unresolved = state.unresolved.as_deref().unwrap_or(&[]);
        if state.unresolved.as_ref().is_some_and(Vec::is_empty) {
            return Err(Error::InvalidTypeMap(
                "empty unresolved arrays must be omitted".into(),
            ));
        }
        if !unresolved.is_empty() {
            counts.unresolved_output_states += 1;
        }
        let mut last_unresolved_key: Option<String> = None;
        for row in unresolved {
            if row.json_kinds.is_empty() || row.reason.is_empty() {
                return Err(Error::InvalidTypeMap(
                    "unresolved row lacks kinds or reason".into(),
                ));
            }
            let mut last_kind = None;
            for kind in &row.json_kinds {
                let name = json_kind_name(*kind);
                if last_kind.is_some_and(|previous| previous >= name.as_bytes()) {
                    return Err(Error::InvalidTypeMap(
                        "unresolved jsonKinds are not sorted".into(),
                    ));
                }
                last_kind = Some(name.as_bytes());
                if binding_kinds.contains(kind) {
                    return Err(Error::InvalidTypeMap(
                        "binding and unresolved row overlap".into(),
                    ));
                }
            }
            validate_sorted_source_references(&row.sources, source_ids, true)?;
            let key = unresolved_sort_key(row)?;
            if last_unresolved_key
                .as_ref()
                .is_some_and(|previous| previous.as_bytes() >= key.as_bytes())
            {
                return Err(Error::InvalidTypeMap(
                    "unresolved rows are not canonically sorted".into(),
                ));
            }
            last_unresolved_key = Some(key);
        }
    }

    let mut reached = vec![false; states.len()];
    let mut queue = VecDeque::from([0_usize]);
    while let Some(index) = queue.pop_front() {
        if reached[index] {
            continue;
        }
        reached[index] = true;
        for transition in states[index].keys.as_deref().unwrap_or(&[]) {
            queue.push_back(parse_state_id(&transition.to, states.len())?);
        }
        if let Some(target) = states[index].any_index.as_ref() {
            queue.push_back(parse_state_id(target, states.len())?);
        }
    }
    if reached.iter().any(|value| !value) {
        return Err(Error::InvalidTypeMap(
            "automaton contains unreachable states".into(),
        ));
    }
    if discovered.iter().any(|value| !value) {
        return Err(Error::InvalidTypeMap(
            "canonical discovery did not encounter every state".into(),
        ));
    }
    Ok(counts)
}

fn validate_extension_points(points: &[ExtensionPoint], states: &[ArtifactState]) -> Result<()> {
    let mut prefixes = HashSet::new();
    for point in points {
        if point.note.is_empty() {
            return Err(Error::InvalidTypeMap(
                "extension point note is empty".into(),
            ));
        }
        validate_segments(&point.prefix)?;
        if !prefixes.insert(point.prefix.clone()) {
            return Err(Error::InvalidTypeMap(
                "duplicate extension point prefix".into(),
            ));
        }
        if resolve_pattern_state(states, &point.prefix)?.is_none() {
            return Err(Error::InvalidTypeMap(
                "extension point prefix is unreachable".into(),
            ));
        }
    }
    Ok(())
}

fn validate_selectors(selectors: &[SelectorBinding], source_ids: &HashSet<String>) -> Result<()> {
    let mut identities = HashSet::new();
    for selector in selectors {
        if selector.segments.is_empty() {
            return Err(Error::InvalidTypeMap(
                "added selector has no segments".into(),
            ));
        }
        validate_segments(&selector.segments)?;
        validate_tag_kind(selector.tag, selector.json_kind)?;
        if selector.evidence.is_empty() {
            return Err(Error::InvalidTypeMap(
                "added selector has no evidence".into(),
            ));
        }
        let mut evidence = HashSet::new();
        for source_id in &selector.evidence {
            if source_id.is_empty()
                || source_id.contains('#')
                || !source_ids.contains(source_id)
                || !evidence.insert(source_id)
            {
                return Err(Error::InvalidTypeMap(
                    "added selector evidence is invalid".into(),
                ));
            }
        }
        if !identities.insert((selector.segments.clone(), selector.json_kind)) {
            return Err(Error::InvalidTypeMap(
                "duplicate added selector path and kind".into(),
            ));
        }
    }
    Ok(())
}

fn validate_coverage(coverage: &Coverage, counts: &AutomatonCounts) -> Result<()> {
    if coverage.concrete_path_cardinality != "infinite"
        || coverage.states.value() != counts.states
        || coverage.key_transitions.value() != counts.key_transitions
        || coverage.index_transitions.value() != counts.index_transitions
        || coverage.resolved_outputs.value() != counts.resolved_outputs
        || coverage.unresolved_output_states.value() != counts.unresolved_output_states
        || coverage.structurally_untyped_object_states.value()
            != counts.structurally_untyped_object_states
        || coverage.notes.iter().any(String::is_empty)
    {
        return Err(Error::InvalidTypeMap(
            "coverage metadata is invalid or stale".into(),
        ));
    }

    // This source-local count cannot be recomputed from the materialized DFA.
    let _ = coverage.structurally_untyped_object_source_nodes.value();
    if !canonical_counts_match(&coverage.by_tag.values(), &counts.by_tag)
        || !canonical_counts_match(&coverage.by_basis.values(), &counts.by_basis)
    {
        return Err(Error::InvalidTypeMap(
            "coverage count maps are stale or non-canonical".into(),
        ));
    }
    Ok(())
}

fn canonical_counts_match<const N: usize>(
    actual: &[Option<usize>; N],
    expected: &[usize; N],
) -> bool {
    actual
        .iter()
        .zip(expected)
        .all(|(actual, expected)| match *expected {
            0 => actual.is_none(),
            count => *actual == Some(count),
        })
}

fn validate_segments(segments: &[SegmentPattern]) -> Result<()> {
    for segment in segments {
        match segment {
            SegmentPattern::Key(segment) => {
                if segment.key.nfc().ne(segment.key.chars()) {
                    return Err(Error::InvalidTypeMap(
                        "structured segment key is not NFC".into(),
                    ));
                }
            }
            SegmentPattern::AnyIndex(segment) if !segment.any_index => {
                return Err(Error::InvalidTypeMap("anyIndex must be true".into()))
            }
            SegmentPattern::AnyIndex(_) => {}
        }
    }
    Ok(())
}

fn resolve_pattern_state(
    states: &[ArtifactState],
    segments: &[SegmentPattern],
) -> Result<Option<usize>> {
    let mut index = 0;
    for segment in segments {
        let state = &states[index];
        let target =
            match segment {
                SegmentPattern::Key(segment) => state
                    .keys
                    .as_deref()
                    .unwrap_or(&[])
                    .iter()
                    .find_map(|transition| {
                        (transition.key == segment.key).then_some(transition.to.as_str())
                    }),
                SegmentPattern::AnyIndex(_) => state.any_index.as_deref(),
            };
        let Some(target) = target else {
            return Ok(None);
        };
        index = parse_state_id(target, states.len())?;
    }
    Ok(Some(index))
}

fn validate_tag_kind(tag: ArtifactTag, kind: JsonKind) -> Result<()> {
    let tag = TypeTag::try_from(tag.value())?;
    if tag == TypeTag::BlobRef {
        return Err(Error::BlobRefNotSelectable);
    }
    if !tag_matches_kind(tag, kind) {
        return Err(Error::InvalidTypeMap(
            "binding tag is incompatible with observed kind".into(),
        ));
    }
    Ok(())
}

fn validate_sorted_basis(basis: &[BindingBasis]) -> Result<()> {
    let mut last = None;
    for item in basis {
        let name = item.name();
        if last.is_some_and(|previous| previous >= name.as_bytes()) {
            return Err(Error::InvalidTypeMap(
                "binding basis is not a sorted set".into(),
            ));
        }
        last = Some(name.as_bytes());
    }
    Ok(())
}

fn validate_sorted_source_references(
    references: &[String],
    source_ids: &HashSet<String>,
    allow_empty: bool,
) -> Result<()> {
    if !allow_empty && references.is_empty() {
        return Err(Error::InvalidTypeMap("source references are empty".into()));
    }
    let mut last: Option<&[u8]> = None;
    for reference in references {
        if last.is_some_and(|previous| previous >= reference.as_bytes()) {
            return Err(Error::InvalidTypeMap(
                "source references are not a sorted set".into(),
            ));
        }
        last = Some(reference.as_bytes());
        let source_id = source_id_from_reference(reference)
            .ok_or_else(|| Error::InvalidTypeMap("invalid source reference".into()))?;
        if !source_ids.contains(source_id) {
            return Err(Error::InvalidTypeMap(
                "source reference cites an unknown sourceId".into(),
            ));
        }
    }
    Ok(())
}

fn source_id_from_reference(reference: &str) -> Option<&str> {
    let (source_id, fragment) = reference
        .split_once('#')
        .map_or((reference, None), |(source_id, fragment)| {
            (source_id, Some(fragment))
        });
    if source_id.is_empty()
        || source_id.contains('#')
        || fragment.is_some_and(|fragment| !fragment.is_empty() && !fragment.starts_with('/'))
    {
        None
    } else {
        Some(source_id)
    }
}

fn unresolved_sort_key(row: &Unresolved) -> Result<String> {
    let kinds: Vec<&str> = row
        .json_kinds
        .iter()
        .map(|kind| json_kind_name(*kind))
        .collect();
    serde_json::to_string(&(kinds, &row.reason, &row.sources))
        .map_err(|error| Error::InvalidTypeMap(error.to_string()))
}

const fn json_kind_name(kind: JsonKind) -> &'static str {
    match kind {
        JsonKind::String => "string",
        JsonKind::Number => "number",
        JsonKind::Boolean => "boolean",
        JsonKind::Null => "null",
        JsonKind::Object => "object",
        JsonKind::Array => "array",
    }
}

fn nonempty_unique(values: &[String]) -> bool {
    let mut unique = HashSet::new();
    values
        .iter()
        .all(|value| !value.is_empty() && unique.insert(value))
}

fn is_sha256_id(value: &str) -> bool {
    value
        .strip_prefix("sha256:")
        .is_some_and(|digest| is_lower_hex(digest, 64))
}

fn is_lower_hex(value: &str, length: usize) -> bool {
    value.len() == length
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
}

fn is_relative_source_path(value: &str) -> bool {
    !value.is_empty() && !value.starts_with('/') && !value.split('/').any(|part| part == "..")
}

fn is_absolute_uri(value: &str) -> bool {
    !value.is_empty() && url::Url::parse(value).is_ok()
}

fn compile_states(states: &[ArtifactState]) -> Result<Vec<CompiledState>> {
    states
        .iter()
        .map(|state| {
            let keys = state
                .keys
                .as_deref()
                .unwrap_or(&[])
                .iter()
                .map(|transition| {
                    Ok((
                        transition.key.clone(),
                        parse_state_id(&transition.to, states.len())?,
                    ))
                })
                .collect::<Result<HashMap<_, _>>>()?;
            let any_index = state
                .any_index
                .as_deref()
                .map(|id| parse_state_id(id, states.len()))
                .transpose()?;
            let bindings = state
                .bindings
                .as_deref()
                .unwrap_or(&[])
                .iter()
                .map(|binding| Ok((binding.json_kind, TypeTag::try_from(binding.tag.value())?)))
                .collect::<Result<HashMap<_, _>>>()?;
            Ok(CompiledState {
                keys,
                any_index,
                bindings,
            })
        })
        .collect()
}

fn parse_state_id(id: &str, state_count: usize) -> Result<usize> {
    let index = id
        .strip_prefix('s')
        .filter(|digits| {
            !digits.is_empty()
                && digits.bytes().all(|byte| byte.is_ascii_digit())
                && (*digits == "0" || !digits.starts_with('0'))
        })
        .and_then(|digits| digits.parse::<usize>().ok())
        .ok_or_else(|| Error::InvalidTypeMap(format!("invalid state ID {id}")))?;
    if index >= state_count {
        Err(Error::InvalidTypeMap(format!(
            "state target {id} does not exist"
        )))
    } else {
        Ok(index)
    }
}

fn tag_matches_kind(tag: TypeTag, kind: JsonKind) -> bool {
    matches!(
        (tag, kind),
        (TypeTag::Null, JsonKind::Null)
            | (TypeTag::Bool, JsonKind::Boolean)
            | (TypeTag::String | TypeTag::Bytes, JsonKind::String)
            | (TypeTag::Integer | TypeTag::Decimal, JsonKind::Number)
            | (TypeTag::EmptyArray, JsonKind::Array)
            | (TypeTag::EmptyObject, JsonKind::Object)
    )
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

#[cfg(test)]
mod tests {
    use super::content_id;

    #[test]
    fn content_id_is_algorithm_qualified() {
        assert!(content_id(b"{}").starts_with("sha256:"));
        assert_eq!(content_id(b"{}").len(), 71);
    }
}
