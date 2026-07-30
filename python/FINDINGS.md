# Findings from the independent Python build

Written while implementing `roax-canon` for Python from [`docs/spec/roax-canon-1.md`](../docs/spec/roax-canon-1.md) alone.
The two implementations under `corpus/tools/` were not read while this was built, so where this agrees with them the agreement is evidence and where it disagrees the disagreement is a finding.

**The disagreements are the point of this document.**
The library and its corpus results are in [`README.md`](README.md).

Every item below states which of three things it is, because that distinction is what five independent builds are for:

- **DIVERGENCE** - the specification and the committed corpus require different things, and one of them is wrong.
- **AMBIGUITY** - the specification admits two honest readings and no committed vector discriminates.
- **CONFIRMATION** - something this repository already records, re-measured independently here.

---

## 1. DIVERGENCE: specification section 3.3 requires the type map to authorize an empty container, and the corpus asserts roots that would fail closed under that rule

**This is the one substantive disagreement and it is release-blocking under specification section 1.1.**

Specification section 3.3 says, of the flattener's empty-container outputs:

> An object output is tag 7 EMPTY_OBJECT and an array output is tag 6 EMPTY_ARRAY, but only when the exact selected map authorizes that structured path and observed kind under section 4.2.
> Assigning tags 6 or 7 before map resolution would let an unknown empty issuer extension bypass decision D7's fail-closed rule.

`corpus/type-maps/org.roax.corpus.synthetic.json` binds `a.b` at kind `null` and `a.**` at kind `string`, and binds nothing at kind `array` or kind `object` anywhere.
`corpus/fixtures/records/structure-empty-array.json` and `structure-empty-object.json` carry `a.b` as `[]` and `{}`.
So under the section 3.3 rule those two records have no type tag at `a.b` and MUST fail closed, which means they have no root at all - and the class-5 vectors `record-structure-empty-array` and `record-structure-empty-object` assert one for each.

**Measured, from this implementation:**

| Empty-container rule | Corpus result |
|---|---|
| structural: tag 6 or 7 assigned without a map lookup | 738 passing assertions, 0 failures |
| section 3.3: the map must authorize the path and kind | 734 passing assertions, **2 failures**, both class 5 |

The two failures are exactly `record-structure-empty-array` and `record-structure-empty-object`, each rejected with `type-unresolved`.
Nothing else moves.

**It is not a divergence of vintage, and that was checked rather than assumed.**
The sentence quoted above is absent from `docs/spec/roax-canon-1.md` at commits `955b2f1` and `8bf3bf6` and present from `f77386f` onward, so it arrived with the type-map artifact work, after the corpus was first built.
But the corpus was then **rebuilt** at `d778726`, which touched both `corpus/type-maps/org.roax.corpus.synthetic.json` and `corpus/fixtures/records/structure-empty-array.json`, with the sentence already in the specification.
So the committed corpus asserts those roots against a rule the specification already carried.
`AGENTS.md` states the rule in its own words - "The map must authorize a path before the flattener emits EMPTY_ARRAY or EMPTY_OBJECT, or an unknown empty extension bypasses D7" - so the project holds the specification's reading and the corpus does not implement it.

**Not resolved here, deliberately.**
Specification section 1.1 makes the specification govern and calls a divergence a release-blocking corpus defect that the corpus build MUST report.
Changing the corpus would decide the shape of a fix from inside a data file, and changing the specification is not a library's call.
`roax_canon.flatten.flatten` therefore defaults to the specification's rule and takes `authorize_empty_containers=False` as an explicit opt-out; `python/tools/run_corpus.py` passes the opt-out and prints a four-line notice saying so on every run.

**The narrow fix, if it is wanted:** add two entries to `corpus/type-maps/org.roax.corpus.synthetic.json` binding `a.b` at kind `array` to tag 6 and at kind `object` to tag 7, and rebuild.
The two roots do not change, because the tag those entries authorize is the tag the flattener already emits.
That is a corpus edit and belongs to whoever owns the corpus.

---

## 2. DIVERGENCE, already known: the committed corpus commits four reserved leaves and specification section 11.2 lists five

`schemas/envelope-1.0.json` commits no `roax.typeMap.id` leaf, so the always-emitted reserved set is `roax.recordType`, `roax.schemaVersion`, `roax.recordId`, `roax.issuer.id`, plus the conditional `roax.issuer.keyId`.
It does carry a top-level `typeMap` object with `required: [id, version]` and `id` pinned to `^sha256:[0-9a-f]{64}$`, and that member is OPTIONAL there, which is the distinction that matters: it is outside the root and no leaf authenticates it, so that schema's own description calls it "a hint and nothing more" and directs a verifier that means to rely on it to `schemas/envelope-2.0.json`.
Specification section 11.2 and `schemas/envelope-2.0.json` make it five plus the conditional.

