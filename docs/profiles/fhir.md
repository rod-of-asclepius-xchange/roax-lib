# Profile: HL7 FHIR 4.0.1

**`recordType`:** `hl7.fhir.bundle`
**`schemaVersion`:** `4.0.1` (see the caution in section 6 about what this string means)
**Status:** draft. The type map for this profile does not exist.

---

## 1. What this profile carries

A FHIR R4 resource, canonicalized under `ROAX-CANON/1`.

FHIR is adopted as the **content model**. That is not a close call: inventing a parallel clinical
model for human health records would be disqualifying in healthcare, and FHIR is the dominant
clinical interchange standard.

What is **not** adopted is FHIR's own canonicalization
(`http://hl7.org/fhir/canonicalization/json`, strip whitespace plus alphabetically sort keys).
It answers whole-resource signing, not salted per-field commitment, so it provides no selective
disclosure and defines no Merkle tree over clinical fields. It is a reasonable thing to *also*
support for clinician-signature flows; it cannot be the ROAX commitment rule.

## 2. The full schema is a resource universe, not one record layout

The full `schema.json` declares JSON Schema draft-06 and identifies the HL7 FHIR JSON schema.
Its root discriminator maps `resourceType` values to definitions, and its root `oneOf` spans the
complete resource list.

A structural count found **146 root alternatives and 680 definitions**, in a file of about 3.37 MB.

Consequently a "FHIR record" is not intrinsically a patient document, a Bundle, or even a clinical
resource. It may be an `Account`, a `CapabilityStatement`, a `Patient`, an `Observation`, an
`Immunization`, a `Bundle`, or anything else in that union.

**Consequence for ROAX:** `recordType: hl7.fhir.bundle` says only that the payload is a FHIR
resource of the declared kind. It carries no clinical guarantee. A useful healthcare workflow needs
a declared FHIR profile or implementation guide above the base schema, and choosing whether to
require one is decision D13.

There are no `sample-data.ts` or `schema.test.ts` files in the FHIR reference directory. So there is
no local test evidence that the schema authors intended any particular clinical record beyond the
code-generated schema itself.

## 3. What "lite" actually means

`lite-schema.json` is **not** a minimal patient record and **not** a stronger clinical profile.
It is a packaging and resource-whitelist subset built for Notarise HealthCerts.

Its generator starts from exactly seven resource definitions:

```
Bundle, Device, Observation, Organization, Patient, Practitioner, Specimen
```

It follows their transitive `$ref` dependencies, strips properties beginning with `_` from every
copied top-level definition, replaces `ResourceList` with a union restricted to those seven, sorts
the definitions and writes the result.

It has **85 definitions and is about 234 KB**, against 680 definitions and about 3.37 MB for the
full file.

Three details that matter:

- Removing `_foo` properties removes FHIR's primitive-extension siblings such as `_birthDate`.
  It does **not** remove ordinary `extension` or `modifierExtension`.
- The lite document has metadata and `definitions` but **no root `type`, `$ref` or `oneOf`.**
  Validating a value against `lite-schema.json` at its root therefore constrains nothing. It exists
  to serve definitions referenced by other schemas. A reproduction confirmed that the number `42`
  and an arbitrary object both validate against it at the root.
- Its generator contains a defect: `resourcesFetched.add(...nestedReferences, resource)` assumes
  `Set.add` accepts multiple values, but JavaScript `Set.add` accepts one. Already-queued
  definitions can be revisited. The final object construction deduplicates keys, so the checked-in
  output still has a usable definition set. This is a tooling issue, not a record-semantics rule.

**Conclusion: "lite" must not be mistaken for canonical FHIR R4, a clinical minimum dataset, or a
validation profile sufficient for healthcare semantics.**

## 4. Type-map scope

This is where FHIR costs the most, and it is the reason section 4.3 of the specification calls the
type map the largest gap.

| Source | Definitions | In scope? |
|---|---|---|
| `fhir/4.0.1/schema.json` (full) | 680, 146 root alternatives | Whatever slice this profile admits. Not yet decided - see decision D13. |
| `fhir/4.0.1/lite-schema.json` | 85 | Yes, because the PDT and recovery profiles `$ref` it. |
| `vaccination-healthcert/1.0/schema.json` inline definitions | 7 | Yes, and they are **not** the same seven as lite. |

**The type map must cover the union of three distinct schema scopes, not one.**
The lite schema omits `Immunization` and `ImmunizationRecommendation` entirely while the full schema
has them, and the vaccination healthcert defines its own. A type map built from lite alone silently
fails closed on every vaccination record.

### 4.1 Decimal sites

`decimal` is reachable from `lite-schema.json` at **15 sites**, including `Quantity.value`,
`Observation` via `valueQuantity`, `Extension.valueDecimal`, `Money.value`, `Range`, `Ratio`,
`SampledData` and `Timing_Repeat.duration`.

Each is a place where the trailing-zero rule of specification section 6.2 is load-bearing and where
JCS would produce a non-conformant digest.

