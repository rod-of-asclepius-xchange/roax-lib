# The Kotlin implementation of ROAX-CANON/1

An independent library, written from [`docs/spec/roax-canon-1.md`](../docs/spec/roax-canon-1.md) alone.

It passes all 488 vectors of the committed conformance corpus with zero NOT RUN, producing roots byte-identical to the Rust, TypeScript and Python libraries wherever the corpus covers a behaviour.
What it found on the way is in [`FINDINGS.md`](FINDINGS.md), and three of those findings are things a future implementer will hit in any JVM language.

## What is here

| Path | What it is |
|---|---|
| `roax-canon/src/main/kotlin/io/roax/canon/` | The library. Zero runtime dependencies. |
| `roax-canon/src/test/kotlin/io/roax/canon/conformance/` | The corpus runner. |
| `roax-canon/src/test/kotlin/io/roax/canon/` | The library's own tests, for everything the corpus does not cover. |
| `roax-canon-android/` | The Android packaging of the **same sources**, producing an AAR. |

## Running it

```sh
gradle -p kotlin :roax-canon:test
```

That runs the corpus and every other test.
Four class-10 vectors need the three Singapore MOH sample records, which live in a third-party checkout outside this repository by design.
Without them those four report **NOT RUN**, naming the exact directory and filenames probed; they are never counted as passed.

To run them, extract the records first with the corpus's own utility and point `ROAX_REFERENCE_RECORDS` at the output directory:

```sh
python3 corpus/tools/extract_reference_record.py \
  --module <checkout>/src/sg/gov/moh/recovery-healthcert/2.0/sample-data.ts \
  --export sampleDocument --out /tmp/roax-records/sg.gov.moh.recovery-healthcert.json

python3 corpus/tools/extract_reference_record.py \
  --module <checkout>/src/sg/gov/moh/vaccination-healthcert/1.0/sample-data.ts \
  --export sampleVaccineHealthCert --out /tmp/roax-records/sg.gov.moh.vaccination-healthcert.json

ROAX_REFERENCE_RECORDS=/tmp/roax-records gradle -p kotlin :roax-canon:test
```

**The runner probes two filenames per record**, `<recordType>.json` and `<export>.json`, so one directory satisfies this runner, the TypeScript one and the Rust one at once.
The TypeScript runner names by `<authority>.<profile>.json` and the Rust one names by its export; the vector itself names only the path inside the reference checkout, so the filename is each runner's own contract rather than something the corpus fixes.

## Building the Android artifact

```sh
ANDROID_HOME=~/Library/Android/sdk gradle -p kotlin :roax-canon-android:assembleRelease
```

`:roax-canon-android` compiles `:roax-canon`'s `src/main` directly rather than carrying a second copy of the canonicalization code, and it is **configured only when an SDK is actually found**.
Without one the JVM library still builds and tests, and Gradle says so rather than failing; `-Proax.skipAndroid=true` forces that configuration on a machine that has an SDK.
That matters because this repository has no CI, so a contributor touching only the canonicalization code must not need an Android SDK to run the corpus.

**The Android claim is checked without an Android SDK**, which is the part worth knowing.
`AndroidApiSurfaceTest` reads the compiled class files' constant pools and asserts that every JDK type the library references is on an allow-list of types present on Android API 21+, and that the bytecode is the Java 11 floor.
That is what actually catches the two mistakes that would break the Android build - `java.util.Base64`, which is API 26+, and `java.util.HexFormat`, which is absent from Android entirely - and it is why this library hand-rolls both.

## Protocol boundaries this library draws

- **Issuance and verification, not anchoring.**
  Specification section 2.2 leaves the anchoring registry undesigned, so `VerifierConfig.anchorRoot` and `VerifierConfig.anchorHashAlg` are the seams a deployment plugs it into.
  When `anchorHashAlg` is absent the envelope's own value is used, and that is a **hint being trusted**: mechanism H2 of section 7.4 is the only algorithm binding that works, and this library cannot supply the registry it depends on.
- **No profile-schema validation, and no value-domain validation.**
  Section 4.2 orders complete profile validation **before** map resolution, and ruled decision D13a keeps value-domain rules in a separate, independently versioned layer.
  So the `dose` positive-integer narrowing is not here, and this layer accepts `0` as a grammar-valid INTEGER; refusing it belongs to the profile validator.
  `TypeResolver` is the seam where a caller supplies the exact selected map.
- **Both envelope schema versions, selected explicitly.**
  `EnvelopeProfile.V2_TYPE_MAP_BOUND` is the default and is what section 11.2 now describes, with five always-emitted reserved leaves.
  `EnvelopeProfile.V1_NO_TYPE_MAP_BINDING` governs documents issued before the type-map binding, which is what the committed corpus is built from.
  Section 11 requires a verifier to select one per envelope and never merge them, so this is a parameter rather than a fallback.
- **Tag 8 `BLOB_REF` is registered and refused.**
  The byte layout of section 6.5 is implemented so it never has to be retrofitted, and every issuance and verification path rejects it until a profile declares the binding.
  `Poseidon-BN254` gets the same treatment.

## The two things most likely to be got wrong here

**Numbers never pass through `BigDecimal`, let alone a float.**
`BigDecimal.toString()` emits scientific notation the section 6.2 output grammar does not admit, its parser accepts `+1`, `007`, `.5` and `5.` which the ROAX grammars reject, its `equals` compares scale, and it would have to materialize ten thousand digits before `1.4e+9999` could be measured and rejected.
`toPlainString()` agrees with all seven worked examples in the specification, which is exactly what makes reaching for it dangerous.
`JvmPlatformTrapTest` pins every one of those as executable evidence.

**The Unicode version is a property of the runtime and cannot be pinned from here.**
Section 6.1 pins Unicode 15.1; JDK 17 ships 13.0 tables and JDK 25 ships 16.0, and no installed JDK has 15.1.
`Nfc` is therefore an injectable interface that declares its `unicodeVersion`, the corpus runner reports the comparison on every run, and the library does not claim a conformance it cannot verify.
[`FINDINGS.md`](FINDINGS.md) records what that gap costs, measured.
