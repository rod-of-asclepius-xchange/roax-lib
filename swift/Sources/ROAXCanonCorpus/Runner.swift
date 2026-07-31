import Foundation
import ROAXCanon

/// Runs the committed conformance corpus against this implementation.
///
/// The corpus is the executable arbiter (`corpus/README.md`). With five
/// independent libraries and no shared code, it is the whole enforcement
/// mechanism for cross-language agreement rather than a safety net, so a vector
/// this runner cannot execute is reported NOT RUN with the exact input that
/// would enable it and is never counted as passed.
public struct CorpusRunner {

    public let root: URL
    public let corpus: JSONValue
    public let referenceRecords: URL?
    public let report = Report()

    /// Parsed maps, held in a reference box for the same reason `report` is:
    /// this runner is a struct and `typeMap(for:)` is non-mutating, so a stored
    /// dictionary would be unreachable by construction and every reject and
    /// record vector would re-read and re-parse its map - the FHIR-shaped ones
    /// included - once per vector.
    private let typeMaps = TypeMapCache()

    /// The empty-container reading the record and envelope classes run under.
    ///
    /// See `EmptyContainerPolicy`: specification section 3.3 requires the map to
    /// authorize EMPTY_ARRAY and EMPTY_OBJECT, the committed corpus does not
    /// implement that rule, and this runner reports both readings rather than
    /// choosing one silently.
    public let emptyContainerPolicy: EmptyContainerPolicy

    public init(root: URL, referenceRecords: URL?, emptyContainerPolicy: EmptyContainerPolicy) throws {
        self.root = root
        self.referenceRecords = referenceRecords
        self.emptyContainerPolicy = emptyContainerPolicy
        self.corpus = try loadJSON(root.appendingPathComponent("corpus/conformance-corpus-1.0.json").path)
    }

    public func path(_ relative: String) -> String {
        root.appendingPathComponent(relative).path
    }

    private func vectors(_ name: String) -> [JSONValue] {
        arrayValue(corpus["vectors"]?[name]) ?? []
    }

    private func cls(_ v: JSONValue) -> Int { intValue(v["class"]) ?? 0 }
    private func name(_ v: JSONValue) -> String { stringValue(v["name"]) ?? "<unnamed>" }

    /// Every vector group this runner consumes.
    ///
    /// `vectors(_:)` above answers an unknown group with the empty array, so a
    /// corpus that grew a group this file does not read would contribute zero
    /// assertions and report the same green it reported before the group
    /// existed. That is the exact defect shape the corpus exists to prevent, so
    /// an unconsumed group is a hard failure rather than a quiet skip.
    static let consumedGroups: Set<String> = [
        "encodePath", "encodeValue", "reject", "leaf", "tree", "inclusion", "negativeProof",
        "typeMap", "record", "unlinkability", "normalization", "envelope", "roundTrip",
    ]

    /// The groups the corpus carries that this runner does not consume.
    public var unconsumedGroups: [String] {
        guard case .object(let members)? = corpus["vectors"] else { return [] }
        return members.map(\.key).filter { !Self.consumedGroups.contains($0) }.sorted()
    }

    public func run() {
        let unconsumed = unconsumedGroups
        if !unconsumed.isEmpty {
            report.record(
                .fail("the corpus carries vector group(s) this runner does not consume: "
                      + unconsumed.joined(separator: ", ")
                      + "; a group read as absent reports the same green as before it existed"),
                class: 0, name: "vector-group-coverage")
            return
        }
        runEncodePath()
        runEncodeValue()
        runReject()
        runLeaf()
        runTree()
        runInclusion()
        runNegativeProof()
        runTypeMap()
        runRecord()
        runUnlinkability()
        runNormalization()
        runEnvelope()
        runRoundTrip()
    }

    // MARK: encodePath

