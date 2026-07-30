# Profile: Singapore MOH Recovery HealthCert 2.0

**`recordType`:** `sg.gov.moh.recovery-healthcert` **`schemaVersion`:** `2.0` **Status:** published as [`type-maps/sg.gov.moh.recovery-healthcert-2.0.json`](../../type-maps/sg.gov.moh.recovery-healthcert-2.0.json) at exact artifact ID `sha256:db935b67a3a82754921267e3af237b606f7489b46e05aa892d175b8d87504177`.
The lite-FHIR `Narrative.div` and four `base64Binary` slots remain unresolved, null placeholders admitted by FHIR but rejected by the pinned schema fail closed, 65 Bundle-reachable lite-FHIR object nodes omit an object type, and the recovery root remains an issuer extension point, as audited in [`docs/type-maps.md`](../type-maps.md) sections 1.3, 1.5, 2 and 5.

Recovery is the closest sibling of PDT and shares most of its shape.
This document states what differs, and does not restate what is identical.

---

## 1. Record shape

Seven required fields - the PDT six plus `validUntil`:

```
id, version, type, validFrom, validUntil, fhirVersion, fhirBundle
```

Differences from PDT:

| | PDT 2.0 | Recovery 2.0 |
|---|---|---|
| `version` | `pdt-healthcert-v2.0` | `rec-healthcert-v2.0` |
| `type` | `PCR`, `ART`, `SER`, `LAMP`; scalar **or array** | `PCR`, `ART`, `SER`; **scalar only** |
| `validUntil` | absent | required, date-time |
| Workflow variants | three schemas (base, clinic, endorsed) | one schema |

**`type` being scalar-only is the single most important difference for the type map.**
The PDT type map must handle a polymorphic `type`; the recovery one must not accept an array there.
A type map shared between the two families would be wrong for one of them.

`fhirBundle` again references the lite FHIR 4.0.1 `Bundle`, so entries carry a nested `.resource` - the genuine FHIR layout, same as PDT and unlike vaccination.

## 2. The `$id` collision - a real defect

**The recovery schema's `$id` is copied from PDT and points at `.../pdt-healthcert/2.0/schema.json`, despite the file being the recovery schema.**

This collides with PDT's schema identity in any validator that registers both by `$id`.
Depending on registration order, one schema silently shadows the other, and a recovery record can end up validated against the PDT rules - which would accept an array-valued `type` and would not require `validUntil`.

**Requirement for ROAX:** an implementation MUST NOT resolve these reference schemas by `$id`.
Load them by path, or rewrite the `$id` at load time and record that it did so.
A test that registers both and asserts the recovery rules still apply belongs in the conformance corpus (`docs/conformance-corpus.md`, class 13).

This defect is in the reference schemata, not in ROAX, and ROAX cannot fix it upstream.
It can only refuse to be caught by it.

## 3. Type-map scope

- The lite FHIR 4.0.1 definitions reachable from `Bundle`, identical to PDT and audited in [`fhir.md`](fhir.md) section 4.
- The recovery envelope fields declared at `references/schemata/src/sg/gov/moh/recovery-healthcert/2.0/schema.json`, read at upstream commit `09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa`, with `type` bound as scalar STRING only.
- No OpenAttestation or Notarise composition is included because recovery has one source schema rather than clinic and endorsed variants.

The executable DFA has 317 states, 640 exact KEY transitions, 159 INDEX transitions and 310 resolved outputs, as reported in [`docs/type-maps.md`](../type-maps.md) section 2.3.
The finite scalar audit counts 331 declared units, of which 319 are confident, seven use an operative FHIR element-name inference and five remain unresolved, as audited in [`docs/type-maps.md`](../type-maps.md) section 2.2.
Separately, 65 reached lite-FHIR object-applicator source nodes collapse to 63 marked DFA states because those definitions omit `type: "object"`, as audited in [`docs/type-maps.md`](../type-maps.md) sections 1.5 and 2.3.
Its exact artifact ID, `recordType` and `schemaVersion` are checked together when selecting this map, under [`docs/type-maps.md`](../type-maps.md) section 4 and specification section 4.2.
The open recovery root permits issuer properties but supplies no semantic type for an unknown path, so issuers add such paths only through immutable scoped child artifacts under [`docs/type-maps.md`](../type-maps.md) section 5.

