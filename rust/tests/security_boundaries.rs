use roax_canon::{
    disclose, fold_inclusion_proof_untrusted, issue_full_copy, merkle_tree_hash, parse_envelope,
    verify_disclosed, CommitmentContext, Disclosure, Error, Hash, HashAlgorithm, Issuer, JsonKind,
    JsonValue, Path, Profile, ReservedLeafSet, SchemaValidator, TypeResolver, TypeTag,
    VerificationPolicy,
};

#[derive(Debug)]
struct StringProfile;

impl SchemaValidator for StringProfile {
    fn validate_record(&self, _record: &JsonValue) -> roax_canon::Result<()> {
        Ok(())
    }
}

impl TypeResolver for StringProfile {
    fn resolve(&self, _path: &Path, kind: JsonKind) -> roax_canon::Result<TypeTag> {
        if kind == JsonKind::String {
            Ok(TypeTag::String)
        } else {
            Err(Error::UnknownTypeBinding {
                path: Path::new(),
                kind,
            })
        }
    }

    fn ensure_lookup_decision_independent(
        &self,
        _path: &Path,
        _kind: JsonKind,
    ) -> roax_canon::Result<()> {
        Ok(())
    }
}

impl Profile for StringProfile {
    fn record_type(&self) -> &'static str {
        "org.example.record"
    }

    fn validate_context(&self, context: &CommitmentContext) -> roax_canon::Result<()> {
        if context.record_type == self.record_type()
            && context.schema_version == "opaque"
            && context.reserved_leaf_set == ReservedLeafSet::EnvelopeV1
        {
            Ok(())
        } else {
            Err(Error::TypeMapIdentityMismatch)
        }
    }

    fn resolver(&self) -> &dyn TypeResolver {
        self
    }

    fn minimum_disclosure_paths(&self) -> Vec<Path> {
        Vec::new()
    }
}

#[derive(Debug)]
struct ReservedFloorProfile;

impl SchemaValidator for ReservedFloorProfile {
    fn validate_record(&self, record: &JsonValue) -> roax_canon::Result<()> {
        StringProfile.validate_record(record)
    }
}

impl TypeResolver for ReservedFloorProfile {
    fn resolve(&self, path: &Path, kind: JsonKind) -> roax_canon::Result<TypeTag> {
        StringProfile.resolve(path, kind)
    }

    fn ensure_lookup_decision_independent(
        &self,
        path: &Path,
        kind: JsonKind,
    ) -> roax_canon::Result<()> {
        StringProfile.ensure_lookup_decision_independent(path, kind)
    }
}

impl Profile for ReservedFloorProfile {
    fn record_type(&self) -> &str {
        StringProfile.record_type()
    }

    fn validate_context(&self, context: &CommitmentContext) -> roax_canon::Result<()> {
        StringProfile.validate_context(context)
    }

    fn resolver(&self) -> &dyn TypeResolver {
        self
    }

    fn minimum_disclosure_paths(&self) -> Vec<Path> {
        vec![Path::new().with_key("roax.issuer.keyId")]
    }
}

fn context() -> CommitmentContext {
    CommitmentContext {
        hash_algorithm: HashAlgorithm::Sha256,
        reserved_leaf_set: ReservedLeafSet::EnvelopeV1,
        record_type: "org.example.record".into(),
        schema_version: "opaque".into(),
        type_map: None,
        record_id: "record-1".into(),
        issuer: Issuer {
            id: "did:example:issuer".into(),
            key_id: None,
        },
    }
}

fn parsed_disclosure(
    segments: &str,
    tag: &str,
    value_member: &str,
    root: Hash,
    leaf_count: u64,
    audit_path: &[Hash],
) -> Disclosure {
    let audit_path = audit_path
        .iter()
        .map(|hash| format!("\"{}\"", hex::encode(hash)))
        .collect::<Vec<_>>()
        .join(",");
    let envelope = format!(
        r#"{{
          "canon":"ROAX-CANON/1",
          "hashAlg":"SHA-256",
          "recordType":"org.example.record",
          "schemaVersion":"opaque",
          "recordId":"record-1",
          "root":"{}",
          "leafCount":{},
          "issuer":{{"id":"did:example:issuer"}},
          "disclosure":{{"mode":"selective","leaves":[{{
            "segments":{segments},
            "index":0,
            "tag":{tag},
            {value_member}
            "salt":"09090909090909090909090909090909",
            "auditPath":[{audit_path}]
          }}]}}
        }}"#,
        hex::encode(root),
        leaf_count,
    );
    let parsed =
        parse_envelope(envelope.as_bytes(), ReservedLeafSet::EnvelopeV1).expect("test envelope");
    let roax_canon::ParsedEnvelope::Disclosed(disclosure) = parsed else {
        panic!("test envelope must be disclosed");
    };
    disclosure
}

#[test]
fn untrusted_fold_accepts_the_documented_forged_size_but_disclosure_does_not() {
    let raw_leaves: Vec<Hash> = (0_u8..32)
        .map(|byte| {
            let mut hash = [0; 32];
            hash[0] = byte;
            hash
        })
        .collect();
    let left = merkle_tree_hash(&raw_leaves[..4]);
    let proof = [
        merkle_tree_hash(&raw_leaves[4..8]),
        merkle_tree_hash(&raw_leaves[8..16]),
        merkle_tree_hash(&raw_leaves[16..32]),
    ];
    let root = merkle_tree_hash(&raw_leaves);
    assert!(fold_inclusion_proof_untrusted(&left, 0, 8, &proof, &root));

    let disclosure = parsed_disclosure(
        r#"[{"key":"x"}]"#,
        "2",
        r#""value":"not-an-internal-node","#,
        root,
        8,
        &proof,
    );
    let error = verify_disclosed(
        &disclosure,
        &StringProfile,
        VerificationPolicy {
            anchored_root: root,
            anchored_hash_algorithm: HashAlgorithm::Sha256,
        },
    )
    .expect_err("the safe boundary must recompute the leaf hash");
    assert_eq!(error, Error::InvalidInclusionProof);
}