    private func runEncodePath() {
        for v in vectors("encodePath") {
            let outcome: Outcome
            do {
                let segments = try parseCorpusSegments(arrayValue(v["segments"]) ?? [])
                let encoded = PathEncoding.encode(segments).roaxHex
                let display = PathEncoding.display(segments)
                if encoded != stringValue(v["encodedHex"]) {
                    outcome = .fail("encodePath \(encoded) != \(stringValue(v["encodedHex"]) ?? "?")")
                } else if display != stringValue(v["displayPath"]) {
                    outcome = .fail("displayPath \(display.debugDescription) != \(stringValue(v["displayPath"])?.debugDescription ?? "?")")
                } else {
                    outcome = .pass
                }
            } catch {
                outcome = .fail("threw \(error)")
            }
            report.record(outcome, class: cls(v), name: name(v))
        }
    }

    // MARK: encodeValue

    private func runEncodeValue() {
        for v in vectors("encodeValue") {
            let outcome: Outcome
            do {
                guard let rawTag = intValue(v["tag"]), let tag = TypeTag(rawValue: UInt8(rawTag)) else {
                    report.record(.fail("no usable tag"), class: cls(v), name: name(v))
                    continue
                }
                let encoded = try ValueEncoding.encode(tag: tag, value: try carrier(tag: tag, input: v["input"]))
                let expected = stringValue(v["encodedHex"]) ?? ""
                outcome = encoded.roaxHex == expected
                    ? .pass
                    : .fail("encodeValue \(encoded.roaxHex) != \(expected)")
            } catch {
                outcome = .fail("threw \(error)")
            }
            report.record(outcome, class: cls(v), name: name(v))
        }
    }

    /// Turns a vector's `input` into the carrier the tag expects.
    ///
    /// BYTES is carried as lowercase hex here and in the envelope, not as
    /// base64: base64 is the *record's* spelling, and the pinned RFC 4648 form
    /// governs admitting it rather than committing it.
    private func carrier(tag: TypeTag, input: JSONValue?) throws -> EncodableValue {
        switch InputForm.classify(input) {
        case .utf16(let units):
            return .text(try UTF16Input.string(fromCodeUnits: units))
        case .jsonText, .segments:
            throw ROAXError.malformedJSON("escape form is not a value carrier")
        case .literal(let value):
            switch (tag, value) {
            case (.null, _), (.emptyArray, _), (.emptyObject, _):
                return .none
            case (.bool, .bool(let b)):
                return .bool(b)
            case (.bytes, .string(let hex)):
                guard let bytes = [UInt8].roaxFromHex(hex) else {
                    throw ROAXError.valueKindMismatch(tag: .bytes, detail: "not lowercase hex")
                }
                return .bytes(bytes)
            case (_, .string(let s)):
                return .text(s)
            default:
                throw ROAXError.valueKindMismatch(tag: tag, detail: "unsupported carrier")
            }
        }
    }

    // MARK: reject

    private func runReject() {
        for v in vectors("reject") {
            let expectedReason = stringValue(v["reason"]) ?? "?"
            let outcome: Outcome
            do {
                try performRejectable(v)
                outcome = .fail("accepted; expected rejection for \(expectedReason)")
            } catch let e as ROAXError {
                outcome = ReasonEquivalence.matches(corpusReason: expectedReason, thrown: e)
                    ? .pass
                    : .fail("rejected for \(e.reason), expected \(expectedReason) (\(e))")
            } catch {
                outcome = .fail("threw a non-ROAX error: \(error)")
            }
            report.record(outcome, class: cls(v), name: name(v))
        }
    }

