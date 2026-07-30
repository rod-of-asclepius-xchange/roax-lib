# Profile: Singapore MOH PDT HealthCert 2.0

**`recordType`:** `sg.gov.moh.pdt-healthcert`
**`schemaVersion`:** `2.0`
**Status:** the base profile map is published as [`type-maps/sg.gov.moh.pdt-healthcert-2.0.json`](../../type-maps/sg.gov.moh.pdt-healthcert-2.0.json) at exact artifact ID `sha256:4f8cecc59c85101b8b567658c90651bcbf8f9d4dc279571aa40a03cf04f434ff`.
The published base artifact intentionally excludes 20 path/kind pairs present in the endorsed sample because no clinic or endorsed composition artifact has been selected, the lite-FHIR `Narrative.div` and four `base64Binary` slots remain unresolved, and 65 Bundle-reachable lite-FHIR object nodes omit an object type, as audited in [`docs/type-maps.md`](../type-maps.md) sections 1.2, 1.3, 1.5 and 2.

PDT is the pre-departure test certificate.
It is the most structurally complex of the three healthcert families, because it is not one schema but three compositional views of a workflow.

---

## 1. Record shape

The base schema requires six fields:

```
id, version, type, validFrom, fhirVersion, fhirBundle
```

- `version` is fixed to `pdt-healthcert-v2.0`.
- `type` is either one of `PCR`, `ART`, `SER`, `LAMP`, **or** a non-empty array of those values with unique items.
  Both forms are legal, which matters for the type map: the same path is sometimes a string and sometimes an array.
- `validFrom` is a date-time.
- `fhirBundle` references the **lite** FHIR 4.0.1 `Bundle` definition, so its entries carry a nested `.resource`.
  This is the genuine FHIR Bundle layout, unlike the vaccination profile.
- The optional `logo` is described only as base64.
  There is no encoding pattern.
- **The top object does not set `additionalProperties: false`,** so extensions are allowed.
  That is the opposite of the vaccination profile and it directly affects how the fail-closed rule behaves here - see section 5.

## 2. Three schemas, one workflow

| File | Composition |
|---|---|
| `schema.json` | Base clinical content. |
| `clinic-provider-schema.json` | An `allOf` of the base content and OpenAttestation 2.0. |
| `endorsed-schema.json` | An `allOf` of the base content and the Notarise OpenAttestation profile, which itself composes OA 2.0 and Notarise metadata. |

The implied sequence:

```
base PDT clinical record
        |
        v
clinic-issued OA record
  + clinic issuer / renderer
        |
        v
government-endorsed OA record
  + masked identity in the visible outer PDT
  + Notarise metadata / optional EU certificate
  + the original clinic OA document as a base64 attachment
```

**This is confirmed, not inferred, for the attachment step.**
The `text/open-attestation` attachment in the endorsed sample was decoded and found to be an OA v2 wrapped clinic document: its unsalted payload matches the clinic sample, and its `signature.targetHash` and `merkleRoot` are the same single-document digest, recomputed independently from 119 flattened field leaves with zero obfuscated leaves.

**But the workflow is not schema-enforced.**
The endorsed schema does not require an attachment, a masked national identifier, a new `id`, a distinct endorser, or any cryptographic or content relationship between the visible endorsed payload and the attachment.
The clinic and endorsed test suites contain one happy-path assertion each.

So the sequence above is strong fixture evidence about intent, and a weak guarantee about any particular document.

## 3. Type-map scope

The published base map contains only these sources:

- The lite FHIR 4.0.1 definitions reachable from `Bundle`, as audited in [`fhir.md`](fhir.md) section 4.
- The seven PDT base fields declared at `references/schemata/src/sg/gov/moh/pdt-healthcert/2.0/schema.json`, read at upstream commit `09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa`.

