#!/usr/bin/env node
// Reflow this repository's Markdown to one full sentence per physical line.
//
// The convention is stated in AGENTS.md, "Documentation conventions in force here": one full
// sentence per physical line, normal Markdown structure preserved, nothing reflowed inside code.
// This tool is the executable form of that convention, so the rule that was applied is readable
// rather than reconstructed from a diff, and so it can be re-run when new documents land.
//
//   node tools/reflow-markdown.mjs                 # check; exit 1 if any file would change
//   node tools/reflow-markdown.mjs --write         # rewrite in place
//   node tools/reflow-markdown.mjs --self-test     # sentence-splitter cases, no repository needed
//   node tools/reflow-markdown.mjs --verify-render # additionally compare rendered HTML
//   node tools/reflow-markdown.mjs --line-map out.json
//
// It is zero-dependency for everything except --verify-render, which needs markdown-it installed
// OUTSIDE this tree and named by ROAX_MARKDOWN_IT, exactly as tools/check-type-maps.mjs takes Ajv
// from ROAX_AJV. A missing renderer is reported NOT RUN and exits 2, which is neither a pass nor a
// failure.
//
// THE TOOL FAILS CLOSED. Any Markdown construct it does not model - a tilde fence, an indented code
// block, a lazy continuation, a setext heading, a hard line break in prose, an HTML block, a link
// reference definition, a GFM table written without leading pipes - refuses the file and exits
// non-zero rather than guessing at it. That is the same posture decision D7 takes for an unbound
// type-map path, and it is what makes the tool safe to point at a document nobody has read.