    /// Drives one reject vector to the boundary its shape names.
    ///
    /// A reject vector carrying a `recordType` is a **whole-record** rejection:
    /// its `input` is record text and the runner MUST flatten it through the
    /// committed type map for that profile. That shape exists because three of
    /// the five bindings ruled on 2026-07-30 are stated as rejections rather
    /// than as tags, and a tag-bearing reject vector arrives at the value
    /// encoder already in the carrier form, so it can never exercise a rejection
    /// that happens where a record value is converted into that carrier.
    private func performRejectable(_ v: JSONValue) throws {
        let form = InputForm.classify(v["input"])

        if let recordType = stringValue(v["recordType"]) {
            guard case .jsonText(let text) = form else {
                throw ROAXError.malformedJSON("a record-shaped reject vector needs $jsonText")
            }
            let record = try JSONScanner.parse(text)
            let resolver = try typeMap(for: recordType)
            let committer = Committer<SHA256Hash>(
                resolver: resolver,
                emptyContainerPolicy: emptyContainerPolicy
            )
            // No record identity is carried, because flattening needs none: the
            // assertion is a rejection at the record boundary and not a tree.
            _ = try committer.flatten(record)
            return
        }

        switch form {
        case .jsonText(let text):
            _ = try JSONScanner.parse(text)
        case .segments(let segs):
            let segments = try parseCorpusSegments(segs)
            try ReservedNamespace.check(segments)
            _ = PathEncoding.encode(segments)
        case .utf16(let units):
            let text = try UTF16Input.string(fromCodeUnits: units)
            if let rawTag = intValue(v["tag"]), let tag = TypeTag(rawValue: UInt8(rawTag)) {
                _ = try ValueEncoding.encode(tag: tag, value: .text(text))
            }
        case .literal(let value):
            guard let rawTag = intValue(v["tag"]), let tag = TypeTag(rawValue: UInt8(rawTag)) else {
                throw ROAXError.malformedJSON("reject vector has no tag and no escape form")
            }
            _ = try ValueEncoding.encode(tag: tag, value: try carrier(tag: tag, input: value))
        }
    }

    // MARK: leaf

    private func runLeaf() {
        for v in vectors("leaf") {
            let outcome: Outcome
            do {
                guard let rawTag = intValue(v["tag"]), let tag = TypeTag(rawValue: UInt8(rawTag)),
                      let salt = hexBytes(v["saltHex"])
                else {
                    report.record(.fail("malformed vector"), class: cls(v), name: name(v))
                    continue
                }
                let segments = try parseCorpusSegments(arrayValue(v["segments"]) ?? [])
                let encodedValue = try ValueEncoding.encode(
                    tag: tag, value: try carrier(tag: tag, input: v["value"])
                )
                let hash = try LeafConstruction.leafHash(
                    segments: segments, tag: tag, encodedValue: encodedValue,
                    salt: salt, hash: SHA256Hash.self
                )
                let expected = stringValue(v["leafHash"]) ?? ""
                outcome = hash.roaxHex == expected ? .pass : .fail("leafHash \(hash.roaxHex) != \(expected)")
            } catch {
                outcome = .fail("threw \(error)")
            }
            report.record(outcome, class: cls(v), name: name(v))
        }
    }

    // MARK: tree, inclusion, negative proofs

    private func runTree() {
        for v in vectors("tree") {
            let leaves = (arrayValue(v["leafHashes"]) ?? []).compactMap { value -> [UInt8]? in
                guard case .string(let hex) = value else { return nil }
                return [UInt8].roaxFromHex(hex)
            }
            let root = MerkleTree.root(leaves, hash: SHA256Hash.self).roaxHex
            let expected = stringValue(v["root"]) ?? ""
            report.record(
                root == expected ? .pass : .fail("MTH \(root) != \(expected)"),
                class: cls(v), name: name(v)
            )
        }
    }

