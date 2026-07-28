# Profile: Singapore MOH Recovery HealthCert 2.0

**`recordType`:** `sg.gov.moh.recovery-healthcert`
**`schemaVersion`:** `2.0`
**Status:** draft. The type map for this profile does not exist.

Recovery is the closest sibling of PDT and shares most of its shape. This document states what
differs, and does not restate what is identical.

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

`fhirBundle` again references the lite FHIR 4.0.1 `Bundle`, so entries carry a nested `.resource` -
the genuine FHIR layout, same as PDT and unlike vaccination.

## 2. The `$id` collision - a real defect

**The recovery schema's `$id` is copied from PDT and points at
`.../pdt-healthcert/2.0/schema.json`, despite the file being the recovery schema.**

This collides with PDT's schema identity in any validator that registers both by `$id`. Depending on
registration order, one schema silently shadows the other, and a recovery record can end up
validated against the PDT rules - which would accept an array-valued `type` and would not require
`validUntil`.

**Requirement for ROAX:** an implementation MUST NOT resolve these reference schemas by `$id`.
Load them by path, or rewrite the `$id` at load time and record that it did so. A test that
registers both and asserts the recovery rules still apply belongs in the conformance corpus
(`docs/conformance-corpus.md`, class 13).

This defect is in the reference schemata, not in ROAX, and ROAX cannot fix it upstream. It can only
refuse to be caught by it.

## 3. Type-map scope

- The lite FHIR 4.0.1 definitions reachable from `Bundle`, identical to PDT.
- The recovery envelope fields, with `type` bound as a scalar `STRING` **only**.
- No OpenAttestation or Notarise composition - recovery has one schema, so there is no clinic or
  endorsed variant to cover.

`logo` is present here too and is a base64 blob. In the recovery sample it is 2,618 bytes, much
smaller than the PDT and vaccination blobs but still the largest single value in that record.
Bind as `STRING` per specification section 6.3.

## 4. Non-redactable paths

| Path | Why |
|---|---|
| `roax.canon`, `roax.hashAlg`, `roax.recordType`, `roax.schemaVersion`, `roax.recordId`, `roax.issuer.id` | The reserved floor (spec section 11.2), which every profile carries. `roax.issuer.keyId` is additionally non-redactable whenever it is present. |
| `version` | Pins `rec-healthcert-v2.0`. Also the only field that distinguishes this from a PDT record if `recordType` were ever mis-set. |
| `type` | The test kind. |
| `validFrom` | Start of the validity interval. |
| `validUntil` | **End of the validity interval.** This is the recovery-specific addition and it is the important one: a recovery certificate whose expiry can be withheld while the rest verifies is an expired certificate that presents as valid. |

`validUntil` is the clearest single illustration of why the minimum-disclosure floor exists at all.
Without it the holder chooses whether the verifier learns the certificate has expired.

## 5. Known defects and cautions

- **The `$id` collision** - section 2. The most consequential of the three.
- **`fhirVersion` is unvalidated** - see [`fhir.md`](fhir.md) section 6.
- **A minimal Bundle validates.** `{"resourceType":"Bundle"}` satisfies `fhirBundle`. Confirmed by
  reproduction.

## 6. What the schema and tests do NOT enforce

Tests accept the three scalar types and reject a missing, unknown or array-valued `type`; they
reject a missing `id` or `version`, missing or invalid validity dates, and missing FHIR fields.

Neither the schema nor the tests require that:

- the Observation is **positive** - which is the entire clinical premise of a recovery certificate;
- the observation date precedes the certificate interval;
- `validUntil` is later than `validFrom`;
- the Patient is connected to the Observation;
- references resolve;
- any clinical resource is present at all.

**The first of these deserves emphasis.** A recovery certificate asserts recovery, which implies a
prior positive result. The schema does not check the result is positive. A record carrying a
negative observation validates identically.

**Consequence for ROAX:** the same caution as PDT, sharpened. A valid
`sg.gov.moh.recovery-healthcert` root proves a typed payload was committed by an issuer. It does not
prove recovery, does not prove a positive result, and does not prove the validity interval is
coherent. If ROAX intends to claim recovery semantics, those rules have to be added by this profile
and enforced above the protocol layer. That is part of decision D13.
