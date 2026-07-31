use roax_canon::{
    audit_path, commit_full_copy_with_salts, fold_inclusion_proof_untrusted, generate_salts,
    disclose, issue_full_copy_with_salts, leaf_hash, merkle_tree_hash, parse_envelope_value,
    reserved_leaf_set_for,
    verify_disclosed, verify_full, CommitmentContext,
    Error, HashAlgorithm, Issuer, JsonKind, JsonValue, LeafValue, ParsedEnvelope, Path, Profile,
    ReservedLeafSet, Salt, SaltMap, SchemaValidator, Segment, TypeResolver, TypeTag,
    VerificationPolicy, CANON_VERSION, UNICODE_VERSION,
};
use serde::Deserialize;
use serde_json::Value;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::env;
use std::fmt::Debug;
use std::fs;
use std::path::{Path as FsPath, PathBuf};
use unicode_normalization::UnicodeNormalization;

const CLASS_COUNT: u8 = 20;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct Corpus {
    #[serde(rename = "corpusVersion")]
    version: String,
    canon: String,
    unicode_version: String,
    hash_alg: String,
    vectors: Vectors,
}

/// Every vector group this runner consumes.
///
/// `deny_unknown_fields` is the group guard and is load-bearing rather than tidy. Serde's default
/// is to IGNORE an unknown member, so a corpus that grew a group this file does not read would
/// deserialize cleanly, contribute zero assertions and report the same green it reported before
/// the group existed - the exact defect shape the corpus exists to prevent. With it, adding a
/// group to the corpus file fails this test at parse time until the group is consumed here.
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Vectors {
    encode_path: Vec<Value>,
    encode_value: Vec<Value>,
    reject: Vec<Value>,
    leaf: Vec<Value>,
    tree: Vec<Value>,
    inclusion: Vec<Value>,
    negative_proof: Vec<Value>,
    type_map: Vec<Value>,
    record: Vec<Value>,
    unlinkability: Vec<Value>,
    normalization: Vec<Value>,
    envelope: Vec<Value>,
    round_trip: Vec<Value>,
}

#[derive(Debug, Default)]
struct ClassResult {
    passed: usize,
    failures: Vec<String>,
    skips: Vec<String>,
}

#[derive(Debug, Default)]
struct Report {
    classes: BTreeMap<u8, ClassResult>,
}

impl Report {
    fn pass(&mut self, class: u8) {
        self.classes.entry(class).or_default().passed += 1;
    }

    fn fail(&mut self, class: u8, message: impl Into<String>) {
        self.classes
            .entry(class)
            .or_default()
            .failures
            .push(message.into());
    }

    fn skip(&mut self, class: u8, message: impl Into<String>) {
        self.classes
            .entry(class)
            .or_default()
            .skips
            .push(message.into());
    }

    #[allow(clippy::needless_pass_by_value)]
    fn check<T: Debug + PartialEq>(
        &mut self,
        class: u8,
        name: &str,
        field: &str,
        got: T,
        expected: T,
    ) {
        if got == expected {
            self.pass(class);
        } else {
            self.fail(
                class,
                format!("{name} {field}: got {got:?}, expected {expected:?}"),
            );
        }
    }

    fn finish(mut self) {
        let class_10 = self.classes.entry(10).or_default();
        if class_10.passed == 0 && !class_10.skips.is_empty() {
            class_10.failures.push(
                "class 10 was skipped because no external recovery sample was supplied".into(),
            );
        }
        for class in 1..=CLASS_COUNT {
            let result = self.classes.entry(class).or_default();
            let status =
                if !result.failures.is_empty() && result.passed == 0 && !result.skips.is_empty() {
                    "FAIL - SKIPPED NOT RUN"
                } else if !result.failures.is_empty() {
                    "FAIL"
                } else if result.passed == 0 && !result.skips.is_empty() {
                    "SKIPPED - NOT RUN"
                } else if result.passed == 0 {
                    "NO VECTORS"
                } else if result.skips.is_empty() {
                    "PASS"
                } else {
                    "PASS WITH SKIPS"
                };
            eprintln!(
                "class {class:>2}: {status}, {} assertions, {} failures, {} skipped",
                result.passed,
                result.failures.len(),
                result.skips.len()
            );
            for skip in &result.skips {
                eprintln!("    SKIPPED: {skip}");
            }
            for failure in result.failures.iter().take(12) {
                eprintln!("    FAIL: {failure}");
            }
        }

        let failures: usize = self
            .classes
            .values()
            .map(|result| result.failures.len())
            .sum();
        assert_eq!(
            failures, 0,
            "{failures} conformance failures; see the per-class report above"
        );
    }
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct LegacyMapDocument {
    type_map_version: String,
    record_type: String,
    schema_version: String,
    entries: Vec<LegacyMapEntry>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct LegacyMapEntry {
    pattern: String,
    json_kind: JsonKind,
    tag: u8,
}

#[derive(Clone, Debug)]
enum LegacyPatternSegment {
    Key(String),
    AnyIndex,
    AnyRemainder,
}

#[derive(Clone, Debug)]
struct CompiledLegacyEntry {
    pattern: Vec<LegacyPatternSegment>,
    kind: JsonKind,
    tag: TypeTag,
}

#[derive(Clone, Debug)]
struct LegacyTypeMap {
    record_type: String,
    schema_version: String,
    entries: Vec<CompiledLegacyEntry>,
}

impl LegacyTypeMap {
    fn load(path: &FsPath) -> Result<Self, String> {
        let document: LegacyMapDocument =
            serde_json::from_slice(&fs::read(path).map_err(|error| error.to_string())?)
                .map_err(|error| error.to_string())?;
        if document.type_map_version.is_empty() {
            return Err("legacy type-map version is empty".into());
        }
        let entries = document
            .entries
            .into_iter()
            .map(|entry| {
                Ok(CompiledLegacyEntry {
                    pattern: compile_legacy_pattern(&entry.pattern)?,
                    kind: entry.json_kind,
                    tag: TypeTag::try_from(entry.tag).map_err(|error| error.to_string())?,
                })
            })
            .collect::<Result<Vec<_>, String>>()?;
        Ok(Self {
            record_type: document.record_type,
            schema_version: document.schema_version,
            entries,
        })
    }

    fn select(&self, record_type: &str, schema_version: &str) -> Result<(), Error> {
        if self.record_type == record_type && self.schema_version == schema_version {
            Ok(())
        } else {
            Err(Error::TypeMapIdentityMismatch)
        }
    }
}

impl TypeResolver for LegacyTypeMap {
    fn resolve(&self, path: &Path, kind: JsonKind) -> roax_canon::Result<TypeTag> {
        // The committed 1.0 corpus maps predate map-authorized empty containers.
        // Keeping this compatibility behavior in the adapter lets the library retain
        // the current fail-closed resolver contract.
        match kind {
            JsonKind::Array => return Ok(TypeTag::EmptyArray),
            JsonKind::Object => return Ok(TypeTag::EmptyObject),
            _ => {}
        }

        let mut matches = self.entries.iter().filter(|entry| {
            entry.kind == kind && legacy_pattern_matches(&entry.pattern, path.segments())
        });
        let Some(first) = matches.next() else {
            return Err(Error::UnknownTypeBinding {
                path: path.clone(),
                kind,
            });
        };
        if matches.any(|entry| entry.tag != first.tag) {
            return Err(Error::InvalidTypeMap(
                "legacy display patterns resolve to conflicting tags".into(),
            ));
        }
        Ok(first.tag)
    }
}

fn compile_legacy_pattern(pattern: &str) -> Result<Vec<LegacyPatternSegment>, String> {
    let mut compiled = Vec::new();
    for part in pattern.split('.') {
        if part == "**" {
            compiled.push(LegacyPatternSegment::AnyRemainder);
            continue;
        }
        let mut key = part;
        let mut indexes = 0;
        while let Some(prefix) = key.strip_suffix("[*]") {
            indexes += 1;
            key = prefix;
        }
        if !key.is_empty() {
            // Ruled decision D14a: the lookup matches over NFC-normalized keys, on BOTH
            // sides. The pattern token is normalized once here at compile time and the
            // segment key in `legacy_pattern_matches`.
            compiled.push(LegacyPatternSegment::Key(key.nfc().collect()));
        }
        for _ in 0..indexes {
            compiled.push(LegacyPatternSegment::AnyIndex);
        }
    }
    if compiled.is_empty() {
        Err(format!("empty legacy pattern {pattern:?}"))
    } else {
        Ok(compiled)
    }
}

fn legacy_pattern_matches(pattern: &[LegacyPatternSegment], path: &[Segment]) -> bool {
    let mut path_index = 0;
    for part in pattern {
        match part {
            LegacyPatternSegment::AnyRemainder => return path_index < path.len(),
            LegacyPatternSegment::Key(expected) => {
                let Some(Segment::Key(actual)) = path.get(path_index) else {
                    return false;
                };
                // Ruled decision D14a. The pattern token is already NFC, so only the
                // segment key is normalized here.
                if actual.nfc().ne(expected.chars()) {
                    return false;
                }
                path_index += 1;
            }
            LegacyPatternSegment::AnyIndex => {
                if !matches!(path.get(path_index), Some(Segment::Index(_))) {
                    return false;
                }
                path_index += 1;
            }
        }
    }
    path_index == path.len()
}

#[derive(Clone, Debug, Default)]
struct DisclosureResolver {
    tags: HashMap<(Vec<u8>, JsonKind), TypeTag>,
}

impl DisclosureResolver {
    fn insert(&mut self, path: &Path, kind: JsonKind, tag: TypeTag) -> Result<(), String> {
        let key = (path.encode().map_err(|error| error.to_string())?, kind);
        if self.tags.insert(key, tag).is_some() {
            return Err("duplicate disclosure resolver binding".into());
        }
        Ok(())
    }
}

impl TypeResolver for DisclosureResolver {
    fn resolve(&self, path: &Path, kind: JsonKind) -> roax_canon::Result<TypeTag> {
        self.tags
            .get(&(path.encode()?, kind))
            .copied()
            .ok_or_else(|| Error::UnknownTypeBinding {
                path: path.clone(),
                kind,
            })
    }
}

struct LegacyProfile<'a> {
    record_type: String,
    schema_version: String,
    resolver: &'a dyn TypeResolver,
    floor: Vec<Path>,
}

impl<'a> LegacyProfile<'a> {
    fn new(map: &'a LegacyTypeMap) -> Self {
        Self {
            record_type: map.record_type.clone(),
            schema_version: map.schema_version.clone(),
            resolver: map,
            floor: Vec::new(),
        }
    }
}

impl SchemaValidator for LegacyProfile<'_> {
    fn validate_record(&self, _record: &JsonValue) -> roax_canon::Result<()> {
        Ok(())
    }
}

