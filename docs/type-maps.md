# ROAX type maps, coverage and issuer extensions

**Status:** base artifacts published at `typeMapVersion: 1.0.0`.
The five undetermined bindings were ruled on 2026-07-30 and the lookup normalizes its key under ruled decision D14a.
Two of the five rulings are operative in the corpus-side maps; none of the four that are bindings is yet in the four published artifacts, for the reason section 1.6 states.
Every path outside those five still fails closed.

This document defines the type-map artifact lifecycle required by decision D7 and reports exactly what the pinned reference schemas do and do not type.
The operative artifacts are in `type-maps/`, and their format is defined by `schemas/type-map-artifact-1.0.json`.

## 1. The five undetermined bindings, ruled

**All five were ruled on 2026-07-30.**
Before that they failed closed, because ROAX-CANON/1 section 4.2 and ruled decision D7 admit a binding only where evidence determines one ROAX tag, and the pinned reference schemas determine none of these five.
A ruling is what binds such a path, and a ruling lands in a document rather than in a resolver improvement.

**Each ruling carries its evidence grade, and the grades are not decoration.**
A Decisive ruling has a governing standard or a validation order that leaves no remaining type choice.
A Strong one rests on external evidence that the selected schema does not itself state.
A Moderate one rests on a profile declaration rather than on any schema, which is a materially weaker footing and must not read like the others to whoever revisits it.

| Binding | Ruling | Grade | What the ruling rests on |
|---|---|---|---|
| Vaccination signed-certificate `dose` | **INTEGER**, plus a profile narrowing to a positive integer | Strong | The EU Digital COVID Certificate these certificates mirror defines its dose-sequence number as a positive integer. The pinned schema says only `type: "number"` and chooses neither ROAX numeric tag. See section 1.1. |
| FHIR `base64Binary` | **BYTES** over the decoded octets, with canonical RFC 4648 base64 as an input-admissibility condition | Strong | FHIR R4 defines the datatype as a stream of bytes and its JSON form as base64 text, so BYTES commits the value rather than the transport spelling. See section 1.3. |
| Signed-certificate `expiryDateTime` | **STRING**, by explicit profile declaration | Moderate | The field name, both examples and the standard meaning of `date-time`. **Not the schema**, which carries a `format` and no `type` and formally admits every JSON kind. See section 1.1. |
| FHIR `Narrative.div` | **STRING** over the escaped XHTML text, without parsing or reserializing it | Decisive | FHIR R4's normative JSON representation states that `Narrative.div` is one escaped XHTML string. See section 1.3. |
| FHIR primitive-array null placeholders | **No NULL binding**, and **reject** such records until a versioned schema and type-map revision admits the FHIR representation | Decisive | Complete profile validation runs before map resolution under ROAX-CANON/1 section 4.2, so a map may not widen a record its own selected schema refuses. See section 1.3. |

**Two of the five reach the corpus as operative bindings today, and three do not.**
`dose` and `expiryDateTime` are operative in `corpus/type-maps/sg.gov.moh.vaccination-healthcert.json`, which is what class 10 resolves against, and the shipped vaccination sample commits as a result.
The three FHIR rulings are recorded here and pinned as tag semantics by corpus vectors over the synthetic profile, while the four published artifacts in `type-maps/` still carry their pre-ruling `unresolved` rows.
Section 1.6 states exactly why and what the next change must do.

What remains genuinely unbound is a different list, and none of it was ruled here:

| Classification | Paths | Current result |
|---|---|---|
| Outside the selected base-schema scope | The 20 PDT endorsed-sample path-kind pairs | Each proposed STRING binding is listed with its composition-schema evidence in section 1.2, but the PDT base profile selects none of them, and the clean answer is a versioned composition profile rather than 20 authored bindings. Nobody has ruled one, so the PDT sample stays uncommittable. |
| Structurally underconstrained | The full and lite FHIR object-applicator definitions in section 1.5 | KEY traversal is retained, while non-object tags are never inferred from `properties`, `required` or `additionalProperties`. |
| Structurally underconstrained | The 26 vaccination object-intended patterns in section 1.4 | Object child traversal is supported, while every non-object alternative remains unbound. |

### 1.1 Vaccination signed EU certificate fields, RULED

#### `dose` is INTEGER, grade Strong, plus a profile narrowing to a positive integer

The source says only `type: "number"` and carries no integer or decimal constraint at `references/schemata/src/sg/gov/tech/notarise/1.0/schema.json#/properties/notarisationMetadata/properties/signedEuHealthCerts/items/anyOf/0/properties/dose`, read at upstream commit `09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa`.
JSON Schema Core draft-07 section 4.2.1 models `number` as an arbitrary-precision base-10 value and places lexical distinctions outside its data model, so `type: "number"` chooses neither of the distinct INTEGER and DECIMAL tags ROAX-CANON/1 section 6.1 defines.
The schema therefore settles nothing and the ruling comes from outside it.

The European Commission's EU Digital COVID Certificate JSON Schema Specification 1.3.0 calls both the dose-sequence number `v/dn` and the series total `v/sd` positive integers, and the authoritative schema at tag `1.3.0`, commit `a603410d760fefc9073931c8c807759d9714c136`, makes both reference `dose_posint`, which is `integer` with minimum 1.

**The grade is Strong rather than Decisive for a specific reason.**
The EU DCC is a different specification, and the Singapore wrapper never states that its wrapper-level `dose` is the EU DCC `dn` field: the wrapper carries the signed DCC in `qr`, while `dose` is adjacent wrapper metadata.
The correspondence is a well-supported inference and not a declared mapping.

**The ruling is INTEGER plus a positive-integer profile narrowing, and the second half is not optional.**
A bare type-map edit would leave `0` and every negative value formally valid under the selected profile, because both are grammar-valid ROAX INTEGERs.
A fractional value is already refused one layer down by the section 6.2 INTEGER grammar, so the narrowing is about `0` and the negatives and about nothing else.

**The narrowing is not in the type map and not in the canonicalization layer, and that placement is itself ruled.**
A type map answers which tag a structured path and observed kind select; a value-domain constraint is a different question, and ROAX-CANON/1 section 4.2 puts it in a different place and a different order, requiring complete profile validation before map resolution.
Decision D13 was ruled D13a with a split that keeps value-domain validation in "a separate, independently versioned conformance layer" and rejected merging it into the protocol layer explicitly, because that puts profile governance on the critical path of a cryptographic specification (`docs/decisions.md`, D13).
So the rule is declared by `docs/profiles/vaccination-healthcert.md` section 6, enforced by the profile validator, and executable in `corpus/tools/profile_rules.py` and `profile_rules.mjs`, which run as the issuer's half of section 4.2 step 1 before any leaf is built.
`corpus/tools/run.sh` step 5 self-tests both, and `rust/tests/dfa_profile_protocol.rs` pins the layering through the `SchemaValidator` seam by showing the ruled profile refuse `0` while the bare canonicalization layer accepts it.

#### `expiryDateTime` is STRING, grade Moderate, by explicit profile declaration