    private func runInclusion() {
        // Every inclusion vector is derived from the tree vector named
        // `tree-n<size>`, so the leaf list needed to REGENERATE an audit path is
        // recovered from there rather than carried per vector.
        var treesBySize = [Int: [[UInt8]]]()
        for v in vectors("tree") {
            let leaves = (arrayValue(v["leafHashes"]) ?? []).compactMap { value -> [UInt8]? in
                guard case .string(let hex) = value else { return nil }
                return [UInt8].roaxFromHex(hex)
            }
            treesBySize[leaves.count] = leaves
        }

        for v in vectors("inclusion") {
            guard let leafHash = hexBytes(v["leafHash"]),
                  let index = intValue(v["index"]),
                  let treeSize = intValue(v["treeSize"]),
                  let expectedRoot = hexBytes(v["root"]),
                  let expect = boolValue(v["expect"])
            else {
                report.record(.fail("malformed vector"), class: cls(v), name: name(v))
                continue
            }
            let auditPath = (arrayValue(v["auditPath"]) ?? []).compactMap { value -> [UInt8]? in
                guard case .string(let hex) = value else { return nil }
                return [UInt8].roaxFromHex(hex)
            }

            let verified = MerkleTree.verifyInclusion(
                leafHash: leafHash, index: index, treeSize: treeSize,
                auditPath: auditPath, root: expectedRoot, hash: SHA256Hash.self
            )
            if verified != expect {
                report.record(.fail("verify returned \(verified), expected \(expect)"),
                              class: cls(v), name: name(v))
                continue
            }

            // The second half of the class: GENERATING the audit path for
            // `index` must reproduce `auditPath`.
            if expect, let leaves = treesBySize[treeSize] {
                do {
                    let generated = try MerkleTree.inclusionProof(
                        leaves: leaves, index: index, hash: SHA256Hash.self
                    )
                    if generated.map(\.roaxHex) != auditPath.map(\.roaxHex) {
                        report.record(.fail("regenerated audit path differs"),
                                      class: cls(v), name: name(v))
                        continue
                    }
                } catch {
                    report.record(.fail("audit path generation threw \(error)"),
                                  class: cls(v), name: name(v))
                    continue
                }
            }
            report.record(.pass, class: cls(v), name: name(v))
        }
    }

    private func runNegativeProof() {
        for v in vectors("negativeProof") {
            guard let leafHash = hexBytes(v["leafHash"]),
                  let index = intValue(v["index"]),
                  let treeSize = intValue(v["treeSize"]),
                  let expectedRoot = hexBytes(v["root"])
            else {
                report.record(.fail("malformed vector"), class: cls(v), name: name(v))
                continue
            }
            let auditPath = (arrayValue(v["auditPath"]) ?? []).compactMap { value -> [UInt8]? in
                guard case .string(let hex) = value else { return nil }
                return [UInt8].roaxFromHex(hex)
            }
            let verified = MerkleTree.verifyInclusion(
                leafHash: leafHash, index: index, treeSize: treeSize,
                auditPath: auditPath, root: expectedRoot, hash: SHA256Hash.self
            )
            report.record(verified ? .fail("a negative proof verified") : .pass,
                          class: cls(v), name: name(v))
        }
    }

    // MARK: type maps

    private func typeMap(for recordType: String) throws -> DisplayPatternTypeMap {
        // `typeMapVector` identifies its map by `recordType` alone, so the
        // runner resolves it by the convention corpus/type-maps/<recordType>.json.
        if let cached = typeMaps.map(for: recordType) { return cached }
        let file = path("corpus/type-maps/\(recordType).json")
        let map = try DisplayPatternTypeMap(json: try loadJSON(file))
        typeMaps.store(map, for: recordType)
        return map
    }

    private func runTypeMap() {
        for v in vectors("typeMap") {
            let outcome: Outcome
            do {
                guard let recordType = stringValue(v["recordType"]),
                      let kindText = stringValue(v["jsonKind"]),
                      let kind = JSONKind(rawValue: kindText)
                else {
                    report.record(.fail("malformed vector"), class: cls(v), name: name(v))
                    continue
                }
                let map = try typeMap(for: recordType)
                let segments = try parseCorpusSegments(arrayValue(v["segments"]) ?? [])
                let expectFailClosed = boolValue(v["expectFailClosed"]) ?? false
                do {
                    let tag = try map.resolve(segments: segments, jsonKind: kind)
                    if expectFailClosed {
                        outcome = .fail("resolved to \(tag.rawValue); expected fail-closed")
                    } else if let expected = intValue(v["expectTag"]), Int(tag.rawValue) == expected {
                        outcome = .pass
                    } else {
                        outcome = .fail("resolved \(tag.rawValue) != expectTag \(intValue(v["expectTag"]) ?? -1)")
                    }
                } catch let e as ROAXError {
                    outcome = expectFailClosed ? .pass : .fail("failed closed unexpectedly: \(e)")
                }
            } catch {
                outcome = .fail("threw \(error)")
            }
            report.record(outcome, class: cls(v), name: name(v))
        }
    }

