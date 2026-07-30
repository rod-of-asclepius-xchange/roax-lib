// Versioned profile value rules, implementation B.
//
// A ROAX type map answers which tag a structured path and observed JSON kind select
// (specification section 4.2). A value-domain constraint is a different question and section 4.2
// puts it earlier: "Issuance MUST first validate against the pinned profile schema and then
// resolve every emitted leaf through the exact selected map." Profile validation runs BEFORE
// resolution and is not part of it.
//
// Decision D13 already ruled where a rule like this lives, and it is not in the canonicalization
// layer. D13a was ruled with a split: the protocol layer proves commitment and issuer identity
// and says so, while value-domain and clinical validation is "a separate, independently
// versioned conformance layer" (`docs/decisions.md`, D13). Merging them was rejected explicitly.
// So the positive-integer narrowing on a dose number is a profile-validation rule by ruling, and
// `roax_ref.mjs` deliberately does not carry it.
//
// This module is the ISSUER's half of section 4.2 step 1, executable. `check_corpus.mjs` is the
// issuer when it recomputes class 10, so a record violating a declared rule is refused here and
// never reaches a root.
//
// Every path is SEGMENTS and never display notation, which is the section 5.2 trap one layer
// above hashing: `notarisationMetadata.reference` reads as one token and is TWO segments, and a
// rule holding the dotted string as a single KEY matches nothing and is silently unenforced.
// `null` stands for any array index.

import * as ref from "./roax_ref.mjs";

// The revision of `docs/profiles/<profile>.md` section 6 this table implements.
export const PROFILE_RULE_VERSION = "1.1";

// A grammar-valid ROAX INTEGER of magnitude at least 1. No leading `-`, so `-1`, `0` and `-0`
// (which canonicalizes to `0`) are all outside the rule.
const POSITIVE_INTEGER = /^[1-9][0-9]*$/;

export const PROFILE_VALUE_RULES = {
  "sg.gov.moh.vaccination-healthcert": [
    {
      segments: ["notarisationMetadata", "signedEuHealthCerts", null, "dose"],
      ruleId: "dose-positive-integer",
      test: (canonical) => POSITIVE_INTEGER.test(canonical),
      // The dose number is bound INTEGER and the profile narrows it to a positive integer. The
      // type-map binding alone leaves `0` and every negative value formally valid under the
      // selected profile, because both are grammar-valid ROAX INTEGERs. A fractional value is
      // already refused one layer down by the section 6.2 INTEGER grammar, so this rule is
      // about `0` and the negatives and nothing else.
      why: "docs/profiles/vaccination-healthcert.md section 6",
    },
  ],
};

export class ProfileRuleError extends Error {
  constructor(ruleId, path, detail) {
    super(`${ruleId} at ${path}: ${detail}`);
    this.ruleId = ruleId;
    this.path = path;
    this.detail = detail;
  }
}

function matches(pattern, segments) {
  if (pattern.length !== segments.length) return false;
  return pattern.every((expected, i) => {
    const seg = segments[i];
    if (expected === null) return Object.prototype.hasOwnProperty.call(seg, "index");
    return Object.prototype.hasOwnProperty.call(seg, "key") && seg.key === expected;
  });
}

// Apply every declared rule for `recordType` to already-flattened leaves, throwing on the first
// violation. Running after flattening is deliberate: the rule is stated over the canonical
// INTEGER text, so it cannot disagree with the value the leaf actually commits.
export function checkRecord(recordType, leaves) {
  const rules = PROFILE_VALUE_RULES[recordType];
  if (!rules) return;
  for (const leaf of leaves) {
    for (const rule of rules) {
      if (!matches(rule.segments, leaf.segments)) continue;
      if (leaf.tag !== ref.TAG.INTEGER) {
        throw new ProfileRuleError(
          rule.ruleId,
          ref.displayPath(leaf.segments),
          `the rule is stated over an INTEGER leaf and this leaf is ${ref.TAG_NAME[leaf.tag]}`,
        );
      }
      const canonical = ref.canonicalInteger(leaf.value);
      if (!rule.test(canonical)) {
        throw new ProfileRuleError(
          rule.ruleId,
          ref.displayPath(leaf.segments),
          `${canonical} is not positive`,
        );
      }
    }
  }
}

// ---------------------------------------------------------------------------------------------
// Self-test
// ---------------------------------------------------------------------------------------------
//
// These rejections are NOT conformance vectors. Ruled decision D13a keeps value-domain
// validation out of the canonicalization layer, so a corpus vector for this rule would demand it
// from five implementations that by that ruling do not carry it. The corpus pins the ACCEPT case
// instead - the class-10 vaccination record commits, and its `dose` values are 1 and 2 - and the
// rejections are pinned here, in the profile layer that owns them.
//
// The discriminating values are `0` and the negatives. A fractional `1.5` is already refused one
// layer down by the section 6.2 INTEGER grammar, so a self-test using it would pass without the
// rule existing at all.

const DOSE_PATH = [
  { key: "notarisationMetadata" },
  { key: "signedEuHealthCerts" },
  { index: 0 },
  { key: "dose" },
];
const PROFILE = "sg.gov.moh.vaccination-healthcert";

function doseLeaf(value, { tag = ref.TAG.INTEGER, segments = DOSE_PATH } = {}) {
  return { segments, tag, value };
}

export function selfTest() {
  const failures = [];

  const expectAccept = (label, leaves) => {
    try {
      checkRecord(PROFILE, leaves);
    } catch (error) {
      failures.push(`${label}: unexpectedly refused (${error.message})`);
    }
  };
  const expectReject = (label, leaves) => {
    try {
      checkRecord(PROFILE, leaves);
    } catch (error) {
      if (error instanceof ProfileRuleError) return;
      failures.push(`${label}: refused with the wrong error (${error.message})`);
      return;
    }
    failures.push(`${label}: accepted, and the rule requires a refusal`);
  };

  // The values the shipped sample carries.
  for (const value of ["1", "2", "999"]) expectAccept(`dose ${value}`, [doseLeaf(value)]);

  // The values the NARROWING refuses and the INTEGER grammar alone does not. Each is a
  // grammar-valid ROAX INTEGER, so without this rule each would commit.
  for (const value of ["0", "-0", "-1", "-999"]) {
    ref.canonicalInteger(value);
    expectReject(`dose ${value}`, [doseLeaf(value)]);
  }

  // The rule cannot widen into another path or another profile.
  expectAccept("a different path carrying 0", [
    doseLeaf("0", { segments: [{ key: "somethingElse" }] }),
  ]);
  try {
    checkRecord("org.roax.corpus.synthetic", [doseLeaf("0")]);
  } catch (error) {
    failures.push(`unruled profile: unexpectedly refused (${error.message})`);
  }

  // Stated over an INTEGER leaf, so the same value at another tag is refused rather than
  // silently skipped: skipping would let a map change turn the rule off.
  expectReject("dose bound STRING", [doseLeaf("1", { tag: ref.TAG.STRING })]);

  if (failures.length > 0) {
    for (const line of failures) console.error(`FAIL: ${line}`);
    return 1;
  }
  console.log(`validated profile value rules, rule version ${PROFILE_RULE_VERSION}`);
  return 0;
}

if (process.argv[1] && process.argv[1].endsWith("profile_rules.mjs")) {
  process.exit(selfTest());
}