#[test]
fn disclosed_record_paths_cannot_enter_any_reserved_subtree() {
    for segments in [
        r#"[{"key":"roax.extension"},{"key":"child"}]"#,
        r#"[{"key":"roax.typeMap.id"}]"#,
    ] {
        let disclosure = parsed_disclosure(segments, "2", r#""value":"x","#, [0; 32], 5, &[]);
        assert_eq!(
            verify_disclosed(
                &disclosure,
                &StringProfile,
                VerificationPolicy {
                    anchored_root: [0; 32],
                    anchored_hash_algorithm: HashAlgorithm::Sha256,
                },
            ),
            Err(Error::ReservedNamespaceCollision)
        );
    }
}

#[test]
fn disclosure_parser_requires_canonical_numeric_carriers() {
    for (tag, value) in [("3", "-0"), ("4", "1e2")] {
        let envelope = format!(
            r#"{{
              "canon":"ROAX-CANON/1",
              "hashAlg":"SHA-256",
              "recordType":"org.example.record",
              "schemaVersion":"opaque",
              "recordId":"record-1",
              "root":"{}",
              "leafCount":5,
              "issuer":{{"id":"did:example:issuer"}},
              "disclosure":{{"mode":"selective","leaves":[{{
                "segments":[{{"key":"x"}}],
                "index":0,
                "tag":{tag},
                "value":"{value}",
                "salt":"03030303030303030303030303030303",
                "auditPath":[]
              }}]}}
            }}"#,
            "0".repeat(64),
        );
        assert!(matches!(
            parse_envelope(envelope.as_bytes(), ReservedLeafSet::EnvelopeV1),
            Err(Error::InvalidValueCarrier | Error::InvalidInteger | Error::InvalidDecimal)
        ));
    }
}

#[test]
fn envelope_anchor_is_closed_and_schema_shaped() {
    let invalid = br#"{
      "canon":"ROAX-CANON/1",
      "hashAlg":"SHA-256",
      "recordType":"org.example.record",
      "schemaVersion":"opaque",
      "recordId":"record-1",
      "root":"0000000000000000000000000000000000000000000000000000000000000000",
      "leafCount":5,
      "issuer":{"id":"did:example:issuer"},
      "anchor":{"chainId":1,"registry":"0x0000000000000000000000000000000000000000","seed":"secret"},
      "record":{},
      "salts":[]
    }"#;
    assert!(matches!(
        parse_envelope(invalid, ReservedLeafSet::EnvelopeV1),
        Err(Error::InvalidEnvelope(_))
    ));
}

#[test]
fn schema_integer_metadata_accepts_integral_fraction_and_exponent_tokens() {
    let input = br#"{
      "canon":"ROAX-CANON/1",
      "hashAlg":"SHA-256",
      "recordType":"org.example.record",
      "schemaVersion":"opaque",
      "recordId":"record-1",
      "root":"0000000000000000000000000000000000000000000000000000000000000000",
      "leafCount":5e0,
      "issuer":{"id":"did:example:issuer"},
      "anchor":{"chainId":0.0,"registry":"0x0000000000000000000000000000000000000000"},
      "disclosure":{"mode":"selective","leaves":[{
        "segments":[{"key":"items"},{"index":0.0}],
        "index":0e0,
        "tag":2.0,
        "value":"x",
        "salt":"00000000000000000000000000000000",
        "auditPath":[]
      }]}
    }"#;
    assert!(parse_envelope(input, ReservedLeafSet::EnvelopeV1).is_ok());
}

#[test]
fn commitment_context_rejects_schema_invalid_identity_hints() {
    let mut invalid = context();
    invalid.record_id.clear();
    assert!(matches!(invalid.validate(), Err(Error::InvalidContext(_))));

    let mut invalid = context();
    invalid.issuer.id = "relative/path".into();
    assert!(matches!(invalid.validate(), Err(Error::InvalidContext(_))));
}

#[test]
fn profile_floor_cannot_promote_a_reserved_leaf() {
    let record = JsonValue::from_slice(br#"{"x":"value"}"#).expect("record");
    let (_, commitment) = issue_full_copy(&record, &context(), &StringProfile).expect("commitment");
    assert_eq!(
        disclose(&commitment, &ReservedFloorProfile, &[]),
        Err(Error::ReservedNamespaceCollision)
    );

    let disclosure = disclose(&commitment, &StringProfile, &[]).expect("disclosure");
    assert_eq!(
        verify_disclosed(
            &disclosure,
            &ReservedFloorProfile,
            VerificationPolicy {
                anchored_root: commitment.root(),
                anchored_hash_algorithm: HashAlgorithm::Sha256,
            },
        ),
        Err(Error::ReservedNamespaceCollision)
    );
}

#[test]
fn disclosure_retains_the_context_that_created_the_commitment() {
    let record = JsonValue::from_slice(br#"{"x":"value"}"#).expect("record");
    let issued_context = context();
    let (_, commitment) =
        issue_full_copy(&record, &issued_context, &StringProfile).expect("commitment");
    let mut unrelated_context = issued_context.clone();
    unrelated_context.record_id = "record-2".into();
    assert_ne!(commitment.context(), &unrelated_context);

    let disclosure = disclose(&commitment, &StringProfile, &[]).expect("disclosure");
    assert_eq!(disclosure.context(), &issued_context);
}
