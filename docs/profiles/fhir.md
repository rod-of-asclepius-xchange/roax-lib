# Profile: HL7 FHIR 4.0.1

**`recordType`:** `hl7.fhir.bundle`
**`schemaVersion`:** `4.0.1` (see the caution in section 6 about what this string means)
**Status:** published as [`type-maps/hl7.fhir.bundle-4.0.1.json`](../../type-maps/hl7.fhir.bundle-4.0.1.json) at exact artifact ID `sha256:0e9e642bc89c081e2e6faf651acdc25c46fac83201248ef53a7c812181279807`.
`base64Binary`, `Narrative.div` and the FHIR null-placeholder conflict were **ruled on 2026-07-30** with their evidence grades, and 659 object-applicator source nodes still omit an object type, as audited in [`docs/type-maps.md`](../type-maps.md) sections 1.3, 1.5 and 2.
**The published artifact does not yet carry the two new bindings**: it still declares those slots `unresolved`, because regeneration is blocked on 34 merged object states, and section 1.6 of that document states why hand-editing a generated artifact is the wrong fix and what the next change must do.

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

**Consequence for ROAX:** `recordType: hl7.fhir.bundle` says only that the payload is a FHIR resource admitted by the complete 146-alternative root union.
It carries no clinical guarantee.
A useful healthcare workflow needs a declared FHIR profile or implementation guide above the base schema, as required by the separation in specification section 2.3.

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

This is where FHIR costs the most.
The four published artifacts keep their schema scopes separate rather than pretending they share one path universe, as required by the exact-map selection rule in specification section 4.2 and [`docs/type-maps.md`](../type-maps.md) sections 2 and 4.

| Source | Definitions | Published scope |
|---|---|---|
| `fhir/4.0.1/schema.json` (full) | 680 definitions, 146 root alternatives | The complete root union is materialized in [`hl7.fhir.bundle-4.0.1.json`](../../type-maps/hl7.fhir.bundle-4.0.1.json). |
| `fhir/4.0.1/lite-schema.json` | 85 definitions | The definitions reachable from `Bundle` are materialized separately in the PDT and recovery artifacts because those healthcert schemas `$ref` the lite file. |
| `vaccination-healthcert/1.0/schema.json` inline definitions | 7 definitions | The flattened inline definitions are materialized only in the vaccination artifact and never gain a genuine Bundle `.resource` segment. |

The full-FHIR artifact reaches 678 of 680 definitions and carries 2,663 states, 7,313 exact KEY transitions and 1,715 INDEX transitions, as reported in [`docs/type-maps.md`](../type-maps.md) sections 2.2 and 2.3.
The two unused named definitions are `oid` and `uuid`, while their inline value fields remain covered, as reported in the same audit.
The finite scalar audit counts 3,345 schema-local slots, of which 3,264 are confident, 74 use an operative FHIR element-name inference and seven remain unresolved, as reported in [`docs/type-maps.md`](../type-maps.md) section 2.2.
Those seven source slots collapse to two unresolved DFA states because six `base64Binary` occurrences share a definition and `Narrative.div` supplies the other state, as reported in [`docs/type-maps.md`](../type-maps.md) sections 1.3 and 2.3.
Both are ruled - `base64Binary` BYTES over the decoded octets at grade Strong, `Narrative.div` STRING over the escaped XHTML text at grade Decisive - and both figures above still count them unresolved because the artifact does not yet carry the rulings.
Separately, 659 reached object-applicator source nodes collapse to 504 marked DFA states because the FHIR definitions omit `type: "object"`, as audited in [`docs/type-maps.md`](../type-maps.md) sections 1.5 and 2.3.

The lite schema omits `Immunization` and `ImmunizationRecommendation` entirely, while the full schema has them and the vaccination healthcert defines its own flattened variants.
Reusing the PDT or recovery map for vaccination would therefore fail closed on central clinical content, while searching another installed map after a miss is forbidden by [`docs/type-maps.md`](../type-maps.md) section 5.1.

### 4.1 Decimal sites

The lite source audit has **16 schema-local decimal slots**, consisting of 15 decimal `$ref` slots plus inline `Extension.valueDecimal`, as reported in [`docs/type-maps.md`](../type-maps.md) section 2.3.
They include `Quantity.value`, `Observation` via `valueQuantity`, `Extension.valueDecimal`, `Money.value`, `Range`, `Ratio`, `SampledData` and `Timing_Repeat.duration`.

Each is a place where the trailing-zero rule of specification section 6.2 is load-bearing and where JCS would produce a non-conformant digest.