import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {lstatSync, readFileSync, realpathSync, writeFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

// Files the convention applies to but that this tool must not rewrite today.
//
// docs/type-maps.md is being edited by separate in-flight work that settles the NFC matching
// divergence and the undetermined type bindings, and that work reflows its own prose to this same
// convention. Rewriting it here would collide. Remove the entry once that lands; --no-exclusions
// overrides it for a one-off run.
const EXCLUDED = new Set(['docs/type-maps.md']);

// ---------------------------------------------------------------------------------------------
// Sentence boundaries
// ---------------------------------------------------------------------------------------------

// A period that ends one of these does not end a sentence. Drawn from what this repository
// actually contains plus the ordinary English set; `e.g.` is the only member that occurs here
// today, twice, both inside the quoted FHIR R4 decimal rule.
const ABBREVIATIONS = new Set([
  'a.m.', 'al.', 'approx.', 'ca.', 'cf.', 'ch.', 'chap.', 'co.', 'corp.', 'dr.', 'e.g.', 'ed.',
  'eds.', 'eq.', 'eqs.', 'esp.', 'est.', 'etc.', 'fig.', 'figs.', 'i.e.', 'ibid.', 'inc.', 'jr.',
  'ltd.', 'max.', 'min.', 'mr.', 'mrs.', 'ms.', 'no.', 'nos.', 'op.', 'p.', 'p.m.', 'ph.d.', 'pp.',
  'prof.', 'resp.', 'sec.', 'secs.', 'sr.', 'st.', 'u.k.', 'u.s.', 'vol.', 'vols.', 'vs.', 'viz.',
]);

const SENTENCE_PUNCTUATION = '.!?';
// Characters that may stand between the terminal punctuation and the space. `*` and `_` are here
// because these documents lead paragraphs with a bold thesis sentence, `**Like this.** Then the
// rest`, 257 times; without them the whole paragraph stays on one line.
const CLOSERS = '"\')]’”*_';

// Mark every offset whose punctuation must not be read as prose: an inline code span, an autolink,
// a link destination, and either half of a backslash escape. A period inside `docs/spec/foo.md:12`
// or inside <https://hl7.org/fhir/R4/datatypes.html> is not a sentence end.
//
// Code spans need a real scanner rather than a regex: CommonMark closes a run of N backticks with
// the next run of exactly N, so ``a ` b`` is one span and /`[^`]*`/ would misread it.
function protectedOffsets(text) {
  const mask = new Uint8Array(text.length);
  let i = 0;
  while (i < text.length) {
    const ch = text[i];
    if (ch === '\\') {
      mask[i] = 1;
      if (i + 1 < text.length) mask[i + 1] = 1;
      i += 2;
      continue;
    }
    if (ch === '`') {
      let open = 0;
      while (i + open < text.length && text[i + open] === '`') open += 1;
      let j = i + open;
      let close = -1;
      while (j < text.length) {
        if (text[j] !== '`') {
          j += 1;
          continue;
        }
        let run = 0;
        while (j + run < text.length && text[j + run] === '`') run += 1;
        if (run === open) {
          close = j;
          break;
        }
        j += run;
      }
      if (close < 0) {
        i += open;
        continue;
      }
      for (let k = i; k < close + open; k += 1) mask[k] = 1;
      i = close + open;
      continue;
    }
    if (ch === '<') {
      const autolink = /^<[A-Za-z][A-Za-z0-9+.-]*:[^<>\s]*>/.exec(text.slice(i));
      if (autolink) {
        for (let k = i; k < i + autolink[0].length; k += 1) mask[k] = 1;
        i += autolink[0].length;
        continue;
      }
      i += 1;
      continue;
    }
    if (ch === ']' && text[i + 1] === '(') {
      let depth = 1;
      let j = i + 2;
      while (j < text.length && depth > 0) {
        if (text[j] === '\\') {
          j += 2;
          continue;
        }
        if (text[j] === '(') depth += 1;
        else if (text[j] === ')') depth -= 1;
        j += 1;
      }
      if (depth === 0) {
        for (let k = i + 1; k < j; k += 1) mask[k] = 1;
        i = j;
        continue;
      }
      i += 1;
      continue;
    }
    i += 1;
  }
  return mask;
}

// A line that begins with any of these would be read as the start of a new block rather than as a
// continuation of the paragraph it came from, so a sentence starting with one is never cut onto
// its own line. This is what keeps a mid-paragraph "2. " from becoming an ordered list.
function opensABlock(segment) {
  return (
    /^#{1,6}(\s|$)/.test(segment) ||
    /^(`{3,}|~{3,})/.test(segment) ||
    /^>/.test(segment) ||
    /^([-*+]|\d{1,9}[.)])(\s|$)/.test(segment) ||
    /^\|/.test(segment) ||
    /^\[[^\]]+\]:\s/.test(segment) ||
    /^<[A-Za-z!/?]/.test(segment) ||
    /^[-=*_]{2,}\s*$/.test(segment) ||
    /^\s/.test(segment)
  );
}

// Split one logical paragraph into sentences. Returns offsets into `text` at which to cut; each
// cut offset is the index of the single space that separates two sentences.
function sentenceCuts(text) {
  const mask = protectedOffsets(text);
  const cuts = [];
  for (let i = 0; i < text.length; i += 1) {
    if (mask[i] || !SENTENCE_PUNCTUATION.includes(text[i])) continue;

    let end = i;
    while (end + 1 < text.length && SENTENCE_PUNCTUATION.includes(text[end + 1]) && !mask[end + 1]) {
      end += 1;
    }
    const run = text.slice(i, end + 1);
    i = end;

    // An ellipsis is not a sentence end. Both occurrences here are elisions inside a quotation.
    if (/^\.{2,}$/.test(run)) continue;

    let after = end + 1;
    while (after < text.length && CLOSERS.includes(text[after]) && !mask[after]) after += 1;

    // A boundary needs whitespace after it, which is what makes 0.010, 4.2 and v22.21.0 safe
    // without any numeric special case.
    if (after >= text.length || text[after] !== ' ') continue;
    if (text.slice(after + 1).trim() === '') continue;

    let start = i;
    while (start > 0 && !/\s/.test(text[start - 1])) start -= 1;
    const word = text.slice(start, end + 1);
    if (ABBREVIATIONS.has(word.toLowerCase())) continue;
    // A lone capital before the period is an initial, not a sentence end.
    if (/^[A-Za-z]\.$/.test(word)) continue;

    cuts.push(after);
  }
  return cuts;
}

// Split, then merge back anything that must not start a line. The right-hand side is deliberately
// permissive about case: `dogtag` and `pdt` start sentences in these documents.
export function splitSentences(text) {
  const cuts = sentenceCuts(text);
  const pieces = [];
  let prev = 0;
  for (const cut of cuts) {
    pieces.push([prev, cut]);
    prev = cut + 1;
  }
  pieces.push([prev, text.length]);

  const merged = [];
  // A sentence that begins with a block marker cannot be given its own line, so it stays on the
  // previous one. Its own tail must follow it there: the period that ended the marker was never a
  // sentence boundary, so `glue` carries the merge one piece further.
  let glue = false;
  for (const piece of pieces) {
    const segment = text.slice(piece[0], piece[1]);
    const opens = opensABlock(segment);
    if (merged.length > 0 && (segment === '' || opens || glue)) {
      merged[merged.length - 1][1] = piece[1];
    } else {
      merged.push([piece[0], piece[1]]);
    }
    glue = opens;
  }
  return merged;
}

// ---------------------------------------------------------------------------------------------
// Block structure
// ---------------------------------------------------------------------------------------------

class Unmodelled extends Error {}

const ATX = /^ {0,3}#{1,6}(\s|$)/;
const THEMATIC = /^ {0,3}((\*[ \t]*){3,}|(-[ \t]*){3,}|(_[ \t]*){3,})$/;
const TABLE_ROW = /^ {0,3}\|/;
const FENCE = /^( {0,3})(`{3,}|~{3,})(.*)$/;
const LIST_ITEM = /^( {0,3})([-*+]|\d{1,9}[.)])( +)(.*)$/;
const QUOTE = /^( {0,3})>( ?)(.*)$/;
const LINK_DEF = /^ {0,3}\[[^\]]+\]:\s/;
const SETEXT = /^ {0,3}(=+|-+)[ \t]*$/;

// A GFM delimiter row written without a leading pipe, which is the shape of a table whose rows
// carry no outer pipes. GFM admits that table and TABLE_ROW deliberately does not match it: the
// `^ {0,3}\|` anchor is what keeps a mid-paragraph `|` out of the table branch. So such a table
// reaches the paragraph branch, where nothing downstream would notice it - the delimiter row is
// not a thematic break, not a setext underline and not a list item, so it joins the paragraph and
// the whole table collapses into one line of prose. That is a rendering change, not a reflow, and
// the fail-closed posture refuses it. A thematic break carries no pipe and cannot match; a
// pipe-leading row is caught by TABLE_ROW first and cannot match either.
const PIPELESS_DELIMITER = /^ {0,3}:?-+:?( *\| *:?-+:?)+ *$/;

// A metadata field line: a bold label whose colon sits immediately inside the closing delimiter,
// such as `**Status:**` or `**`recordType`:**`. These carry one field each, are authored one per
// line, and end in no sentence punctuation, so sentence splitting alone merges a whole field list
// into a single 300-character line - which defeats the readable-diff purpose the convention exists
// for. A field line therefore always starts its own output line and is never joined onto the line
// before it. Requiring the colon before the closing `**` is what keeps the `**A bold thesis
// sentence.** Then the rest` paragraph opening these documents use 257 times out of the rule.
const METADATA_FIELD = /^(\*\*|__)(?![*_])[^\n]{1,80}?:\1(\s|$)/;

// CommonMark lets only some blocks interrupt a paragraph, and the list rule is the one that
// matters here: a bullet may interrupt, but an ordered item may only if its number is 1 and its
// content is non-empty. docs/spec/roax-canon-1.md wraps "while building class 9. It is recorded
// here" so that a line begins "9. ", and reading that as a list would invent an ordered list where
// the renderer sees running prose.
function interruptsParagraph(line) {
  if (line.trim() === '') return true;
  const item = LIST_ITEM.exec(line);
  if (item) {
    if (item[4].trim() === '') return false;
    return /^[-*+]$/.test(item[2]) || /^1[.)]$/.test(item[2]);
  }
  return (
    ATX.test(line) ||
    THEMATIC.test(line) ||
    TABLE_ROW.test(line) ||
    FENCE.test(line) ||
    QUOTE.test(line) ||
    LINK_DEF.test(line) ||
    /^ {0,3}<[A-Za-z!/?]/.test(line)
  );
}