    // MARK: records

    private func runRecord() {
        for v in vectors("record") {
            let vectorName = name(v)
            let vectorClass = cls(v)

            guard let recordType = stringValue(v["recordType"]),
                  let schemaVersion = stringValue(v["schemaVersion"]),
                  let recordId = stringValue(v["recordId"]),
                  let issuerId = stringValue(v["issuerId"]),
                  let saltsFile = stringValue(v["saltsFile"]),
                  let expectedLeafCount = intValue(v["leafCount"]),
                  let expectedRoot = stringValue(v["root"])
            else {
                if stringValue(v["envelopeFile"]) != nil {
                    // `corpus/README.md` allows a record vector to carry the
                    // whole thing as one full envelope copy. No committed vector
                    // uses that carrier; a runner that does not implement it
                    // must fail rather than report NOT RUN.
                    report.record(.fail("the envelopeFile record carrier is not implemented"),
                                  class: vectorClass, name: vectorName)
                } else {
                    report.record(.fail("malformed vector"), class: vectorClass, name: vectorName)
                }
                continue
            }

            // A vector naming a reference-checkout record needs that checkout.
            guard let recordSource = recordSource(for: v) else {
                let probed = referenceRecords?.appendingPathComponent("\(recordType).json").path
                    ?? "<unset>"
                report.record(.notRun(
                    "needs a reference record at \(probed); set ROAX_REFERENCE_RECORDS "
                    + "to a directory holding <recordType>.json extracted with "
                    + "corpus/tools/extract_reference_record.py"
                ), class: vectorClass, name: vectorName)
                continue
            }

            do {
                let identity = RecordIdentity(
                    recordType: recordType,
                    schemaVersion: schemaVersion,
                    recordId: recordId,
                    issuerId: issuerId,
                    issuerKeyId: stringValue(v["issuerKeyId"])
                )
                let record = try loadJSON(recordSource)
                let salts = try loadSaltSet(path(saltsFile))
                let committer = Committer<SHA256Hash>(
                    resolver: try typeMap(for: recordType),
                    emptyContainerPolicy: emptyContainerPolicy
                )
                let commitment = try committer.commit(
                    record: record, salts: salts,
                    context: CommitmentContext(identity: identity)
                )
                if commitment.leafCount != expectedLeafCount {
                    report.record(.fail("leafCount \(commitment.leafCount) != \(expectedLeafCount)"),
                                  class: vectorClass, name: vectorName)
                } else if commitment.root.roaxHex != expectedRoot {
                    report.record(.fail("root \(commitment.root.roaxHex) != \(expectedRoot)"),
                                  class: vectorClass, name: vectorName)
                } else {
                    report.record(.pass, class: vectorClass, name: vectorName)
                }
            } catch {
                report.record(.fail("threw \(error)"), class: vectorClass, name: vectorName)
            }
        }
    }

    /// Where a record vector's record text comes from.
    ///
    /// Class 10 names the MOH samples in a checkout that lives outside this
    /// repository by design; every other class carries a synthetic fixture.
    private func recordSource(for v: JSONValue) -> String? {
        if let file = stringValue(v["recordFile"]) {
            let full = path(file)
            if FileManager.default.fileExists(atPath: full) { return full }
            // Class 10 names its records by a path INSIDE the reference
            // checkout, with a `#export` fragment, so the name never resolves
            // in this repository. Falling through to the extracted directory is
            // what makes those four vectors runnable.
        }
        guard let recordType = stringValue(v["recordType"]), let referenceRecords else { return nil }
        let candidate = referenceRecords.appendingPathComponent("\(recordType).json").path
        return FileManager.default.fileExists(atPath: candidate) ? candidate : nil
    }

