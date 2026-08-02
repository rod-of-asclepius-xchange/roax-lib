use roax_canon::{
    disclose, fold_inclusion_proof_untrusted, issue_full_copy, merkle_tree_hash, parse_envelope,
    verify_disclosed, CommitmentContext, Disclosure, Error, Hash, HashAlgorithm, Issuer, JsonKind,
    JsonValue, Ordering, Path, Profile, ReservedLeafSet, SchemaValidator, Segment, TypeResolver,
    TypeTag, VerificationPolicy,
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
        ordering: Ordering::default(),
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
            anchored_ordering: Ordering::default(),
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
                    anchored_ordering: Ordering::default(),
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
                anchored_ordering: Ordering::default(),
            },
        ),
        Err(Error::ReservedNamespaceCollision)
    );
}

/// A `hash`-ordered disclosure verifies only under the registry that names that ordering.
///
/// Pinned HERE because no corpus vector reaches it: every class-20 round-trip vector is
/// path-ordered, so nothing in the corpus asks a library to issue a `hash`-ordered copy and then
/// verify it. That is the surface on which the TypeScript library was found issuing an envelope
/// its own verifier refused, which is exactly what conformance corpus class 20 exists to catch.
#[test]
fn ordering_comes_from_the_registry_and_a_disagreeing_one_is_refused() {
    let record = JsonValue::from_slice(br#"{"x":"value"}"#).expect("record");
    for issued in [Ordering::Path, Ordering::Hash] {
        let mut issued_context = context();
        issued_context.ordering = issued;
        let (full, commitment) =
            issue_full_copy(&record, &issued_context, &StringProfile).expect("commitment");

        // The outer member is SELF-DESCRIPTION and is asserted here because no verifier reads it,
        // so nothing else in this suite can see it go missing. Both envelope schemas define its
        // ABSENCE as meaning `path`, so a hash-ordered copy without it would assert an ordering
        // it was not issued under.
        let full_json = full.to_json_value();
        let JsonValue::Object(ref members) = full_json else {
            panic!("a full copy is a JSON object");
        };
        let declared = members.iter().find(|(name, _)| name == "ordering");
        match issued {
            Ordering::Path => assert!(declared.is_none(), "a path-ordered copy emits no member"),
            Ordering::Hash => assert_eq!(
                declared.map(|(_, value)| value),
                Some(&JsonValue::String("hash".into())),
            ),
        }

        // Specification section 11.2: the ordering leaf is committed for `hash` and for nothing
        // else, so the two orderings differ in leaf COUNT as well as in placement.
        let has_ordering_leaf = commitment
            .leaves()
            .iter()
            .any(|leaf| leaf.path().segments() == [Segment::Key("roax.ordering".into())]);
        assert_eq!(has_ordering_leaf, issued == Ordering::Hash);

        let disclosure = disclose(&commitment, &StringProfile, &[]).expect("disclosure");
        // H2: the ordering comes from the anchoring registry. BOTH answers are exercised, so the
        // refusal of the wrong one is evidence rather than an untested branch (section 9.5).
        for registry_says in [Ordering::Path, Ordering::Hash] {
            let outcome = verify_disclosed(
                &disclosure,
                &StringProfile,
                VerificationPolicy {
                    anchored_root: commitment.root(),
                    anchored_hash_algorithm: HashAlgorithm::Sha256,
                    anchored_ordering: registry_says,
                },
            );
            assert_eq!(
                outcome.is_ok(),
                registry_says == issued,
                "issued {}, registry {}",
                issued.name(),
                registry_says.name(),
            );
        }
    }
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