### 4.2 Extensions

`Extension` has 53 properties: `id`, `url`, `extension` (recursive), and **50** `value[x]` variants.
Four of those are numeric: `valueDecimal`, `valueInteger`, `valuePositiveInt`, `valueUnsignedInt`.

The DFA follows those exact KEY transitions and its recursive `extension` INDEX transition without enumerating concrete array indexes, as defined by [`schemas/type-map-artifact-1.0.json`](../../schemas/type-map-artifact-1.0.json) and [`docs/type-maps.md`](../type-maps.md) section 3.
Every emitted leaf still requires an output for its observed JSON kind, so recursion does not turn an unknown suffix into an inferred type under specification section 4.2.

### 4.3 The schema is closed, which is good news

Every occurrence of `additionalProperties` in the lite schema is `false` - 66 of them, all `false`.

That makes unknown KEY paths genuine errors rather than ordinary additional properties.
It did not settle the six `base64Binary` slots, the untyped `Narrative.div`, or the FHIR null-placeholder conflict, and nothing in a schema could have: each needed a ruling, and all three were ruled on 2026-07-30 under [`docs/type-maps.md`](../type-maps.md) section 1.3.

- **`base64Binary` is BYTES over the decoded octets**, grade Strong, because FHIR R4 defines the datatype as a stream of bytes while identifying its JSON form as base64 text, so BYTES commits the value rather than the transport spelling. The canonical RFC 4648 section 4 form specification section 6.3 pins is an input-admissibility condition and never the committed value.
- **`Narrative.div` is STRING over the escaped XHTML text**, grade Decisive, because FHIR R4's normative JSON representation states it is one escaped XHTML string. An implementation MUST NOT parse, normalize as markup, or reserialize the XHTML for commitment: STRING selects `utf8(NFC(s))` and nothing more, and a separate FHIR validator still owns the XHTML content rules.
- **Primitive-array null placeholders get NO NULL binding and the record is REJECTED**, grade Decisive, until a versioned schema and type-map revision admits the FHIR representation. Specification section 4.2 runs complete profile validation before map resolution, so the pinned schema wins and the map may not widen a record its own schema refuses; adding NULL to the map alone would contradict the schema rather than resolve it.

The third ruling is operative today, because it is expressed as an absence and the artifacts already carry no NULL output. The first two are not yet in the artifact, for the reason section 1.6 gives.

### 4.4 Polymorphic fields are real and already present

In the shipped vaccination sample, `fhirBundle.entry[0].identifier[0].type` is the string `"PPN"`
while `identifier[1].type` is the object `{ text: "NRIC" }`.

A whole-document canonicalizer does not care, while a type map keyed by path alone cannot express it.
This is the concrete reason each DFA state may carry distinct outputs keyed by observed JSON kind, as defined by [`schemas/type-map-artifact-1.0.json`](../../schemas/type-map-artifact-1.0.json) and [`docs/type-maps.md`](../type-maps.md) section 3.

## 5. Non-redactable paths

Minimum set for this profile, per specification section 10.2:

| Path | Why |
|---|---|
| `roax.recordType` | Selects the registered profile and is checked against the fetched artifact (spec sections 4.2 and 11.2). |
| `roax.schemaVersion` | Selects the exact schema generation and is checked by opaque equality against the fetched artifact (spec sections 4.2 and 12.1). |
| `roax.typeMap.id` | Selects the exact immutable base or issuer-extension artifact, so verification cannot resolve a leaf without it ([`docs/type-maps.md`](../type-maps.md) section 4 and spec section 11.2). |
| `roax.recordId` | Identifies which record it is. |
| `roax.issuer.id` | Identifies who issued it. |
| `resourceType` | Without it a disclosed FHIR resource does not say what kind of resource it is. |

`resourceType` is the FHIR-specific addition.
The other five are the reserved floor every profile carries, per specification section 11.2 and [`docs/type-maps.md`](../type-maps.md) section 4.

Three distinctions are worth keeping straight.
`roax.recordType`, `roax.schemaVersion` and `roax.typeMap.id` are mandatory **by arithmetic rather than by policy** because the verifier checks the exact artifact ID and its two profile selectors before it can resolve any disclosed leaf, under [`docs/type-maps.md`](../type-maps.md) section 4.
`roax.recordId` and `roax.issuer.id` are policy choices about a verifier being able to say what it is looking at.
`roax.issuer.keyId` is committed but optional to disclose because requiring it would break key rotation on an already-anchored record, under specification section 11.2.

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