Both source branches carry `format: "date-time"` and a string example and declare **no instance type** at `references/schemata/src/sg/gov/tech/notarise/1.0/schema.json#/properties/notarisationMetadata/properties/signedEuHealthCerts/items/anyOf`, read at the same upstream commit.
Under JSON Schema Validation draft-07 sections 7.2 and 7.3.1, `format` is an annotation unless validation behaviour is explicitly enabled, and a `date-time` format attribute applies to string instances, so the keyword neither creates a string type nor rejects a non-string instance.
The schema formally admits every JSON kind.

**This ruling therefore rests on a profile declaration and not on the schema, which is exactly what its Moderate grade records.**
The supporting evidence is the field name, both shipped examples and the standard meaning of `date-time`, and no separate governing specification for this wrapper field was found.
That is materially weaker than the `dose` ruling, which has an external standard behind it, and weaker again than the Decisive FHIR rulings in section 1.3.
The declaration is in `docs/profiles/vaccination-healthcert.md` section 6, and a future upstream `type: "string"` correction would upgrade the footing without changing the tag.

#### What the two rulings unblocked

The shipped vaccination sample now commits, at 91 leaves without an issuer key identifier and 92 with one, and class 10 goes from 1 of 3 records to 2 of 3 (`corpus/README.md`).
It commits against the CORPUS-SIDE map, which carries both bindings; the published `type-maps/sg.gov.moh.vaccination-healthcert-1.0.json` still declares both slots `unresolved`, as section 1.6 states.
Both rulings are held apart from the schema walk in `corpus/tools/build_type_maps.py`, which refuses to build if a ruling names a path the walk did not independently report unbound, or collides with a binding the schema determines.
That guard is what keeps a ruling able only to resolve a measured gap rather than to change a derived tag.

### 1.2 PDT fields present in the endorsed sample but absent from the base schema

The PDT base object declares seven members and leaves `additionalProperties` open at `references/schemata/src/sg/gov/moh/pdt-healthcert/2.0/schema.json`, read at upstream commit `09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa`.
Its shipped endorsed sample reaches 20 `(path pattern, observed JSON kind)` pairs that the base schema does not declare.
The clinic and endorsed composition files are useful evidence, but `recordType: sg.gov.moh.pdt-healthcert` plus `schemaVersion: 2.0` does not select one of those workflow variants.
The base map therefore does not silently promote either composition into the profile.

Each candidate below proposes STRING and remains non-operative:

| Path pattern | Kind | Proposed tag | Evidence |
|---|---|---:|---|
| `$template.name` | string | 2 | OA 2.0 declares string at `references/schemata/src/__schema__/com/openattestation/2.0/schema.json#/properties/$template/oneOf/1/properties/name`. |
| `$template.type` | string | 2 | OA 2.0 declares string at `references/schemata/src/__schema__/com/openattestation/2.0/schema.json#/properties/$template/oneOf/1/properties/type`. |
| `$template.url` | string | 2 | OA 2.0 declares string at `references/schemata/src/__schema__/com/openattestation/2.0/schema.json#/properties/$template/oneOf/1/properties/url`. |
| `attachments[*].data` | string | 2 | OA 2.0 declares string at `references/schemata/src/__schema__/com/openattestation/2.0/schema.json#/properties/attachments/items/properties/data`. |
| `attachments[*].filename` | string | 2 | OA 2.0 declares string at `references/schemata/src/__schema__/com/openattestation/2.0/schema.json#/properties/attachments/items/properties/filename`. |
| `attachments[*].type` | string | 2 | OA 2.0 declares string at `references/schemata/src/__schema__/com/openattestation/2.0/schema.json#/properties/attachments/items/properties/type`. |
| `issuers[*].id` | string | 2 | OA 2.0 declares string at `references/schemata/src/__schema__/com/openattestation/2.0/schema.json#/definitions/issuer/properties/id`. |
| `issuers[*].identityProof.key` | string | 2 | OA 2.0 declares string in its DID identity-proof definitions. |
| `issuers[*].identityProof.location` | string | 2 | OA 2.0 declares string in its DNS identity-proof definitions. |
| `issuers[*].identityProof.type` | string | 2 | OA 2.0 declares string in all three identity-proof definitions. |
| `issuers[*].name` | string | 2 | OA 2.0 declares string at `references/schemata/src/__schema__/com/openattestation/2.0/schema.json#/definitions/issuer/properties/name`. |
| `issuers[*].revocation.type` | string | 2 | OA 2.0 declares string at `references/schemata/src/__schema__/com/openattestation/2.0/schema.json#/definitions/issuer/properties/revocation/properties/type`. |
| `notarisationMetadata.notarisedOn` | string | 2 | Notarise 1.0 declares string at `references/schemata/src/sg/gov/tech/notarise/1.0/schema.json#/properties/notarisationMetadata/properties/notarisedOn`. |
| `notarisationMetadata.passportNumber` | string | 2 | Notarise 1.0 declares string at `references/schemata/src/sg/gov/tech/notarise/1.0/schema.json#/properties/notarisationMetadata/properties/passportNumber`. |
| `notarisationMetadata.reference` | string | 2 | Notarise 1.0 declares string at `references/schemata/src/sg/gov/tech/notarise/1.0/schema.json#/properties/notarisationMetadata/properties/reference`. |
| `notarisationMetadata.signedEuHealthCerts[*].appleCovidCardUrl` | string | 2 | Notarise 1.0 declares string in both signed certificate branches. |
| `notarisationMetadata.signedEuHealthCerts[*].expiryDateTime` | string | 2 | Notarise 1.0 carries a date-time annotation and string examples but no type, so this proposal is weaker than the other 19. |
| `notarisationMetadata.signedEuHealthCerts[*].qr` | string | 2 | Notarise 1.0 declares string in both signed certificate branches. |
| `notarisationMetadata.signedEuHealthCerts[*].type` | string | 2 | Notarise 1.0 restricts both branches to string const or string enum values. |
| `notarisationMetadata.url` | string | 2 | Notarise 1.0 declares string at `references/schemata/src/sg/gov/tech/notarise/1.0/schema.json#/properties/notarisationMetadata/properties/url`. |

The clean ruling is to register distinct PDT base, clinic and endorsed profile variants, or to declare their union explicitly and version that profile decision.
Until that happens, the base PDT map accepts its seven declared fields and its lite FHIR Bundle, while those 20 sample pairs fail closed under ROAX-CANON/1 section 4.2.

### 1.3 FHIR XHTML, base64Binary and null placeholders, RULED

#### `base64Binary` is BYTES over the decoded octets, grade Strong

The pinned full and lite FHIR schemas define `base64Binary` as a JSON string and describe its semantic value as a stream of bytes, at `references/schemata/src/sg/gov/moh/fhir/4.0.1/schema.json#/definitions/base64Binary` and `references/schemata/src/sg/gov/moh/fhir/4.0.1/lite-schema.json#/definitions/base64Binary`, both read at upstream commit `09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa`.
FHIR R4 defines the datatype as a stream of bytes encoded using base64 while identifying its JSON representation as a JSON string containing base64 text.
That value-versus-serialization distinction is exactly the choice ROAX-CANON/1 section 6.3 leaves to a profile, between STRING over the base64 text and BYTES over the decoded bytes.

