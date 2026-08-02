# Record profiles

**This directory is the `recordType` registry, and every document in it is a profile *of* one protocol rather than a variant of it.**
Two kinds of author are represented today: an international standards body, through HL7 FHIR 4.0.1, and one national health authority, through the three Singapore MOH healthcerts.
Nothing in the protocol layer makes that set final.
[`schemas/envelope-2.0.json`](../../schemas/envelope-2.0.json) constrains `recordType` to a lowercase reverse-DNS *form* rather than to a list, and [ROAX-CANON/1 section 12.2](../spec/roax-canon-1.md#122-future-proofing-is-a-standing-constraint-not-a-section) requires new profiles to arrive by a registry entry here and never by editing the specification.
A further jurisdiction is therefore a document in this directory plus a type map, and the section below states exactly what such a document must declare.

There are four profile documents **today** because the four record families **do not share one concrete object.**
They share a boundary, not a schema.
That is a finding about these four families and it is what a fifth would also have to be measured against, rather than a limit on how many there may be.

That finding is load-bearing, so it is stated here with its evidence rather than assumed.

## There is no field required by all four

- Full FHIR 4.0.1 is any one of 146 resource types and has no healthcert envelope at all.
- PDT and recovery require `id`, `version`, `type`, validity, `fhirVersion` and `fhirBundle`.
- Vaccination requires `id`, `name`, validity, `fhirBundle`, `issuers`, `$template` and `notarisationMetadata`.

Across the three healthcert schemas, only `id`, `validFrom`, `fhirVersion` and `fhirBundle` are required by all three.
PDT and recovery additionally share `version` and `type`.

**And even `fhirBundle` has two incompatible layouts.**
PDT and recovery wrap a genuine FHIR Bundle whose entries carry a nested `.resource`; the vaccination healthcert puts `resourceType` and `fullUrl` directly on each entry.
Anything that treated `fhirBundle` as one shape would be wrong for one of the two.

That physical intersection is too small to represent healthcare meaning.
A single flattened "common healthcert" schema is not supported by the evidence.

## What is common, then

Only this:

```
protocol version
canonicalization / hash / tree algorithm identifiers
schema-or-profile identifier (committed, not merely advisory)
exact type-map artifact identifier (committed, not merely advisory)
typed payload tree
salted commitments and disclosure proofs
optional anchoring metadata
```

Everything clinical - FHIR constraints, test semantics, validity rules, vaccine semantics, issuer/notary/rendering workflow, cross-reference invariants - belongs to a profile.

This boundary comes from the OpenAttestation audit's section 6.3.
It was re-checked against dogtag before being adopted here, because the audit reached it without consulting dogtag; see [the specification section 14.1](../spec/roax-canon-1.md#141-the-boundary-question-checked) for that reconciliation and its conclusion.

## What each profile document must declare

**This directory is the `recordType` registry.**
`schemas/envelope-2.0.json` constrains `recordType` to a lowercase reverse-DNS *form* rather than to a closed list, because the list is extensible.
It is the registry that closes it: **adding a `recordType` value REQUIRES adding a profile document here declaring at least the first three rows below**, and a syntactically valid `recordType` with no profile document is not a valid record.

The v1 registry is `sg.gov.moh.vaccination-healthcert`, `sg.gov.moh.pdt-healthcert`, `sg.gov.moh.recovery-healthcert` and `hl7.fhir.bundle`.

| Item | Why |
|---|---|
| `recordType`, `schemaVersion` and exact type-map artifact | They are committed inside the root as reserved leaves and are checked together when selecting a map (spec sections 4.2 and 11.2; [`type-maps.md`](../type-maps.md) section 4). |
| Type-map scope | Which schema definitions the type map covers for this family, including every unresolved path that fails closed (spec section 4.2; [`type-maps.md`](../type-maps.md) sections 1 and 2). |
| Non-redactable paths | The minimum-disclosure floor (spec section 10.2). Without it a disclosed copy can hide what the record is. |
| Blob-bearing fields | Which fields carry base64 and how they are bound (spec section 6.3). The healthcert schemas' explicitly typed blob fields bind as `STRING` over the base64 text, while FHIR `base64Binary` was ruled `BYTES` over the decoded octets on 2026-07-30 at evidence grade Strong, a binding the published artifacts do not yet carry ([`type-maps.md`](../type-maps.md) sections 1.3 and 1.6). The content-addressed binding, tag 8 `BLOB_REF`, is defined and **selected by none of them**, so a profile that wants it must say so explicitly and must also state how the blob travels out of band (spec section 6.5). |
| Known schema defects | So an implementer is not surprised by them. |
| What the schema does NOT enforce | The gap between what the samples show and what the schema requires. This gap is large and is the single most misleading thing about these families. |

## Published type maps

Each row names one exact immutable artifact.
The artifact ID, `recordType` and `schemaVersion` are checked together, and `typeMapVersion` is equality-only metadata rather than a version range, under [`type-maps.md`](../type-maps.md) sections 4 and 5.2.

| Profile | Published artifact | Exact artifact ID | Fail-closed gaps |
|---|---|---|---|
| Full FHIR root union | [`hl7.fhir.bundle-4.0.1.json`](../../type-maps/hl7.fhir.bundle-4.0.1.json) | `sha256:0e9e642bc89c081e2e6faf651acdc25c46fac83201248ef53a7c812181279807` | Six schema-local `base64Binary` slots and `Narrative.div` are unresolved, schema-rejected FHIR null placeholders remain unbound, and 659 object-applicator source nodes omit an object type ([`type-maps.md`](../type-maps.md) sections 1.3, 1.5 and 2.2). |
| PDT base plus lite FHIR Bundle | [`sg.gov.moh.pdt-healthcert-2.0.json`](../../type-maps/sg.gov.moh.pdt-healthcert-2.0.json) | `sha256:4f8cecc59c85101b8b567658c90651bcbf8f9d4dc279571aa40a03cf04f434ff` | Four lite `base64Binary` slots and `Narrative.div` are unresolved, 65 reached lite object nodes omit an object type, and the 20 endorsed-sample path/kind pairs undeclared by the base schema are intentionally absent ([`type-maps.md`](../type-maps.md) sections 1.2, 1.3 and 1.5). |
| Recovery plus lite FHIR Bundle | [`sg.gov.moh.recovery-healthcert-2.0.json`](../../type-maps/sg.gov.moh.recovery-healthcert-2.0.json) | `sha256:db935b67a3a82754921267e3af237b606f7489b46e05aa892d175b8d87504177` | Four lite `base64Binary` slots and `Narrative.div` are unresolved, 65 reached lite object nodes omit an object type, and the open root makes issuer-extension coverage unbounded ([`type-maps.md`](../type-maps.md) sections 1.3, 1.5 and 2.2). |
| Vaccination flattened profile | [`sg.gov.moh.vaccination-healthcert-1.0.json`](../../type-maps/sg.gov.moh.vaccination-healthcert-1.0.json) | `sha256:de7bb92226af5fa5dc5064d9cb203329abc69160f4280fdf739e66e5e0151e93` | `dose` and `expiryDateTime` are unresolved in these bytes, and 26 object-intended schemas leave non-object alternatives unbound ([`type-maps.md`](../type-maps.md) sections 1.1 and 1.4). |

Every gap in that column is measured on the PUBLISHED bytes.
Five of them - vaccination `dose` and `expiryDateTime`, FHIR `base64Binary`, `Narrative.div` and the primitive-array null placeholders - were ruled on 2026-07-30 with their evidence grades, and no published artifact carries a ruled binding yet, because regeneration is blocked ([`type-maps.md`](../type-maps.md) section 1.6).
The null-placeholder ruling is the one that needs no row: its outcome is "publish no NULL binding", which these bytes already satisfy.
The two vaccination rulings are operative in the corpus-side map conformance class 10 resolves against, which is what makes the shipped vaccination sample committable there.

The executable artifact format is [`schemas/type-map-artifact-1.0.json`](../../schemas/type-map-artifact-1.0.json).
Issuer additions use immutable scoped child artifacts rather than defaulting an unknown path from its JSON syntax, as specified in [`type-maps.md`](../type-maps.md) section 5 and ROAX-CANON/1 section 4.2.

## A caution that applies to all four

**"Required within a resource" and "the bundle must contain that resource" are different statements.**
The reference schemas frequently do the former and not the latter.

A validator reproduction against the audited schemas confirmed that both PDT and recovery accept their required envelopes with a `fhirBundle` of `{"resourceType":"Bundle"}` and nothing else, and accept an arbitrary `fhirVersion` string.
That follows directly from the schemas; it is not a bug in the validator.

So ROAX must not infer clinical guarantees from the fact that a record validates.
The protocol layer commits what it is given.
Whether what it was given is clinically meaningful is a profile question, and today the profiles largely do not answer it.

**Decision D13 was ruled on 2026-07-28 and turned that caution into a normative rule.**
Specification section 2.3 states what a valid root proves - a typed payload committed by an identified issuer, and nothing clinical - and forbids any surface derived from this protocol from asserting a clinical fact on the strength of root validity alone.
Enforcing subject, event, cardinality and reference rules is a **separate, independently versioned conformance layer** that a deployment may adopt, deliberately kept off the canonicalization critical path so that it can arrive later as an additive change.
Each of the four documents below records, in its own last section, what its family's schema does not enforce; that section is the input to that layer, not a to-do list for this one.

## Provenance

All four profiles were derived from the reference schemata read in place, read-only, under `references/schemata/src/sg/gov/moh`, at Open-Attestation/schemata commit `09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa`.

**No reference schema is copied into this repository.**
`references/` is excluded by `.gitignore` by design.
These four documents cite the reference schemas by file and by the section or definition concerned; line-level citations into `dogtag-mono-repo` appear in [the specification section 14](../spec/roax-canon-1.md#14-reconciliation-with-dogtag).

## Documents

The registry as it stands.
One entry is an international standard and three are one jurisdiction's; a further jurisdiction is added here rather than anywhere else.

- [`fhir.md`](fhir.md) - HL7 FHIR 4.0.1, full and lite
- [`pdt-healthcert.md`](pdt-healthcert.md) - Singapore MOH PDT HealthCert 2.0
- [`recovery-healthcert.md`](recovery-healthcert.md) - Singapore MOH Recovery HealthCert 2.0
- [`vaccination-healthcert.md`](vaccination-healthcert.md) - Singapore MOH Vaccination HealthCert 1.0