Confirmed from the fixtures rather than assumed: `corpus/fixtures/envelopes/guard-accept-bare-roax.json` carries a two-key record, `leafCount: 6`, and a `salts` array naming exactly those four reserved paths.
`record-typed-scalars` at 9 leaves against `record-typed-scalars-with-key-id` at 10 isolates the conditional leaf as the only difference.

`AGENTS.md` already records this and calls closing it corpus-rebuild work.
It is repeated here only because it is the single thing that would silently break a reader who implemented section 11.2 as written and then ran the corpus: **every** record and envelope vector fails, on leaf count and on root.

`roax_canon.reserved_leaves` models both structural sets and defaults to `RESERVED_V1`, because that is the set every committed artifact uses (`python/src/roax_canon/record.py:50-63` and `:89-113`).
The package cannot issue, emit or verify envelope 2.0 yet: exact structured-path DFA artifact loading and content-ID reproduction are deliberately not implemented, so those operations reject with `type-map-rejected` rather than trusting the display-pattern corpus resolver by `recordType` (`python/src/roax_canon/record.py:242-252`; `python/src/roax_canon/disclose.py:47-56`; `python/src/roax_canon/verify.py:404-410`; specification section 4.2).
No committed vector exercises the structural 2.0 leaf set.

---

## 3. AMBIGUITY, new: specification section 10 step 1's record-leaf tag check is not performable for an envelope-1.0 disclosed copy

Specification section 10 step 1 requires a verifier to check "a record leaf's tag against the exact selected map under section 4.2".
Section 4.2 selects the exact map by content ID, committed at `roax.typeMap.id`.
`schemas/envelope-1.0.json` commits no such leaf, and the optional top-level `typeMap.id` it does carry sits outside the root, so for a 1.0 disclosed copy the only thing available is an unauthenticated hint and there is no way to identify a map the envelope actually committed to.

This is observable in the corpus rather than merely theoretical.
`corpus/fixtures/envelopes/floor-hl7-fhir-bundle-complete.json` is a disclosed copy at `recordType: "hl7.fhir.bundle"`, and `corpus/type-maps/` contains **no** `hl7.fhir.bundle` map at all - only the synthetic, PDT, recovery and vaccination ones.
An implementer who followed step 1 literally and picked a map by `recordType` would fail that vector closed, and every other `floor-hl7-fhir-bundle-*` accept vector with it.

**Reading taken:** the reserved half of step 1 is performable and is performed - a disclosed leaf at a single `roax.`-prefixed segment must carry tag 2 STRING, from the fixed table in section 11.2.
The record-leaf half is skipped for a 1.0 envelope, and `roax_canon.verify` says so in a comment at the site rather than omitting it silently.
The type map is consulted for **full** copies, where the record body is present and the tag is needed to build a leaf at all.

**What would settle it:** the corpus rebuild that item 2 describes.
Once `roax.typeMap.id` is committed and the artifact is fetchable, step 1 becomes performable for both halves and this reading expires.

---

## 4. AMBIGUITY, new: `**` in a display-notation type-map pattern is not stated to match one segment or zero

`schemas/type-map-1.0.json` says `'**' matches any run of segments`.
A run of zero segments is a defensible reading of "run", and it changes what a map binds: under it, `a.**` at kind `string` would also bind the value at `a` itself.

**Reading taken:** one or more.
The narrower reading, because the wider one silently widens every map that uses the token, and widening a fail-closed allow-list is the direction that cannot be undone by a later ruling.

**No committed vector discriminates.**
The synthetic map's only `**` entry is `a.**` at kind `string`, and `a` is an object in every fixture that has it, so it is never observed as a string.
Stated rather than left implicit, because a corpus that later added such a fixture would settle this from inside a data file.

---

## 5. AMBIGUITY, resolved by the schema's own rationale rather than by a vector: a display-pattern entry whose `jsonKind` does not match is skipped, not fatal

Two readings of first-match in `schemas/type-map-1.0.json`:

- **A**: the first entry whose *pattern* matches wins; if its `jsonKind` disagrees with the observed kind, fail closed.
- **B**: an entry whose `jsonKind` disagrees is not applicable; keep scanning.