**BYTES is ruled because it commits the FHIR value, the decoded octet sequence, rather than the transport spelling used to carry it.**
Full FHIR has six reachable schema-local `base64Binary` slots and lite FHIR has four.

**The grade is Strong rather than Decisive because STRING remains a legitimate profile choice elsewhere.**
A profile is permitted to commit a serialization as STRING when preserving that exact spelling is itself the intended semantics, and the explicitly typed healthcert blob fields still bind as STRING for that reason (ROAX-CANON/1 section 6.3).
So this ruling says what FHIR `base64Binary` means, and it does not say that base64 is always BYTES.

**The canonical base64 form is an INPUT-ADMISSIBILITY condition and never the committed value, and the distinction is load-bearing.**
ROAX-CANON/1 section 6.3 already pins RFC 4648 section 4: the standard alphabet, with padding, and no line wrapping, rejecting the URL-safe alphabet of RFC 4648 section 5, absent or excess padding, any character outside the alphabet including a line break, and a final quantum whose unused bits are non-zero.
That pin has to survive a BYTES ruling rather than become redundant under it.
RFC 4648 section 3.5 explains why: without it, several spellings decode to the same octets, so two implementations can agree about the bytes while disagreeing about whether the record is admissible at all.
Three of the four rejection vectors added for this ruling decode to the accepted fixture's octets under a permissive decoder, which is that hazard exhibited rather than described.

#### `Narrative.div` is STRING over the escaped XHTML text, grade Decisive

`Narrative.div` resolves to `#/definitions/xhtml`, whose reference definition carries a description and no JSON instance type, at `references/schemata/src/sg/gov/moh/fhir/4.0.1/lite-schema.json#/definitions/xhtml`, read at the same upstream commit.
FHIR R4's normative JSON representation states that XHTML is represented as an escaped string and that the `Narrative.div` element is represented as one escaped XHTML string.

**That directly governing rule leaves no remaining type choice, which is what makes this ruling Decisive where the two above are not.**
The tag is a carrier type and nothing more: STRING selects `utf8(NFC(s))` under ROAX-CANON/1 section 6.1, so an implementation MUST NOT parse the XHTML, normalize it as markup, or reserialize it for commitment.
A separate FHIR validator may still enforce the allowed XHTML content rules, because a carrier type does not validate markup structure.

#### Primitive-array null placeholders publish no NULL binding and reject the record, grade Decisive

FHIR R4's normative JSON representation uses JSON nulls in paired repeating primitive and `_foo` arrays so that values, ids and extensions stay aligned by index, including a null in the value array where a repeating primitive has metadata but no value.
The pinned schemas reject at least the value-array half of that representation, because primitive array items reference a non-null primitive type: `HumanName.given[]` references the FHIR string definition with no null branch at `references/schemata/src/sg/gov/moh/fhir/4.0.1/lite-schema.json#/definitions/HumanName/properties/given`, read at the same upstream commit.
The full schema has 175 schema-local primitive-array slots and the lite schema has 12.

**This is a schema-versus-standard admission conflict and not an ambiguous type, which is why it is Decisive.**
ROAX-CANON/1 section 4.2 requires complete profile validation before map resolution, so the exact selected schema wins for the current artifacts and the map may not widen a record its own schema refuses.
Adding NULL to the map alone would contradict the schema rather than resolve it.

**The ruling is therefore expressed as an absence, and an absence needs a vector or it is unfalsifiable.**
`corpus/type-maps/org.roax.corpus.synthetic.json` binds `name[*].given[*]` for `string` and declares nothing for `null`, and `reject-fhir-primitive-array-null-placeholder` asserts that a record carrying the placeholder is refused.
If standard-conformant placeholders are later required, governance publishes a new schema and profile version that explicitly admits null at the paired primitive-array item sites, together with the exact corresponding type map carrying NULL outputs, in one change.

### 1.4 Vaccination object-intended schemas that omit `type: "object"`

Twenty-six vaccination path patterns contain `properties` but omit an object type.
JSON Schema Validation draft-07 sections 6.5.4 and 6.5.3 apply `properties` and `required` only to object instances, so non-object values bypass those keywords.

The DFA follows declared child properties when the observed value is an object and authorizes an empty object only when the object branch carries no effective required member.
It supplies no scalar, array or null output merely because those malformed alternatives happen to pass the weak schema.

The affected patterns are:

```text
attachments[*]
fhirBundle.entry[*]
fhirBundle.entry[*].extension[*]
fhirBundle.entry[*].identifier[*]
fhirBundle.entry[*].identifier[*].type
fhirBundle.entry[*].name[*]
fhirBundle.entry[*].type.coding[*]
fhirBundle.entry[*].collection
fhirBundle.entry[*].code
fhirBundle.entry[*].code.coding[*]
fhirBundle.entry[*].valueCodeableConcept
fhirBundle.entry[*].valueCodeableConcept.coding[*]
fhirBundle.entry[*].performer
fhirBundle.entry[*].performer.name[*]
fhirBundle.entry[*].qualification[*]
fhirBundle.entry[*].contact
fhirBundle.entry[*].contact.telecom[*]
fhirBundle.entry[*].contact.address
fhirBundle.entry[*].endpoint
fhirBundle.entry[*].vaccineCode.coding[*]
fhirBundle.entry[*].performer[*]
fhirBundle.entry[*].recommendation[*]
fhirBundle.entry[*].recommendation[*].targetDisease.coding[*]
fhirBundle.entry[*].recommendation[*].forecastStatus.coding[*]
fhirBundle.entry[*].recommendation[*].dateCriterion[*]
fhirBundle.entry[*].recommendation[*].dateCriterion[*].code.coding[*]
```

This profile preserves the flattened pseudo-FHIR shape exactly.
No path above gains an `entry[*].resource` segment, as required by `docs/profiles/vaccination-healthcert.md` section 2.1 and ROAX-CANON/1 section 8.

### 1.5 FHIR object applicators that omit `type: "object"`

The pinned full FHIR schema has 659 definitions containing `properties`, and none declares `type: "object"`, at `references/schemata/src/sg/gov/moh/fhir/4.0.1/schema.json#/definitions`, read at upstream commit `09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa`.
The pinned lite schema has 66 such definitions and no explicitly typed object definition at `references/schemata/src/sg/gov/moh/fhir/4.0.1/lite-schema.json#/definitions`, read at the same upstream commit.
The Bundle-reachable lite scope uses 65 of those 66 definitions because `Element` is unreachable from `Bundle`.

