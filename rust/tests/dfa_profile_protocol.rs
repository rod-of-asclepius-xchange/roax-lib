//! The published structured-path DFA driven through the whole protocol.
//!
//! `conformance_corpus.rs` resolves tags through the corpus-era display-pattern
//! maps and `published_type_maps.rs` calls [`DfaTypeMap`] at resolver level, so
//! neither exercises a published artifact through `issue_full_copy`,
//! `verify_full`, `disclose` and `verify_disclosed`. Decision D14 has two
//! high-level call sites - construction and disclosed verification - and only
//! the resolver methods behind them were covered.

use roax_canon::type_map::content_id;
use roax_canon::Ordering;
use roax_canon::{
    disclose, issue_full_copy, parse_envelope, verify_disclosed, verify_full, CommitmentContext,
    DfaTypeMap, Error, HashAlgorithm, Issuer, JsonKind, JsonValue, ParsedEnvelope, Path, Profile,
    ReservedLeafSet, SchemaValidator, Segment, TypeMapDescriptor, TypeResolver, TypeTag,
    VerificationPolicy,
};
use serde_json::json;
use std::fs;
use std::path::{Path as FsPath, PathBuf};

const RECOVERY_MAP_ID: &str =
    "sha256:db935b67a3a82754921267e3af237b606f7489b46e05aa892d175b8d87504177";

/// A profile whose authority is one exact published or synthetic artifact.
struct DfaProfile {
    map: DfaTypeMap,
    floor: Vec<Path>,
}

impl SchemaValidator for DfaProfile {
    fn validate_record(&self, _record: &JsonValue) -> roax_canon::Result<()> {
        // A deployed profile validates the complete record schema here. These
        // tests are about the type-map and protocol boundaries around it.
        Ok(())
    }
}

impl TypeResolver for DfaProfile {
    fn resolve(&self, path: &Path, kind: JsonKind) -> roax_canon::Result<TypeTag> {
        self.map.resolve(path, kind)
    }
}

impl Profile for DfaProfile {
    fn record_type(&self) -> &str {
        self.map.record_type()
    }

    fn validate_context(&self, context: &CommitmentContext) -> roax_canon::Result<()> {
        let descriptor = context
            .type_map
            .as_ref()
            .ok_or(Error::UnsupportedEnvelopeGeneration)?;
        self.map.select(
            &context.record_type,
            &context.schema_version,
            descriptor,
            &context.issuer.id,
        )
    }