**Reading B is taken, and it is required rather than preferred.**
That schema's own justification for the `jsonKind` field is polymorphism - in the shipped vaccination sample `fhirBundle.entry[0].identifier[0].type` is the string `"PPN"` while `identifier[1].type` is the object `{ text: "NRIC" }` - and expressing that needs two entries with the *same* pattern and different kinds.
Under reading A the second could never be reached.

No committed vector discriminates: the one place the two readings could differ is a path matched by an entry whose kind is wrong and by a later entry whose kind is right, and the corpus has no such observation.
Recorded so the next implementer does not have to re-derive it.

---

## 6. AMBIGUITY, new and small: two record keys that differ only in normalization form are distinct member names and one path

Specification section 3.2 requires duplicate keys in a map to be REJECTED.
Section 6.1 normalizes keys to NFC before they are encoded.
`{"é": 1, "é": 2}` satisfies section 3.2 - the two member names are distinct as received - and produces two leaves at one encoded path, which specification section 9 says cannot happen ("Paths are unique by construction, so the order is total and tie-free").

The specification does not say which rule wins, and there is no corpus reason code for it.
`roax_canon` rejects with its own code `duplicate-path`, at the sort, and states in the source that this is the one reachable way to produce a tie.
Reporting it as `duplicate-key` was considered and not taken: the keys genuinely are not duplicates as received, and collapsing the two conditions would hide which check fired.

No committed vector carries such a record.

---

## 7. CONFIRMATION: the corpus is genuinely neutral about decision D14, measured from a third matcher

`docs/decisions.md` part 2a leaves open whether the type-map lookup matches over an NFC-normalized key or over the bytes as received, and `corpus/README.md` ambiguity 4 records that both reference implementations compare raw.

Measured here rather than assumed.
This implementation's matcher compares raw and passes all 738 assertions.
Patching an NFC normalization onto both sides of the comparison and re-running gives **the same 738 passes**.
So no committed vector depends on the answer, which is what the synthetic map's two `Kelvin` spellings - U+212A and ASCII `K`, confirmed by reading the file's code points - were put there to guarantee.

`roax_canon.typemap` compares raw and says in its module docstring that adding an `nfc()` there would rule D14 silently.

---

## 8. CONFIRMATION, with a number the corpus README does not give: the display-path floor trap is caught by two ACCEPT vectors, not by the reject vector

`corpus/README.md` states that a minimum-disclosure floor path is SEGMENTS and never display notation, and that `floor-sg-gov-moh-vaccination-healthcert-*` reveals two segments.

Measured here by deliberately carrying the vaccination floor entry as one dotted `KEY("notarisationMetadata.reference")`, the way `docs/profiles/vaccination-healthcert.md` section 4 prints it for humans, and re-running.

**4 assertions fail, across 2 vectors, and both are on the ACCEPT side:**

- `floor-sg-gov-moh-vaccination-healthcert-complete`
- `floor-sg-gov-moh-vaccination-healthcert-omits-issuer-key-id`

Both are rejected with `minimum-disclosure-floor` because the broken floor asks for a leaf no record has.
The vector that looks like it should catch it, `floor-sg-gov-moh-vaccination-healthcert-omits-notarisationMetadata-reference`, **passes under the broken floor**, for the wrong reason: the entry it withholds was never findable either way.

That is worth stating precisely, because the reject vector is the one an implementer would expect to be load-bearing and it is not.

---

## 9. CONFIRMATION: the envelope rejection-reason precedence is derivable from the fixtures, and three orderings would report a true but different cause

`corpus/README.md` warns that several fixtures are rejectable for more than one cause.
Three places where the order is what the vector actually pins, each derived from the fixture rather than chosen:

- **`guard-reject-reserved-collision.json`** carries an all-zero placeholder root, so the reserved-namespace guard has to fire during flattening.
  An implementation that compared the root first reports `root-mismatch` and looks correct.
- **`full-copy-salts-length-not-leaf-count.json`** has `leafCount: 10` and 9 salts, so it also disagrees with the derived leaf count.
  The `salts` length check has to precede the derived-count check or the reason is `leaf-count-mismatch`.
- **`full-copy-salts-duplicate-path.json`** has 9 salts for `leafCount: 9` with `flag` named twice, so it also leaves a real leaf unsalted.
  The duplicate check has to precede the missing-salt check.

