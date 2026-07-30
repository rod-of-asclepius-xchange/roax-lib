use roax_canon::type_map::content_id;
use roax_canon::{
    DfaTypeMap, Error, JsonKind, Path, Segment, TypeMapDescriptor, TypeResolver,
    TypeTag,
};
use serde::Deserialize;
use serde_json::json;
use std::fs;
use std::path::{Path as FsPath, PathBuf};

const EXPECTED_MAPS: [(&str, &str, &str, &str); 4] = [
    (
        "hl7.fhir.bundle",
        "4.0.1",
        "1.0.0",
        "sha256:0e9e642bc89c081e2e6faf651acdc25c46fac83201248ef53a7c812181279807",
    ),
    (
        "sg.gov.moh.pdt-healthcert",
        "2.0",
        "1.0.0",
        "sha256:4f8cecc59c85101b8b567658c90651bcbf8f9d4dc279571aa40a03cf04f434ff",
    ),
    (
        "sg.gov.moh.recovery-healthcert",
        "2.0",
        "1.0.0",
        "sha256:db935b67a3a82754921267e3af237b606f7489b46e05aa892d175b8d87504177",
    ),
    (
        "sg.gov.moh.vaccination-healthcert",
        "1.0",
        "1.0.0",
        "sha256:de7bb92226af5fa5dc5064d9cb203329abc69160f4280fdf739e66e5e0151e93",
    ),
];

#[derive(Debug, Deserialize)]
struct Registry {
    maps: Vec<RegistryRow>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RegistryRow {
    id: String,
    path: String,
    type_map_version: String,
    record_type: String,
    schema_version: String,
}

#[derive(Clone, Copy)]
enum TestSegment<'a> {
    Key(&'a str),
    Index(u32),
}

use TestSegment::{Index as I, Key as K};

fn repository_root() -> PathBuf {
    FsPath::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("the Rust crate must be directly beneath the repository root")
        .to_owned()
}

fn registry() -> Registry {
    let bytes = fs::read(repository_root().join("type-maps/registry-1.0.0.json"))
        .expect("published type-map registry");
    serde_json::from_slice(&bytes).expect("valid published type-map registry")
}

fn row<'a>(registry: &'a Registry, record_type: &str) -> &'a RegistryRow {
    registry
        .maps
        .iter()
        .find(|row| row.record_type == record_type)
        .unwrap_or_else(|| panic!("missing registry row for {record_type}"))
}

fn artifact_bytes(row: &RegistryRow) -> Vec<u8> {
    let relative = FsPath::new(&row.path);
    assert!(!relative.is_absolute(), "registry path must be relative");
    assert!(
        relative.starts_with("type-maps"),
        "registry path must stay in type-maps"
    );
    fs::read(repository_root().join(relative)).expect("published type-map artifact")
}

fn load(row: &RegistryRow) -> DfaTypeMap {
    DfaTypeMap::from_exact_bytes(&artifact_bytes(row), &row.id)
        .unwrap_or_else(|error| panic!("{} must load: {error}", row.record_type))
}

