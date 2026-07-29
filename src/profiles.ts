/**
 * The profile registry and the minimum-disclosure floors (specification section 10.2).
 *
 * > **Each profile MUST declare a set of non-redactable paths, and a disclosed copy that omits any
 * > of them MUST be rejected.**
 *
 * Without it a holder can withhold the very fields that say what the record is - its type, its
 * version, its issuer - and the disclosed copy still verifies against a genuine root, leaving the
 * verifier with a cryptographically valid proof of something it cannot identify. Neither source
 * research report specifies this; it comes from dogtag, where `NON_OBFUSCATABLE` is enforced
 * inside the integrity gate itself (`dogtag-mono-repo`,
 * `crates/dogtag-standard-rs/src/verify.rs:253` and `:273-277`).
 *
 * **Every floor path is carried as SEGMENTS and never as display notation.** This is the section
 * 5.2 trap one layer above hashing and it has already been made once in this project:
 * `docs/profiles/vaccination-healthcert.md` section 4 prints `notarisationMetadata.reference` for
 * humans, and read as a single key that floor entry asks for a leaf whose key is literally the
 * eighteen-character dotted string. No record has one, so the floor would match nothing and be
 * SILENTLY UNENFORCED while every fixture built the same way agreed with it. Carrying segments is
 * what makes the mistake unwriteable.
 */

import type { Path } from './path.js';

export interface ProfileFloor {
  /** The `recordType` this floor applies to. */
  readonly recordType: string;
  /** The profile's OWN non-redactable paths. The reserved half is added per identity. */
  readonly profilePaths: readonly Path[];
  /** Where the paths come from, so the table is checkable rather than trusted. */
  readonly citation: string;
}

/**
 * The four profiles registered under `docs/profiles/`.
 *
 * Specification section 12.2 makes the registry the extension point rather than the schema: new
 * profiles arrive by a registry entry and never by editing the specification, and an unknown
 * profile MUST fail closed with a stated reason and MUST NEVER default to a guess.
 */
export const PROFILE_FLOORS: readonly ProfileFloor[] = [
  {
    recordType: 'hl7.fhir.bundle',
    profilePaths: [[{ key: 'resourceType' }]],
    citation: 'docs/profiles/fhir.md section 5',
  },
  {
    recordType: 'sg.gov.moh.pdt-healthcert',
    profilePaths: [[{ key: 'version' }], [{ key: 'type' }], [{ key: 'validFrom' }]],
    citation: 'docs/profiles/pdt-healthcert.md section 4',
  },
  {
    recordType: 'sg.gov.moh.recovery-healthcert',
    profilePaths: [
      [{ key: 'version' }],
      [{ key: 'type' }],
      [{ key: 'validFrom' }],
      // The recovery-specific addition and the important one: a recovery certificate whose expiry
      // can be withheld while the rest verifies is an expired certificate that presents as valid.
      [{ key: 'validUntil' }],
    ],
    citation: 'docs/profiles/recovery-healthcert.md section 4',
  },
  {
    recordType: 'sg.gov.moh.vaccination-healthcert',
    profilePaths: [
      [{ key: 'validFrom' }],
      // TWO segments. Printed as `notarisationMetadata.reference` for humans; a floor holding that
      // dotted string as a single KEY matches nothing.
      [{ key: 'notarisationMetadata' }, { key: 'reference' }],
    ],
    citation: 'docs/profiles/vaccination-healthcert.md section 4',
  },
];

export function floorFor(recordType: string): ProfileFloor | undefined {
  return PROFILE_FLOORS.find((p) => p.recordType === recordType);
}

/** The profile identifiers a default verifier is configured with. */
export const REGISTERED_PROFILES: ReadonlySet<string> = new Set(
  PROFILE_FLOORS.map((p) => p.recordType),
);