impl Profile for LegacyProfile<'_> {
    fn record_type(&self) -> &str {
        &self.record_type
    }

    fn validate_context(&self, context: &CommitmentContext) -> roax_canon::Result<()> {
        if context.schema_version != self.schema_version {
            return Err(Error::TypeMapIdentityMismatch);
        }
        // BOTH reserved-leaf generations are accepted here, because the committed corpus now
        // carries both: 54 fixtures predate the section 4.2 binding and carry no `typeMap`, and
        // the type-map binding family carries the member and commits `roax.typeMap.id`.
        //
        // WHAT THIS HARNESS PROFILE DOES NOT DO, stated rather than implied: it does not fetch
        // the artifact `typeMap.id` names, does not reproduce its content ID, and does not compare
        // the artifact's own recordType or typeMapVersion. It cannot - the corpus identifiers are
        // corpus-authored placeholders in the right FORM addressing no published artifact, which
        // `corpus/tools/envelope_fixtures.py` says outright, and no artifact exists for the
        // display-pattern maps under `corpus/type-maps/` at all. So what these vectors assert is
        // the one thing a single envelope can evidence: the identifier a copy presents is the
        // identifier its root commits.
        match (context.reserved_leaf_set, &context.type_map) {
            (ReservedLeafSet::EnvelopeV1, None) | (ReservedLeafSet::EnvelopeV2, Some(_)) => Ok(()),
            _ => Err(Error::TypeMapIdentityMismatch),
        }
    }

    fn resolver(&self) -> &dyn TypeResolver {
        self.resolver
    }

    fn minimum_disclosure_paths(&self) -> Vec<Path> {
        self.floor.clone()
    }
}

fn repository_root() -> PathBuf {
    FsPath::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("the Rust crate must be directly beneath the repository root")
        .to_owned()
}

fn read_corpus(root: &FsPath) -> Corpus {
    serde_json::from_slice(
        &fs::read(root.join("corpus/conformance-corpus-1.0.json"))
            .expect("committed conformance corpus"),
    )
    .expect("valid conformance corpus")
}

fn load_legacy_maps(root: &FsPath) -> HashMap<String, LegacyTypeMap> {
    let mut maps = HashMap::new();
    for entry in fs::read_dir(root.join("corpus/type-maps")).expect("legacy corpus type maps") {
        let path = entry.expect("type-map directory entry").path();
        if path
            .extension()
            .is_some_and(|extension| extension == "json")
        {
            let map = LegacyTypeMap::load(&path)
                .unwrap_or_else(|error| panic!("{}: {error}", path.display()));
            assert!(
                maps.insert(map.record_type.clone(), map).is_none(),
                "duplicate legacy record type"
            );
        }
    }
    maps
}

fn field<'a>(value: &'a Value, key: &str) -> &'a Value {
    value
        .get(key)
        .unwrap_or_else(|| panic!("missing field {key} in {value}"))
}

fn optional_field<'a>(value: &'a Value, key: &str) -> Option<&'a Value> {
    value.get(key)
}

fn string_field<'a>(value: &'a Value, key: &str) -> &'a str {
    field(value, key)
        .as_str()
        .unwrap_or_else(|| panic!("{key} is not a string in {value}"))
}

fn integer_field(value: &Value, key: &str) -> u64 {
    field(value, key)
        .as_u64()
        .unwrap_or_else(|| panic!("{key} is not an unsigned integer in {value}"))
}

fn bool_field(value: &Value, key: &str) -> bool {
    field(value, key)
        .as_bool()
        .unwrap_or_else(|| panic!("{key} is not a boolean in {value}"))
}

fn vector_identity(value: &Value) -> (u8, &str) {
    (
        u8::try_from(integer_field(value, "class")).expect("class fits in u8"),
        string_field(value, "name"),
    )
}

fn parse_hash(value: &str) -> Result<[u8; 32], String> {
    let bytes = hex::decode(value).map_err(|error| error.to_string())?;
    bytes
        .try_into()
        .map_err(|_| format!("hash is not 32 bytes: {value}"))
}

fn path_from_segments(value: &Value) -> Result<Path, String> {
    let array = value
        .as_array()
        .ok_or_else(|| "segments must be an array".to_owned())?;
    let mut segments = Vec::with_capacity(array.len());
    for segment in array {
        if let Some(key) = segment.get("key") {
            segments.push(Segment::Key(
                key.as_str()
                    .ok_or_else(|| "segment key must be a string".to_owned())?
                    .to_owned(),
            ));
        } else if let Some(index) = segment.get("index") {
            let raw = index
                .as_u64()
                .ok_or_else(|| "segment index must be an unsigned integer".to_owned())?;
            segments.push(Segment::Index(
                u32::try_from(raw).map_err(|_| "index-out-of-32-bit-range".to_owned())?,
            ));
        } else {
            return Err("segment-malformed".into());
        }
    }
    Ok(Path::from_segments(segments))
}

fn tag(value: u64) -> Result<TypeTag, String> {
    TypeTag::try_from(u8::try_from(value).map_err(|error| error.to_string())?)
        .map_err(|error| error.to_string())
}

