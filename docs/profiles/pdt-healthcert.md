# Profile: Singapore MOH PDT HealthCert 2.0

**`recordType`:** `sg.gov.moh.pdt-healthcert`
**`schemaVersion`:** `2.0`
**Status:** draft. The type map for this profile does not exist.

PDT is the pre-departure test certificate. It is the most structurally complex of the three
healthcert families, because it is not one schema but three compositional views of a workflow.

---

## 1. Record shape

The base schema requires six fields:

```
id, version, type, validFrom, fhirVersion, fhirBundle
```

- `version` is fixed to `pdt-healthcert-v2.0`.
- `type` is either one of `PCR`, `ART`, `SER`, `LAMP`, **or** a non-empty array of those values with
  unique items. Both forms are legal, which matters for the type map: the same path is sometimes a
  string and sometimes an array.
- `validFrom` is a date-time.
- `fhirBundle` references the **lite** FHIR 4.0.1 `Bundle` definition, so its entries carry a nested
  `.resource`. This is the genuine FHIR Bundle layout, unlike the vaccination profile.
- The optional `logo` is described only as base64. There is no encoding pattern.
- **The top object does not set `additionalProperties: false`,** so extensions are allowed. That is
  the opposite of the vaccination profile and it directly affects how the fail-closed rule behaves
  here - see section 5.

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

**This is confirmed, not inferred, for the attachment step.** The `text/open-attestation`
attachment in the endorsed sample was decoded and found to be an OA v2 wrapped clinic document: its
unsalted payload matches the clinic sample, and its `signature.targetHash` and `merkleRoot` are the
same single-document digest, recomputed independently from 119 flattened field leaves with zero
obfuscated leaves.

**But the workflow is not schema-enforced.** The endorsed schema does not require an attachment, a
masked national identifier, a new `id`, a distinct endorser, or any cryptographic or content
relationship between the visible endorsed payload and the attachment. The clinic and endorsed test
suites contain one happy-path assertion each.

So the sequence above is strong fixture evidence about intent, and a weak guarantee about any
particular document.

## 3. Type-map scope

- The lite FHIR 4.0.1 definitions reachable from `Bundle` (see [`fhir.md`](fhir.md) section 4).
- The PDT envelope fields.
- OpenAttestation 2.0 fields, for the clinic variant.
- Notarise 1.0 fields, for the endorsed variant.

Two specific hazards:

- **`type` is polymorphic by design** - scalar string or array of strings. The type map must carry
  both, keyed by observed JSON kind.
- **`attachments[].data` and `logo` are large base64 blobs.** In the endorsed sample,
  `attachments[0].data` is 17,440 bytes, the single largest value in any reference record. Bind them
  as `STRING` over the base64 text per specification section 6.3. See decision D9 for the size
  question - blobs are 60-70% of all hashed bytes across the three samples.

## 4. Non-redactable paths

| Path | Why |
|---|---|
| `roax.recordType`, `roax.schemaVersion`, `roax.recordId`, `roax.issuer.id` | The reserved floor (spec section 11.2), which every profile carries. The first three are mandatory by arithmetic rather than policy: without them a verifier cannot select the type map or rebuild a salt preimage, so it cannot verify at all. `roax.issuer.keyId` is committed but OPTIONAL to disclose, because requiring it would break key rotation on already-anchored records. |
| `version` | Pins `pdt-healthcert-v2.0`. Without it a disclosed copy does not say which healthcert version it is. |
| `type` | The test kind. A PDT certificate that does not say whether it was PCR or ART is not a test certificate. |
| `validFrom` | A validity claim with no start is not checkable. |

`validUntil` is deliberately absent from this list because the PDT base schema does not have one;
that is the recovery profile.

## 5. Interaction with the fail-closed rule - read this

The PDT base object **allows additional properties.** So a real PDT record may legitimately carry
fields the type map has never seen.

Under decision D7 (unknown paths fail closed), such a record is **rejected at issuance** rather than
being given a guessed type tag. That is the intended behaviour and it is safe, but it means:

> For this profile, the type map must be maintained as an allowlist that issuers can extend, and
> extending it is a versioned change to the type map (`schemas/type-map-1.0.json`).

This is a genuine operational cost of D7 and it lands hardest on PDT. It is recorded in
`docs/decisions.md` under D7 rather than being smoothed over here.

## 6. Known defects and cautions

- **`fhirVersion` is unvalidated** - example `4.0.1`, not `const` or `enum`. See
  [`fhir.md`](fhir.md) section 6.
- **`logo` has no base64 pattern**, so it is not validated as base64 at all.
- **A minimal Bundle validates.** `{"resourceType":"Bundle"}` satisfies `fhirBundle`. Confirmed by
  reproduction against the audited schema.

## 7. What the schema and tests do NOT enforce

The tests validate the sample, all four scalar `type` values and a multi-type certificate; they
reject a missing `id`, `version` or `type`, unknown or duplicate types, a missing or malformed
`validFrom`, and a missing FHIR version or bundle.

They do **not** test, and the schema does not require, that:

- the Bundle contains a Patient, an Observation or a Specimen;
- `type` agrees with the observation's method;
- the result is negative;
- references resolve;
- a test has a subject, a performer, a laboratory or a collection time;
- the external `fhirVersion` agrees with the hard-wired 4.0.1 schema;
- identifiers are UUIDs;
- the `logo` is valid base64.

These omissions agree with the schema. They are not missing test coverage over a stricter rule; the
rule is genuinely absent.

**Consequence for ROAX:** a valid `sg.gov.moh.pdt-healthcert` root proves that a particular typed
payload was committed by a particular issuer. It does not prove that the payload describes a test,
still less a negative one. Any product surface that says "negative PDT result" is making a claim the
protocol layer does not support, and must derive it from the payload itself after disclosure.