    func loadSaltSet(_ file: String) throws -> SaltAssignment {
        let json = try loadJSON(file)
        let rows = arrayValue(json["salts"]) ?? []
        switch stringValue(json["pairing"]) {
        case "positional":
            let salts: [[UInt8]] = try rows.map {
                guard case .string(let hex) = $0, let bytes = [UInt8].roaxFromHex(hex), bytes.count == 16
                else { throw ROAXError.malformedJSON("a positional salt is not 32 lowercase hex") }
                return bytes
            }
            return .positional(salts)
        default:
            var pairs = [(Path, [UInt8])]()
            for row in rows {
                guard case .array(let segs)? = row["segments"],
                      let salt = hexBytes(row["salt"]), salt.count == 16
                else { throw ROAXError.malformedJSON("a path-paired salt entry is malformed") }
                pairs.append((try parseCorpusSegments(segs), salt))
            }
            return try SaltAssignment.byPath(pairs)
        }
    }

    // MARK: unlinkability

    private func runUnlinkability() {
        for v in vectors("unlinkability") {
            let outcome: Outcome
            do {
                guard let rawTag = intValue(v["tag"]), let tag = TypeTag(rawValue: UInt8(rawTag)),
                      let trials = intValue(v["trials"]),
                      let pathRows = arrayValue(v["paths"])
                else {
                    report.record(.fail("malformed vector"), class: cls(v), name: name(v))
                    continue
                }
                let paths = try pathRows.map { try parseCorpusSegments(arrayValue($0) ?? []) }
                let value = try carrier(tag: tag, input: v["value"])
                let encoded = try ValueEncoding.encode(tag: tag, value: value)

                // Nothing is compared against a pinned value: under ruled
                // decision D4b there is none to pin, so the runner performs
                // independent issuances with ITS OWN generator and asserts the
                // three relations.
                var saltsPerIssuance = [[[UInt8]]]()
                var hashesPerIssuance = [[[UInt8]]]()
                for _ in 0..<trials {
                    let salts = SaltSource.draw(count: paths.count)
                    saltsPerIssuance.append(salts)
                    hashesPerIssuance.append(try zip(paths, salts).map { p, s in
                        try LeafConstruction.leafHash(
                            segments: p, tag: tag, encodedValue: encoded,
                            salt: s, hash: SHA256Hash.self
                        )
                    })
                }

                var problems = [String]()
                if boolValue(v["expectDistinctSaltsWithinIssuance"]) == true {
                    for salts in saltsPerIssuance where Set(salts.map(\.roaxHex)).count != salts.count {
                        problems.append("a salt repeated within one issuance")
                        break
                    }
                }
                if boolValue(v["expectDistinctSaltsAcrossIssuances"]) == true {
                    let all = saltsPerIssuance.flatMap { $0 }.map(\.roaxHex)
                    if Set(all).count != all.count { problems.append("a salt repeated across issuances") }
                }
                if boolValue(v["expectDistinctLeafHashesAcrossIssuances"]) == true {
                    // The same path and the same value in two issuances must not
                    // produce the same leaf hash; that equality is exactly the
                    // cross-record patient-linkage hazard decision D4b removed.
                    for i in 0..<paths.count {
                        let column = hashesPerIssuance.map { $0[i].roaxHex }
                        if Set(column).count != column.count {
                            problems.append("leaf hashes repeated across issuances at path \(i)")
                            break
                        }
                    }
                }
                outcome = problems.isEmpty ? .pass : .fail(problems.joined(separator: "; "))
            } catch {
                outcome = .fail("threw \(error)")
            }
            report.record(outcome, class: cls(v), name: name(v))
        }
    }

    // MARK: normalization, end to end