// The "only 1 may interrupt" rule governs a paragraph, not a list that is already open: a sibling
// `2.` after item 1 starts item 2, which is what every renderer does and what the table of
// contents in docs/spec/roax-canon-1.md relies on. So an under-indented line ends the current item
// whenever it is any list item at all.
function endsListItem(line) {
  const item = LIST_ITEM.exec(line);
  if (item && item[4].trim() !== '') return true;
  return interruptsParagraph(line);
}

// Reflow a run of lines that share one container. `numbers` carries each line's 1-based number in
// the original file so the output can report where a line came from. Returns the output lines and,
// per output line, the original line numbers that fed it.
function reflowLines(lines, numbers, file) {
  const out = [];
  const sources = [];
  const emit = (text, from) => {
    out.push(text);
    sources.push(from);
  };
  const refuse = (index, why) => {
    throw new Unmodelled(`${file}:${numbers[index] ?? '?'}: ${why}`);
  };

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    if (line.trim() === '') {
      emit(line, [numbers[i]]);
      i += 1;
      continue;
    }

    const fence = FENCE.exec(line);
    if (fence) {
      if (fence[2][0] === '~') refuse(i, 'tilde fenced code block is not modelled');
      const width = fence[2].length;
      const opened = i;
      emit(line, [numbers[i]]);
      i += 1;
      let closed = false;
      while (i < lines.length) {
        const inner = lines[i];
        emit(inner, [numbers[i]]);
        i += 1;
        const end = /^ {0,3}(`{3,})[ \t]*$/.exec(inner);
        if (end && end[1].length >= width) {
          closed = true;
          break;
        }
      }
      if (!closed) refuse(opened, 'unterminated fenced code block');
      continue;
    }

    if (ATX.test(line) || THEMATIC.test(line)) {
      emit(line, [numbers[i]]);
      i += 1;
      continue;
    }

    if (TABLE_ROW.test(line)) {
      while (i < lines.length && TABLE_ROW.test(lines[i])) {
        emit(lines[i], [numbers[i]]);
        i += 1;
      }
      continue;
    }

    if (LINK_DEF.test(line)) refuse(i, 'link reference definition is not modelled');
    if (PIPELESS_DELIMITER.test(line)) refuse(i, 'GFM table without leading pipes is not modelled');
    if (/^ {0,3}<[A-Za-z!/?]/.test(line)) refuse(i, 'HTML block is not modelled');
    if (/\[\^/.test(line)) refuse(i, 'footnote syntax is not modelled');
    if (line.includes('\t')) refuse(i, 'tab in Markdown is not modelled');
    if (/^ {4,}\S/.test(line)) refuse(i, 'indented code block is not modelled');

    const quote = QUOTE.exec(line);
    if (quote) {
      const inner = [];
      const innerNumbers = [];
      const indent = quote[1];
      while (i < lines.length) {
        const match = QUOTE.exec(lines[i]);
        if (!match) break;
        if (match[1] !== indent) refuse(i, 'block quote changes indentation mid-quote');
        if (match[2] === '' && match[3] !== '') refuse(i, 'block quote marker without a space is not modelled');
        inner.push(match[3]);
        innerNumbers.push(numbers[i]);
        i += 1;
      }
      if (i < lines.length && lines[i].trim() !== '') refuse(i, 'lazy block quote continuation is not modelled');
      const reflowed = reflowLines(inner, innerNumbers, file);
      for (let k = 0; k < reflowed.out.length; k += 1) {
        const text = reflowed.out[k];
        emit(text === '' ? `${indent}>` : `${indent}> ${text}`, reflowed.sources[k]);
      }
      continue;
    }

    const item = LIST_ITEM.exec(line);
    if (item) {
      const [, indent, marker, gap, first] = item;
      const column = indent.length + marker.length + gap.length;
      const inner = [first];
      const innerNumbers = [numbers[i]];
      i += 1;
      while (i < lines.length) {
        const next = lines[i];
        if (next.trim() === '') {
          const follower = lines[i + 1];
          const continues =
            follower !== undefined &&
            follower.trim() !== '' &&
            /^ */.exec(follower)[0].length >= column;
          if (!continues) break;
          inner.push('');
          innerNumbers.push(numbers[i]);
          i += 1;
          continue;
        }
        const depth = /^ */.exec(next)[0].length;
        if (depth >= column) {
          inner.push(next.slice(column));
          innerNumbers.push(numbers[i]);
          i += 1;
          continue;
        }
        if (!endsListItem(next)) refuse(i, 'lazy list continuation is not modelled');
        break;
      }
      const reflowed = reflowLines(inner, innerNumbers, file);
      emit(`${indent}${marker}${gap}${reflowed.out[0]}`, reflowed.sources[0]);
      for (let k = 1; k < reflowed.out.length; k += 1) {
        const text = reflowed.out[k];
        emit(text === '' ? '' : ' '.repeat(column) + text, reflowed.sources[k]);
      }
      continue;
    }

    // Everything else is a paragraph.
    const paragraph = [];
    const paragraphNumbers = [];
    const start = i;
    while (i < lines.length) {
      const next = lines[i];
      // A setext underline is tested first: after a paragraph line, `---` is an H2 rather than the
      // thematic break the same characters mean anywhere else.
      if (paragraph.length > 0 && SETEXT.test(next)) refuse(i, 'setext heading underline is not modelled');
      if (paragraph.length > 0 && interruptsParagraph(next)) break;
      // A pipe-less delimiter row does not interrupt a paragraph, so it would be swallowed here.
      // It is refused rather than made to interrupt: interrupting would restructure the document
      // silently, which is the opposite of failing closed.
      if (PIPELESS_DELIMITER.test(next)) refuse(i, 'GFM table without leading pipes is not modelled');
      if (/[ \t]+$/.test(next) || /\\$/.test(next)) {
        refuse(i, 'hard line break inside prose is not modelled');
      }
      paragraph.push(next);
      paragraphNumbers.push(numbers[i]);
      i += 1;
    }
    const leading = /^ */.exec(paragraph[0])[0];
    if (leading.length > 3) refuse(start, 'paragraph indented four or more spaces is not modelled');

    // Metadata field lines partition the paragraph before anything is joined: each one opens a
    // group, so it keeps the line the author gave it. Everything else in a group is joined and cut
    // on sentence boundaries exactly as before, which is why a field line that wrapped still
    // absorbs its continuation.
    const groups = [[]];
    for (let k = 0; k < paragraph.length; k += 1) {
      if (k > 0 && METADATA_FIELD.test(paragraph[k].trim())) groups.push([]);
      groups[groups.length - 1].push(k);
    }

    for (const group of groups) {
      // Join into one logical string, remembering which original line each character came from, so
      // a sentence that spans a wrap can report both.
      let joined = '';
      const spans = [];
      for (const k of group) {
        const text = paragraph[k].trim();
        if (joined !== '') joined += ' ';
        spans.push([joined.length, joined.length + text.length, paragraphNumbers[k]]);
        joined += text;
      }

      for (const [from, to] of splitSentences(joined)) {
        const contributors = spans
          .filter((span) => span[0] < to && span[1] > from)
          .map((span) => span[2]);
        emit(
          leading + joined.slice(from, to),
          contributors.length > 0 ? contributors : [paragraphNumbers[group[0]]],
        );
      }
    }
  }

  return {out, sources};
}

// ---------------------------------------------------------------------------------------------
// Invariants
// ---------------------------------------------------------------------------------------------

// Every non-whitespace character of the document, in order, ignoring the block quote markers that
// legitimately change in number when a quoted paragraph is rewrapped. Reflow moves line breaks and
// nothing else, so this digest must be identical before and after.
function contentDigest(text) {
  const stripped = text
    .split('\n')
    .map((line) => line.replace(/^(?:[ \t]*>[ \t]?)+/, ''))
    .join('');
  return createHash('sha256').update(stripped.replace(/\s+/g, ''), 'utf8').digest('hex');
}

// Lines that must survive byte for byte: fenced code content and every table row.
function verbatimLines(text) {
  const kept = [];
  let inFence = false;
  let width = 0;
  for (const line of text.split('\n')) {
    const fence = FENCE.exec(line);
    if (!inFence && fence) {
      inFence = true;
      width = fence[2].length;
      kept.push(`fence:${line}`);
      continue;
    }
    if (inFence) {
      kept.push(`code:${line}`);
      const end = /^ {0,3}(`{3,}|~{3,})[ \t]*$/.exec(line);
      if (end && end[1].length >= width) inFence = false;
      continue;
    }
    if (TABLE_ROW.test(line)) kept.push(`table:${line}`);
  }
  return kept;
}