Resulting order, pinned in a comment in `roax_canon.verify._verify_full_copy`: seed members, envelope shape, `canon`, algorithm allow-list, profile allow-list, anchored root, then salts duplicate, salts length, flatten and guard, missing salt, derived leaf count, root.

`corpus/fixtures/envelopes/salt-leak-disclosed-copy-with-master-salt.json` is separately worth naming: `masterSalt` is not in `schemas/envelope-1.0.json`'s closed property set, so the fixture is schema-invalid, and a verifier that let a generic unknown-property error win would report `envelope-shape` where the vector wants `master-salt-in-envelope`.
The seed-member check therefore runs before the unknown-member check, and it names a list rather than one field, because specification section 7.3 rule 3 binds any future revision that reintroduces a derived salt.

Both checks run at **every** object `schemas/envelope-1.0.json` closes and not at the top level alone, which is what makes them a defence rather than a gesture.
Each nested object is dereferenced by named key, so an extra member one level down would otherwise be ignored: a `disclosure` carrying its own `salts` array, or an `issuer` carrying a `masterSalt`, hands a reader the salt of an undisclosed leaf inside a copy that verifies `ok`, which is the accept path that makes it a leak rather than a curiosity.
`anchor` is closed for the adjacent reason rather than the same one: no check in the module dereferences it, and being unread is exactly what makes it a place to park bytes nobody looks at.
The seed scan skips a name the object legitimately declares, because `salt` is in the list and is the member being asked for on a `salts` entry and on a disclosed leaf.
No committed vector moves, measured over all 54 envelope fixtures rather than assumed: the observed nested key sets are exactly `issuer{id, keyId}`, `disclosure{mode, leaves}`, `salts` entry `{segments, salt}` and leaf `{segments, displayPath, index, tag, value, salt, auditPath}`, and no fixture carries `anchor` or `typeMap` at all.
The only undeclared member anywhere in the 54 is the top-level `masterSalt` of `salt-leak-disclosed-copy-with-master-salt.json`, which is the fixture that asks to be rejected.

---

## 10. CONFIRMATION: specification section 11.1's forged-tree-size measurement reproduces in Python

Specification section 11.1 records that the claim "a wrong `leafCount` makes the audit path fail" is false, measured on Node.
Reproduced here independently, in `python/tests/test_pipeline.py::test_forged_tree_size_reproduces_the_section_11_1_measurement`: on an 8-leaf tree, the internal node `MTH(L[0:4])` presented as the leaf at index 0 fails with the true tree size 8 and **verifies** with a forged tree size of 2 and the audit path `[MTH(L[4:8])]`.

This is why `roax_canon.verify.verify_envelope` has no parameter that accepts a leaf hash: the defence in specification section 10 step 2 is made structural rather than procedural.

---

## 11. The four ambiguities this build inherited and adopted unchanged

Recorded in `corpus/README.md` before this work started.
Each was reached independently here and resolved the same way, which is corroboration rather than agreement by construction, since the reference implementations were not read.

1. **The 1024-digit bound's scope.**
   Section 6.2 states it under *Canonical decimal* and its justification counts class 2's 40-digit integer against it.
   Applied to INTEGER as well as DECIMAL.
2. **What the bound counts.**
   Read as the padded form *before* the output-grammar normalization, which is the literal reading and the memory-safe one.
   Under it `0e99999` is rejected; under the other it canonicalizes to `0`.
   No vector carries `0e99999`.
3. **Decision D14, the lookup's normalization.** See item 7.
4. **The pattern field is display notation** and cannot address a key containing `.`, `[` or `]`.
   `a.**` reaches such a key; an ambiguous pattern is rejected rather than mis-parsed.

---

## 12. Python-specific hazards, each demonstrated rather than asserted

Not specification findings.
Recorded because these Python defaults fail silently and the corpus does not cover all of them.