JSON Schema Validation draft-06 sections 6.17, 6.18 and 6.20 apply `required`, `properties` and `additionalProperties` only to object instances.
A direct reference to one such complex definition can therefore admit a non-object value even though the definition is plainly object-intended.
For example, the `Identifier` definition has object applicators and no object type at `references/schemata/src/sg/gov/moh/fhir/4.0.1/schema.json#/definitions/Identifier`, read at the pinned upstream commit.

Combinators make the admission defect context-dependent rather than universal.
The full root and its `ResourceList` use `oneOf` across many object-intended definitions, so a scalar that vacuously satisfies more than one branch is rejected by the exactly-one rule in JSON Schema Validation draft-06 section 6.28.
A direct `$ref` to one complex definition admits that scalar, while an `anyOf` may also admit it under JSON Schema Validation draft-06 section 6.27.

The artifacts do not guess tags for any of these schema-silent non-object cases.
They retain the KEY transitions needed for object instances, mark each affected DFA state with non-operative `structurallyUntypedObject: true`, and emit no scalar, array or null output merely because an object keyword is inapplicable.
Complete profile validation still decides whether a particular context admits the observed non-object value before map resolution, under ROAX-CANON/1 section 4.2.

### 1.6 Where the five rulings have and have not landed

**Stated plainly, because a ruling recorded as if it were operative is worse than one recorded as open.**
The five rulings of sections 1.1 and 1.3 are made: vaccination `dose` INTEGER and `expiryDateTime` STRING, and the three FHIR ones for `base64Binary`, `Narrative.div` and the primitive-array null placeholders.

**Four of the five rulings are bindings, and not one of those four is in the four published artifacts.**
All four artifacts lag, not three.
`type-maps/hl7.fhir.bundle-4.0.1.json`, `sg.gov.moh.pdt-healthcert-2.0.json` and `sg.gov.moh.recovery-healthcert-2.0.json` still carry their pre-ruling `unresolved` rows for `base64Binary` and `Narrative.div`, and `type-maps/sg.gov.moh.vaccination-healthcert-1.0.json` still carries them for `dose` and `expiryDateTime` at states `s64` and `s65`.
The coverage figures in section 2 are measured on those bytes and still count every one of them as unresolved.
The fifth ruling is the exception in kind rather than in status: the primitive-array null-placeholder outcome IS "publish no NULL binding", so the artifacts already satisfy it by carrying no NULL output, and nothing has to land for it.

**The two vaccination rulings ARE operative, in a different artifact.**
`corpus/tools/build_type_maps.py` holds them in its `RULED_BINDINGS` table and writes them into `corpus/type-maps/sg.gov.moh.vaccination-healthcert.json`, which is the corpus-side map conformance class 10 resolves the shipped vaccination sample against.
That is why the sample commits at all, at the 91 leaves section 1.1 reports, and why class 10 moved from 1 of 3 records to 2 of 3.
The corpus-side map and the published artifact are separate bytes with separate version lines, so the sample committing is not evidence that a published artifact carries a binding.

The reason the published side lags is section 6: those four artifacts can currently be neither regenerated nor `--check`ed, because the generator fails closed on 34 merged object states.
`tools/build-type-maps.mjs` also has no ruling mechanism at all - nothing corresponding to the corpus-side `RULED_BINDINGS` - so even an unblocked regeneration would reproduce every one of those `unresolved` rows today.
Hand-editing a generated artifact would replace a regeneration blocked by a recorded ruling with one that is unreproducible in principle, and it would move four content IDs, the registry, the section 2.1 identity table and the IDs pinned in `rust/tests/published_type_maps.rs` and `kotlin/roax-canon/src/test/kotlin/io/roax/canon/PublishedTypeMapTest.kt` on bytes no generator can reproduce.
`tools/check-type-maps.mjs` passing on the untouched artifacts is the signal that this is still the safe regime.

**What is pinned today, and what it does and does not prove.**
The ruled tag SEMANTICS of the three FHIR rulings are exercised by corpus vectors over the synthetic profile: BYTES committing decoded octets and refusing four non-canonical spellings, STRING committing escaped XHTML unparsed, and the null placeholder failing closed.
Those hold five independent implementations to what each ruling means.
They are **not** the FHIR profile binding, and `corpus/README.md` says the same where the vectors live.

**What the next change must do**, in one change so that no intermediate state has a ruling in prose and a contradicting artifact:

1. Resolve the 34 merged object states combinator-aware, so the generator runs again.
2. Give `tools/build-type-maps.mjs` a ruling table held apart from the schema walk, under the same guards as the corpus-side one: a ruling may only resolve a path the walk independently reported unbound, and may never overwrite a tag the schema determines.
3. Regenerate all four artifacts with the four ruled bindings applied, which converts the affected `unresolved` rows into bindings; the null-placeholder ruling needs no row and must stay an absence.
4. Bump `typeMapVersion` by MINOR under section 5.2 on each artifact that gained a binding, since the change is additive and makes previously rejected records issuable.
5. Update the section 2.1 identity table, `type-maps/registry-1.0.0.json`, the section 2 coverage figures and the pinned IDs in `rust/tests/published_type_maps.rs` and `kotlin/roax-canon/src/test/kotlin/io/roax/canon/PublishedTypeMapTest.kt`, the second of which also asserts that the vaccination artifact still fails closed for `dose` and `expiryDateTime`, so step 3 moves it too.
6. Delete this section.

## 2. Published artifacts and finite coverage

Concrete path counts are infinite because arrays admit arbitrary indexes and FHIR resource and extension definitions recurse.
Claiming a finite absolute path total would therefore be false.
Coverage is reported with two finite measures: schema-local scalar slots for source audit, and DFA states, transitions and outputs for the executable map.

### 2.1 Artifact identities

An artifact ID is SHA-256 over `utf8("ROAX-TYPE-MAP/1\0") || exactArtifactBytes`.
This raw-byte construction is deliberately scoped to type-map control artifacts and does not change ROAX record canonicalization.
It avoids parsing an artifact through a floating-point JSON model before identifying it, consistent with ROAX-CANON/1 sections 3.2 and 6.4.
A consumer MUST decode the identified bytes as strict UTF-8 and reject duplicate JSON object member names and unpaired surrogate escapes after JSON escape decoding before interpreting the artifact, under the single-interpretation requirement in ROAX-CANON/1 section 3.2.
The content ID authenticates bytes, but it cannot make two permissive JSON parsers agree about malformed UTF-8, duplicate names or invalid Unicode scalar values.

| Profile | `schemaVersion` | `typeMapVersion` | Artifact ID |
|---|---|---|---|
| `hl7.fhir.bundle` | `4.0.1` | `1.0.0` | `sha256:0e9e642bc89c081e2e6faf651acdc25c46fac83201248ef53a7c812181279807` |
| `sg.gov.moh.pdt-healthcert` | `2.0` | `1.0.0` | `sha256:4f8cecc59c85101b8b567658c90651bcbf8f9d4dc279571aa40a03cf04f434ff` |
| `sg.gov.moh.recovery-healthcert` | `2.0` | `1.0.0` | `sha256:db935b67a3a82754921267e3af237b606f7489b46e05aa892d175b8d87504177` |
| `sg.gov.moh.vaccination-healthcert` | `1.0` | `1.0.0` | `sha256:de7bb92226af5fa5dc5064d9cb203329abc69160f4280fdf739e66e5e0151e93` |

