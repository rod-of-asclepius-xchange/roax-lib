# roax-lib

Open protocol standards and multi-language libraries for **human healthcare records**.

The goal is a language-neutral way to canonically serialize, merklize, anchor and
selectively disclose real health records - FHIR, and Singapore MOH's PDT, recovery
and vaccination healthcerts - integrating with ROAX.

Status: **design phase.** Specifications and schemas are being drafted for review
before any library code is written.

## Why not OpenAttestation

OpenAttestation derives a document's digest by walking a JSON object in JavaScript
into salted key-value paths. The digest therefore depends on JavaScript's object and
string semantics, which is what makes it awkward to reimplement faithfully in Rust,
Swift, Kotlin or Go. A protocol intended to have first-class libraries in several
languages cannot inherit that constraint.

## Repository layout

This repository contains only the protocol: specifications, schemas, and libraries.

Reference material used during design - including third-party schemata - is kept
**outside** this repository by design and is never committed here.