`logo` is present here too and is a base64 blob.
In the recovery sample it is 2,618 bytes, much smaller than the PDT and vaccination blobs but still the largest single value in that record.
The published map binds it as STRING over its base64 text because the recovery schema declares a string, under specification sections 4.2 and 6.3.

## 4. Non-redactable paths

| Path | Why |
|---|---|
| `roax.recordType`, `roax.schemaVersion`, `roax.typeMap.id`, `roax.recordId`, `roax.issuer.id` | The reserved floor (spec section 11.2), which every profile carries. `roax.recordType`, `roax.schemaVersion` and `roax.typeMap.id` are mandatory by arithmetic because the verifier checks the exact artifact ID and its two profile selectors before resolving any disclosed leaf ([`docs/type-maps.md`](../type-maps.md) section 4). `roax.recordId` and `roax.issuer.id` are mandatory by policy, so a disclosed copy says which record it is and who issued it. `roax.recordId` was arithmetic until decision D4 was ruled D4b on 2026-07-28, which removed the salt preimage it used to be an input to. `roax.issuer.keyId` is committed but OPTIONAL to disclose under specification section 11.2, because requiring it would break key rotation on already-anchored records. |
| `version` | Pins `rec-healthcert-v2.0`. Also the only field that distinguishes this from a PDT record if `recordType` were ever mis-set. |
| `type` | The test kind. |
| `validFrom` | Start of the validity interval. |
| `validUntil` | **End of the validity interval.** This is the recovery-specific addition and it is the important one: a recovery certificate whose expiry can be withheld while the rest verifies is an expired certificate that presents as valid. |

`validUntil` is the clearest single illustration of why the minimum-disclosure floor exists at all.
Without it the holder chooses whether the verifier learns the certificate has expired.

## 5. Known defects and cautions

- **The `$id` collision** - section 2.
  The most consequential of the three.
- **`fhirVersion` is unvalidated** - see [`fhir.md`](fhir.md) section 6.
- **A minimal Bundle validates.**
  `{"resourceType":"Bundle"}` satisfies `fhirBundle`.
  Confirmed by reproduction.

## 6. What the schema and tests do NOT enforce

Tests accept the three scalar types and reject a missing, unknown or array-valued `type`; they reject a missing `id` or `version`, missing or invalid validity dates, and missing FHIR fields.

Neither the schema nor the tests require that:

- the Observation is **positive** - which is the entire clinical premise of a recovery certificate;
- the observation date precedes the certificate interval;
- `validUntil` is later than `validFrom`;
- the Patient is connected to the Observation;
- references resolve;
- any clinical resource is present at all.

**The first of these deserves emphasis.**
A recovery certificate asserts recovery, which implies a prior positive result.
The schema does not check the result is positive.
A record carrying a negative observation validates identically.

**Consequence for ROAX:** the same caution as PDT, sharpened.
A valid `sg.gov.moh.recovery-healthcert` root proves a typed payload was committed by an issuer.
It does not prove recovery, does not prove a positive result, and does not prove the validity interval is coherent.
If ROAX intends to claim recovery semantics, those rules have to be added by this profile and enforced above the protocol layer.

**Decision D13 is ruled and that makes this normative.**
Specification section 2.3 states that no surface derived from this protocol may assert a clinical fact from root validity alone, and puts clinical validation in a separate, independently versioned layer.
"Proof of recovery" on a screen, derived from a root that verified, is exactly the claim that section forbids.