The machine-readable copy is `type-maps/registry-1.0.0.json`.
An ID authenticates exact bytes but does not grant authority, just as an algorithm digest does not grant issuer authority under ROAX-CANON/1 section 7.4.

### 2.2 Source-level scalar coverage

The table deliberately separates direct or constraint-derived evidence from FHIR-specific inference.
The inference column counts exactly the operative bindings whose evidence is a generated FHIR element-name suffix, which is the `fhir-element-name` basis in `coverage.byBasis`: 74 for full FHIR, 7 for each lite scope and none for vaccination.
Those are the suffixes `Decimal`, `Integer`, `PositiveInt` and `UnsignedInt`.
A binding taken from a named FHIR primitive definition such as `decimal`, `integer`, `positiveInt` or `unsignedInt` reads a declared type name rather than an element-name suffix, so it is counted as confident; that is the `fhir-named-primitive` basis, with 8 bindings for full FHIR and 4 for each lite scope.
JSON Schema Validation draft-06 section 6.3.3 makes `pattern` a string keyword, so the numeric regex is not itself a validator constraint on `type: "number"`; FHIR R4 JSON section 2.6.2.3 and the generated element names supply the semantic evidence.

| Profile scope | Finite scalar audit units | Confident | Operative FHIR element-name inference | Unresolved | Additional gaps outside the declared scalar set |
|---|---:|---:|---:|---:|---|
| Full FHIR root union | 3,345 schema-local slots | 3,264 | 74 | 7 | Null placeholders conflict with the reference schema, and 659 object-applicator source nodes omit an object type. |
| PDT base plus lite Bundle | 331 declared units | 319 | 7 | 5 | 20 endorsed-sample pairs are undeclared by the base schema, and 65 reachable lite-FHIR object nodes omit an object type. |
| Recovery plus lite Bundle | 331 declared units | 319 | 7 | 5 | The open root makes issuer extension coverage unbounded, and 65 reachable lite-FHIR object nodes omit an object type. |
| Vaccination | 83 intended scalar path patterns | 81 | 0 | 2 | 33 source nodes collapse to 26 object-intended DFA states that admit untyped non-object alternatives in some contexts. |

The seven unresolved full-FHIR slots are six `base64Binary` occurrences plus `Narrative.div`.
The five unresolved lite-FHIR slots are four `base64Binary` occurrences plus `Narrative.div`.
The vaccination unresolved rows are `dose` and `expiryDateTime`.

The full FHIR profile starts at the reference schema's 146-resource root union.
Its misleading `hl7.fhir.bundle` identifier does not narrow the source to `#/definitions/Bundle`, as documented in `docs/profiles/fhir.md` sections 2 and 6.
The map reaches 678 of 680 definitions; unused named primitives `oid` and `uuid` are the two exceptions, while their inline value fields remain covered.

### 2.3 Executable DFA coverage

| Profile | States | KEY transitions | INDEX transitions | Scalar outputs | EMPTY_ARRAY | EMPTY_OBJECT | Explicit unresolved states | Untyped object source nodes | Untyped object DFA states |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Full FHIR root union | 2,663 | 7,313 | 1,715 | 574 | 1,715 | 395 | 2 | 659 | 504 |
| PDT base plus lite Bundle | 317 | 639 | 160 | 98 | 159 | 53 | 2 | 65 | 63 |
| Recovery plus lite Bundle | 317 | 640 | 159 | 98 | 159 | 53 | 2 | 65 | 63 |
| Vaccination flattened profile | 143 | 122 | 20 | 81 | 6 | 7 | 2 | 33 | 26 |

Full FHIR's 574 scalar outputs are 34 BOOL, 458 STRING, 61 INTEGER and 21 DECIMAL.
PDT and recovery each expose 7 BOOL, 80 STRING, 9 INTEGER and 2 DECIMAL outputs.
Vaccination exposes 81 STRING outputs and no numeric output, and every figure in this table is measured on the PUBLISHED artifact bytes, which do not carry the 2026-07-30 rulings.
So `dose` is still counted unresolved here even though it is ruled INTEGER, and the corpus-side map class 10 resolves against does carry it; section 1.6 owns that difference.
No artifact emits NULL, BYTES or BLOB_REF.
That sentence is measured rather than aspirational, and it remains true after the rulings for three different reasons: the ruled FHIR primitive-array null-placeholder outcome IS "publish no NULL binding", so the absence of NULL is the ruling being in force; BYTES is absent because the `base64Binary` ruling is not in these bytes yet; and no version-1 profile selects BLOB_REF, as ruled by decision D9 and defined in ROAX-CANON/1 section 6.5.

The earlier estimate of 15 lite-FHIR decimal sites omitted inline `Extension.valueDecimal`.
The audited source has 15 decimal `$ref` slots plus that inline field, for 16 schema-local decimal slots.

## 3. Resolver semantics

The DFA is a path authorizer and type resolver, not a display-pattern matcher.
Its input is the structured KEY and INDEX sequence already required by ROAX-CANON/1 section 5.

A conforming resolver MUST perform these steps, in this order, under ROAX-CANON/1 sections 3.3, 4.2 and 5:

1. Start at `automaton.start`, which is `s0`.
2. For a KEY segment, NFC-normalize the key under the pinned Unicode version and take the one transition whose `key` equals it.
   This is ruled decision D14a; the paragraphs below state why it is the rule rather than one of two readings.
3. For an INDEX segment, take `anyIndex`.
4. Fail closed immediately if the required transition is absent.
5. At a scalar or empty-container leaf, select the one binding whose `jsonKind` equals the observed JSON kind.
6. Fail closed if the binding is absent, even when the tag seems mechanically obvious from JSON syntax.
7. Emit the binding's tag and continue with ROAX-CANON/1 section 6.

### 3.1 Step 2 normalizes, and decision D14 is why that is a rule rather than a choice

**Decision D14 asked whether the lookup matches over an NFC-normalized key or over the bytes as received, and it was ruled D14a, NORMALIZE, on 2026-07-30** (`docs/decisions.md` part 2a).
Step 2 above described a normalizing resolver before the ruling, while both corpus reference implementations, the TypeScript library and the Python library compared raw, so one logical question had two answers in one tree.
The ruling is now stated by ROAX-CANON/1 section 4.2 and every matcher in this repository follows it.

Two reasons, and the second is what makes the first more than a preference.

**A raw comparison checks bytes no part of the record commits.**
Section 11.2's general rule is "check the bytes you commit, not the bytes you received".
A STRING leaf commits `utf8(NFC(s))` under section 6.1, and an encoded KEY segment commits `NFC(key)` under section 5.1.
So the lookup is the only place in the pipeline that would have looked at an unnormalized key, and it would have decided admissibility on a spelling the root never records.