fn json_kind(value: &str) -> Result<JsonKind, String> {
    match value {
        "string" => Ok(JsonKind::String),
        "number" => Ok(JsonKind::Number),
        "boolean" => Ok(JsonKind::Boolean),
        "null" => Ok(JsonKind::Null),
        "object" => Ok(JsonKind::Object),
        "array" => Ok(JsonKind::Array),
        other => Err(format!("unknown JSON kind {other}")),
    }
}

fn leaf_value_from_carrier(tag: TypeTag, value: Option<&Value>) -> Result<LeafValue, String> {
    match tag {
        TypeTag::Null if value.is_none() => Ok(LeafValue::Null),
        TypeTag::EmptyArray if value.is_none() => Ok(LeafValue::EmptyArray),
        TypeTag::EmptyObject if value.is_none() => Ok(LeafValue::EmptyObject),
        TypeTag::Bool => value
            .and_then(Value::as_bool)
            .map(LeafValue::Bool)
            .ok_or_else(|| "BOOL carrier must be a boolean".into()),
        TypeTag::String => value
            .and_then(Value::as_str)
            .map(|text| LeafValue::String(text.to_owned()))
            .ok_or_else(|| "STRING carrier must be a string".into()),
        TypeTag::Integer => value
            .and_then(Value::as_str)
            .map(|text| LeafValue::Integer(text.to_owned()))
            .ok_or_else(|| "INTEGER carrier must be a string".into()),
        TypeTag::Decimal => value
            .and_then(Value::as_str)
            .map(|text| LeafValue::Decimal(text.to_owned()))
            .ok_or_else(|| "DECIMAL carrier must be a string".into()),
        TypeTag::Bytes => {
            let text = value
                .and_then(Value::as_str)
                .ok_or_else(|| "BYTES carrier must be lowercase hex".to_owned())?;
            let bytes = hex::decode(text).map_err(|error| error.to_string())?;
            if hex::encode(&bytes) != text {
                return Err("BYTES carrier must be canonical lowercase hex".into());
            }
            Ok(LeafValue::Bytes(bytes))
        }
        TypeTag::BlobRef => {
            let carrier = json_value_from_serde(
                value.ok_or_else(|| "BLOB_REF carrier is absent".to_owned())?,
            )?;
            LeafValue::from_disclosure_carrier(TypeTag::BlobRef, Some(&carrier))
                .map_err(|error| error.to_string())
        }
        _ => Err("carrier does not match tag".into()),
    }
}

fn json_value_from_serde(value: &Value) -> Result<JsonValue, String> {
    match value {
        Value::Null => Ok(JsonValue::Null),
        Value::Bool(value) => Ok(JsonValue::Bool(*value)),
        Value::String(value) => Ok(JsonValue::String(value.clone())),
        Value::Number(value) => Ok(JsonValue::Number(value.to_string())),
        Value::Array(values) => values
            .iter()
            .map(json_value_from_serde)
            .collect::<Result<Vec<_>, _>>()
            .map(JsonValue::Array),
        Value::Object(entries) => entries
            .iter()
            .map(|(key, value)| Ok((key.clone(), json_value_from_serde(value)?)))
            .collect::<Result<Vec<_>, String>>()
            .map(JsonValue::Object),
    }
}

fn observed_kind_from_tag(tag: TypeTag) -> Result<JsonKind, Error> {
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

fn v1_context(
    record_type: &str,
    schema_version: &str,
    record_id: &str,
    issuer_id: &str,
    issuer_key_id: Option<&str>,
) -> CommitmentContext {
    CommitmentContext {
        hash_algorithm: HashAlgorithm::Sha256,
        reserved_leaf_set: ReservedLeafSet::EnvelopeV1,
        record_type: record_type.to_owned(),
        schema_version: schema_version.to_owned(),
        type_map: None,
        record_id: record_id.to_owned(),
        issuer: Issuer {
            id: issuer_id.to_owned(),
            key_id: issuer_key_id.map(str::to_owned),
        },
    }
}

fn reserved_paths(context: &CommitmentContext) -> Vec<Path> {
    let mut keys = vec![
        "roax.recordType",
        "roax.schemaVersion",
        "roax.recordId",
        "roax.issuer.id",
    ];
    if context.issuer.key_id.is_some() {
        keys.push("roax.issuer.keyId");
    }
    keys.into_iter()
        .map(|key| Path::from_segments(vec![Segment::Key(key.into())]))
        .collect()
}

fn flatten_paths(value: &JsonValue, path: &Path, output: &mut Vec<Path>) -> Result<(), String> {
    match value {
        JsonValue::Object(entries) if !entries.is_empty() => {
            for (key, child) in entries {
                flatten_paths(child, &path.with_key(key.clone()), output)?;
            }
        }
        JsonValue::Array(values) if !values.is_empty() => {
            for (index, child) in values.iter().enumerate() {
                let index =
                    u32::try_from(index).map_err(|_| "index-out-of-32-bit-range".to_owned())?;
                flatten_paths(child, &path.with_index(index), output)?;
            }
        }
        _ => output.push(path.clone()),
    }
    Ok(())
}

fn ordered_v1_paths(record: &JsonValue, context: &CommitmentContext) -> Result<Vec<Path>, String> {
    let mut paths = Vec::new();
    flatten_paths(record, &Path::new(), &mut paths)?;
    paths.extend(reserved_paths(context));
    paths.sort_by_key(|path| path.encode().expect("corpus paths are encodable"));
    let mut encoded = HashSet::new();
    for path in &paths {
        if !encoded.insert(
            path.encode()
                .map_err(|error| canonical_rejection_reason(&error, None).to_owned())?,
        ) {
            return Err("duplicate-normalized-path".into());
        }
    }
    Ok(paths)
}

fn salt_map_from_document(
    document: &Value,
    declared_pairing: &str,
    ordered_paths: &[Path],
) -> Result<SaltMap, String> {
    let actual_pairing = string_field(document, "pairing");
    if actual_pairing != declared_pairing {
        return Err(format!(
            "salt pairing is {actual_pairing}, vector declares {declared_pairing}"
        ));
    }
    let salts = field(document, "salts")
        .as_array()
        .ok_or_else(|| "salts must be an array".to_owned())?;
    let mut map = SaltMap::new();
    match declared_pairing {
        "path" => {
            for entry in salts {
                let path = path_from_segments(field(entry, "segments"))?;
                let salt = Salt::from_hex(string_field(entry, "salt"))
                    .map_err(|error| error.to_string())?;
                map.insert(path, salt).map_err(|error| error.to_string())?;
            }
        }
        "positional" => {
            if salts.len() != ordered_paths.len() {
                return Err(format!(
                    "{} positional salts for {} leaves",
                    salts.len(),
                    ordered_paths.len()
                ));
            }
            for (path, salt) in ordered_paths.iter().zip(salts) {
                let salt_text = salt
                    .as_str()
                    .ok_or_else(|| "positional salt must be a string".to_owned())?;
                map.insert(
                    path.clone(),
                    Salt::from_hex(salt_text).map_err(|error| error.to_string())?,
                )
                .map_err(|error| error.to_string())?;
            }
        }
        other => return Err(format!("unsupported salt pairing {other}")),
    }
    Ok(map)
}

fn profile_floor(record_type: &str) -> Option<Vec<Path>> {
    let keys: Vec<Vec<&str>> = match record_type {
        "hl7.fhir.bundle" => vec![vec!["resourceType"]],
        "sg.gov.moh.pdt-healthcert" => {
            vec![vec!["version"], vec!["type"], vec!["validFrom"]]
        }
        "sg.gov.moh.recovery-healthcert" => vec![
            vec!["version"],
            vec!["type"],
            vec!["validFrom"],
            vec!["validUntil"],
        ],
        "sg.gov.moh.vaccination-healthcert" => {
            vec![vec!["validFrom"], vec!["notarisationMetadata", "reference"]]
        }
        "org.roax.corpus.synthetic" => vec![vec!["marker"]],
        _ => return None,
    };
    Some(
        keys.into_iter()
            .map(|keys| {
                Path::from_segments(
                    keys.into_iter()
                        .map(|key| Segment::Key(key.to_owned()))
                        .collect(),
                )
            })
            .collect(),
    )
}

fn legacy_envelope_reason(error: &Error) -> &'static str {
    match error {
        Error::ReservedNamespaceCollision => "reserved-namespace",
        Error::MissingSalt(_) => "salt-missing-for-leaf",
        Error::DuplicateSaltPath => "salts-duplicate-path",
        Error::ExtraSaltPath => "salt-not-for-leaf",
        Error::LeafCountMismatch => "leaf-count-mismatch",
        Error::RootMismatch => "root-mismatch",
        Error::InvalidInclusionProof | Error::InvalidLeafIndex => "inclusion-proof-failed",
        Error::DuplicateDisclosurePath => "disclosed-leaf-duplicate-path",
        Error::MinimumDisclosureFloor => "minimum-disclosure-floor",
        // DECLARED EQUIVALENCE on the second variant, and it is narrow. `reserved_leaf_set_for`
        // selects the 2.0 generation only for a copy that COMMITS `roax.typeMap.id`, so reaching
        // `TypeMapNotNamed` through this runner means exactly one thing: the root commits the
        // identifier and the presenter supplied no outer member. The reference implementations
        // call that `outer-identity-mismatch`, because for them absence on one side IS the
        // disagreement; this crate refuses it one layer earlier, at the generation gate, and keeps
        // a distinct variant so that a verifier which REQUIRES the binding on a copy naming none
        // on either side is not told a disagreement occurred. `corpus/README.md` owns the table of
        // such divergences. The two arms share a body here and nowhere else.
        Error::OuterIdentityMismatch | Error::TypeMapNotNamed => "outer-identity-mismatch",
        Error::InvalidValueCarrier => "disclosed-leaf-value-carrier",
        Error::BlobRefNotSelectable => "blob-ref-unbound",
        Error::UnknownTypeBinding { .. } => "type-map-fail-closed",
        Error::UnsupportedAlgorithm(_) => "hash-alg-not-allowed",
        _ => error.code(),
    }
}