| Hazard | Default behaviour | Where it is closed |
|---|---|---|
| `json.loads` parses `0.010` through a float | becomes `0.01` | `jsonio.loads`, `parse_float=JsonNumber` |
| `json.loads` parses `9223372036854775807` through a float | becomes `9223372036854776000` | same |
| `json.loads` parses `1e999` through a float | becomes `inf` | same, and the literal survives verbatim |
| `json.loads` accepts `NaN`, `Infinity`, `-Infinity` | produces floats | `parse_constant` raises `non-finite-number` |
| a plain `dict` object hook drops duplicate keys | `{"a":1,"a":2}` becomes `{"a":2}` | `object_pairs_hook` raises `duplicate-key` |
| **`parse_int=str, parse_float=str` collapses `5` and `"5"`** | the type map resolves the wrong tag | `JsonNumber` is a distinct `str` subclass; `json_kind` reads the type |
| **`JsonNumber` subclasses `str`, so it passes `isinstance(x, str)` at an unchecked carrier boundary** | a JSON number reaches a member a schema pins to a string and may be committed or verified under the wrong observed kind | `jsonio.is_json_string`, applied to the outer identity and optional type-map descriptor (`verify._verify`), structured-path keys (`path.segments_from_json`), every string member of the display-pattern map carrier (`typemap.DisplayPatternTypeMap.__init__`), a record-side base64 BYTES value (`flatten._coerce_record_value`), disclosed values at tags 2 through 5 (`verify._decode_carrier`) and every envelope hex field (`verify._hexbytes`) |
| `$` in a regular expression also matches before a trailing newline | `"1.0\n"` is accepted and canonicalized | every full-string conformance grammar under `python/src/roax_canon` is anchored `\A` and `\Z`; the TypeScript sample reader uses prefix token scanners with explicit boundary checks |
| `\d` matches non-ASCII decimal digits, and `int("１２")` is 12 | a fullwidth numeral canonicalizes | grammars spell `[0-9]` out; `isdigit`, `isdecimal`, `isnumeric` are never used |
| `str` holds unpaired surrogates and `unicodedata.normalize` passes them through | fails later at `.encode("utf-8")`, after the guard has run | explicit check before normalization, `unpaired-surrogate` |
| `bytes.fromhex` accepts uppercase and embedded spaces | `"AB CD"` decodes | envelope hex fields validated lowercase and fixed-length |
| CPython 3.11+ defaults to a 4300-digit `int()` conversion cap | `1e` + 5000 digits raises `ValueError`, not the specification's bound | exponent refused by digit count first, `digit-bound-exceeded` |
| `base64.b64decode(validate=True)` accepts non-canonical trailing bits | RFC 4648 section 3.5's non-canonical case passes | explicit final-quantum check |

**The `JsonNumber` row is the residual of closing the row above it, and it is worth spelling out.**
Both halves of `JsonNumber` are deliberate: subclassing `str` is what keeps the literal verbatim (specification section 6.4), and being a distinct type is what stops the JSON number `5` and the JSON string `"5"` collapsing at the type-map lookup (specification section 4.2).
The first half is what makes it invisible to an `isinstance(x, str)` test, so each
schema-string boundary named in the table must distinguish a genuine JSON string from
`JsonNumber` rather than relying on `isinstance`.
The one that mattered is `disclosure.leaves[].value`, because that carrier feeds the leaf hash directly: measured on CPython 3.13, a disclosed tag-4 leaf carrying `0.010` as a JSON number canonicalized to the same bytes the genuine leaf committed and verified `ok`, while any consumer re-reading the same envelope with a stdlib parser reads `0.01`.
`schemas/envelope-1.0.json` pins that carrier to `"type": "string"` and says why in its own description, so this is a defect of this implementation rather than a finding against the specification.
Closing it at the verifier exposed the same hazard on the encoder: `disclosed_copy` was emitting the record's `JsonNumber` straight into that carrier.
`_carrier_value` now follows one uniform rule instead, at every tag: **the envelope carries the value the leaf hash committed, never the record's original literal.**
So STRING travels as its NFC form (specification section 6.1), INTEGER and DECIMAL travel canonicalized (specification section 6.2), and BYTES already travelled as hex of the committed bytes (specification section 6.3).
The narrower `str()` conversion alone would have left a second mismatch behind: a record decimal written `1e2` commits the bytes `100` but was emitted as `"1e2"`, which `schemas/envelope-1.0.json` rejects by the pattern it pins on that carrier, so this library was writing a disclosed copy its own schema refuses while verifying it happily, because `canonical_decimal` re-expands the literal on the way back in.
The verifier is deliberately NOT tightened to match: `canonical_decimal` yields an identical leaf hash from either spelling, so rejecting a non-canonical carrier on input would change accept and reject behaviour for no security gain.
`canonical_integer`, `canonical_decimal` and `nfc` are reused rather than reimplemented, because a second preimage builder is the drift specification section 8 exists to prevent.
The full-copy `record` body is deliberately NOT covered by any of this: specification section 7.3 has that body carry record numbers in their original JSON form, and the flattener resolves those through the observed JSON kind.
No committed vector supplies a hostile JSON number at one of these schema-string
boundaries.
Normal disclosed tag-2 values do reach `_decode_carrier` - 317 committed leaf values do
so - while tags 3, 4 and 5 do not, so focused unit tests hold the hostile forms and the
unreached tag carriers.
A separate focused test holds the record-side BYTES boundary, which no version-1 profile
selects (specification section 6.5).