### 4.2 Extensions

`Extension` has 53 properties: `id`, `url`, `extension` (recursive), and **50** `value[x]` variants.
Four of those are numeric: `valueDecimal`, `valueInteger`, `valuePositiveInt`, `valueUnsignedInt`.

The typed-path scheme handles extensions naturally because it never needs a closed schema to
*flatten*, only to *type*. So the type map needs one entry per `value[x]` suffix - 50 entries,
mechanically derivable from the schema.

### 4.3 The schema is closed, which is good news

Every occurrence of `additionalProperties` in the lite schema is `false` - 66 of them, all `false`.

That means a complete type map is achievable and an unknown path is genuinely an error rather than a
normal occurrence. It is what makes the fail-closed rule (decision D7) practical rather than
obstructive.

### 4.4 Polymorphic fields are real and already present

In the shipped vaccination sample, `fhirBundle.entry[0].identifier[0].type` is the string `"PPN"`
while `identifier[1].type` is the object `{ text: "NRIC" }`.

A whole-document canonicalizer does not care. A type map keyed by path alone cannot express it.
This is the concrete reason the type map is keyed by **(path pattern, observed JSON kind)** - see
`schemas/type-map-1.0.json`.

## 5. Non-redactable paths

Minimum set for this profile, per specification section 10.2:

| Path | Why |
|---|---|
| `roax.recordType` | Selects the type map, so verification cannot start without it. |
| `roax.schemaVersion` | The other half of the type-map lookup key. |
| `roax.recordId` | Identifies which record it is. |
| `roax.issuer.id` | Identifies who issued it. |
| `resourceType` | Without it a disclosed FHIR resource does not say what kind of resource it is. |

`resourceType` is the FHIR-specific addition. The other four are the reserved floor every profile
carries, per specification section 11.2.

Two distinctions worth keeping straight. The **first two** are mandatory **by arithmetic rather than
by policy**: a verifier without them cannot select the type map and so cannot run the procedure at
all, so withholding one yields no proof rather than a weaker one. `roax.recordId` and
`roax.issuer.id` are policy choices, about a verifier being able to say what it is looking at.
And `roax.issuer.keyId` is **committed but optional to disclose**, because requiring it would break
key rotation on an already-anchored record.

**`roax.recordId` was in the arithmetic group until decision D4 was ruled D4b on 2026-07-28.** Under
the derived-salt construction the specification carried before that ruling, the record identifier was
inside every salt preimage and a verifier genuinely could not recompute a leaf hash without it.
Specification section 7 has no preimage now, so nothing a verifier computes consumes it. Its place in
this table is unchanged; only the reason is.

Neither `roax.canon` nor `roax.hashAlg` appears here, and both absences are deliberate.
`canon` is already bound into the domain string of every leaf, so a leaf restating it
would pay bytes on every disclosed copy for a property already held.
`hashAlg` cannot be bound by a leaf at all, because the leaf would be hashed under the algorithm it
names; specification section 7.4 gives the three mechanisms that replace it.

## 6. Known defects and cautions

- **`fhirVersion` is not validated anywhere.** In the healthcert schemas it has the *example*
  `4.0.1`, not a `const` or an `enum`. A reproduction confirmed that both PDT and recovery accept
  the arbitrary string `"anything"` there while still validating against the hard-wired 4.0.1
  schema. So the record's own claim about its FHIR version is unchecked, and ROAX's
  `schemaVersion` MUST NOT be copied from it without validation.
- **The root of `lite-schema.json` constrains nothing** (section 3). Do not use it as a root
  validator.
- **The identifier `hl7.fhir.bundle` names a resource kind this profile does not require.** Section
  2 establishes that the payload may be an `Account`, a `Patient`, an `Observation` or anything else
  in the 146-alternative root union, yet the identifier says `bundle` and is committed inside the
  root at `roax.recordType`, where it is non-redactable and cannot be corrected for an issued
  record. A reader who treats the identifier as an assertion that the payload is a `Bundle` is
  reading more than the profile guarantees. Whether to narrow the profile to genuine Bundles or to
  rename the identifier belongs to the clinical-validation layer that decision D13's ruling puts
  outside `ROAX-CANON/1` (specification section 2.3); nothing here settles it.

## 7. What this profile does NOT enforce

Everything clinical. Specifically, nothing here requires that a record has a patient, has any
clinical resource, has internally consistent references, or means anything at all beyond being a
syntactically valid FHIR resource.

If ROAX wants to claim clinical semantics, that requires named implementation profiles above the
base schema, with profile governance.

**Decision D13 is ruled and the ruling makes that a separate layer rather than a pending question.**
The protocol layer commits what it is given and asserts nothing clinical, and specification section
2.3 states normatively that no surface derived from this protocol may claim a clinical fact from root
validity alone. Named implementation profiles are a separate, independently versioned conformance
layer a deployment may adopt, kept off the canonicalization critical path so that it can arrive later
without touching a byte of the digest rule.