**Under a raw comparison two records that render identically diverge, and one of them is refused outright.**
A key written decomposed fails the lookup and is refused by the fail-closed rule of section 4.2, while its composed twin resolves and commits.
Nothing distinguishes the two to whoever typed the key.
That is precisely the invisible-divergence failure decision D12 was ruled to prevent, arriving one layer up: D12 reasoned that a record passing through a normalizing form field must not get a different root, and under raw matching it does not get a different root, it gets rejected instead, just as invisibly.
Ruling raw would have reintroduced at the type-map layer the exact hazard already ruled out at the leaf layer.

**Both sides of the comparison normalize, not only the segment key.**
A published artifact's transition keys are validated NFC at load, so the DFA needs no further work; a display-pattern matcher normalizes its pattern token at parse time.
Normalizing only the segment key would leave a decomposed pattern permanently dead rather than provably redundant.

**Normalizing does not widen a map.**
Fail-closed still applies to any key whose NFC form is not a declared transition, and a ruling on the lookup changes no leaf bytes: rebuilding the committed corpus under D14a changed zero existing vectors, because encoded paths already normalized every KEY segment.
`corpus/README.md` records the two vectors that discriminate the readings, both of which fail closed under raw matching.

Path authorization MUST happen before the flattener assigns EMPTY_ARRAY or EMPTY_OBJECT, under ruled decision D7 and ROAX-CANON/1 section 3.3.
Otherwise an unknown issuer extension containing only an empty container bypasses the fail-closed allowlist.

The DFA intentionally carries no first-match rule.
Each state has at most one output for an observed JSON kind, and generation fails on a conflicting output, under ROAX-CANON/1 section 4.2.

A resolver MUST read outputs only from `automaton.states[*].bindings`, under ROAX-CANON/1 section 4.2 and the artifact schema.
The state-level `unresolved` rows and `structurallyUntypedObject` markers and the top-level `extensionPoints`, `addedSelectors` and `coverage` fields are audit or lifecycle metadata and never supply a tag.
A path represented only by that metadata remains unknown and fails closed.
An `unresolved` row is nevertheless operative for the extension lifecycle rather than purely descriptive: section 5 admits a shape-2 issuer selector only where such a row already names the observed kind, so removing or inventing one changes which paths an issuer may bind.

The type map does not replace complete profile validation.
For example, the full FHIR union may admit a path under one resource branch even when a sibling `resourceType` value names another branch.
Issuance MUST first validate against the pinned profile schema and then resolve every emitted leaf through the exact selected map, under ROAX-CANON/1 section 4 and the applicable document in `docs/profiles/`.

The vaccination compiler loads its inline pseudo-FHIR definitions exactly as written.
The PDT and recovery compilers load their lite FHIR reference by file path.
No compiler registers or selects a source by `$id`, because `docs/profiles/recovery-healthcert.md` section 2 and `docs/profiles/vaccination-healthcert.md` section 5 document two copied identifiers.

## 4. Exact map selection

`recordType + schemaVersion` cannot distinguish two issuer extensions of the same profile.
The exact effective map therefore needs a content identity in every issued root, as required by ruled decision D7 and the immutable-record rule in ROAX-CANON/1 section 12.2.

The extension mechanism adds this envelope member:

```json
{
  "typeMap": {
    "id": "sha256:<64 lowercase hex>",
    "version": "1.0.0"
  }
}
```

It also adds one always-emitted reserved leaf:

```text
[KEY("roax.typeMap.id")] -> STRING -> envelope.typeMap.id
```

`roax.typeMap.id` MUST be disclosed in every copy, and the fetched artifact's `typeMapVersion` MUST equal `envelope.typeMap.version`, under this section and ROAX-CANON/1 sections 10.2 and 11.2.
The exact ID is authoritative for selection.
The semver is metadata and MUST NOT be used to search for a latest, highest or compatible map, under ROAX-CANON/1 section 12.1.

Binding the ID rather than only the semver is load-bearing.
Two independent issuers may both publish `1.1.0`, while their artifact bytes, content IDs and issuer scopes remain distinct.

This reserved leaf raises the tree floor from five to six:

- Five reserved leaves are always emitted: `roax.recordType`, `roax.schemaVersion`, `roax.recordId`, `roax.issuer.id` and `roax.typeMap.id`.
- At least one record leaf remains mandatory under ROAX-CANON/1 section 3.3.
- `roax.issuer.keyId` remains conditional under ROAX-CANON/1 section 11.2.

An artifact location, mirror URL or inline artifact copy is an untrusted routing hint.
Authority comes from the profile registry for a base map and from the anchored issuer identity for an issuer-scoped child, following the outside-the-root rule in ROAX-CANON/1 section 11.3.

## 5. Issuer extension workflow

An issuer extension is an immutable, materialized child artifact.
It names one exact parent ID, carries the complete effective DFA, lists its new structured selectors in `addedSelectors`, and narrows `scope` to named issuer identities.

An illustrative PDT child carries these lifecycle fields in addition to the complete inherited-and-extended automaton:

```json
{
  "typeMapVersion": "1.1.0",
  "parentTypeMapId": "sha256:<64 lowercase hex>",
  "scope": {
    "kind": "issuers",
    "issuerIds": ["did:web:issuer.example"]
  },
  "sourceSchemas": [
    {
      "sourceId": "pdt-extension-schema",
      "kind": "content",
      "uri": "https://issuer.example/schemas/pdt-extension.json",
      "digest": "sha256:<64 lowercase hex>"
    }
  ],
  "addedSelectors": [
    {
      "segments": [
        {"key": "$template"},
        {"key": "name"}
      ],
      "jsonKind": "string",
      "tag": 2,
      "evidence": [
        "pdt-extension-schema"
      ]
    }
  ]
}
```

This is an explanatory fragment rather than a valid standalone artifact because the mandatory source, coverage and complete `automaton` fields are omitted.
The complete carrier shape is defined by `schemas/type-map-artifact-1.0.json`.
Every operative DFA binding also cites a `sourceId`, optionally followed by a JSON Pointer fragment, so inherited and added outputs remain traceable to immutable evidence under that schema.

An issuer adding an unknown selector or resolving a previously unbound observed kind MUST complete this workflow under ruled decision D7 and ROAX-CANON/1 sections 4.2 and 12.2:

1. Select the exact approved base or existing issuer-scoped parent by content ID.
2. Publish a supplemental schema or normative profile declaration that determines the new path's semantic type.
3. Pin that evidence by a public repository URI, repository-relative path and immutable commit, or by a public URI plus SHA-256 over the exact retrieved bytes.
4. Retrieve the pinned evidence during publication review and verify the named Git object and path or recompute the exact-byte content digest.
5. Give each evidence record an artifact-local `sourceId` and cite that exact ID from every submitted selector.
6. Submit exact structured KEY and `anyIndex` selectors with observed JSON kind and tag.
7. Reject tag 8 BLOB_REF unless the selected profile explicitly declares that binding and its out-of-band carriage, under ROAX-CANON/1 section 6.5.
8. Prove that each selector lies under a declared extension point, has no inherited output for the same observed kind and remains valid under the base profile schema.
9. Materialize the complete effective DFA and verify that every parent transition and output remains unchanged.
10. Run the extension validator against the exact parent and child bytes.
11. Publish the exact bytes, calculate the content ID, and make the artifact retrievable before issuing a record against it.
12. Put that exact ID and semver in the envelope and issue only for an `issuer.id` inside the artifact scope.