// Every blank line, in place, and the kind of block each run of non-blank lines opens with.
// Rewrapping the inside of a run is invisible here, which is the point: that is the only thing
// reflow is allowed to do. A lost or gained blank line, a heading that became prose, a paragraph
// that became a list, or a code fence that moved all show up.
function blockSignature(text) {
  const marks = [];
  let inFence = false;
  let width = 0;
  let inRun = false;
  for (const line of text.split('\n')) {
    if (inFence) {
      const end = /^ {0,3}(`{3,}|~{3,})[ \t]*$/.exec(line);
      if (end && end[1].length >= width) inFence = false;
      continue;
    }
    const fence = FENCE.exec(line);
    if (fence) {
      marks.push('code');
      inFence = true;
      width = fence[2].length;
      inRun = true;
      continue;
    }
    if (line.trim() === '') {
      marks.push('blank');
      inRun = false;
      continue;
    }
    let kind;
    if (ATX.test(line)) kind = 'heading';
    else if (THEMATIC.test(line)) kind = 'break';
    else if (TABLE_ROW.test(line)) kind = 'table';
    else if (QUOTE.test(line)) kind = 'quote';
    else if (LIST_ITEM.test(line)) kind = 'list';
    else kind = 'prose';
    // Opening kind of the run, plus every mid-run line whose bytes are carried through verbatim
    // and whose count must therefore not move.
    if (!inRun) marks.push(kind);
    else if (kind === 'heading' || kind === 'break' || kind === 'table') marks.push(`mid:${kind}`);
    inRun = true;
  }
  return marks.join(',');
}

// The measurement the convention is actually about: prose lines carrying more than one sentence.
export function multiSentenceLines(text) {
  const found = [];
  let inFence = false;
  let width = 0;
  text.split('\n').forEach((line, index) => {
    const fence = FENCE.exec(line);
    if (!inFence && fence) {
      inFence = true;
      width = fence[2].length;
      return;
    }
    if (inFence) {
      const end = /^ {0,3}(`{3,}|~{3,})[ \t]*$/.exec(line);
      if (end && end[1].length >= width) inFence = false;
      return;
    }
    if (line.trim() === '' || TABLE_ROW.test(line) || ATX.test(line) || THEMATIC.test(line)) return;
    let content = line.replace(/^(?:[ \t]*>[ \t]?)+/, '').replace(/^\s+/, '');
    const item = /^([-*+]|\d{1,9}[.)])\s+/.exec(content);
    if (item) content = content.slice(item[0].length);
    if (content === '') return;
    if (splitSentences(content).length > 1) found.push({line: index + 1, text: line});
  });
  return found;
}