fn verify_legacy_envelope(bytes: &[u8], maps: &HashMap<String, LegacyTypeMap>) -> (bool, String) {
    // The generation is chosen by `reserved_leaf_set_for`, from what the envelope COMMITS, and
    // never from the outer `typeMap` member alone. Choosing on the member hands the choice to the
    // party the binding constrains: a holder deletes it, withholds the leaf, and a verifier
    // reading only the member drops to the 1.0 generation where `roax.typeMap.id` is not in the
    // floor and nothing asks for it. The corpus fixture
    // `identity-outer-type-map-member-stripped` is exactly that copy.
    //
    // Passing `EnvelopeV1` unconditionally, which this runner used to do, was correct only while
    // no committed fixture carried a `typeMap` member - which was itself the corpus gap the
    // type-map binding vectors were added to close.
    let value = match JsonValue::from_slice(bytes) {
        Ok(value) => value,
        Err(error) => return (false, legacy_envelope_reason(&error).to_owned()),
    };
    let parsed = match parse_envelope_value(&value, reserved_leaf_set_for(&value)) {
        Ok(parsed) => parsed,
        Err(error) => return (false, legacy_envelope_reason(&error).to_owned()),
    };
    let context = match &parsed {
        ParsedEnvelope::Full(copy) => copy.context(),
        ParsedEnvelope::Disclosed(disclosure) => disclosure.context(),
    };
    let Some(floor) = profile_floor(&context.record_type) else {
        return (false, "profile-unknown".into());
    };
    let result = match parsed {
        ParsedEnvelope::Full(copy) => {
            if u64::try_from(copy.salts().len()).ok() == Some(copy.leaf_count()) {
                let map = maps
                    .get(&copy.context().record_type)
                    .ok_or_else(|| "type-map-missing".to_owned());
                map.and_then(|map| {
                    let profile = LegacyProfile {
                        record_type: copy.context().record_type.clone(),
                        schema_version: copy.context().schema_version.clone(),
                        resolver: map,
                        floor,
                    };
                    let policy = VerificationPolicy {
                        anchored_root: copy.root(),
                        anchored_hash_algorithm: HashAlgorithm::Sha256,
                    };
                    verify_full(&copy, &profile, policy)
                        .map(|_| ())
                        .map_err(|error| legacy_envelope_reason(&error).to_owned())
                })
            } else {
                Err("salts-length-not-leaf-count".into())
            }
        }
        ParsedEnvelope::Disclosed(disclosure) => {
            let mut resolver = DisclosureResolver::default();
            let build = disclosure.leaves().iter().try_for_each(|leaf| {
                if matches!(
                    leaf.path().segments(),
                    [Segment::Key(key)] if key.starts_with("roax.")
                ) {
                    Ok(())
                } else {
                    resolver.insert(
                        leaf.path(),
                        observed_kind_from_tag(leaf.tag()).map_err(|error| error.to_string())?,
                        leaf.tag(),
                    )
                }
            });
            build.and_then(|()| {
                let profile = LegacyProfile {
                    record_type: disclosure.context().record_type.clone(),
                    schema_version: disclosure.context().schema_version.clone(),
                    resolver: &resolver,
                    floor,
                };
                let policy = VerificationPolicy {
                    anchored_root: disclosure.root(),
                    anchored_hash_algorithm: HashAlgorithm::Sha256,
                };
                verify_disclosed(&disclosure, &profile, policy)
                    .map_err(|error| legacy_envelope_reason(&error).to_owned())
            })
        }
    };
    match result {
        Ok(()) => (true, "ok".into()),
        Err(reason) => (false, reason),
    }
}

fn canonical_rejection_reason(error: &Error, raw_json: Option<&str>) -> &'static str {
    match error {
        Error::NumberExpansionLimit => "digit-bound-exceeded",
        Error::InvalidDecimal => "decimal-grammar",
        Error::InvalidInteger => "integer-grammar",
        Error::InvalidJson { .. }
            if raw_json.is_some_and(|raw| raw.contains("NaN") || raw.contains("Infinity")) =>
        {
            "non-finite-number"
        }
        Error::DuplicateKey { .. } => "duplicate-key",
        Error::UnpairedSurrogate => "unpaired-surrogate",
        Error::ReservedNamespaceCollision => "reserved-namespace",
        // Two conditions this crate spells differently from the reference implementations, both
        // surfaced by the record-shaped reject vectors of the 2026-07-30 type rulings, which are
        // the first vectors to reach either one. `corpus/README.md` records all the spellings.
        //
        // The mappings are DECLARED here rather than absorbed into the comparison, so a
        // rejection for a DIFFERENT reason still fails. This function already exists to
        // reconcile this crate's names with the corpus's reference spellings.
        //
        // Fail-closed: this crate and the TypeScript library say "type-map-fail-closed", the
        // references say "type-map-uncovered-path", the Python library says "type-unresolved".
        Error::UnknownTypeBinding { .. } => "type-map-uncovered-path",
        // Non-canonical base64: this crate says "invalid-base64" while the references, the
        // TypeScript library and the Python library all say "base64-not-canonical".
        Error::InvalidBase64 => "base64-not-canonical",
        _ => error.code(),
    }
}

fn validate_utf16_escape(value: &Value) -> Result<String, String> {
    let units = field(value, "$utf16")
        .as_array()
        .ok_or_else(|| "$utf16 must be an array".to_owned())?
        .iter()
        .map(|unit| {
            let unit = unit
                .as_str()
                .ok_or_else(|| "$utf16 unit must be a string".to_owned())?;
            u16::from_str_radix(unit, 16).map_err(|_| "$utf16 unit is not hexadecimal".to_owned())
        })
        .collect::<Result<Vec<_>, _>>()?;
    std::char::decode_utf16(units)
        .collect::<Result<String, _>>()
        .map_err(|_| "unpaired-surrogate".to_owned())
}

