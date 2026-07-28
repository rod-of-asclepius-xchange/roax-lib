# Record profiles

There are four profile documents because the four record families **do not share one concrete
object.** They share a boundary, not a schema.

That finding is load-bearing, so it is stated here with its evidence rather than assumed.

## There is no field required by all four

- Full FHIR 4.0.1 is any one of 146 resource types and has no healthcert envelope at all.
- PDT and recovery require `id`, `version`, `type`, validity, `fhirVersion` and `fhirBundle`.
- Vaccination requires `id`, `name`, validity, `fhirBundle`, `issuers`, `$template` and
  `notarisationMetadata`.

Across the three healthcert schemas, only `id`, `validFrom`, `fhirVersion` and `fhirBundle` are
required by all three. PDT and recovery additionally share `version` and `type`.

**And even `fhirBundle` has two incompatible layouts.** PDT and recovery wrap a genuine FHIR Bundle
whose entries carry a nested `.resource`; the vaccination healthcert puts `resourceType` and
`fullUrl` directly on each entry. Anything that treated `fhirBundle` as one shape would be wrong for
one of the two.

That physical intersection is too small to represent healthcare meaning. A single flattened
"common healthcert" schema is not supported by the evidence.

## What is common, then

Only this:

```
protocol version
canonicalization / hash / tree algorithm identifiers
schema-or-profile identifier (committed, not merely advisory)
typed payload tree
salted commitments and disclosure proofs
optional anchoring metadata
```

Everything clinical - FHIR constraints, test semantics, validity rules, vaccine semantics,
issuer/notary/rendering workflow, cross-reference invariants - belongs to a profile.

This boundary comes from the OpenAttestation audit's section 6.3.
It was re-checked against dogtag before being adopted here, because the audit reached it without
consulting dogtag; see [the specification section 14.1](../spec/roax-canon-1.md#141-the-boundary-question-checked)
for that reconciliation and its conclusion.

## What each profile document must declare

**This directory is the `recordType` registry.**
`schemas/envelope-1.0.json` constrains `recordType` to a lowercase reverse-DNS *form* rather than to
a closed list, because the list is extensible. It is the registry that closes it: **adding a
`recordType` value REQUIRES adding a profile document here declaring at least the first three rows
below**, and a syntactically valid `recordType` with no profile document is not a valid record.

The v1 registry is `sg.gov.moh.vaccination-healthcert`, `sg.gov.moh.pdt-healthcert`,
`sg.gov.moh.recovery-healthcert` and `hl7.fhir.bundle`.

| Item | Why |
|---|---|
| `recordType` and `schemaVersion` values | They are committed inside the root as reserved leaves (spec section 11.2). |
| Type-map scope | Which schema definitions the type map must cover for this family (spec section 4.2). |
| Non-redactable paths | The minimum-disclosure floor (spec section 10.2). Without it a disclosed copy can hide what the record is. |
| Blob-bearing fields | Which fields carry base64 and how they are bound (spec section 6.3). |
| Known schema defects | So an implementer is not surprised by them. |
| What the schema does NOT enforce | The gap between what the samples show and what the schema requires. This gap is large and is the single most misleading thing about these families. |

## A caution that applies to all four

**"Required within a resource" and "the bundle must contain that resource" are different
statements.** The reference schemas frequently do the former and not the latter.

A validator reproduction against the audited schemas confirmed that both PDT and recovery accept
their required envelopes with a `fhirBundle` of `{"resourceType":"Bundle"}` and nothing else, and
accept an arbitrary `fhirVersion` string. That follows directly from the schemas; it is not a bug in
the validator.

So ROAX must not infer clinical guarantees from the fact that a record validates. The protocol layer
commits what it is given. Whether what it was given is clinically meaningful is a profile question,
and today the profiles largely do not answer it.

## Provenance

All four profiles were derived from the reference schemata read in place, read-only, under
`references/schemata/src/sg/gov/moh`, at Open-Attestation/schemata commit
`09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa`.

**No reference schema is copied into this repository.** `references/` is excluded by `.gitignore`
by design. These four documents cite the reference schemas by file and by the section or definition
concerned; line-level citations into `dogtag-mono-repo` appear in
[the specification section 14](../spec/roax-canon-1.md#14-reconciliation-with-dogtag).

## Documents

- [`fhir.md`](fhir.md) - HL7 FHIR 4.0.1, full and lite
- [`pdt-healthcert.md`](pdt-healthcert.md) - Singapore MOH PDT HealthCert 2.0
- [`recovery-healthcert.md`](recovery-healthcert.md) - Singapore MOH Recovery HealthCert 2.0
- [`vaccination-healthcert.md`](vaccination-healthcert.md) - Singapore MOH Vaccination HealthCert 1.0