// Prose line lengths, excluding code, tables and headings: the p90 the convention is measured by.
export function proseLineLengths(text) {
  const lengths = [];
  let inFence = false;
  let width = 0;
  for (const line of text.split('\n')) {
    const fence = FENCE.exec(line);
    if (!inFence && fence) {
      inFence = true;
      width = fence[2].length;
      continue;
    }
    if (inFence) {
      const end = /^ {0,3}(`{3,}|~{3,})[ \t]*$/.exec(line);
      if (end && end[1].length >= width) inFence = false;
      continue;
    }
    if (line.trim() === '' || TABLE_ROW.test(line) || ATX.test(line) || THEMATIC.test(line)) continue;
    lengths.push([...line].length);
  }
  return lengths;
}

// ---------------------------------------------------------------------------------------------
// Driver
// ---------------------------------------------------------------------------------------------

export function reflowDocument(text, file) {
  if (text.includes('\r')) throw new Unmodelled(`${file}: carriage return is not modelled`);
  const trailing = text.endsWith('\n');
  const body = trailing ? text.slice(0, -1) : text;
  const lines = body.split('\n');
  const numbers = lines.map((_, index) => index + 1);
  const {out, sources} = reflowLines(lines, numbers, file);
  const result = out.join('\n') + (trailing ? '\n' : '');

  if (contentDigest(result) !== contentDigest(text)) {
    throw new Unmodelled(`${file}: reflow changed document content, not only line breaks`);
  }
  const before = verbatimLines(text);
  const after = verbatimLines(result);
  if (before.length !== after.length || before.some((line, index) => line !== after[index])) {
    throw new Unmodelled(`${file}: reflow altered a fenced code block or a table row`);
  }
  if (blockSignature(result) !== blockSignature(text)) {
    throw new Unmodelled(`${file}: reflow changed the block structure`);
  }

  // Original line -> the output line it first appears on.
  const lineMap = new Map();
  sources.forEach((contributors, index) => {
    for (const original of contributors) {
      if (!lineMap.has(original)) lineMap.set(original, index + 1);
    }
  });
  return {text: result, lineMap};
}

function listMarkdownFiles() {
  const listed = execFileSync('git', ['ls-files', '-z', '*.md'], {cwd: REPO_ROOT, encoding: 'utf8'});
  return listed
    .split('\0')
    .filter((entry) => entry !== '')
    .filter((entry) => !lstatSync(path.join(REPO_ROOT, entry)).isSymbolicLink());
}

function loadRenderer() {
  const root = process.env.ROAX_MARKDOWN_IT;
  if (!root) return {ok: false, reason: 'ROAX_MARKDOWN_IT is not set'};
  try {
    const require = createRequire(path.join(path.resolve(root), 'index.js'));
    const MarkdownIt = require('markdown-it');
    const md = new MarkdownIt({html: true, linkify: false, typographer: false});
    if (!md.render('| a |\n| - |\n| b |\n').includes('<table>')) {
      return {ok: false, reason: 'the configured markdown-it preset does not enable tables'};
    }
    return {ok: true, render: (text) => md.render(text)};
  } catch (error) {
    return {ok: false, reason: `markdown-it could not be loaded from ROAX_MARKDOWN_IT: ${error.message}`};
  }
}

// HTML equality under the whitespace rules the browser applies: runs of whitespace collapse
// everywhere except inside <pre>, where they are significant.
function normalizeHtml(html) {
  const parts = html.split(/(<pre[\s\S]*?<\/pre>)/);
  return parts
    .map((part, index) => (index % 2 === 1 ? part : part.replace(/\s+/g, ' ')))
    .join('')
    .trim();
}

function percentile(sorted, fraction) {
  if (sorted.length === 0) return 0;
  return sorted[Math.min(sorted.length - 1, Math.floor(fraction * sorted.length))];
}

const SELF_TESTS = [
  ['Two sentences here. And the second one.', ['Two sentences here.', 'And the second one.']],
  ['Section 4.2 says so.', ['Section 4.2 says so.']],
  ['See specification section 4.2. The next sentence starts here.',
    ['See specification section 4.2.', 'The next sentence starts here.']],
  ['FHIR R4 says SHALL. dogtag strips them.', ['FHIR R4 says SHALL.', 'dogtag strips them.']],
  ['Checked against them. pdt\'s floor is a subset.', ['Checked against them.', 'pdt\'s floor is a subset.']],
  ['The precision has significance: e.g. 0.010 is different to 0.01, and precision is kept.',
    ['The precision has significance: e.g. 0.010 is different to 0.01, and precision is kept.']],
  ['That is i.e. the same thing. Then more.', ['That is i.e. the same thing.', 'Then more.']],
  ['It says "MUST cover ... an unknown empty array", and the corpus agrees.',
    ['It says "MUST cover ... an unknown empty array", and the corpus agrees.']],
  ['Node v22.21.0 was used. It worked.', ['Node v22.21.0 was used.', 'It worked.']],
  ['See `docs/spec/roax-canon-1.md:912-913`. The rule holds.',
    ['See `docs/spec/roax-canon-1.md:912-913`.', 'The rule holds.']],
  ['A period inside `a.b[0].c` is display only. Never hash it.',
    ['A period inside `a.b[0].c` is display only.', 'Never hash it.']],
  ['Read <https://hl7.org/fhir/R4/datatypes.html> for the rule. Then apply it.',
    ['Read <https://hl7.org/fhir/R4/datatypes.html> for the rule.', 'Then apply it.']],
  ['See [the note](https://example.org/a.b.c) first. Then the table.',
    ['See [the note](https://example.org/a.b.c) first.', 'Then the table.']],
  ['`roax.recordId` is mandatory. `roax.typeMap.id` is arithmetic.',
    ['`roax.recordId` is mandatory.', '`roax.typeMap.id` is arithmetic.']],
  ['It failed. 2. is a list marker and must not open a line.',
    ['It failed. 2. is a list marker and must not open a line.']],
  ['It failed. - a bullet must not open a line either.',
    ['It failed. - a bullet must not open a line either.']],
  ['Is it settled? No, it is open. It stays open.',
    ['Is it settled?', 'No, it is open.', 'It stays open.']],
  ['Written by J. Smith. The next one follows.', ['Written by J. Smith.', 'The next one follows.']],
  ['The count is 34 states (see section 1.5). That is a lower bound.',
    ['The count is 34 states (see section 1.5).', 'That is a lower bound.']],
  ['Trailing zeros matter: 0.010 is not 0.01. FHIR R4 says SHALL.',
    ['Trailing zeros matter: 0.010 is not 0.01.', 'FHIR R4 says SHALL.']],
  ['One sentence with no terminator', ['One sentence with no terminator']],
  ['Spans `a ` b` are one code span. Done.', ['Spans `a ` b` are one code span.', 'Done.']],
  ['**A bold thesis sentence.** Then the rest of the paragraph.',
    ['**A bold thesis sentence.**', 'Then the rest of the paragraph.']],
  ['*One emphasised claim.* A second one.', ['*One emphasised claim.*', 'A second one.']],
  ['**Bold spanning two sentences. Both inside it.** After.',
    ['**Bold spanning two sentences.', 'Both inside it.**', 'After.']],
];

const DOCUMENT_SELF_TESTS = [
  // A fenced block is never reflowed, and neither is a table.
  ['```sh\nrun --a. --b. --c\n```\n\n| a. b | c. d |\n| ---- | ---- |\n',
    '```sh\nrun --a. --b. --c\n```\n\n| a. b | c. d |\n| ---- | ---- |\n'],
  // A wrapped paragraph collapses onto sentence lines.
  ['One sentence that was\nwrapped across lines. A second\none also wrapped.\n',
    'One sentence that was wrapped across lines.\nA second one also wrapped.\n'],
  // List markers, continuation indent and nesting survive.
  ['- First item here. It\n  continues on.\n- Second.\n',
    '- First item here.\n  It continues on.\n- Second.\n'],
  ['1. Numbered item. It\n   wraps too.\n',
    '1. Numbered item.\n   It wraps too.\n'],
  // A block quote keeps its marker on every emitted line, including the blank one.
  ['> Quoted sentence one. Quoted\n> sentence two.\n>\n> Third.\n',
    '> Quoted sentence one.\n> Quoted sentence two.\n>\n> Third.\n'],
  // A quote nested in a list item.
  ['- Item.\n\n  > Quoted here. And\n  > more.\n',
    '- Item.\n\n  > Quoted here.\n  > And more.\n'],
  // A heading is one line whatever it contains, and a thematic break is untouched.
  ['## A heading. With two sentences.\n\n---\n\nBody. Text.\n',
    '## A heading. With two sentences.\n\n---\n\nBody.\nText.\n'],
  // An inline code span that was split across a wrap rejoins with a single space.
  ['Run `tool --out\nfile.json`, then stop. Done.\n',
    'Run `tool --out file.json`, then stop.\nDone.\n'],
  // A block of metadata field lines keeps one field per line. None of these ends in sentence
  // punctuation, so without the rule the whole block would merge into a single line.
  ['**Status:** draft for review.\n**Version string:** `ROAX-CANON/1`\n**Date:** 2026-07-28\n',
    '**Status:** draft for review.\n**Version string:** `ROAX-CANON/1`\n**Date:** 2026-07-28\n'],
  ['**`recordType`:** `hl7.fhir.bundle`\n__Date:__ 2026-07-28\n',
    '**`recordType`:** `hl7.fhir.bundle`\n__Date:__ 2026-07-28\n'],
  // A field line that wrapped still absorbs its continuation; the next field line still splits.
  ['**Label:** a value that\nwrapped across lines\n**Other:** second value\n',
    '**Label:** a value that wrapped across lines\n**Other:** second value\n'],
  // Ordinary wrapped prose still joins: a bold thesis sentence carries no colon inside the closing
  // delimiter, so it is not a field line and the rule leaves the 257 sites like it alone.
  ['**A bold thesis sentence.** Then the\nrest of the paragraph continues.\n',
    '**A bold thesis sentence.**\nThen the rest of the paragraph continues.\n'],
  ['A sentence about `**Label:**` that\nwrapped, and a second one follows here.\n',
    'A sentence about `**Label:**` that wrapped, and a second one follows here.\n'],
];

function runSelfTest() {
  let failures = 0;
  for (const [input, expected] of SELF_TESTS) {
    const actual = splitSentences(input).map(([from, to]) => input.slice(from, to));
    if (JSON.stringify(actual) !== JSON.stringify(expected)) {
      failures += 1;
      console.log(`FAIL split  ${JSON.stringify(input)}`);
      console.log(`     want   ${JSON.stringify(expected)}`);
      console.log(`     got    ${JSON.stringify(actual)}`);
    }
  }
  for (const [input, expected] of DOCUMENT_SELF_TESTS) {
    let actual;
    try {
      actual = reflowDocument(input, '<self-test>').text;
    } catch (error) {
      actual = `THREW ${error.message}`;
    }
    if (actual !== expected) {
      failures += 1;
      console.log(`FAIL doc    ${JSON.stringify(input)}`);
      console.log(`     want   ${JSON.stringify(expected)}`);
      console.log(`     got    ${JSON.stringify(actual)}`);
    }
    if (actual === expected) {
      const again = reflowDocument(actual, '<self-test>').text;
      if (again !== actual) {
        failures += 1;
        console.log(`FAIL idem   ${JSON.stringify(input)}`);
        console.log(`     second ${JSON.stringify(again)}`);
      }
    }
  }
  // Constructs the tool must refuse rather than guess at.
  const refusals = [
    ['~~~\ncode\n~~~\n', 'tilde fence'],
    ['Text with a hard break  \nand a continuation.\n', 'hard line break'],
    ['<div>\nblock\n</div>\n', 'HTML block'],
    ['[ref]: https://example.org\n', 'link reference definition'],
    ['A note[^1] here.\n\n[^1]: The note.\n', 'footnote'],
    ['\tTabbed line\n', 'tab'],
    ['A heading\n=========\n', 'setext heading'],
    ['    indented code\n', 'indented code'],
    ['```\nunterminated\n', 'unterminated fence'],
    ['a | b\n--- | ---\n1 | 2\n', 'GFM table without leading pipes'],
    [':--- | ---:\n', 'GFM delimiter row without leading pipes, alone'],
  ];
  for (const [input, label] of refusals) {
    let refused = false;
    try {
      reflowDocument(input, '<self-test>');
    } catch (error) {
      refused = error instanceof Unmodelled;
    }
    if (!refused) {
      failures += 1;
      console.log(`FAIL refuse ${label}: accepted ${JSON.stringify(input)}`);
    }
  }
  const total = SELF_TESTS.length + DOCUMENT_SELF_TESTS.length + refusals.length;
  console.log(failures === 0 ? `self-test: ${total} cases pass` : `self-test: ${failures} FAILURES`);
  return failures === 0 ? 0 : 1;
}

function main(argv) {
  const flags = new Set(argv.filter((arg) => arg.startsWith('--')));
  const positional = argv.filter((arg) => !arg.startsWith('--'));
  const mapIndex = argv.indexOf('--line-map');
  const mapPath = mapIndex >= 0 ? argv[mapIndex + 1] : null;
  const explicit = positional.filter((arg) => arg !== mapPath);

  if (flags.has('--self-test')) return runSelfTest();

  const write = flags.has('--write');
  const verify = flags.has('--verify-render');
  let renderer = {ok: false, reason: 'not requested'};
  if (verify) {
    renderer = loadRenderer();
    if (!renderer.ok) {
      console.log(`NOT RUN  render comparison: ${renderer.reason}`);
      console.log('         install markdown-it outside this tree and set ROAX_MARKDOWN_IT');
      return 2;
    }
  }

  let files = explicit.length > 0 ? explicit : listMarkdownFiles();
  if (explicit.length === 0 && !flags.has('--no-exclusions')) {
    for (const excluded of EXCLUDED) {
      if (files.includes(excluded)) console.log(`skipped  ${excluded} (see EXCLUDED in this tool)`);
    }
    files = files.filter((entry) => !EXCLUDED.has(entry));
  }

  const maps = {};
  let changed = 0;
  let failed = 0;
  let renderMismatch = 0;
  const lengthsBefore = [];
  const lengthsAfter = [];
  let multiBefore = 0;
  let multiAfter = 0;

  for (const file of files) {
    const absolute = path.resolve(REPO_ROOT, file);
    const original = readFileSync(absolute, 'utf8');
    let result;
    try {
      result = reflowDocument(original, file);
    } catch (error) {
      if (!(error instanceof Unmodelled)) throw error;
      console.log(`REFUSED  ${error.message}`);
      failed += 1;
      continue;
    }

    lengthsBefore.push(...proseLineLengths(original));
    lengthsAfter.push(...proseLineLengths(result.text));
    multiBefore += multiSentenceLines(original).length;
    multiAfter += multiSentenceLines(result.text).length;

    if (verify) {
      const before = normalizeHtml(renderer.render(original));
      const after = normalizeHtml(renderer.render(result.text));
      if (before !== after) {
        let at = 0;
        while (at < before.length && at < after.length && before[at] === after[at]) at += 1;
        console.log(`RENDER   ${file}: HTML differs at offset ${at}`);
        console.log(`         before ${JSON.stringify(before.slice(Math.max(0, at - 60), at + 120))}`);
        console.log(`         after  ${JSON.stringify(after.slice(Math.max(0, at - 60), at + 120))}`);
        renderMismatch += 1;
        continue;
      }
    }

    if (result.text !== original) {
      changed += 1;
      const idempotent = reflowDocument(result.text, file).text === result.text;
      if (!idempotent) {
        console.log(`UNSTABLE ${file}: a second pass would change it again`);
        failed += 1;
        continue;
      }
      if (write) writeFileSync(absolute, result.text);
      console.log(
        `${write ? 'wrote   ' : 'would   '} ${file}` +
          ` (${original.split('\n').length} -> ${result.text.split('\n').length} lines` +
          `${verify ? ', render identical' : ''})`,
      );
    } else {
      console.log(`ok       ${file}${verify ? ' (render identical)' : ''}`);
    }
    maps[file] = Object.fromEntries(result.lineMap);
  }

  if (mapPath) {
    writeFileSync(path.resolve(mapPath), `${JSON.stringify(maps, null, 2)}\n`);
    console.log(`line map written to ${mapPath}`);
  }

  const sortBefore = lengthsBefore.slice().sort((a, b) => a - b);
  const sortAfter = lengthsAfter.slice().sort((a, b) => a - b);
  console.log('');
  console.log(`files            ${files.length}`);
  console.log(`changed          ${changed}`);
  console.log(`refused          ${failed}`);
  if (verify) console.log(`render mismatch  ${renderMismatch}`);
  console.log(
    `prose p90        ${percentile(sortBefore, 0.9)} before -> ${percentile(sortAfter, 0.9)} after` +
      ` (rises by design: a whole sentence is longer than a 100-column wrap)`,
  );
  console.log(`multi-sentence   ${multiBefore} before -> ${multiAfter} after (target 0)`);

  if (failed > 0 || renderMismatch > 0) return 1;
  if (!write && changed > 0) return 1;
  return 0;
}

// Compare resolved paths rather than strings. `import.meta.url` is percent-encoded and already
// realpathed by the loader, while `process.argv[1]` is neither, so the string form goes false for a
// checkout under a path containing a space or a non-ASCII character and for any invocation through a
// symlink. That failure is silent - main() never runs, nothing is printed and the exit status is 0,
// which reads as "every file conforms" - and a fail-open entry point is the one thing this tool must
// not have. Same idiom as tools/check-type-map-extension.mjs:1769-1779.
function isDirectInvocation() {
  if (process.argv[1] === undefined) return false;
  const modulePath = fileURLToPath(import.meta.url);
  try {
    return realpathSync(process.argv[1]) === realpathSync(modulePath);
  } catch {
    return path.resolve(process.argv[1]) === modulePath;
  }
}

if (isDirectInvocation()) {
  process.exit(main(process.argv.slice(2)));
}