fn reject_path_input(value: &Value) -> Result<(), String> {
    let segments = field(value, "$segments")
        .as_array()
        .ok_or_else(|| "$segments must be an array".to_owned())?;
    let mut decoded = Vec::with_capacity(segments.len());
    for segment in segments {
        if let Some(key) = segment.get("key") {
            let key = if key.get("$utf16").is_some() {
                validate_utf16_escape(key)?
            } else {
                key.as_str()
                    .ok_or_else(|| "segment key must be a string".to_owned())?
                    .to_owned()
            };
            decoded.push(Segment::Key(key));
        } else if let Some(index) = segment.get("index") {
            let index = index
                .as_u64()
                .ok_or_else(|| "segment index must be an unsigned integer".to_owned())?;
            decoded.push(Segment::Index(
                u32::try_from(index).map_err(|_| "index-out-of-32-bit-range".to_owned())?,
            ));
        } else {
            return Err("segment-malformed".into());
        }
    }
    if let Some(Segment::Key(key)) = decoded.first() {
        if key.nfc().collect::<String>().starts_with("roax.") {
            return Err("reserved-namespace".into());
        }
    }
    Path::from_segments(decoded)
        .encode()
        .map(|_| ())
        .map_err(|error| canonical_rejection_reason(&error, None).to_owned())
}

fn run_reject_vector(vector: &Value, maps: &HashMap<String, LegacyTypeMap>) -> Result<(), String> {
    let input = field(vector, "input");
    // A `recordType` makes this a WHOLE-RECORD rejection: read the record and commit it through
    // that profile's COMMITTED map. The map must be the committed one rather than a permissive
    // stand-in, because several of these vectors assert that a path has NO binding for an
    // observed kind, which a resolve-everything map makes unfalsifiable.
    if let Some(record_type) = vector.get("recordType").and_then(Value::as_str) {
        let raw = input
            .get("$jsonText")
            .and_then(Value::as_str)
            .ok_or_else(|| "a record-shaped reject vector carries $jsonText".to_owned())?;
        let map = maps
            .get(record_type)
            .ok_or_else(|| format!("no committed type map for {record_type}"))?;
        let record = JsonValue::from_str(raw)
            .map_err(|error| canonical_rejection_reason(&error, Some(raw)).to_owned())?;
        // The identity below is arbitrary and the vector carries none, because every one of
        // these rejections happens at a RECORD leaf: no reserved leaf is involved, and the
        // rejection is reached before a tree exists.
        let context = v1_context(
            record_type,
            &map.schema_version,
            "urn:uuid:00000000-0000-4000-8000-000000000000",
            "did:web:corpus.roax.invalid",
            None,
        );
        // `ordered_v1_paths` reports its own canonical reason code, and a duplicate encoded path
        // or an out-of-range index is NOT a fail-closed type binding: the declared comparison
        // only holds if each of those reaches the vector under its own name.
        let ordered = ordered_v1_paths(&record, &context)?;
        let salts = generate_salts(&ordered).map_err(|error| error.to_string())?;
        return commit_full_copy_with_salts(&record, &context, &LegacyProfile::new(map), &salts)
            .map(|_| ())
            .map_err(|error| canonical_rejection_reason(&error, None).to_owned());
    }
    if input.get("$segments").is_some() {
        return reject_path_input(input);
    }
    if let Some(raw) = input.get("$jsonText").and_then(Value::as_str) {
        return JsonValue::from_str(raw)
            .map(|_| ())
            .map_err(|error| canonical_rejection_reason(&error, Some(raw)).to_owned());
    }
    if input.get("$utf16").is_some() {
        validate_utf16_escape(input)?;
        return Ok(());
    }
    let selected_tag = tag(integer_field(vector, "tag"))?;
    let value = leaf_value_from_carrier(selected_tag, Some(input))?;
    value
        .encode()
        .map(|_| ())
        .map_err(|error| canonical_rejection_reason(&error, None).to_owned())
}

fn split_point(value: usize) -> usize {
    assert!(value > 1);
    if value.is_power_of_two() {
        value / 2
    } else {
        1_usize << (usize::BITS - 1 - value.leading_zeros())
    }
}

fn flip_last_byte(mut value: [u8; 32]) -> [u8; 32] {
    value[31] ^= 1;
    value
}

type NegativeProofFields = ([u8; 32], Vec<[u8; 32]>, [u8; 32]);

fn negative_proof_fields(
    vector: &Value,
    leaves: &[[u8; 32]],
) -> Result<NegativeProofFields, String> {
    let attack = string_field(vector, "attack");
    let vector_index =
        usize::try_from(integer_field(vector, "index")).map_err(|error| error.to_string())?;
    let root = merkle_tree_hash(leaves);
    if attack == "index-out-of-range" {
        return Ok((
            leaves[0],
            audit_path(leaves, 0).map_err(|error| error.to_string())?,
            root,
        ));
    }
    if attack == "internal-node-as-leaf" {
        let split = split_point(leaves.len());
        return Ok((
            merkle_tree_hash(&leaves[..split]),
            vec![merkle_tree_hash(&leaves[split..])],
            root,
        ));
    }
    let mut proof = audit_path(leaves, vector_index).map_err(|error| error.to_string())?;
    let mut claimed_root = root;
    match attack {
        "wrong-root" => claimed_root = flip_last_byte(root),
        "flipped-sibling" => {
            let first = proof
                .first_mut()
                .ok_or_else(|| "cannot flip an empty audit path".to_owned())?;
            *first = flip_last_byte(*first);
        }
        "truncated-audit-path" => {
            proof.pop();
        }
        "extended-audit-path" => proof.push(root),
        other => return Err(format!("unsupported negative proof attack {other}")),
    }
    Ok((leaves[vector_index], proof, claimed_root))
}

fn load_record_for_vector(root: &FsPath, vector: &Value) -> Result<Option<JsonValue>, String> {
    let reference = string_field(vector, "recordFile");
    let bytes = if reference.starts_with("corpus/") {
        fs::read(root.join(reference)).map_err(|error| error.to_string())?
    } else {
        let export_name = reference
            .split_once('#')
            .map(|(_, export)| export)
            .ok_or_else(|| format!("external record reference has no export: {reference}"))?;
        let candidate = if let Some(file) = env::var_os("ROAX_RECOVERY_SAMPLE") {
            PathBuf::from(file)
        } else if let Some(directory) = env::var_os("ROAX_EXTRACTED_RECORDS") {
            PathBuf::from(directory).join(format!("{export_name}.json"))
        } else {
            return Ok(None);
        };
        if !candidate.exists() {
            return Ok(None);
        }
        fs::read(candidate).map_err(|error| error.to_string())?
    };
    JsonValue::from_slice(&bytes)
        .map(Some)
        .map_err(|error| error.to_string())
}

/// The commitment context a class-20 vector names.
///
/// Unlike `context_from_vector` this carries the type-map descriptor, because every class-20
/// vector commits `roax.typeMap.id`: specification section 11.2 marks that leaf ALWAYS emitted, so
/// an ISSUANCE without one is not something the current specification permits, and
/// `schemas/envelope-1.0.json` keeps the member optional only for envelopes already issued under
/// it.
fn round_trip_context(vector: &Value) -> CommitmentContext {
    let descriptor = field(vector, "typeMap");
    CommitmentContext {
        hash_algorithm: HashAlgorithm::Sha256,
        reserved_leaf_set: ReservedLeafSet::EnvelopeV2,
        record_type: string_field(vector, "recordType").to_owned(),
        schema_version: string_field(vector, "schemaVersion").to_owned(),
        type_map: Some(roax_canon::TypeMapDescriptor {
            id: string_field(descriptor, "id").to_owned(),
            version: string_field(descriptor, "version").to_owned(),
        }),
        record_id: string_field(vector, "recordId").to_owned(),
        issuer: Issuer {
            id: string_field(vector, "issuerId").to_owned(),
            key_id: optional_field(vector, "issuerKeyId")
                .and_then(Value::as_str)
                .map(str::to_owned),
        },
    }
}