fn structured_path(segments: &[TestSegment<'_>]) -> Path {
    Path::from_segments(
        segments
            .iter()
            .map(|segment| match segment {
                TestSegment::Key(key) => Segment::Key((*key).to_owned()),
                TestSegment::Index(index) => Segment::Index(*index),
            })
            .collect(),
    )
}

fn assert_tag(map: &DfaTypeMap, segments: &[TestSegment<'_>], kind: JsonKind, expected: TypeTag) {
    let path = structured_path(segments);
    assert_eq!(
        map.resolve(&path, kind),
        Ok(expected),
        "{} must bind structured path {:?} observed as {kind:?}",
        map.record_type(),
        path.segments()
    );
}

fn assert_unbound(map: &DfaTypeMap, segments: &[TestSegment<'_>], kind: JsonKind) {
    let path = structured_path(segments);
    assert_eq!(
        map.resolve(&path, kind),
        Err(Error::UnknownTypeBinding {
            path: path.clone(),
            kind,
        }),
        "{} must fail closed at structured path {:?} observed as {kind:?}",
        map.record_type(),
        path.segments()
    );
}

#[test]
fn registry_ids_select_all_four_exact_published_artifacts() {
    let registry = registry();
    assert_eq!(registry.maps.len(), EXPECTED_MAPS.len());

    for (record_type, schema_version, type_map_version, expected_id) in EXPECTED_MAPS {
        let row = row(&registry, record_type);
        assert_eq!(row.schema_version, schema_version);
        assert_eq!(row.type_map_version, type_map_version);
        assert_eq!(row.id, expected_id);

        let bytes = artifact_bytes(row);
        assert_eq!(content_id(&bytes), row.id);

        let map = load(row);
        assert_eq!(map.id(), row.id);
        assert_eq!(map.record_type(), row.record_type);
        assert_eq!(map.schema_version(), row.schema_version);
        assert_eq!(map.version(), row.type_map_version);

        let descriptor = TypeMapDescriptor {
            id: row.id.clone(),
            version: row.type_map_version.clone(),
        };
        map.select(
            &row.record_type,
            &row.schema_version,
            &descriptor,
            "did:example:any-profile-issuer",
        )
        .expect("the exact registry identity must select its base map");

        let wrong_id = TypeMapDescriptor {
            id: format!("{}0", row.id),
            version: row.type_map_version.clone(),
        };
        assert_eq!(
            map.select(
                &row.record_type,
                &row.schema_version,
                &wrong_id,
                "did:example:any-profile-issuer",
            ),
            Err(Error::TypeMapIdentityMismatch)
        );

        let wrong_version = TypeMapDescriptor {
            id: row.id.clone(),
            version: "1.0.1".to_owned(),
        };
        assert_eq!(
            map.select(
                &row.record_type,
                &row.schema_version,
                &wrong_version,
                "did:example:any-profile-issuer",
            ),
            Err(Error::TypeMapIdentityMismatch)
        );
        assert_eq!(
            map.select(
                "org.roax.corpus.synthetic",
                &row.schema_version,
                &descriptor,
                "did:example:any-profile-issuer",
            ),
            Err(Error::TypeMapIdentityMismatch)
        );
        assert_eq!(
            map.select(
                &row.record_type,
                "not-the-pinned-schema-version",
                &descriptor,
                "did:example:any-profile-issuer",
            ),
            Err(Error::TypeMapIdentityMismatch)
        );
    }

    let first = row(&registry, EXPECTED_MAPS[0].0);
    let second = row(&registry, EXPECTED_MAPS[1].0);
    assert_eq!(
        DfaTypeMap::from_exact_bytes(&artifact_bytes(first), &second.id)
            .expect_err("bytes from one registry row cannot select another row"),
        Error::TypeMapIdMismatch
    );
}

#[test]
fn fhir_map_preserves_pinned_operative_and_fail_closed_bindings() {
    let registry = registry();
    let fhir = load(row(&registry, "hl7.fhir.bundle"));
    assert_tag(
        &fhir,
        &[K("resourceType")],
        JsonKind::String,
        TypeTag::String,
    );
    assert_tag(
        &fhir,
        &[K("multipleBirthInteger")],
        JsonKind::Number,
        TypeTag::Integer,
    );
    assert_tag(
        &fhir,
        &[K("valueQuantity"), K("value")],
        JsonKind::Number,
        TypeTag::Decimal,
    );
    assert_tag(
        &fhir,
        &[
            K("extension"),
            I(0),
            K("extension"),
            I(1),
            K("valueDecimal"),
        ],
        JsonKind::Number,
        TypeTag::Decimal,
    );
    assert_unbound(&fhir, &[K("text"), K("div")], JsonKind::String);
    assert_unbound(&fhir, &[K("data")], JsonKind::String);
    assert_unbound(&fhir, &[K("notInSchema")], JsonKind::String);
}

#[test]
fn pdt_map_preserves_pinned_operative_and_fail_closed_bindings() {
    let registry = registry();
    let pdt = load(row(&registry, "sg.gov.moh.pdt-healthcert"));
    assert_tag(&pdt, &[K("id")], JsonKind::String, TypeTag::String);
    assert_tag(&pdt, &[K("type"), I(0)], JsonKind::String, TypeTag::String);
    assert_unbound(&pdt, &[K("type")], JsonKind::Array);
    assert_tag(
        &pdt,
        &[
            K("fhirBundle"),
            K("entry"),
            I(0),
            K("resource"),
            K("valueQuantity"),
            K("value"),
        ],
        JsonKind::Number,
        TypeTag::Decimal,
    );
    assert_unbound(&pdt, &[K("$template"), K("name")], JsonKind::String);
    assert_unbound(
        &pdt,
        &[K("notarisationMetadata"), K("reference")],
        JsonKind::String,
    );
    assert_unbound(&pdt, &[K("issuerAddedEmptyArray")], JsonKind::Array);
    assert_unbound(&pdt, &[K("issuerAddedEmptyObject")], JsonKind::Object);
}

#[test]
fn recovery_map_preserves_pinned_operative_and_fail_closed_bindings() {
    let registry = registry();
    let recovery = load(row(&registry, "sg.gov.moh.recovery-healthcert"));
    assert_tag(
        &recovery,
        &[K("validUntil")],
        JsonKind::String,
        TypeTag::String,
    );
    assert_unbound(&recovery, &[K("type"), I(0)], JsonKind::String);
    assert_unbound(&recovery, &[K("issuerAdded")], JsonKind::String);
}

#[test]
fn vaccination_map_preserves_pinned_operative_and_fail_closed_bindings() {
    let registry = registry();
    let vaccination = load(row(&registry, "sg.gov.moh.vaccination-healthcert"));
    assert_tag(
        &vaccination,
        &[K("attachments")],
        JsonKind::Array,
        TypeTag::EmptyArray,
    );
    assert_tag(
        &vaccination,
        &[K("attachments"), I(0)],
        JsonKind::Object,
        TypeTag::EmptyObject,
    );
    assert_tag(
        &vaccination,
        &[K("fhirBundle"), K("entry"), I(0), K("birthDate")],
        JsonKind::String,
        TypeTag::String,
    );
    assert_unbound(
        &vaccination,
        &[
            K("fhirBundle"),
            K("entry"),
            I(0),
            K("resource"),
            K("birthDate"),
        ],
        JsonKind::String,
    );
    assert_unbound(
        &vaccination,
        &[
            K("notarisationMetadata"),
            K("signedEuHealthCerts"),
            I(0),
            K("dose"),
        ],
        JsonKind::Number,
    );
    assert_unbound(
        &vaccination,
        &[
            K("notarisationMetadata"),
            K("signedEuHealthCerts"),
            I(0),
            K("expiryDateTime"),
        ],
        JsonKind::String,
    );
    assert_unbound(
        &vaccination,
        &[K("notarisationMetadata"), K("issuerAdded")],
        JsonKind::String,
    );
}

#[test]
fn exact_bytes_and_strict_json_are_enforced_before_artifact_interpretation() {
    let registry = registry();
    let row = row(&registry, EXPECTED_MAPS[0].0);
    let mut tampered = artifact_bytes(row);
    tampered.push(b' ');

    assert_eq!(
        DfaTypeMap::from_exact_bytes(&tampered, &row.id)
            .expect_err("a byte change must not retain the registry identity"),
        Error::TypeMapIdMismatch
    );

    let malformed = b"{";
    assert!(matches!(
        DfaTypeMap::from_exact_bytes(malformed, &content_id(malformed)),
        Err(Error::InvalidJson { .. })
    ));

    let invalid_utf8 = [0xff];
    assert!(matches!(
        DfaTypeMap::from_exact_bytes(&invalid_utf8, &content_id(&invalid_utf8)),
        Err(Error::InvalidUtf8(_))
    ));

    let duplicate_member = br#"{"format":"ROAX-TYPE-MAP/1","format":"ROAX-TYPE-MAP/1"}"#;
    assert_eq!(
        DfaTypeMap::from_exact_bytes(duplicate_member, &content_id(duplicate_member))
            .expect_err("duplicate JSON object names must have no interpretation"),
        Error::DuplicateKey {
            key: "format".to_owned(),
        }
    );
}

fn synthetic_artifact(key: &str) -> serde_json::Value {
    json!({
        "format": "ROAX-TYPE-MAP/1",
        "typeMapVersion": "1.0.0",
        "recordType": "org.roax.test.lookup",
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
                {
                    "id": "s0",
                    "keys": [{ "key": key, "to": "s1" }]
                },
                {
                    "id": "s1",
                    "bindings": [{
                        "jsonKind": "string",
                        "tag": 2,
                        "basis": ["schema-type"],
                        "sources": ["test-source"]
                    }]
                }
            ]
        }
    })
}

fn encoded_artifact(artifact: &serde_json::Value) -> Vec<u8> {
    serde_json::to_vec(artifact).expect("synthetic artifact must serialize")
}

fn exact_json_number(literal: &str) -> serde_json::Value {
    let value: serde_json::Value = serde_json::from_str(literal).expect("valid exact JSON number");
    assert!(value.is_number());
    value
}

#[test]
fn malformed_dfa_transition_keys_are_rejected() {
    let non_nfc = encoded_artifact(&synthetic_artifact("e\u{301}"));
    assert_eq!(
        DfaTypeMap::from_exact_bytes(&non_nfc, &content_id(&non_nfc))
            .expect_err("transition keys must already be NFC"),
        Error::InvalidTypeMap("transition key is not NFC".to_owned())
    );

    let mut duplicate = synthetic_artifact("key");
    let keys = duplicate["automaton"]["states"][0]["keys"]
        .as_array_mut()
        .expect("synthetic root state keys");
    keys.push(keys[0].clone());
    let duplicate = encoded_artifact(&duplicate);
    assert_eq!(
        DfaTypeMap::from_exact_bytes(&duplicate, &content_id(&duplicate))
            .expect_err("a state cannot contain duplicate KEY transitions"),
        Error::InvalidTypeMap("duplicate KEY transition".to_owned())
    );
}

#[test]
fn nested_unknown_carrier_members_are_rejected() {
    let mut artifact = synthetic_artifact("key");
    artifact["automaton"]["states"][1]["bindings"][0]["unexpected"] = json!(true);
    let bytes = encoded_artifact(&artifact);

    let error = DfaTypeMap::from_exact_bytes(&bytes, &content_id(&bytes))
        .expect_err("unknown members inside bindings must be rejected");
    assert!(
        matches!(&error, Error::InvalidTypeMap(message) if message.contains("unknown field `unexpected`")),
        "unexpected error: {error}"
    );
}

#[test]
fn source_uris_match_the_executable_checker_url_semantics() {
    let mut artifact = synthetic_artifact("key");
    artifact["sourceSchemas"][0]["uri"] = json!("https://");
    let bytes = encoded_artifact(&artifact);

    let error = DfaTypeMap::from_exact_bytes(&bytes, &content_id(&bytes))
        .expect_err("a special-scheme URL without a host must be rejected");
    assert!(
        matches!(&error, Error::InvalidTypeMap(message) if message.contains("sourceSchema")),
        "unexpected error: {error}"
    );
}

#[test]
fn explicit_null_is_rejected_for_all_omittable_carrier_members() {
    let cases = [
        ("parentTypeMapId", "", "parentTypeMapId"),
        ("state keys", "/automaton/states/0", "keys"),
        ("state anyIndex", "/automaton/states/0", "anyIndex"),
        ("state bindings", "/automaton/states/1", "bindings"),
        ("state unresolved", "/automaton/states/0", "unresolved"),
        (
            "state structurallyUntypedObject",
            "/automaton/states/0",
            "structurallyUntypedObject",
        ),
        ("coverage byTag", "/coverage/byTag", "2"),
        ("coverage byBasis", "/coverage/byBasis", "schema-type"),
    ];

    for (label, object_pointer, member) in cases {
        let mut artifact = synthetic_artifact("key");
        let object = if object_pointer.is_empty() {
            artifact.as_object_mut()
        } else {
            artifact
                .pointer_mut(object_pointer)
                .and_then(serde_json::Value::as_object_mut)
        }
        .unwrap_or_else(|| panic!("synthetic object for {label}"));
        object.insert(member.to_owned(), serde_json::Value::Null);
        let bytes = encoded_artifact(&artifact);

        let error = DfaTypeMap::from_exact_bytes(&bytes, &content_id(&bytes))
            .expect_err("explicit null in an omittable carrier member must be rejected");
        assert!(
            matches!(&error, Error::InvalidTypeMap(message) if message.contains("invalid type: null")),
            "unexpected error for {label}: {error}"
        );
    }
}

#[test]
fn mathematical_integer_number_forms_are_accepted_without_float_conversion() {
    let mut artifact = synthetic_artifact("key");
    artifact["automaton"]["states"][1]["bindings"][0]["tag"] = exact_json_number("2.0");
    artifact["coverage"]["states"] = exact_json_number("2e0");
    artifact["coverage"]["keyTransitions"] = exact_json_number("10e-1");
    artifact["coverage"]["indexTransitions"] = exact_json_number("-0.0e999999999999999999999");
    artifact["coverage"]["resolvedOutputs"] = exact_json_number("1.0");
    artifact["coverage"]["unresolvedOutputStates"] = exact_json_number("0e999999999999999999999");
    artifact["coverage"]["structurallyUntypedObjectSourceNodes"] = exact_json_number("0.0");
    artifact["coverage"]["structurallyUntypedObjectStates"] = exact_json_number("0e0");
    artifact["coverage"]["byTag"]["2"] = exact_json_number("1e+0");
    artifact["coverage"]["byBasis"]["schema-type"] = exact_json_number("10e-1");
    let bytes = encoded_artifact(&artifact);

    DfaTypeMap::from_exact_bytes(&bytes, &content_id(&bytes))
        .expect("mathematically integral JSON numbers must satisfy integer carriers");
}

#[test]
fn invalid_mathematical_integer_number_forms_are_rejected() {
    let cases = [
        (
            "non-integral binding tag",
            "/automaton/states/1/bindings/0",
            "tag",
            "2.5",
        ),
        (
            "negative binding tag",
            "/automaton/states/1/bindings/0",
            "tag",
            "-1",
        ),
        (
            "binding tag above schema maximum",
            "/automaton/states/1/bindings/0",
            "tag",
            "9",
        ),
        (
            "non-integral coverage count",
            "/coverage",
            "states",
            "12e-1",
        ),
        ("negative coverage count", "/coverage", "states", "-1"),
        (
            "overflowing coverage count",
            "/coverage",
            "states",
            "1e999999999999999999999",
        ),
        (
            "non-integral sparse tag count",
            "/coverage/byTag",
            "2",
            "1.1",
        ),
        (
            "negative sparse basis count",
            "/coverage/byBasis",
            "schema-type",
            "-1e0",
        ),
    ];

    for (label, object_pointer, member, literal) in cases {
        let mut artifact = synthetic_artifact("key");
        artifact
            .pointer_mut(object_pointer)
            .and_then(serde_json::Value::as_object_mut)
            .unwrap_or_else(|| panic!("synthetic object for {label}"))
            .insert(member.to_owned(), exact_json_number(literal));
        let bytes = encoded_artifact(&artifact);

        let error = DfaTypeMap::from_exact_bytes(&bytes, &content_id(&bytes))
            .expect_err("invalid mathematical integer carrier must be rejected");
        assert!(
            matches!(error, Error::InvalidTypeMap(_)),
            "unexpected error for {label}: {error}"
        );
    }
}

#[test]
fn stale_coverage_counts_are_rejected() {
    let mut artifact = synthetic_artifact("key");
    artifact["coverage"]["resolvedOutputs"] = json!(2);
    let bytes = encoded_artifact(&artifact);

    assert_eq!(
        DfaTypeMap::from_exact_bytes(&bytes, &content_id(&bytes))
            .expect_err("coverage must match the materialized DFA"),
        Error::InvalidTypeMap("coverage metadata is invalid or stale".to_owned())
    );
}

#[test]
fn noncanonical_breadth_first_state_numbering_is_rejected() {
    let mut artifact = synthetic_artifact("a");
    artifact["automaton"]["states"][0]["keys"][0]["to"] = json!("s2");
    artifact["automaton"]["states"][0]["keys"]
        .as_array_mut()
        .expect("synthetic root state keys")
        .push(json!({ "key": "b", "to": "s1" }));
    artifact["automaton"]["states"]
        .as_array_mut()
        .expect("synthetic states")
        .push(json!({ "id": "s2" }));
    artifact["coverage"]["states"] = json!(3);
    artifact["coverage"]["keyTransitions"] = json!(2);
    let bytes = encoded_artifact(&artifact);

    assert_eq!(
        DfaTypeMap::from_exact_bytes(&bytes, &content_id(&bytes))
            .expect_err("state IDs must follow canonical breadth-first discovery"),
        Error::InvalidTypeMap(
            "DFA state numbering is not canonical breadth-first order".to_owned()
        )
    );
}

#[test]
fn issuer_child_artifacts_require_parent_and_additivity_validation() {
    let mut artifact = synthetic_artifact("key");
    artifact["parentTypeMapId"] = json!(format!("sha256:{}", "1".repeat(64)));
    artifact["scope"] = json!({
        "kind": "issuers",
        "issuerIds": ["did:example:issuer"]
    });
    artifact["addedSelectors"] = json!([{
        "segments": [{ "key": "issuerExtension" }],
        "jsonKind": "string",
        "tag": exact_json_number("2e0"),
        "evidence": ["test-source"]
    }]);
    let bytes = encoded_artifact(&artifact);

    assert_eq!(
        DfaTypeMap::from_exact_bytes(&bytes, &content_id(&bytes))
            .expect_err("standalone loading cannot validate child additivity"),
        Error::InvalidTypeMap(
            "issuer child artifacts require parent and additivity validation".to_owned()
        )
    );
}

#[test]
fn the_lookup_matches_a_key_under_nfc_on_both_sides() {
    // Ruled decision D14a. The artifact declares the COMPOSED spelling, and the two
    // structured paths below render identically to a reader.
    //
    // Under the retired raw reading the decomposed path resolved to
    // `UnknownTypeBinding` while its composed twin resolved to STRING, so one of two
    // records that look the same was refused outright by the fail-closed rule. Under
    // D14a both resolve to the same tag, which is what makes the two spellings behave
    // identically end to end.
    let bytes = encoded_artifact(&synthetic_artifact("\u{e9}"));
    let id = content_id(&bytes);
    let composed = structured_path(&[K("\u{e9}")]);
    let decomposed = structured_path(&[K("e\u{301}")]);
    // The crux of the ruling, asserted rather than described: the two paths ENCODE
    // IDENTICALLY, because `Path::encode` normalizes every KEY segment under
    // ROAX-CANON/1 section 5.1. So the composed and decomposed records commit the same
    // bytes, and a raw lookup would have decided admissibility on a spelling neither
    // root records.
    assert_eq!(composed.encode(), decomposed.encode());
    assert_ne!(composed, decomposed);

    let map = DfaTypeMap::from_exact_bytes(&bytes, &id).expect("valid synthetic type map");
    assert_eq!(
        map.resolve(&composed, JsonKind::String),
        Ok(TypeTag::String)
    );
    assert_eq!(
        map.resolve(&decomposed, JsonKind::String),
        Ok(TypeTag::String)
    );

    // Both sides are normalized rather than only the segment key: an artifact whose
    // transition key is NOT already NFC is refused at load, so a DECOMPOSED artifact
    // key can never become a live transition that only a decomposed record reaches.
    let decomposed_artifact = encoded_artifact(&synthetic_artifact("e\u{301}"));
    assert_eq!(
        DfaTypeMap::from_exact_bytes(&decomposed_artifact, &content_id(&decomposed_artifact))
            .expect_err("a non-NFC transition key must be refused"),
        Error::InvalidTypeMap("transition key is not NFC".to_owned())
    );
}