The executable DFA has 317 states, 639 exact KEY transitions, 160 INDEX transitions and 310 resolved outputs, as reported in [`docs/type-maps.md`](../type-maps.md) section 2.3.
The finite scalar audit counts 331 declared units, of which 319 are confident, seven use an operative FHIR element-name inference and five remain unresolved, with the 20 sample-only pairs reported separately, as audited in [`docs/type-maps.md`](../type-maps.md) section 2.2.
Separately, 65 reached lite-FHIR object-applicator source nodes collapse to 63 marked DFA states because those definitions omit `type: "object"`, as audited in [`docs/type-maps.md`](../type-maps.md) sections 1.5 and 2.3.
Its exact artifact ID, `recordType` and `schemaVersion` are checked together when selecting this map, under [`docs/type-maps.md`](../type-maps.md) section 4 and specification section 4.2.

The base map does **not** include OpenAttestation 2.0 or Notarise 1.0 merely because the clinic and endorsed composition schemas exist.
The endorsed sample reaches 20 path/kind pairs that the base schema does not declare, and every one remains non-operative pending a versioned composition ruling or issuer extension, as listed with evidence in [`docs/type-maps.md`](../type-maps.md) section 1.2.
The shipped endorsed sample is therefore uncommittable under this exact fail-closed base map.

Two specific hazards:

- **`type` is polymorphic by design** because the base schema admits a scalar string or an array of strings.
  The published DFA carries outputs for both observed kinds rather than inferring either from JSON syntax, under specification section 4.2 and [`docs/type-maps.md`](../type-maps.md) section 3.
- **`logo` is an operative STRING binding, while `attachments[*].data` is only a proposal.**
  The base schema declares `logo` as a string, but the undeclared attachment path cannot become operative until the composition is selected through [`docs/type-maps.md`](../type-maps.md) section 5.

## 4. Non-redactable paths

| Path | Why |
|---|---|
| `roax.recordType`, `roax.schemaVersion`, `roax.typeMap.id`, `roax.recordId`, `roax.issuer.id` | The reserved floor (spec section 11.2), which every profile carries. `roax.recordType`, `roax.schemaVersion` and `roax.typeMap.id` are mandatory by arithmetic because the verifier checks the exact artifact ID and its two profile selectors before resolving any disclosed leaf ([`docs/type-maps.md`](../type-maps.md) section 4). `roax.recordId` and `roax.issuer.id` are mandatory by policy, so a disclosed copy says which record it is and who issued it. `roax.recordId` was arithmetic until decision D4 was ruled D4b on 2026-07-28, which removed the salt preimage it used to be an input to. `roax.issuer.keyId` is committed but OPTIONAL to disclose under specification section 11.2, because requiring it would break key rotation on already-anchored records. |
| `version` | Pins `pdt-healthcert-v2.0`. Without it a disclosed copy does not say which healthcert version it is. |
| `type` | The test kind. A PDT certificate that does not say whether it was PCR or ART is not a test certificate. |
| `validFrom` | A validity claim with no start is not checkable. |

`validUntil` is deliberately absent from this list because the PDT base schema does not have one; that is the recovery profile.

## 5. Interaction with the fail-closed rule - read this

The PDT base object **allows additional properties.**
So a real PDT record may legitimately carry fields the type map has never seen.

**Decision D7 is ruled D7a - fail closed, permanently** (2026-07-28, `docs/decisions.md`).
Such a record is rejected at issuance rather than being given a guessed type tag, under specification section 4.2.

For this profile, the exact DFA is an allowlist that issuers extend through the immutable child-artifact workflow in [`docs/type-maps.md`](../type-maps.md) section 5.
The artifact format is [`schemas/type-map-artifact-1.0.json`](../../schemas/type-map-artifact-1.0.json), and a child carries a complete effective DFA plus the exact parent ID, new structured selectors and issuer scope.
The issued record commits the child's exact ID at `roax.typeMap.id`, so two issuers may extend independently without either branch silently becoming shared policy, under [`docs/type-maps.md`](../type-maps.md) sections 4 and 5.1.

An issuer extension MUST be additive and MUST preserve every parent transition and output at the logical DFA level, under [`docs/type-maps.md`](../type-maps.md) sections 5 and 5.1 and specification section 12.2.
A correction to an existing binding is therefore a replacement profile artifact rather than an issuer extension, while records already anchored under the old exact ID keep verifying under that artifact.