    private func runNormalization() {
        for v in vectors("normalization") {
            let outcome: Outcome
            do {
                guard let nfdFile = stringValue(v["recordFileNFD"]),
                      let nfcFile = stringValue(v["recordFileNFC"]),
                      let saltsFile = stringValue(v["saltsFile"]),
                      let recordType = stringValue(v["recordType"]),
                      let schemaVersion = stringValue(v["schemaVersion"]),
                      let recordId = stringValue(v["recordId"]),
                      let issuerId = stringValue(v["issuerId"]),
                      let expectSameRoot = boolValue(v["expectSameRoot"]),
                      let expectedRoot = stringValue(v["root"])
                else {
                    report.record(.fail("malformed vector"), class: cls(v), name: name(v))
                    continue
                }
                let identity = RecordIdentity(
                    recordType: recordType, schemaVersion: schemaVersion,
                    recordId: recordId, issuerId: issuerId
                )
                let committer = Committer<SHA256Hash>(
                    resolver: try typeMap(for: recordType),
                    emptyContainerPolicy: emptyContainerPolicy
                )
                // ONE salt set for both forms, so any difference between the two
                // roots is normalization and nothing else.
                let salts = try loadSaltSet(path(saltsFile))
                let context = CommitmentContext(identity: identity)
                let nfdRoot = try committer.commit(
                    record: try loadJSON(path(nfdFile)), salts: salts, context: context
                ).root.roaxHex
                let nfcRoot = try committer.commit(
                    record: try loadJSON(path(nfcFile)), salts: salts, context: context
                ).root.roaxHex

                if (nfdRoot == nfcRoot) != expectSameRoot {
                    outcome = .fail("roots agree=\(nfdRoot == nfcRoot), expected \(expectSameRoot)")
                } else if nfcRoot != expectedRoot {
                    outcome = .fail("root \(nfcRoot) != \(expectedRoot)")
                } else {
                    outcome = .pass
                }
            } catch {
                outcome = .fail("threw \(error)")
            }
            report.record(outcome, class: cls(v), name: name(v))
        }
    }

    // MARK: envelopes

    private func runEnvelope() {
        for v in vectors("envelope") {
            let outcome: Outcome
            guard let file = stringValue(v["envelopeFile"]),
                  let expectAccept = boolValue(v["expectAccept"])
            else {
                report.record(.fail("malformed vector"), class: cls(v), name: name(v))
                continue
            }
            let expectedReason = stringValue(v["reason"]) ?? "ok"

            do {
                let envelopeJSON = try loadJSON(path(file))
                let envelope = try Envelope.parse(json: envelopeJSON)
                // A full copy has to flatten its record, so the verifier needs
                // the map for that profile.
                let resolver = try? typeMap(for: envelope.recordType)
                let verifier = EnvelopeVerifier<SHA256Hash>(
                    resolver: resolver,
                    emptyContainerPolicy: emptyContainerPolicy
                )
                try verifier.verify(envelope)
                outcome = expectAccept
                    ? .pass
                    : .fail("accepted; expected rejection for \(expectedReason)")
            } catch let e as ROAXError {
                if expectAccept {
                    outcome = .fail("rejected for \(e.reason): \(e)")
                } else if ReasonEquivalence.matches(
                    vector: name(v), corpusReason: expectedReason, thrown: e
                ) {
                    // The reason is not decoration: several fixtures are
                    // rejectable for more than one cause, so a boolean alone
                    // would pass an implementation that never ran the check the
                    // vector is about.
                    outcome = .pass
                } else {
                    outcome = .fail("rejected for \(e.reason), expected \(expectedReason) (\(e))")
                }
            } catch {
                outcome = .fail("threw a non-ROAX error: \(error)")
            }
            report.record(outcome, class: cls(v), name: name(v))
        }
    }
    // MARK: class 20 - issue, disclose, then verify this library's OWN output