/// An envelope's comparison form with the aspects the specification does not fix removed. Applied
/// to BOTH sides, so what survives the comparison is what the specification actually says.
///
/// Three things are relaxed and nothing else. `disclosure.leaves` is ordered by leaf index and a
/// full copy's `salts` by its entry's structured path, because every leaf carries its own index
/// and every salt entry its own path, so neither array order carries anything. `displayPath` is
/// DROPPED: it is display only and never hashed (specification section 5.2), and
/// `schemas/envelope-1.0.json` leaves it out of `disclosedLeaf.required`, so a conforming producer
/// may omit it and a comparison that noticed would fail conforming work.
///
/// Everything else stays exact - both array LENGTHS, every leaf's segments, index, tag, value
/// carrier, salt and audit path, and every scalar identity field - so a producer that omitted a
/// per-leaf value carrier still fails, which is the defect this class exists for.
fn normalized_for_comparison(mut value: Value) -> Value {
    if let Some(salts) = value.get_mut("salts").and_then(Value::as_array_mut) {
        salts.sort_by_key(|entry| {
            serde_json::to_string(entry.get("segments").unwrap_or(&Value::Null)).unwrap_or_default()
        });
    }
    if let Some(leaves) = value
        .get_mut("disclosure")
        .and_then(|disclosure| disclosure.get_mut("leaves"))
        .and_then(Value::as_array_mut)
    {
        for leaf in leaves.iter_mut() {
            if let Some(members) = leaf.as_object_mut() {
                members.remove("displayPath");
            }
        }
        leaves.sort_by_key(|leaf| {
            leaf.get("index")
                .and_then(Value::as_str)
                .and_then(|text| text.strip_prefix("$numberLiteral:"))
                .and_then(|digits| digits.parse::<u64>().ok())
                .unwrap_or(u64::MAX)
        });
    }
    value
}

/// A comparison form for a parsed envelope: members sorted, numbers kept as SOURCE TEXT.
///
/// Semantic and not byte-for-byte, because JSON member order is not fixed by the specification;
/// [`normalized_for_comparison`] removes the rest of what it does not fix. A number's source text
/// is the one thing that must survive: the full copy carries the record's literals and
/// re-serializing them through a float destroys exactly what the root was computed from
/// (specification sections 6.4 and 7.3).
fn comparable_json(value: &JsonValue) -> Value {
    match value {
        JsonValue::Object(members) => {
            let mut map = serde_json::Map::new();
            for (key, entry) in members {
                map.insert(key.clone(), comparable_json(entry));
            }
            Value::Object(map)
        }
        JsonValue::Array(items) => Value::Array(items.iter().map(comparable_json).collect()),
        JsonValue::Number(literal) => {
            Value::String(format!("$numberLiteral:{literal}"))
        }
        JsonValue::String(text) => Value::String(text.clone()),
        JsonValue::Bool(flag) => Value::Bool(*flag),
        JsonValue::Null => Value::Null,
    }
}

fn context_from_vector(vector: &Value) -> CommitmentContext {
    v1_context(
        string_field(vector, "recordType"),
        string_field(vector, "schemaVersion"),
        string_field(vector, "recordId"),
        string_field(vector, "issuerId"),
        optional_field(vector, "issuerKeyId").and_then(Value::as_str),
    )
}

fn commit_corpus_record(
    root: &FsPath,
    vector: &Value,
    record: &JsonValue,
    map: &LegacyTypeMap,
) -> Result<roax_canon::Commitment, String> {
    let context = context_from_vector(vector);
    map.select(&context.record_type, &context.schema_version)
        .map_err(|error| error.to_string())?;
    let ordered_paths = ordered_v1_paths(record, &context)?;
    let salt_document: Value = serde_json::from_slice(
        &fs::read(root.join(string_field(vector, "saltsFile")))
            .map_err(|error| error.to_string())?,
    )
    .map_err(|error| error.to_string())?;
    let salts = salt_map_from_document(
        &salt_document,
        string_field(vector, "saltPairing"),
        &ordered_paths,
    )?;
    commit_full_copy_with_salts(record, &context, &LegacyProfile::new(map), &salts)
        .map_err(|error| error.to_string())
}

fn vector_count(vectors: &Vectors) -> usize {
    vectors.encode_path.len()
        + vectors.encode_value.len()
        + vectors.reject.len()
        + vectors.leaf.len()
        + vectors.tree.len()
        + vectors.inclusion.len()
        + vectors.negative_proof.len()
        + vectors.type_map.len()
        + vectors.record.len()
        + vectors.unlinkability.len()
        + vectors.normalization.len()
        + vectors.envelope.len()
        + vectors.round_trip.len()
}