    fn resolver(&self) -> &dyn TypeResolver {
        self
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

fn key_path(keys: &[&str]) -> Path {
    Path::from_segments(
        keys.iter()
            .map(|key| Segment::Key((*key).to_owned()))
            .collect(),
    )
}

fn context_for(map: &DfaTypeMap, record_id: &str) -> CommitmentContext {
    CommitmentContext {
        hash_algorithm: HashAlgorithm::Sha256,
        reserved_leaf_set: ReservedLeafSet::EnvelopeV2,
        record_type: map.record_type().to_owned(),
        schema_version: map.schema_version().to_owned(),
        type_map: Some(TypeMapDescriptor {
            id: map.id().to_owned(),
            version: map.version().to_owned(),
        }),
        record_id: record_id.to_owned(),
        issuer: Issuer {
            id: "did:example:issuer".to_owned(),
            key_id: None,
        },
        ordering: Ordering::default(),
    }
}

/// The synthetic artifact of `published_type_maps.rs`, rebuilt here so this file
/// stays independent of that one's helpers.
fn lookup_artifact(key: &str) -> Vec<u8> {
    let artifact = json!({
        "format": "ROAX-TYPE-MAP/1",
        "typeMapVersion": "1.0.0",
        "recordType": "org.roax.test.protocol",
        "schemaVersion": "1",
        "scope": { "kind": "profile" },
        "sourceSchemas": [{
            "sourceId": "test-source",
            "kind": "content",
            "uri": "https://example.invalid/schema.json",
            "digest": format!("sha256:{}", "0".repeat(64))
        }],
        "extensionPoints": [],
        "addedSelectors": [],
        "coverage": {
            "concretePathCardinality": "infinite",
            "states": 2,
            "keyTransitions": 1,
            "indexTransitions": 0,
            "resolvedOutputs": 1,
            "unresolvedOutputStates": 0,
            "structurallyUntypedObjectSourceNodes": 0,
            "structurallyUntypedObjectStates": 0,
            "byTag": { "2": 1 },
            "byBasis": { "schema-type": 1 },
            "notes": []
        },
        "automaton": {
            "representation": "structured-path-dfa/1",
            "start": "s0",
            "states": [
                { "id": "s0", "keys": [{ "key": key, "to": "s1" }] },
                { "id": "s1", "bindings": [{
                    "jsonKind": "string",
                    "tag": 2,
                    "basis": ["schema-type"],
                    "sources": ["test-source"]
                }] }
            ]
        }
    });
    serde_json::to_vec(&artifact).expect("synthetic artifact must serialize")
}

#[test]
fn a_published_artifact_drives_issue_verify_disclose_and_verify() {
    let bytes =
        fs::read(repository_root().join("type-maps/sg.gov.moh.recovery-healthcert-2.0.json"))
            .expect("published recovery type map");
    let map = DfaTypeMap::from_exact_bytes(&bytes, RECOVERY_MAP_ID)
        .expect("the published recovery artifact must load");

    let profile = DfaProfile {
        map,
        floor: vec![
            key_path(&["version"]),
            key_path(&["type"]),
            key_path(&["validFrom"]),
            key_path(&["validUntil"]),
        ],
    };
    let context = context_for(
        &profile.map,
        "urn:uuid:00000000-0000-4000-8000-000000000001",
    );

    // Structurally minimal but schema-shaped: the profile's floor plus the
    // smallest Bundle the reference schema admits.
    let record = JsonValue::from_str(
        r#"{"id":"00000000-0000-4000-8000-000000000001",
            "version":"rec-healthcert-v2.0",
            "type":"PCR",
            "validFrom":"2022-03-12T04:30:35.065Z",
            "validUntil":"2023-08-28T04:30:35.065Z",
            "fhirVersion":"4.0.1",
            "fhirBundle":{"resourceType":"Bundle"}}"#,
    )
    .expect("record parses");

    let (copy, commitment) =
        issue_full_copy(&record, &context, &profile).expect("the full copy must issue");
    let policy = VerificationPolicy {
        anchored_root: copy.root(),
        anchored_hash_algorithm: HashAlgorithm::Sha256,
        anchored_ordering: Ordering::default(),
    };
    assert_eq!(
        verify_full(&copy, &profile, policy)
            .expect("the full copy must verify")
            .root(),
        copy.root()
    );
    // Five reserved leaves without an issuer keyId, plus the seven record leaves.
    assert_eq!(copy.leaf_count(), 12);
    assert_eq!(commitment.record_leaf_count(), 7);

    let disclosure = disclose(&commitment, &profile, &[key_path(&["fhirVersion"])])
        .expect("the disclosure must build");
    // One requested leaf, the four-path profile floor and the five reserved leaves.
    assert_eq!(disclosure.leaves().len(), 10);
    verify_disclosed(&disclosure, &profile, policy).expect("the disclosure must verify");

    // Withholding the recovery-specific expiry breaks the floor, on the same root.
    let mut envelope: serde_json::Value =
        serde_json::from_str(&disclosure.to_json_string()).expect("the disclosure re-parses");
    envelope["disclosure"]["leaves"]
        .as_array_mut()
        .expect("leaf array")
        .retain(|leaf| leaf["displayPath"] != json!("validUntil"));
    let withheld = serde_json::to_string(&envelope).expect("mutated disclosure serializes");
    assert_eq!(
        verify_text(&withheld, &profile, policy),
        Err(Error::MinimumDisclosureFloor)
    );
}

fn verify_text(text: &str, profile: &dyn Profile, policy: VerificationPolicy) -> Result<(), Error> {
    match parse_envelope(text.as_bytes(), ReservedLeafSet::EnvelopeV2)? {
        ParsedEnvelope::Disclosed(disclosure) => verify_disclosed(&disclosure, profile, policy),
        ParsedEnvelope::Full(_) => panic!("expected a disclosed copy"),
    }
}

#[test]
fn both_high_level_call_sites_resolve_a_decomposed_key_like_its_composed_twin() {
    // Ruled decision D14a: the lookup matches under NFC, so the two spellings behave
    // identically end to end. Under the retired raw reading the decomposed record was
    // refused outright by the fail-closed rule while its composed twin issued, and the
    // two render identically to whoever typed the key.
    //
    // The artifact declares the COMPOSED spelling. Both call sites are covered because
    // each resolves independently: commitment.rs at issuance, envelope.rs at disclosed
    // verification.
    let bytes = lookup_artifact("\u{e9}");
    let id = content_id(&bytes);
    let profile = DfaProfile {
        map: DfaTypeMap::from_exact_bytes(&bytes, &id).expect("synthetic artifact loads"),
        floor: Vec::new(),
    };
    let context = context_for(&profile.map, "record-1");

    // Construction, at commitment.rs's resolver call site.
    let composed = JsonValue::from_str("{\"\\u00e9\":\"x\"}").expect("composed record parses");
    let decomposed = JsonValue::from_str("{\"e\\u0301\":\"x\"}").expect("decomposed record parses");
    let (copy, commitment) =
        issue_full_copy(&composed, &context, &profile).expect("the composed key must issue");
    let (decomposed_copy, _) =
        issue_full_copy(&decomposed, &context, &profile).expect("the decomposed key must issue");
    assert_eq!(decomposed_copy.leaf_count(), copy.leaf_count());

    let policy = VerificationPolicy {
        anchored_root: copy.root(),
        anchored_hash_algorithm: HashAlgorithm::Sha256,
        anchored_ordering: Ordering::default(),
    };
    let disclosure = disclose(&commitment, &profile, &[key_path(&["\u{e9}"])])
        .expect("the composed disclosure must build");
    verify_disclosed(&disclosure, &profile, policy).expect("the composed disclosure must verify");

    // Disclosed verification, at envelope.rs's resolver call site. The encoded path
    // normalizes before hashing, so rewriting the disclosed key to its decomposed
    // spelling leaves the leaf hash and the inclusion proof matching the genuine root.
    // Under raw matching the lookup then failed closed and refused an envelope whose
    // arithmetic is intact; under D14a it verifies.
    let rewritten = disclosure
        .to_json_string()
        .replace("\"\u{e9}\"", "\"e\u{301}\"");
    assert_ne!(rewritten, disclosure.to_json_string());
    verify_text(&rewritten, &profile, policy)
        .expect("a decomposed disclosed key must verify under D14a");
}

/// A type map that binds one INTEGER leaf, for the profile-rule layering test below.
fn integer_artifact() -> Vec<u8> {
    let artifact = json!({
        "format": "ROAX-TYPE-MAP/1",
        "typeMapVersion": "1.0.0",
        "recordType": "org.roax.test.protocol",
        "schemaVersion": "1",
        "scope": { "kind": "profile" },
        "sourceSchemas": [{
            "sourceId": "test-source",
            "kind": "content",
            "uri": "https://example.invalid/schema.json",
            "digest": format!("sha256:{}", "0".repeat(64))
        }],
        "extensionPoints": [],
        "addedSelectors": [],
        "coverage": {
            "concretePathCardinality": "infinite",
            "states": 2,
            "keyTransitions": 1,
            "indexTransitions": 0,
            "resolvedOutputs": 1,
            "unresolvedOutputStates": 0,
            "structurallyUntypedObjectSourceNodes": 0,
            "structurallyUntypedObjectStates": 0,
            "byTag": { "3": 1 },
            "byBasis": { "schema-type": 1 },
            "notes": []
        },
        "automaton": {
            "representation": "structured-path-dfa/1",
            "start": "s0",
            "states": [
                { "id": "s0", "keys": [{ "key": "dose", "to": "s1" }] },
                { "id": "s1", "bindings": [{
                    "jsonKind": "number",
                    "tag": 3,
                    "basis": ["schema-type"],
                    "sources": ["test-source"]
                }] }
            ]
        }
    });
    serde_json::to_vec(&artifact).expect("synthetic artifact must serialize")
}

/// A profile that also enforces a declared value rule, through `SchemaValidator`.
///
/// This is where a value-domain narrowing belongs. ROAX-CANON/1 section 4.2 orders profile
/// validation BEFORE map resolution, and ruled decision D13a keeps value-domain validation in
/// "a separate, independently versioned conformance layer" rather than in the canonicalization
/// layer, so this crate deliberately carries no such rule of its own and exposes this seam
/// instead (`docs/decisions.md`, D13; `docs/profiles/vaccination-healthcert.md` section 6).
struct PositiveDoseProfile {
    inner: DfaProfile,
}

impl SchemaValidator for PositiveDoseProfile {
    fn validate_record(&self, record: &JsonValue) -> roax_canon::Result<()> {
        let JsonValue::Object(members) = record else {
            return Err(Error::ProfileValidation("record must be an object".into()));
        };
        for (key, value) in members {
            if key != "dose" {
                continue;
            }
            // The rule is stated over the exact numeric TEXT, never a parsed float: the whole
            // point of ROAX-CANON/1 sections 3.2 and 6.4 is that a record number never passes
            // through one, and a profile rule reading `as_f64` would reintroduce that hazard at
            // the validation layer.
            let text = match value {
                JsonValue::Number(literal) => literal.as_str(),
                _ => {
                    return Err(Error::ProfileValidation(
                        "dose must be a JSON number".into(),
                    ))
                }
            };
            if !text.starts_with(['1', '2', '3', '4', '5', '6', '7', '8', '9'])
                || !text.bytes().all(|b| b.is_ascii_digit())
            {
                return Err(Error::ProfileValidation(format!(
                    "dose-positive-integer: {text} is not a positive integer"
                )));
            }
        }
        Ok(())
    }
}

impl TypeResolver for PositiveDoseProfile {
    fn resolve(&self, path: &Path, kind: JsonKind) -> roax_canon::Result<TypeTag> {
        self.inner.resolve(path, kind)
    }
}

impl Profile for PositiveDoseProfile {
    fn record_type(&self) -> &str {
        self.inner.record_type()
    }