    /// Every other class runs `EnvelopeVerifier` against bytes the corpus generator wrote.
    ///
    /// That is the gap this class closes, and it is not hypothetical here: this library
    /// once emitted every revealed leaf with `value: nil`, so it issued disclosures its own
    /// verifier refused for `disclosed-leaf-named-without-value` while passing all 488
    /// vectors - including the one naming that very condition. Only a human reading the
    /// source found it. So this drives `Committer.commit` and `Commitment.disclose`, then
    /// puts their output through the real verifier.
    ///
    /// The produced envelope is compared against the committed fixture field by field rather
    /// than by bytes: this package emits no JSON, and JSON member order, `displayPath` and
    /// the order of `disclosure.leaves` are not fixed by the specification anyway.
    private func runRoundTrip() {
        for v in vectors("roundTrip") {
            let vectorName = name(v)
            let vectorClass = cls(v)
            guard let recordType = stringValue(v["recordType"]),
                  let schemaVersion = stringValue(v["schemaVersion"]),
                  let recordId = stringValue(v["recordId"]),
                  let issuerId = stringValue(v["issuerId"]),
                  let recordFile = stringValue(v["recordFile"]),
                  let saltsFile = stringValue(v["saltsFile"]),
                  let expectedLeafCount = intValue(v["leafCount"]),
                  let expectedRoot = stringValue(v["root"]),
                  let disclosePaths = arrayValue(v["disclosePaths"]),
                  let fullCopyFile = stringValue(v["expectedFullCopyFile"]),
                  let disclosedCopyFile = stringValue(v["expectedDisclosedCopyFile"])
            else {
                report.record(.fail("malformed vector"), class: vectorClass, name: vectorName)
                continue
            }

            do {
                let descriptor = v["typeMap"]
                let identity = RecordIdentity(
                    recordType: recordType,
                    schemaVersion: schemaVersion,
                    recordId: recordId,
                    issuerId: issuerId,
                    issuerKeyId: stringValue(v["issuerKeyId"]),
                    typeMapId: stringValue(descriptor?["id"])
                )
                let committer = Committer<SHA256Hash>(
                    resolver: try typeMap(for: recordType),
                    emptyContainerPolicy: emptyContainerPolicy
                )
                let commitment = try committer.commit(
                    record: try loadJSON(path(recordFile)),
                    salts: try loadSaltSet(path(saltsFile)),
                    context: CommitmentContext(identity: identity)
                )
                guard commitment.leafCount == expectedLeafCount else {
                    report.record(.fail("leafCount \(commitment.leafCount) != \(expectedLeafCount)"),
                                  class: vectorClass, name: vectorName)
                    continue
                }
                guard commitment.root.roaxHex == expectedRoot else {
                    report.record(.fail("root \(commitment.root.roaxHex) != \(expectedRoot)"),
                                  class: vectorClass, name: vectorName)
                    continue
                }

                let head = { (record: JSONValue?, salts: [SaltEntry]?, leaves: [DisclosedLeaf]?) in
                    Envelope(
                        recordType: recordType, schemaVersion: schemaVersion, recordId: recordId,
                        issuerId: issuerId, issuerKeyId: stringValue(v["issuerKeyId"]),
                        typeMapId: stringValue(descriptor?["id"]),
                        typeMapVersion: stringValue(descriptor?["version"]),
                        root: commitment.root, leafCount: commitment.leafCount,
                        record: record, salts: salts, disclosedLeaves: leaves
                    )
                }
                let producedFull = head(
                    try loadJSON(path(recordFile)),
                    commitment.leaves.map { SaltEntry(segments: $0.segments, salt: $0.salt) },
                    nil
                )
                let producedDisclosed = head(
                    nil, nil,
                    try commitment.disclose(
                        paths: try disclosePaths.map {
                            try parseCorpusSegments(arrayValue($0) ?? [])
                        },
                        hash: SHA256Hash.self
                    )
                )

                let verifier = EnvelopeVerifier<SHA256Hash>(
                    resolver: try typeMap(for: recordType),
                    emptyContainerPolicy: emptyContainerPolicy
                )
                for (produced, expectedFile) in [(producedFull, fullCopyFile),
                                                 (producedDisclosed, disclosedCopyFile)] {
                    let expected = try Envelope.parse(json: try loadJSON(path(expectedFile)))
                    if let difference = firstEnvelopeDifference(produced: produced, expected: expected) {
                        report.record(.fail("\(expectedFile): \(difference)"),
                                      class: vectorClass, name: vectorName)
                        continue
                    }
                    // The half no static fixture can assert: this library's verifier over
                    // this library's own output.
                    do {
                        try verifier.verify(produced)
                        report.record(.pass, class: vectorClass, name: vectorName)
                    } catch {
                        report.record(
                            .fail("this library issued an envelope its own verifier refused: \(error)"),
                            class: vectorClass, name: vectorName)
                    }
                }
            } catch {
                report.record(.fail("threw \(error)"), class: vectorClass, name: vectorName)
            }
        }
    }
}