**One consequence of the same subclassing is left open, and it belongs to a caller rather than to this package.**
`json.dumps` on a full copy serializes the record body's `JsonNumber` values as JSON **strings**, because `JsonNumber` subclasses `str`, so re-reading that text gives kind `string` where the type map expects kind `number` and the copy fails `type-unresolved`.
This package ships no serializer and specification section 7.3 requires the record body to carry its numbers as numbers, so writing an envelope to the wire is a caller's job and a caller must emit those literals unquoted.
Measured on CPython 3.13; it is unchanged by the fix above, since `full_copy` does not go through `_carrier_value`.

**The Unicode line is clean and worth stating plainly.**
CPython 3.13.5 ships `unicodedata.unidata_version == "15.1.0"`, which is exactly what `ROAX-CANON/1` pins.
Unlike the Node reference implementation, which runs Unicode 16.0 tables against a 15.1 corpus, this build is not running across the 15.1-to-16.0 boundary at all, so its agreement with the corpus on classes 4 and 16 says nothing about version sensitivity in either direction.
`roax_canon.text.unicode_tables_match_pin()` is what a conformance report should read, because CPython ships one table version per build and offers no way to select another.

---

## 13. What this build does NOT cover, stated so a passing corpus run is not misread

- **The structured-path DFA artifacts in `type-maps/` are not implemented.**
  No committed corpus vector exercises them: the corpus resolves through the superseded display-pattern maps in `corpus/type-maps/`, which `schemas/type-map-1.0.json` itself marks non-operative.
  Content-ID reproduction, issuer extensions and extension-point containment are all absent.
  `roax_canon.typemap.TypeResolver` is the seam a DFA resolver drops into unchanged.
- **No anchoring registry read.**
  `VerifierConfig` carries the anchored root and the anchored algorithm and compares both, because specification section 7.4 H2 requires authority to come from there rather than from the document (`python/src/roax_canon/verify.py`, the `anchored_hash_alg` and `anchored_root` comparisons in `_verify`).
  It also carries `registry_address` and `registry_chain_id`, and **neither is consulted by any check in the package**.
  That is the correct behaviour rather than an omission: specification section 11.3 makes an envelope's `anchor` block a routing hint that is never authority, so a mismatch against it is not a rejection and there is nothing to compare.
  Both fields are carried for a caller that does read a registry; this package reads no chain.
  The registry-dependent half of conformance class 18 is unbuilt in the corpus for the same reason and cannot be run.
- **`Poseidon-BN254` is registered and unusable**, and `BLOB_REF` is defined and rejected in issuance and in an envelope, per specification sections 7.4 and 6.5.
  Neither is exercised beyond the corpus's fail-closed vectors.
- **Tag 5 `BYTES` is implemented on both sides and is reached by no corpus vector.**
  No version-1 profile binds it: the healthcert blob fields bind STRING and FHIR
  `base64Binary` is unresolved (specification section 6.3), so every corpus leaf and envelope fixture
  is tag 0 to 4, 6 or 7.
  Both carriers are implemented anyway, and they are different carriers: a *record* carries base64 in
  the pinned RFC 4648 section 4 form, and an *envelope* carries lowercase hex, which is what
  `schemas/envelope-1.0.json` pins.
  An encoder without a decoder is a round trip that does not close, and the corpus cannot see it, so
  `python/tests/test_pipeline.py::test_bytes_leaf_round_trips_through_both_envelope_shapes` pins it
  instead.
- **Class 12 cannot detect a weak CSPRNG** and neither can this runner.
  It asserts the three relations against `secrets.token_bytes`.
  The randomness source is an implementation-review obligation, not a testable one.
- **Class 9's negative proofs are driven through the fold**, not through the full disclosed-copy path, because those vectors carry a leaf hash and no `(path, tag, value, salt)` to recompute one from.
  What closes the envelope attack is that `verify_envelope` has no parameter that accepts
  a leaf hash.
  The corpus has 45 disclosed fixtures across classes 11, 14, 17 and 18, but fixtures
  rejected by earlier checks do not all reach the proof fold, so focused unit tests pin
  recomputation rather than crediting every fixture with that coverage.
