# Profile: Singapore MOH Vaccination HealthCert 1.0

**`recordType`:** `sg.gov.moh.vaccination-healthcert`
**`schemaVersion`:** `1.0`
**Status:** the fail-closed map is published as [`type-maps/sg.gov.moh.vaccination-healthcert-1.0.json`](../../type-maps/sg.gov.moh.vaccination-healthcert-1.0.json) at exact artifact ID `sha256:de7bb92226af5fa5dc5064d9cb203329abc69160f4280fdf739e66e5e0151e93`.
`notarisationMetadata.signedEuHealthCerts[*].dose` and `notarisationMetadata.signedEuHealthCerts[*].expiryDateTime` remain unbound, so the shipped sample is uncommittable under fail-closed, and 26 object-intended schema paths leave their non-object alternatives unbound, as audited in [`docs/type-maps.md`](../type-maps.md) sections 1.1, 1.4 and 2.

**This is the structurally different one.** Read section 2 before anything else; it is the reason
this family cannot share a `fhirBundle` handler with PDT and recovery, and it is the place where a
well-intentioned normalization would break every commitment already made.

---

## 1. Record shape

Eight required fields:

```
id, name, validFrom, fhirVersion, fhirBundle,
issuers, $template, notarisationMetadata
```

Unlike PDT and recovery, the top-level object **closes** with `additionalProperties: false`.
That makes an unknown top-level path genuinely anomalous under the fail-closed rule in specification section 4.2.
It does not make the current map complete because two Notarise scalar paths lack decisive type evidence and 26 nested schemas omit an object type, as audited in [`docs/type-maps.md`](../type-maps.md) sections 1.1 and 1.4.

Note also what is *not* required: there is no `version` field pinning a healthcert version string,
unlike `pdt-healthcert-v2.0` and `rec-healthcert-v2.0`. The record's own identification of its
family rests on `$id`, which is itself defective - see section 5.

## 2. The `fhirBundle` layout is NOT the FHIR Bundle layout

This is the critical finding for this profile.

In PDT and recovery, `fhirBundle` references the lite FHIR `Bundle`, whose entries are wrappers:
the resource sits at `entry[i].resource`.

In vaccination 1.0, `fhirBundle.entry[]` items **directly** match a `Patient`, `Specimen`,
`Observation`, `Organization`, `Immunization`, `ImmunizationRecommendation` or `Location`.
The sample correspondingly places `fullUrl` and `resourceType` directly on each entry.

```
PDT / recovery (genuine FHIR Bundle):     vaccination 1.0 (flattened pseudo-FHIR):

  fhirBundle.entry[0].fullUrl               fhirBundle.entry[0].fullUrl
  fhirBundle.entry[0].resource.resourceType fhirBundle.entry[0].resourceType
  fhirBundle.entry[0].resource.birthDate    fhirBundle.entry[0].birthDate
```

**This is a custom flattened pseudo-FHIR representation, not a FHIR Bundle.**

### 2.1 Why this must not be silently normalized

Under `ROAX-CANON/1` the path is inside every leaf preimage (specification section 8).
`fhirBundle.entry[0].birthDate` and `fhirBundle.entry[0].resource.birthDate` are different paths,
so they are different leaves, so they produce a different root.

> **Normative for this profile:** an implementation MUST commit the flattened layout as it stands.
> It MUST NOT normalize entries into the genuine FHIR wrapper shape before hashing.

Silent normalization would make every existing commitment unverifiable, and would do so quietly -
the record would still look like valid FHIR, and would simply fail to match its anchored root.

Two legitimate options exist and the choice is a product decision, not an implementation detail:

- **Preserve as a distinct payload profile.** Exact compatibility, no semantic rewrite. Consumers
  must handle both the genuine and the flattened Bundle forms. This is what this document specifies.
- **Normalize through a declared, versioned adapter.** Downstream code gets genuine FHIR, but the
  adapter version and both the pre- and post-normalization identities must be explicit, and any
  existing proof remains a proof of the legacy bytes, not of the rewritten record.

This is folded into decision C in `docs/decisions.md`, since it bears directly on what happens to
already-issued Singapore healthcerts.

## 3. Type-map scope

The vaccination healthcert **references neither the full nor the lite FHIR schema.** It defines its
`fhirBundle` inline against its own seven definitions:

