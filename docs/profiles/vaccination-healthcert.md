# Profile: Singapore MOH Vaccination HealthCert 1.0

**`recordType`:** `sg.gov.moh.vaccination-healthcert`
**`schemaVersion`:** `1.0`
**Status:** draft. The type map for this profile does not exist.

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
That makes the fail-closed rule of decision D7 cheap here: the schema is closed, so a complete type
map is achievable and an unknown top-level path is genuinely anomalous.

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
record. This is the concrete case behind the "union of three scopes" requirement in
[`fhir.md`](fhir.md) section 4.

Additional scope for this profile:

- Issuer block: DID, name, revocation, DNS-DID identity proof.
- `$template` renderer fields.
- `notarisationMetadata`, including optional signed EU DCC entries.
- `attachments` and `logo`.

### 3.1 The `dose` trap

`notarisationMetadata.signedEuHealthCerts[].dose` is written as a **bare JSON `1` and `2`** in the
shipped sample.

Under syntactic type inference that is INTEGER. If a future issuer writes `1.0`, syntactic inference
makes it DECIMAL and the record silently gets a different root.

This is the concrete instance of the schema-binding argument in specification section 4, occurring
in a real shipped record rather than in a constructed example. The type map MUST bind this path
explicitly.

### 3.2 Blobs

`logo` is 14,314 bytes in the vaccination sample - a single embedded PNG. Together with the PDT
attachment it is why blobs are 60-70% of all hashed bytes across the reference records
(decision D9). Bind as `STRING` over the base64 text per specification section 6.3.

## 4. Non-redactable paths

| Path | Why |
|---|---|
| `roax.recordType`, `roax.schemaVersion`, `roax.recordId`, `roax.issuer.id` | The reserved floor (spec section 11.2), which every profile carries. The first three are mandatory by arithmetic rather than policy: without them a verifier cannot select the type map or rebuild a salt preimage, so it cannot verify at all. `roax.issuer.keyId` is committed but OPTIONAL to disclose, because requiring it would break key rotation on already-anchored records. |
| `validFrom` | A validity claim with no start is not checkable. |
| `notarisationMetadata.reference` | The notarisation identity. In the sample it equals the outer `id`, though nothing enforces that (section 6). |

**There is no `version` field to pin**, unlike PDT and recovery. For this family, `roax.recordType`
and `roax.schemaVersion` carry the whole burden of saying which record family and version a
disclosed copy belongs to. That makes the reserved floor more load-bearing here than elsewhere, not
less.

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
relied upon. That is part of decision D13.
