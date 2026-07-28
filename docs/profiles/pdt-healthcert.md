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
| `roax.recordType`, `roax.schemaVersion`, `roax.recordId`, `roax.issuer.id` | The reserved floor (spec section 11.2), which every profile carries. The first two are mandatory by arithmetic rather than policy: they select the type map, so without them a verifier cannot verify at all. `roax.recordId` and `roax.issuer.id` are mandatory by policy, so that a disclosed copy says which record it is and who issued it. `roax.recordId` was arithmetic until decision D4 was ruled D4b on 2026-07-28, which removed the salt preimage it used to be an input to; its place here is unchanged and only its reason moved. `roax.issuer.keyId` is committed but OPTIONAL to disclose, because requiring it would break key rotation on already-anchored records. |
| `version` | Pins `pdt-healthcert-v2.0`. Without it a disclosed copy does not say which healthcert version it is. |
| `type` | The test kind. A PDT certificate that does not say whether it was PCR or ART is not a test certificate. |
| `validFrom` | A validity claim with no start is not checkable. |

`validUntil` is deliberately absent from this list because the PDT base schema does not have one;
that is the recovery profile.

## 5. Interaction with the fail-closed rule - read this

The PDT base object **allows additional properties.** So a real PDT record may legitimately carry
fields the type map has never seen.

**Decision D7 is ruled D7a - fail closed, permanently** (2026-07-28, `docs/decisions.md`). Such a
record is **rejected at issuance** rather than being given a guessed type tag. That is the intended
behaviour and it is safe, and the operational cost of it lands hardest on this profile, so it is
planned for here rather than absorbed.

> **For this profile, the type map is an allowlist that issuers extend**, and extending it is a
> versioned change to `typeMapVersion` in `schemas/type-map-1.0.json`. That is not a workaround. It
> is the D7a ruling's own consequence: the type map is a **first-class, independently versioned,
> issuer-extensible artifact with a defined extension path**, not a lookup table shipped once
> (specification section 4.2).

**One constraint on that extension path is load-bearing.** An extension MUST be **additive**. Adding
a binding for a path the map does not cover is safe and is the normal case; retagging a path it
already covers changes the root of every already-issued record that reaches that path, which
specification section 12.2 forbids. A correction to an existing binding is therefore a new profile
version rather than a type-map patch, and any record already anchored under the old binding keeps
verifying under it.

**Why this matters more here than anywhere else.** PDT already has the most real-world traffic of the
three healthcert families, and its open-world base object means an unknown path is a routine event
rather than an anomaly - the opposite of the vaccination profile, whose top-level object closes with
`additionalProperties: false` (see [`vaccination-healthcert.md`](vaccination-healthcert.md) section
1). If extending the map is slow or unclear, fail-closed becomes an adoption blocker exactly where it
can least afford to be, and the pressure to "just default it to STRING for now" will arrive from a
real issuer with a real record. That is the moment refusing is hardest, which is why the refusal is
normative in the specification rather than advisory, and why the extension path being fast is a
deliverable rather than an aspiration.

### 5.1 Blob binding

`logo` and `attachments[].data` are bound as `STRING` over the base64 text (specification section
6.3), and that is unchanged by decision D9's ruling.

Two things that ruling did change, and neither alters a byte of an existing PDT record:

- **One canonical base64 form is now pinned** - RFC 4648 section 4, standard alphabet, with padding,
  no line wrapping (specification section 6.3). This governs a `BYTES` binding rather than a `STRING`
  one, so it does not reach this profile's fields today. It matters here because the PDT schema
  describes `logo` only as base64 with no encoding pattern (section 6 below), so nothing upstream
  constrains what an issuer sends.
- **A content-addressed binding, type tag 8 `BLOB_REF`, is defined and selected by nothing**
  (specification section 6.5). **This profile does not select it**, and an implementation MUST reject
  a record that binds any PDT path to tag 8. It exists so that a future record family issuing under
  Poseidon - where a 14 KB blob costs about 14 ms rather than about 41 microseconds - does not need a
  second leaf-binding form retrofitted after five implementations already exist.

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
protocol layer does not support, and must derive it from the payload itself after disclosure and
attribute it to the payload.

**That is now normative rather than advisory.** Decision D13 is ruled, and specification section 2.3
states that no surface derived from this protocol may assert a clinical fact on the strength of root
validity alone. Enforcing the rules this section lists as absent - that the Bundle contains an
Observation, that `type` agrees with the method, that the result is negative - belongs to the
separate, independently versioned clinical-validation layer that ruling puts outside
`ROAX-CANON/1`.