```
Patient, Specimen, Observation, Organization,
Immunization, ImmunizationRecommendation, Location
```

Compare with lite's seven: `Bundle, Device, Observation, Organization, Patient, Practitioner,
Specimen`. They are **not the same seven.** Lite has `Bundle`, `Device` and `Practitioner`;
vaccination has `Immunization`, `ImmunizationRecommendation` and `Location`.

**Lite omits `Immunization` and `ImmunizationRecommendation` entirely.** A type map built from the
lite schema alone therefore fails closed on the central clinical content of every vaccination
record.
This is why the vaccination definitions are materialized in their own exact artifact rather than being looked up in either healthcert lite-FHIR map, as documented in [`fhir.md`](fhir.md) section 4 and [`docs/type-maps.md`](../type-maps.md) section 2.

Additional scope for this profile:

- Issuer block: DID, name, revocation, DNS-DID identity proof.
- `$template` renderer fields.
- `notarisationMetadata`, including optional signed EU DCC entries.
- `attachments` and `logo`.

The published artifact materializes this exact flattened scope as a DFA with 143 states, 122 exact KEY transitions, 20 INDEX transitions, 81 scalar STRING outputs, six EMPTY_ARRAY outputs and seven EMPTY_OBJECT outputs, as reported in [`docs/type-maps.md`](../type-maps.md) section 2.3.
The finite scalar audit counts 83 intended path patterns, of which 81 are confident and the two named below are unresolved, with no inferred binding, as reported in [`docs/type-maps.md`](../type-maps.md) section 2.2.
Its exact artifact ID, `recordType` and `schemaVersion` are checked together when selecting this map, under [`docs/type-maps.md`](../type-maps.md) section 4 and specification section 4.2.
No numeric output is present because `dose` remains unresolved.

### 3.1 The `dose` trap

`notarisationMetadata.signedEuHealthCerts[*].dose` is written as bare JSON `1` and `2` in the shipped examples, but its source says only `type: "number"` and carries no integer or decimal constraint at `references/schemata/src/sg/gov/tech/notarise/1.0/schema.json#/properties/notarisationMetadata/properties/signedEuHealthCerts/items/anyOf/0/properties/dose`, read at upstream commit `09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa`.
JSON Schema `number` admits integral and fractional values, while specification section 6.1 assigns different tags to INTEGER and DECIMAL.

Two candidate rulings exist, and neither is operative:

- INTEGER is supported by the ordinal meaning and the shipped examples `1` and `2`, but the schema admits fractions and sample syntax is not semantic evidence under specification section 4.2.
- DECIMAL covers the complete numeric domain admitted by the schema, but choosing it would add a semantic ruling that the source never states, as documented in [`docs/type-maps.md`](../type-maps.md) section 1.1.

The published map therefore has no output for observed kind `number` at this path.
Issuance fails closed rather than deriving a tag from whether one JSON writer happened to emit `1`, `1.0` or `1.00`, under specification sections 4.2 and 6.2.

### 3.2 The `expiryDateTime` gap

`notarisationMetadata.signedEuHealthCerts[*].expiryDateTime` has `format: "date-time"` and string examples but no `type` in either source branch at `references/schemata/src/sg/gov/tech/notarise/1.0/schema.json#/properties/notarisationMetadata/properties/signedEuHealthCerts/items/anyOf`, read at upstream commit `09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa`.
Under JSON Schema Validation draft-07 section 7.3.1, `format` is an annotation unless validation behavior is explicitly enabled and does not supply a missing instance type.

STRING is proposed because the field is named as a date-time, every supplied example and fixture uses a string, and RFC 3339 section 5.6 defines date-time as a string production.
That proposal is not operative because the source schema formally admits other JSON kinds, as documented in [`docs/type-maps.md`](../type-maps.md) section 1.1.
The published map therefore supplies no output for any observed kind at this path.

Together, the unbound `dose` and `expiryDateTime` leaves make the shipped vaccination sample uncommittable today.
An implementation MUST report the unresolved binding and stop rather than choose either proposal, under specification section 4.2 and [`docs/type-maps.md`](../type-maps.md) section 3.

### 3.3 Blobs