The 20 endorsed-sample pairs are proposals rather than bindings.
Nineteen have explicit string evidence in the composed OpenAttestation or Notarise schema, while `notarisationMetadata.signedEuHealthCerts[*].expiryDateTime` has only a date-time annotation and string examples with no declared type, as documented in [`docs/type-maps.md`](../type-maps.md) section 1.2.
The base map never chooses STRING for any of those pairs on the strength of their sample syntax.

**Why this matters more here than anywhere else.**
PDT already has the most real-world traffic of the three healthcert families, and its open-world base object means an unknown path is a routine event rather than an anomaly - the opposite of the vaccination profile, whose top-level object closes with `additionalProperties: false` (see [`vaccination-healthcert.md`](vaccination-healthcert.md) section 1).
If extending the map is slow or unclear, fail-closed becomes an adoption blocker exactly where it can least afford to be, and the pressure to "just default it to STRING for now" will arrive from a real issuer with a real record.
That is the moment refusing is hardest, which is why the refusal is normative in the specification rather than advisory, and why the extension path being fast is a deliverable rather than an aspiration.

### 5.1 Blob binding

`logo` is bound as STRING over the base64 text because the PDT base schema declares it as a string, under specification sections 4.2 and 6.3.
`attachments[*].data` is proposed as STRING from the composed OpenAttestation schema but is absent from this base artifact, as documented in [`docs/type-maps.md`](../type-maps.md) section 1.2.

Two things that ruling did change, and neither alters a byte of an existing PDT record:

- **One canonical base64 form is now pinned** - RFC 4648 section 4, standard alphabet, with padding, no line wrapping (specification section 6.3).
  This governs a `BYTES` binding rather than a `STRING` one, so it does not change the operative `logo` STRING binding.
  It matters here because the PDT schema describes `logo` only as base64 with no encoding pattern (section 6 below), so nothing upstream constrains what an issuer sends.
- **A content-addressed binding, type tag 8 `BLOB_REF`, is defined and selected by nothing** (specification section 6.5).
  **This profile does not select it**, and an implementation MUST reject a record that binds any PDT path to tag 8.
  It exists so that a future record family issuing under Poseidon - where a 14 KB blob costs about 14 ms rather than about 41 microseconds - does not need a second leaf-binding form retrofitted after five implementations already exist.

## 6. Known defects and cautions

- **`fhirVersion` is unvalidated** - example `4.0.1`, not `const` or `enum`.
  See [`fhir.md`](fhir.md) section 6.
- **`logo` has no base64 pattern**, so it is not validated as base64 at all.
- **A minimal Bundle validates.**
  `{"resourceType":"Bundle"}` satisfies `fhirBundle`.
  Confirmed by reproduction against the audited schema.

## 7. What the schema and tests do NOT enforce

The tests validate the sample, all four scalar `type` values and a multi-type certificate; they reject a missing `id`, `version` or `type`, unknown or duplicate types, a missing or malformed `validFrom`, and a missing FHIR version or bundle.

They do **not** test, and the schema does not require, that:

- the Bundle contains a Patient, an Observation or a Specimen;
- `type` agrees with the observation's method;
- the result is negative;
- references resolve;
- a test has a subject, a performer, a laboratory or a collection time;
- the external `fhirVersion` agrees with the hard-wired 4.0.1 schema;
- identifiers are UUIDs;
- the `logo` is valid base64.

These omissions agree with the schema.
They are not missing test coverage over a stricter rule; the rule is genuinely absent.

**Consequence for ROAX:** a valid `sg.gov.moh.pdt-healthcert` root proves that a particular typed payload was committed by a particular issuer.
It does not prove that the payload describes a test, still less a negative one.
Any product surface that says "negative PDT result" is making a claim the protocol layer does not support, and must derive it from the payload itself after disclosure and attribute it to the payload.

**That is now normative rather than advisory.**
Decision D13 is ruled, and specification section 2.3 states that no surface derived from this protocol may assert a clinical fact on the strength of root validity alone.
Enforcing the rules this section lists as absent - that the Bundle contains an Observation, that `type` agrees with the method, that the result is negative - belongs to the separate, independently versioned clinical-validation layer that ruling puts outside `ROAX-CANON/1`.