A permissive `additionalProperties` keyword is evidence that a path is allowed, not evidence of its semantic type.
It is insufficient by itself to create a binding under ruled decision D7.

This extension path is not PDT-only.
Recovery also leaves its root open.
Vaccination closes its root but leaves nested issuer, renderer, recommendation, date-criterion and Notarise surfaces open.
The base artifacts list those extension regions as non-operative `extensionPoints`.
Each prefix defines a structured region in which an issuer child may add an exact selector that has no inherited output for the observed JSON kind, under ruled decision D7.
A prefix admits exactly two selector shapes, and `tools/check-type-map-extension.mjs` enforces both:

1. The selector extends the prefix with a segment that the base map does not declare at that prefix state, and may then descend as deep as the issuer needs inside that otherwise untyped subtree.
2. The selector names a direct child of the prefix, exactly one segment deeper, at which the base map has no binding for the observed JSON kind **and** carries an explicit `unresolved` row listing that kind, such as vaccination `dose`.

Silence is not eligibility under shape 2.
A declared path that has neither a binding nor an `unresolved` row for the observed kind is not extensible: the PDT path `type` has no `array` binding and no `unresolved` row, so no issuer may bind EMPTY_ARRAY there, and only a base-map revision can.
The `unresolved` rows are therefore operative for extension admission even though they never supply a tag, and a child MUST carry each inherited row unchanged except for the kinds it resolves with a binding, under section 5.1.

A prefix therefore never reaches a descendant of a path the base map already declares.
The PDT and recovery root prefixes admit undeclared root properties and their subtrees, which is what their open `additionalProperties` root actually permits.
They do not open the shared lite FHIR Bundle, so `base64Binary` and `Narrative.div` stay unresolved for every issuer of those profiles until a base-map revision rules them.
Rebinding a declared path is a base-map revision under section 5.2, not an extension, and overriding an operative parent output is never permitted.
Complete validation against the selected base profile still runs first, so the prefix does not make a schema-invalid path valid under ROAX-CANON/1 section 4.2.

### 5.1 Composition and conflict rules

A child artifact MUST preserve every parent transition and output byte-for-byte at the logical DFA level, under ROAX-CANON/1 section 12.2.
Changing or removing a parent binding is a replacement base-map revision, not an extension.

| Situation | Required result |
|---|---|
| Two issuers add different paths on separate branches | Both issuer-scoped branches are valid. |
| Two issuers add the same selector and tag on separate branches | Both branches remain valid, but neither silently becomes shared policy. |
| Two issuers add the same selector with different tags | Both may remain issuer-scoped, but they cannot be merged. |
| One effective artifact has two outputs for the same path language and observed kind | Reject the artifact. |
| A child overlaps an inherited selector | Reject the child, even if the proposed tag is the same. |
| A child binds a descendant of a path the base map already declares | Reject the child; only a base-map revision may type that subtree. |
| A child adds an `unresolved` row the parent does not carry | Reject the child; parent silence may not be promoted to an extensible gap. |
| A child drops an inherited `unresolved` kind without binding it | Reject the child; a documented gap is erased only by resolving it. |
| Two artifacts carry the same semver | Their content IDs distinguish them, and no verifier chooses by version ordering. |
| Another installed map covers a path missing from the selected map | Fail closed and do not search the other map. |

If independently useful extensions should become common, profile governance publishes a new profile-scoped base artifact after reviewing their evidence.
Existing records keep their original IDs and remain verifiable under ROAX-CANON/1 section 12.2.

### 5.2 Version rules

`typeMapVersion` remains three-part semver because it is a ROAX-owned artifact identifier, while `schemaVersion` remains opaque and equality-only under ROAX-CANON/1 section 12.1.

- PATCH covers artifact notes, provenance or serialization changes with no effective binding change.
- MINOR covers additive, non-overlapping selectors that make previously rejected records issuable.
- MAJOR covers removing, changing, widening or narrowing an existing selector or changing its tag.

Every exact-byte change MUST increment at least PATCH under this section.
Versions are compared only as exact metadata during verification and are never range-resolved.

### 5.3 Materialization rules

An issuer child MUST use canonical DFA state numbering so independent tooling can review the exact bytes deterministically, under the additive-artifact requirement in ROAX-CANON/1 section 12.2.
State `s0` is first, newly encountered targets receive consecutive IDs in breadth-first discovery order, NFC KEY transitions are traversed in UTF-8 byte order, and `anyIndex` is traversed after the KEY transitions.
Within a state, bindings are sorted by `jsonKind`, KEY transitions are sorted by UTF-8 bytes, and the set-valued `basis` and `sources` arrays are sorted without duplicates.
The executable checks for these carrier rules are in `tools/check-type-map-extension.mjs`, and the permitted object shapes are closed by `schemas/type-map-artifact-1.0.json`.
`tools/check-type-maps.mjs` applies that same encoding to the four published base artifacts, so a base map and an issuer child are held to one set of carrier rules rather than two.

## 6. Reproduction and review

The artifacts are generated with:

```sh
node tools/build-type-maps.mjs \
  --references references/schemata \
  --out type-maps
```

**That command currently fails, and the four published artifacts can be neither regenerated nor `--check`ed from the pinned checkout.**
The generator refuses to guess an empty-container tag when merged branches disagree about admitting the empty value, and that refusal now covers objects as well as arrays, because EMPTY_OBJECT is a distinct leaf under ROAX-CANON/1 section 6.1 and a permissive union silently widens the map.
Measured against commit `09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa`, the object rejection fires on 34 states: 30 in full FHIR, 2 in PDT, 2 in recovery and none in vaccination.
The first is the state that merges `#/definitions/ImplementationGuide_Definition`, which requires `resource`, with `#/definitions/Reference`, which admits `{}`.
Resolving those states needs combinator-aware evaluation, which the DFA closure has discarded by the time a state is merged, so it is an open ruling rather than a mechanical fix.
The committed artifacts, their content IDs and the section 2.1 table remain authoritative and are still checked in full by `tools/check-type-maps.mjs`; only regeneration is blocked.

**Which branches each rejection compares.**
Both sides select a branch by container-ness, which is the declared type **or** the applicator keyword: a branch is an object branch when it declares `type: "object"` or declares `properties`, and an array branch when it declares `type: "array"` or declares `items`.
Those are the same keywords `classifyNode` already treats as container markers when it declines to assign a scalar tag.
Selecting on the applicator alone would drop an empty-forbidding branch shaped `{"type": "object", "required": ["x"]}`, and selecting on the declared type alone would drop one shaped `{"items": {...}, "minItems": 1}`.
Either omission lets the surviving permissive branch decide the state on its own, which is the silent widening the rejection exists to prevent.