`logo` is 14,314 bytes in the vaccination sample - a single embedded PNG. Together with the PDT
attachment it is why blobs are 60-70% of all hashed bytes across the reference records
(decision D9).
The published map binds `logo` and declared attachment data as STRING over the base64 text because the source schemas declare strings, under specification sections 4.2 and 6.3.

## 4. Non-redactable paths

| Path | Why |
|---|---|
| `roax.recordType`, `roax.schemaVersion`, `roax.typeMap.id`, `roax.recordId`, `roax.issuer.id` | The reserved floor (spec section 11.2), which every profile carries. `roax.recordType`, `roax.schemaVersion` and `roax.typeMap.id` are mandatory by arithmetic because the verifier checks the exact artifact ID and its two profile selectors before resolving any disclosed leaf ([`docs/type-maps.md`](../type-maps.md) section 4). `roax.recordId` and `roax.issuer.id` are mandatory by policy, so a disclosed copy says which record it is and who issued it. `roax.recordId` was arithmetic until decision D4 was ruled D4b on 2026-07-28, which removed the salt preimage it used to be an input to. `roax.issuer.keyId` is committed but OPTIONAL to disclose under specification section 11.2, because requiring it would break key rotation on already-anchored records. |
| `validFrom` | A validity claim with no start is not checkable. |
| `notarisationMetadata.reference` | The notarisation identity. In the sample it equals the outer `id`, though nothing enforces that (section 6). |

**There is no `version` field to pin**, unlike PDT and recovery.
For this family, `roax.recordType` and `roax.schemaVersion` say which record family and schema version a disclosed copy belongs to, while `roax.typeMap.id` selects the exact base or issuer-extension DFA, under [`docs/type-maps.md`](../type-maps.md) section 4.
That makes the reserved floor more load-bearing here than elsewhere.

## 5. Known defects and cautions

- **The `$id` is wrong.** It points at a PDT interim-healthcert path despite the title saying
  vaccination. This is the second `$id` copy error across the reference schemata - the recovery
  schema has the other one. Same requirement as in
  [`recovery-healthcert.md`](recovery-healthcert.md) section 2: do not resolve these schemas by
  `$id`.
- **Several nested resource definitions omit an explicit `type: "object"`,** which weakens
  validation under JSON Schema's keyword-applicability rules. Keywords like `properties` and
  `required` simply do not apply to a non-object instance, so those definitions accept values they
  appear to constrain.
  The map follows declared object children but leaves every non-object alternative unbound at all 26 affected path patterns, as listed in [`docs/type-maps.md`](../type-maps.md) section 1.4.
- **`fhirBundle.entry` has no `minItems`.** An empty entry array is valid. The `anyOf` restricts an
  item only when an item is present, so the schema does not require a Patient, an Immunization or a
  Recommendation - it does not require any entry at all.

## 6. What the schema does NOT enforce

The local test suite has **exactly one assertion**: that the full sample is valid. There are no
negative tests.

The sample demonstrates five relationships that the schema does not assert:

- the outer `id` equals `notarisationMetadata.reference`;
- `validFrom` equals `notarisedOn`;
- the Patient passport number equals `notarisationMetadata.passportNumber`;
- patient and location references resolve to entry `fullUrl` values;
- the two Immunizations align with the two EU DCC dose records.

Within a resource, the schema is stricter than its siblings: `Patient` requires `resourceType`, a
nationality extension, at least one identifier, at least one name and a birth date, and
`Immunization` requires a resource type, vaccine code, occurrence date and lot number.

**But "required within a resource" is not "the bundle must contain that resource."** Since `entry`
has no `minItems` and the `anyOf` only constrains items that exist, a vaccination healthcert with
an empty bundle validates.

**Consequence for ROAX:** a valid `sg.gov.moh.vaccination-healthcert` root proves a typed payload
was committed by an issuer. It does not prove the record contains a patient, contains any
vaccination, or that its cross-field relationships hold. Those five sample relationships are
plausible product invariants and every one of them would have to be added by this profile to be
relied upon.

**Decision D13 is ruled and that makes this normative.** Specification section 2.3 states that no
surface derived from this protocol may assert a clinical fact from root validity alone, and puts
clinical validation in a separate, independently versioned layer. This profile is the sharpest case
for it: `fhirBundle.entry` has no `minItems`, so a vaccination healthcert with an empty bundle
validates, commits, anchors and verifies while asserting no vaccination at all.