#[test]
#[allow(clippy::too_many_lines)]
fn committed_conformance_corpus() {
    let root = repository_root();
    let corpus = read_corpus(&root);
    assert_eq!(corpus.version, "1.1.0");
    assert_eq!(corpus.canon, CANON_VERSION);
    assert_eq!(corpus.unicode_version, UNICODE_VERSION);
    assert_eq!(corpus.hash_alg, HashAlgorithm::Sha256.name());
    assert_eq!(
        vector_count(&corpus.vectors),
        501,
        "every committed vector array must be consumed"
    );

    let maps = load_legacy_maps(&root);
    let mut report = Report::default();

    for vector in &corpus.vectors.encode_path {
        let (class, name) = vector_identity(vector);
        match path_from_segments(field(vector, "segments")) {
            Ok(path) => {
                match path.encode() {
                    Ok(encoded) => report.check(
                        class,
                        name,
                        "encodedHex",
                        hex::encode(encoded),
                        string_field(vector, "encodedHex").to_owned(),
                    ),
                    Err(error) => report.fail(class, format!("{name} encodedHex: {error}")),
                }
                if let Some(expected) = optional_field(vector, "displayPath") {
                    report.check(
                        class,
                        name,
                        "displayPath",
                        path.display(),
                        expected.as_str().expect("displayPath string").to_owned(),
                    );
                }
            }
            Err(error) => report.fail(class, format!("{name} path decode: {error}")),
        }
    }

    for vector in &corpus.vectors.encode_value {
        let (class, name) = vector_identity(vector);
        let result = tag(integer_field(vector, "tag"))
            .and_then(|tag| leaf_value_from_carrier(tag, optional_field(vector, "input")))
            .and_then(|value| value.encode().map_err(|error| error.to_string()));
        match result {
            Ok(encoded) => report.check(
                class,
                name,
                "encodedHex",
                hex::encode(encoded),
                string_field(vector, "encodedHex").to_owned(),
            ),
            Err(error) => report.fail(class, format!("{name} encodedHex: {error}")),
        }
    }

    for vector in &corpus.vectors.reject {
        let (class, name) = vector_identity(vector);
        let got = match run_reject_vector(vector, &maps) {
            Ok(()) => "<accepted>".to_owned(),
            Err(reason) => reason,
        };
        report.check(
            class,
            name,
            "reason",
            got,
            string_field(vector, "reason").to_owned(),
        );
    }

    for vector in &corpus.vectors.leaf {
        let (class, name) = vector_identity(vector);
        let result = path_from_segments(field(vector, "segments")).and_then(|path| {
            let selected_tag = tag(integer_field(vector, "tag"))?;
            let value = leaf_value_from_carrier(selected_tag, optional_field(vector, "value"))?;
            let salt = Salt::from_hex(string_field(vector, "saltHex"))
                .map_err(|error| error.to_string())?;
            leaf_hash(&path, selected_tag, &value, salt, HashAlgorithm::Sha256)
                .map_err(|error| error.to_string())
        });
        match result {
            Ok(hash) => report.check(
                class,
                name,
                "leafHash",
                hex::encode(hash),
                string_field(vector, "leafHash").to_owned(),
            ),
            Err(error) => report.fail(class, format!("{name} leafHash: {error}")),
        }
    }

    let mut trees = HashMap::new();
    for vector in &corpus.vectors.tree {
        let (class, name) = vector_identity(vector);
        let result = field(vector, "leafHashes")
            .as_array()
            .expect("leafHashes array")
            .iter()
            .map(|value| {
                parse_hash(
                    value
                        .as_str()
                        .ok_or_else(|| "leaf hash is not a string".to_owned())?,
                )
            })
            .collect::<Result<Vec<_>, _>>();
        match result {
            Ok(leaves) => {
                let computed = merkle_tree_hash(&leaves);
                report.check(
                    class,
                    name,
                    "root",
                    hex::encode(computed),
                    string_field(vector, "root").to_owned(),
                );
                trees.insert(name.to_owned(), leaves);
            }
            Err(error) => report.fail(class, format!("{name} tree: {error}")),
        }
    }

    for vector in &corpus.vectors.inclusion {
        let (class, name) = vector_identity(vector);
        let tree_size =
            usize::try_from(integer_field(vector, "treeSize")).expect("tree size fits usize");
        let index = usize::try_from(integer_field(vector, "index")).expect("index fits usize");
        let leaves = trees
            .get(&format!("tree-n{tree_size}"))
            .expect("inclusion tree exists");
        let generated = audit_path(leaves, index).expect("valid inclusion index");
        report.check(
            class,
            name,
            "leafHash",
            hex::encode(leaves[index]),
            string_field(vector, "leafHash").to_owned(),
        );
        report.check(
            class,
            name,
            "auditPath",
            generated.iter().map(hex::encode).collect::<Vec<_>>(),
            field(vector, "auditPath")
                .as_array()
                .expect("auditPath array")
                .iter()
                .map(|value| value.as_str().expect("audit hash string").to_owned())
                .collect::<Vec<_>>(),
        );
        let root_hash = merkle_tree_hash(leaves);
        report.check(
            class,
            name,
            "root",
            hex::encode(root_hash),
            string_field(vector, "root").to_owned(),
        );
        let supplied_hash = parse_hash(string_field(vector, "leafHash")).expect("leaf hash");
        let supplied_root = parse_hash(string_field(vector, "root")).expect("root");
        let supplied_path = field(vector, "auditPath")
            .as_array()
            .expect("auditPath array")
            .iter()
            .map(|value| parse_hash(value.as_str().expect("audit hash string")))
            .collect::<Result<Vec<_>, _>>()
            .expect("valid audit hashes");
        report.check(
            class,
            name,
            "expect",
            fold_inclusion_proof_untrusted(
                &supplied_hash,
                u64::try_from(index).expect("index fits u64"),
                u64::try_from(tree_size).expect("tree size fits u64"),
                &supplied_path,
                &supplied_root,
            ),
            bool_field(vector, "expect"),
        );
    }

    for vector in &corpus.vectors.negative_proof {
        let (class, name) = vector_identity(vector);
        let tree_size =
            usize::try_from(integer_field(vector, "treeSize")).expect("tree size fits usize");
        let leaves = trees
            .get(&format!("tree-n{tree_size}"))
            .expect("negative-proof tree exists");
        match negative_proof_fields(vector, leaves) {
            Ok((leaf, proof, root_hash)) => {
                report.check(
                    class,
                    name,
                    "leafHash",
                    hex::encode(leaf),
                    string_field(vector, "leafHash").to_owned(),
                );
                report.check(
                    class,
                    name,
                    "auditPath",
                    proof.iter().map(hex::encode).collect::<Vec<_>>(),
                    field(vector, "auditPath")
                        .as_array()
                        .expect("auditPath array")
                        .iter()
                        .map(|value| value.as_str().expect("audit hash string").to_owned())
                        .collect::<Vec<_>>(),
                );
                report.check(
                    class,
                    name,
                    "root",
                    hex::encode(root_hash),
                    string_field(vector, "root").to_owned(),
                );
                let index =
                    usize::try_from(integer_field(vector, "index")).expect("index fits usize");
                report.check(
                    class,
                    name,
                    "mustNotVerify",
                    fold_inclusion_proof_untrusted(
                        &leaf,
                        u64::try_from(index).expect("index fits u64"),
                        u64::try_from(tree_size).expect("tree size fits u64"),
                        &proof,
                        &root_hash,
                    ),
                    false,
                );
            }
            Err(error) => report.fail(class, format!("{name} negative proof: {error}")),
        }
    }

    for vector in &corpus.vectors.type_map {
        let (class, name) = vector_identity(vector);
        let Some(map) = maps.get(string_field(vector, "recordType")) else {
            report.fail(class, format!("{name}: legacy type map is missing"));
            continue;
        };
        let result = path_from_segments(field(vector, "segments")).and_then(|path| {
            let kind = json_kind(string_field(vector, "jsonKind"))?;
            map.resolve(&path, kind).map_err(|error| error.to_string())
        });
        if let Some(expected) = optional_field(vector, "expectTag") {
            match result {
                Ok(got) => report.check(
                    class,
                    name,
                    "expectTag",
                    got as u8,
                    u8::try_from(expected.as_u64().expect("expectTag integer"))
                        .expect("expectTag fits u8"),
                ),
                Err(error) => report.fail(class, format!("{name} expectTag: {error}")),
            }
        } else {
            report.check(
                class,
                name,
                "expectFailClosed",
                result.is_err(),
                bool_field(vector, "expectFailClosed"),
            );
        }
    }

    for vector in &corpus.vectors.record {
        let (class, name) = vector_identity(vector);
        let record = match load_record_for_vector(&root, vector) {
            Ok(Some(record)) => record,
            Ok(None) => {
                report.skip(
                    class,
                    format!("{name}: supply ROAX_EXTRACTED_RECORDS or ROAX_RECOVERY_SAMPLE"),
                );
                continue;
            }
            Err(error) => {
                report.fail(class, format!("{name} record load: {error}"));
                continue;
            }
        };
        let Some(map) = maps.get(string_field(vector, "recordType")) else {
            report.fail(class, format!("{name}: legacy type map is missing"));
            continue;
        };
        match commit_corpus_record(&root, vector, &record, map) {
            Ok(commitment) => {
                report.check(
                    class,
                    name,
                    "leafCount",
                    commitment.leaves().len(),
                    usize::try_from(integer_field(vector, "leafCount"))
                        .expect("leaf count fits usize"),
                );
                report.check(
                    class,
                    name,
                    "root",
                    hex::encode(commitment.root()),
                    string_field(vector, "root").to_owned(),
                );
            }
            Err(error) => report.fail(class, format!("{name} record commitment: {error}")),
        }
    }

    for vector in &corpus.vectors.unlinkability {
        let (class, name) = vector_identity(vector);
        let paths = field(vector, "paths")
            .as_array()
            .expect("unlinkability paths")
            .iter()
            .map(path_from_segments)
            .collect::<Result<Vec<_>, _>>();
        let paths = match paths {
            Ok(paths) => paths,
            Err(error) => {
                report.fail(class, format!("{name} paths: {error}"));
                continue;
            }
        };
        let encoded: HashSet<Vec<u8>> = paths
            .iter()
            .map(|path| path.encode().expect("unlinkability paths encode"))
            .collect();
        if encoded.len() != paths.len() {
            report.fail(
                class,
                format!("{name}: paths collide after NFC normalization"),
            );
            continue;
        }
        let selected_tag = tag(integer_field(vector, "tag")).expect("unlinkability tag");
        let value = leaf_value_from_carrier(selected_tag, optional_field(vector, "value"))
            .expect("unlinkability value");
        let trials =
            usize::try_from(integer_field(vector, "trials")).expect("trial count fits usize");
        let mut salts_seen: HashMap<Vec<u8>, HashSet<Salt>> = HashMap::new();
        let mut hashes_seen: HashMap<Vec<u8>, HashSet<[u8; 32]>> = HashMap::new();
        let mut within_distinct = true;
        let mut across_salts_distinct = true;
        let mut across_hashes_distinct = true;
        for _ in 0..trials {
            let salts = generate_salts(&paths).expect("operating-system salt generation");
            let mut within = HashSet::new();
            for path in &paths {
                let salt = salts.get(path).expect("generated salt is addressable");
                within_distinct &= within.insert(salt);
                let path_key = path.encode().expect("path encoding");
                across_salts_distinct &=
                    salts_seen.entry(path_key.clone()).or_default().insert(salt);
                let hash = leaf_hash(path, selected_tag, &value, salt, HashAlgorithm::Sha256)
                    .expect("unlinkability leaf hash");
                across_hashes_distinct &= hashes_seen.entry(path_key).or_default().insert(hash);
            }
        }
        report.check(
            class,
            name,
            "expectDistinctSaltsWithinIssuance",
            within_distinct,
            bool_field(vector, "expectDistinctSaltsWithinIssuance"),
        );
        report.check(
            class,
            name,
            "expectDistinctSaltsAcrossIssuances",
            across_salts_distinct,
            bool_field(vector, "expectDistinctSaltsAcrossIssuances"),
        );
        report.check(
            class,
            name,
            "expectDistinctLeafHashesAcrossIssuances",
            across_hashes_distinct,
            bool_field(vector, "expectDistinctLeafHashesAcrossIssuances"),
        );
    }

    for vector in &corpus.vectors.normalization {
        let (class, name) = vector_identity(vector);
        let Some(map) = maps.get(string_field(vector, "recordType")) else {
            report.fail(class, format!("{name}: legacy type map is missing"));
            continue;
        };
        let context = context_from_vector(vector);
        let salt_document: Value = serde_json::from_slice(
            &fs::read(root.join(string_field(vector, "saltsFile")))
                .expect("normalization salt set"),
        )
        .expect("valid normalization salt set");
        let mut roots = Vec::new();
        for record_field in ["recordFileNFD", "recordFileNFC"] {
            let record = JsonValue::from_slice(
                &fs::read(root.join(string_field(vector, record_field)))
                    .expect("normalization record fixture"),
            )
            .expect("literal-preserving normalization record");
            let ordered_paths =
                ordered_v1_paths(&record, &context).expect("normalization record paths");
            let salts = salt_map_from_document(&salt_document, "path", &ordered_paths)
                .expect("normalization salt pairing");
            match commit_full_copy_with_salts(&record, &context, &LegacyProfile::new(map), &salts) {
                Ok(commitment) => roots.push(commitment.root()),
                Err(error) => {
                    report.fail(class, format!("{name} {record_field}: {error}"));
                    break;
                }
            }
        }
        if roots.len() == 2 {
            report.check(
                class,
                name,
                "expectSameRoot",
                roots[0] == roots[1],
                bool_field(vector, "expectSameRoot"),
            );
            report.check(
                class,
                name,
                "root",
                hex::encode(roots[0]),
                string_field(vector, "root").to_owned(),
            );
        }
    }

    for vector in &corpus.vectors.envelope {
        let (class, name) = vector_identity(vector);
        let bytes =
            fs::read(root.join(string_field(vector, "envelopeFile"))).expect("envelope fixture");
        let (accepted, reason) = verify_legacy_envelope(&bytes, &maps);
        report.check(
            class,
            name,
            "expectAccept",
            accepted,
            bool_field(vector, "expectAccept"),
        );
        report.check(
            class,
            name,
            "reason",
            reason,
            string_field(vector, "reason").to_owned(),
        );
    }

    // Class 20: issue, disclose, then verify the copy THIS crate produced.
    //
    // Every loop above runs this crate's VERIFIER against bytes the corpus generator wrote. That
    // is the gap this class closes: a library can emit a disclosed copy its own verifier refuses
    // and still pass every other vector, because no other vector asks it to PRODUCE one. So this
    // drives the real entry points - `issue_full_copy_with_salts` and `disclose` - rather than
    // assembling an envelope here, which would test this file instead of the crate.
    for vector in &corpus.vectors.round_trip {
        let (class, name) = vector_identity(vector);
        let context = round_trip_context(vector);
        let Some(floor) = profile_floor(&context.record_type) else {
            report.fail(class, format!("{name}: no floor for {}", context.record_type));
            continue;
        };
        let Some(map) = maps.get(&context.record_type) else {
            report.fail(class, format!("{name}: no type map for {}", context.record_type));
            continue;
        };
        let profile = LegacyProfile {
            record_type: context.record_type.clone(),
            schema_version: context.schema_version.clone(),
            resolver: map,
            floor,
        };
        let record = match JsonValue::from_slice(
            &fs::read(root.join(string_field(vector, "recordFile"))).expect("round-trip record"),
        ) {
            Ok(record) => record,
            Err(error) => {
                report.fail(class, format!("{name}: {error}"));
                continue;
            }
        };
        let ordered_paths = match ordered_v1_paths(&record, &context) {
            Ok(paths) => paths,
            Err(error) => {
                report.fail(class, format!("{name}: {error}"));
                continue;
            }
        };
        let salt_document: Value = serde_json::from_slice(
            &fs::read(root.join(string_field(vector, "saltsFile"))).expect("round-trip salts"),
        )
        .expect("round-trip salt document");
        let salts = match salt_map_from_document(
            &salt_document,
            string_field(vector, "saltPairing"),
            &ordered_paths,
        ) {
            Ok(salts) => salts,
            Err(error) => {
                report.fail(class, format!("{name}: {error}"));
                continue;
            }
        };
        let (copy, commitment) =
            match issue_full_copy_with_salts(&record, &context, &profile, &salts) {
                Ok(issued) => issued,
                Err(error) => {
                    report.fail(class, format!("{name}: issuance failed: {error}"));
                    continue;
                }
            };
        report.check(
            class,
            name,
            "leafCount",
            u64::try_from(commitment.leaves().len()).unwrap_or(u64::MAX),
            integer_field(vector, "leafCount"),
        );
        report.check(
            class,
            name,
            "root",
            hex::encode(commitment.root()),
            string_field(vector, "root").to_owned(),
        );

        let requested: Result<Vec<Path>, String> = field(vector, "disclosePaths")
            .as_array()
            .expect("disclosePaths")
            .iter()
            .map(path_from_segments)
            .collect();
        let requested = match requested {
            Ok(paths) => paths,
            Err(error) => {
                report.fail(class, format!("{name}: {error}"));
                continue;
            }
        };
        let disclosure = match disclose(&commitment, &profile, &requested) {
            Ok(disclosure) => disclosure,
            Err(error) => {
                report.fail(class, format!("{name}: disclosure failed: {error}"));
                continue;
            }
        };

        let policy = VerificationPolicy {
            anchored_root: commitment.root(),
            anchored_hash_algorithm: HashAlgorithm::Sha256,
        };
        for (field_name, produced, verified) in [
            (
                "expectedFullCopyFile",
                copy.to_json_value(),
                verify_full(&copy, &profile, policy).map(|_| ()),
            ),
            (
                "expectedDisclosedCopyFile",
                disclosure.to_json_value(),
                verify_disclosed(&disclosure, &profile, policy),
            ),
        ] {
            let expected_bytes = fs::read(root.join(string_field(vector, field_name)))
                .expect("round-trip expected envelope");
            let expected =
                JsonValue::from_slice(&expected_bytes).expect("round-trip expected envelope JSON");
            report.check(
                class,
                name,
                field_name,
                normalized_for_comparison(comparable_json(&produced)),
                normalized_for_comparison(comparable_json(&expected)),
            );
            // And the half no static fixture can assert: this crate's verifier over this crate's
            // own output. A producer that omitted a per-leaf value carrier fails HERE even though
            // every leaf hash it computed was right.
            match verified {
                Ok(()) => report.pass(class),
                Err(error) => report.fail(
                    class,
                    format!("{name}: this crate issued an envelope its own verifier refused: {error}"),
                ),
            }
        }
    }

    report.finish();
}