    fn validate_context(&self, context: &CommitmentContext) -> roax_canon::Result<()> {
        self.inner.validate_context(context)
    }

    fn resolver(&self) -> &dyn TypeResolver {
        self
    }

    fn minimum_disclosure_paths(&self) -> Vec<Path> {
        Vec::new()
    }
}

#[test]
fn a_declared_profile_value_rule_narrows_what_the_integer_binding_admits() {
    // The RULED `dose` binding is INTEGER, and the ruling carries a positive-integer narrowing.
    // The two halves land in different layers and this test pins both, plus the fact that the
    // narrowing is not something the type map could express.
    let bytes = integer_artifact();
    let id = content_id(&bytes);
    let map = DfaTypeMap::from_exact_bytes(&bytes, &id).expect("synthetic artifact loads");
    let context = context_for(&map, "record-1");
    let inner = DfaProfile {
        map,
        floor: Vec::new(),
    };
    let ruled = PositiveDoseProfile { inner };

    // The values the shipped vaccination sample carries.
    for text in ["1", "2"] {
        let record = JsonValue::from_str(&format!("{{\"dose\":{text}}}")).expect("record parses");
        issue_full_copy(&record, &context, &ruled)
            .unwrap_or_else(|error| panic!("dose {text} must issue: {error}"));
    }

    // `0` and the negatives are grammar-valid ROAX INTEGERs, so the TAG alone admits them.
    // Without the profile rule each would commit, which is precisely why the ruling is not a
    // bare type-map edit. A fractional value is refused one layer down by the section 6.2
    // INTEGER grammar and is therefore not the discriminating case.
    for text in ["0", "-0", "-1", "-999"] {
        let record = JsonValue::from_str(&format!("{{\"dose\":{text}}}")).expect("record parses");
        let error = issue_full_copy(&record, &context, &ruled)
            .expect_err(&format!("dose {text} must be refused by the profile rule"));
        assert!(
            matches!(error, Error::ProfileValidation(ref detail)
                if detail.contains("dose-positive-integer")),
            "dose {text} was refused by {error} rather than by the declared profile rule"
        );

        // And the CANONICALIZATION layer accepts the same value, which is the layering this
        // test exists to state: the tag is INTEGER and `0` is a valid INTEGER, so nothing
        // below the profile refuses it.
        let bare = DfaProfile {
            map: DfaTypeMap::from_exact_bytes(&bytes, &id).expect("synthetic artifact loads"),
            floor: Vec::new(),
        };
        issue_full_copy(&record, &context, &bare).unwrap_or_else(|error| {
            panic!("the canonicalization layer must accept {text}: {error}")
        });
    }
}