**What each side asks of a selected branch is every keyword of the pinned dialect that can forbid the empty container.**
For objects that is a non-empty `required` and `minProperties`, which is complete: JSON Schema Validation draft-06 sections 6.17 and 6.16 are the only two that can reject `{}`, while `dependencies` and `propertyNames` pass vacuously on it.
For arrays it is `minItems` **and `contains`**, since a `contains` schema demands at least one matching element under JSON Schema Validation draft-06 section 6.14 and draft-07 section 6.4.6, and the empty array has none; reading `minItems` alone would let a `contains` branch answer that it admits `[]` when it rejects it.
A node whose only container keyword is `contains` needs no matching selector clause, because `classifyNode` leaves such a node unresolved for every JSON kind and an unresolved kind suppresses that kind's binding, so the state fails closed without reaching the comparison at all.

**The comparison, the evidence and the traversal are three different sets, and the two sides do not treat them alike.**
The comparison is the widened container-ness set on both sides.
Traversal is narrow on both: a selected branch declaring no `properties` contributes no KEY transition, and `anyIndex` is derived only from the `items` of branches declaring `type: "array"`.
The evidence sets differ, and the asymmetry is deliberate rather than an oversight.
An EMPTY_ARRAY binding cites only branches declaring `type: "array"`, because an `items` keyword on a node with no declared type constrains the instance *if* it is an array without asserting that it is one, so treating it as evidence of array-ness would infer a tag from an inapplicable keyword, which is exactly what section 1.5 rules out.
An EMPTY_OBJECT binding cites the widened set, so a branch shaped `{"type": "object"}` with no `properties` is cited as a `schema-container-type` source.
That is not the same thing: a declared `type: "object"` asserts object-ness, so the tag still rests on declared schema evidence rather than on an inapplicable keyword.
`--self-test` pins the array half with a case asserting that `{"items": {...}}` alone binds no EMPTY_ARRAY.

**The 34-state count above was taken under the narrower `properties`-only and `type: "array"`-only selections and is therefore a LOWER BOUND rather than an exact count.**
Widening a selection can only add branches to the set whose empty-admission answers are compared, so every state that fired still fires and further states may join them; it cannot remove one.
The array comparison was widened after that measurement as well, so the bound now covers array states and not only object ones.
The count has not been re-measured, because `.gitignore` excludes the reference checkout, and regeneration is blocked either way.

The generator's own rejections are provable without any reference checkout:

```sh
node tools/build-type-maps.mjs --self-test
```

It compiles constructed schemas whose merged object branches disagree through `required` and through `minProperties`, and whose merged array branches disagree through `minItems` and through `contains`, asserts that each is rejected, and asserts that agreeing branches still yield EMPTY_OBJECT and EMPTY_ARRAY respectively.
Both halves of both container-ness disjunctions are pinned independently, which takes four of those cases: an object branch carrying `properties` and no declared type, an object branch carrying `type: "object"` and no `properties`, an array branch carrying `items` and no declared type, and an array branch carrying `type: "array"` and no `items`.
Each is the empty-forbidding side of its disagreement, so narrowing either selector back to one half makes that branch invisible, the state resolves to a single permissive answer, and an empty-container binding is published for a state one reachable branch rejects.
Two further cases assert the other half of the rule: that an `items` keyword on an untyped node binds no EMPTY_ARRAY on its own, and that a `contains` keyword on an untyped node leaves the array kind unresolved rather than binding it.

The reference checkout MUST be at Open-Attestation/schemata commit `09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa`, as recorded in every artifact.
The generator resolves cross-file references by file path and does not inspect `$id`.
Each generated source record also names the public `https://github.com/Open-Attestation/schemata.git` repository, its repository-relative path and the complete commit, so a relative path is never interpreted against an unspecified repository.
For a `kind: "content"` source, `digest` is SHA-256 over the exact retrieved bytes with no domain prefix or JSON reserialization, as defined by `schemas/type-map-artifact-1.0.json`.

The same generator is also meant to compare the checked-in files without rewriting them:

```sh
node tools/build-type-maps.mjs \
  --references references/schemata \
  --out type-maps \
  --check
```

**That comparison currently fails too, on exactly the same 34 states.**
`--check` only changes what happens after a profile is compiled, and the object rejection fires inside compilation, so `--check` never reaches the committed bytes either.
Neither generator invocation can therefore detect drift between the four committed artifacts and the generator that produced them, which is the cost of the fail-closed ruling above.

Both generator invocations need the reference checkout, which `.gitignore` excludes, and both fail closed on those 34 states even once it is present.
The published artifacts and the registry are therefore checked directly from the committed tree instead, with no reference checkout and no dependency on the generator:

```sh
ROAX_AJV=/tmp/roax-ajv node tools/check-type-maps.mjs
```

That checker recomputes every content ID from the exact bytes, validates the four artifacts and `type-maps/registry-1.0.0.json` against `schemas/type-map-artifact-1.0.json` and `schemas/type-map-registry-1.0.json`, exercises both branches of the artifact schema's `parentTypeMapId` conditional with a valid child instance and with instances each branch must reject, applies the shared carrier validation in `tools/check-type-map-extension.mjs` so the carrier invariants have one executable encoding, re-verifies the pinned repository, path and commit of every source and binding reference, and asserts a fixed set of operative and fail-closed path bindings.

It needs Ajv 8 and `ajv-formats` installed outside this tree, because the root `package.json` is the TypeScript library's rather than a place to add schema tooling (`AGENTS.md`, "Validating the schemas"):

```sh
npm install --prefix /tmp/roax-ajv ajv ajv-formats
```

`ROAX_AJV` names that directory, and the tool also resolves Ajv from the working directory when it is already available there.
Passing `--skip-schema-validation` runs the dependency-free subset and says so in its output.

The extension validator's self-tests, including the extension-point containment rules in section 5, run with:

```sh
node tools/check-type-map-extension.mjs --self-test
```

An issuer extension can be checked against its exact parent with:

```sh
node tools/check-type-map-extension.mjs \
  type-maps/sg.gov.moh.pdt-healthcert-2.0.json \
  issuer-pdt-extension.json
```

The validator checks provenance references, issuer scope, exact parent identity, additive semver, extension-point containment, complete selector materialization, DFA reachability and logical preservation of every inherited transition and output.
Those checks implement the extension invariants in ROAX-CANON/1 section 12.2 and the artifact carrier constraints in `schemas/type-map-artifact-1.0.json`.
The validator is intentionally offline and does not fetch evidence, so publication review performs workflow step 4 rather than treating a syntactically valid digest as verified.

The artifact and registry format schemas are `schemas/type-map-artifact-1.0.json` and `schemas/type-map-registry-1.0.json`.
The previous `schemas/type-map-1.0.json` describes the draft display-pattern representation and is superseded for published artifacts because its order-dependent string matcher cannot safely compose issuer extensions.
