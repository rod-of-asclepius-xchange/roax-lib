package io.roax.canon

/**
 * ROAX-CANON/1 section 6.2, canonical integers and decimals.
 *
 * **Nothing here goes through a floating-point type, and nothing here goes through
 * [java.math.BigDecimal] either.** The first is normative (section 6.4). The second is a
 * judgement, and it was made against measurement rather than taste:
 *
 * - `BigDecimal.toString()` emits scientific notation whenever the scale is negative or the
 *   adjusted exponent is below -6, so `1e2` renders `1E+2`, `0e5` renders `0E+5` and `1e-7`
 *   renders `1E-7`. The output grammar this section pins is `^-?(0|[1-9][0-9]*)(\.[0-9]+)?$`,
 *   which admits none of those. `toPlainString()` does agree with all seven worked examples in
 *   the specification, which is exactly what makes reaching for it dangerous.
 * - `BigDecimal`'s own parser accepts `+1`, `007`, `.5`, `5.`, `1E2` and `-0` - every one of
 *   which one of the two grammars below rejects or normalizes differently. Validation would have
 *   to be written by hand regardless, at which point the canonicalization is three lines more.
 * - `BigDecimal` would have to *materialize* an expansion before its length could be measured, so
 *   `1.4e+9999` allocates ten thousand digits on the way to being rejected, and `1.4e+999999999`
 *   is a memory-exhaustion input. The bound below is computed arithmetically and nothing is
 *   allocated for a value that fails it.
 * - `equals` compares scale as well as value, so `0.010`.equals(`0.01`) is false while
 *   `compareTo` is 0. Either is a defensible answer to a different question, and picking up the
 *   wrong one silently is how the trailing-zero requirement gets lost.
 *
 * The grammars are also checked character by character rather than by regular expression, which
 * removes the divergence `corpus/README.md` records: Python's `$` also matches immediately before
 * a trailing newline where JavaScript's does not, and Java's `$` behaves like Python's under
 * `find()`. `reject-decimal-trailing-newline` and `reject-integer-trailing-newline` pin it, and a
 * hand-written scanner cannot express the bug at all.
 */
object Numbers {

    /**
     * A fixed constant of ROAX-CANON/1 (section 6.2), not implementation-chosen: an
     * implementation-chosen limit would mean two conforming implementations disagree about which
     * records they canonicalize at all, which is one of the reasons section 13.3 rejects RDFC-1.0.
     */
    const val MAX_DIGITS: Int = 1024

    /**
     * Any exponent magnitude beyond this necessarily blows [MAX_DIGITS], in either direction, so
     * saturating here preserves every accept/reject decision while keeping the arithmetic below
     * inside a Long. A large positive exponent grows the integer part; a large negative one grows
     * the fraction by the same amount.
     */
    private const val EXPONENT_SATURATION = 1_000_000L

    /**
     * Canonical integer: `^-?(0|[1-9][0-9]*)$`, with `-0` normalizing to `0`.
     *
     * The digit bound is applied here as well as to decimals. Specification section 6.2 states it
     * under *Canonical decimal*, while its own justification counts "class 2's 40-digit integer"
     * against it - which is the first specification ambiguity `corpus/README.md` records. Both
     * corpus reference implementations and the Rust library apply it to INTEGER, no committed
     * vector discriminates, and this library follows the family.
     */
    fun canonicalInteger(input: String): String {
        var i = 0
        val negative = input.startsWith("-")
        if (negative) i = 1
        if (i >= input.length) {
            fail(Reason.INTEGER_GRAMMAR, "not a canonical integer: ${quote(input)}")
        }
        val digitsStart = i
        if (input[i] == '0') {
            i++
        } else {
            if (input[i] !in '1'..'9') {
                fail(Reason.INTEGER_GRAMMAR, "not a canonical integer: ${quote(input)}")
            }
            while (i < input.length && input[i] in '0'..'9') i++
        }
        if (i != input.length) {
            fail(Reason.INTEGER_GRAMMAR, "not a canonical integer: ${quote(input)}")
        }
        val digits = input.substring(digitsStart)
        if (digits.length > MAX_DIGITS) {
            fail(
                Reason.DIGIT_BOUND_EXCEEDED,
                "integer carries ${digits.length} digits, over the $MAX_DIGITS bound",
            )
        }
        if (digits == "0") return "0"
        return if (negative) "-$digits" else digits
    }

    /**
     * Canonical decimal.
     *
     * Input grammar `^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?$`, which is the FHIR R4
     * `decimal` pattern. Canonicalization does only two things: expand exponent notation into
     * positional notation, and drop the sign of a zero-valued magnitude. The digit sequence is
     * never rounded, extended or truncated, so trailing zeros of the fraction survive - `0.010`
     * stays `0.010`, which FHIR R4 says implementations SHALL do.
     */
    fun canonicalDecimal(input: String): String {
        var i = 0
        val negative = input.startsWith("-")
        if (negative) i = 1

        // --- integer part: "0" alone, or [1-9][0-9]* ---
        if (i >= input.length) badDecimal(input)
        val intStart = i
        if (input[i] == '0') {
            i++
        } else {
            if (input[i] !in '1'..'9') badDecimal(input)
            while (i < input.length && input[i] in '0'..'9') i++
        }
        val intDigits = input.substring(intStart, i)

        // --- optional fraction: '.' followed by at least one digit ---
        var fracDigits = ""
        if (i < input.length && input[i] == '.') {
            i++
            val fracStart = i
            while (i < input.length && input[i] in '0'..'9') i++
            if (i == fracStart) badDecimal(input)
            fracDigits = input.substring(fracStart, i)
        }

        // --- optional exponent: [eE] [+-]? digits ---
        var exponent = 0L
        if (i < input.length && (input[i] == 'e' || input[i] == 'E')) {
            i++
            var expNegative = false
            if (i < input.length && (input[i] == '+' || input[i] == '-')) {
                expNegative = input[i] == '-'
                i++
            }
            val expStart = i
            while (i < input.length && input[i] in '0'..'9') i++
            if (i == expStart) badDecimal(input)
            var magnitude = 0L
            for (c in input.substring(expStart, i)) {
                if (magnitude <= EXPONENT_SATURATION) magnitude = magnitude * 10 + (c - '0')
            }
            if (magnitude > EXPONENT_SATURATION) magnitude = EXPONENT_SATURATION
            exponent = if (expNegative) -magnitude else magnitude
        }

        if (i != input.length) badDecimal(input)

        // --- expansion, measured before anything is allocated ---
        val allDigits = intDigits + fracDigits
        val d = allDigits.length.toLong()
        // Position of the decimal point within allDigits after shifting right by `exponent`.
        val pointPos = intDigits.length.toLong() + exponent

        val expandedIntLen = if (pointPos > 0) pointPos else 0L
        val expandedFracLen = if (pointPos >= d) 0L else d - pointPos
        val total = expandedIntLen + expandedFracLen
        if (total > MAX_DIGITS) {
            fail(
                Reason.DIGIT_BOUND_EXCEEDED,
                "expanded positional form carries $total digits, over the $MAX_DIGITS bound",
            )
        }

        // The count above is taken on the padded form BEFORE output-grammar normalization. That is
        // the second ambiguity `corpus/README.md` records, and it is the literal reading and the
        // memory-safe one: under the other reading `0e99999` canonicalizes to `0`, under this one
        // it is rejected. No committed vector carries `0e99999`.

        var intPart: String
        val fracPart: String
        val p = pointPos.toInt()
        when {
            pointPos >= d -> {
                intPart = allDigits + "0".repeat((pointPos - d).toInt())
                fracPart = ""
            }

            pointPos <= 0 -> {
                intPart = ""
                fracPart = "0".repeat(-p) + allDigits
            }

            else -> {
                intPart = allDigits.substring(0, p)
                fracPart = allDigits.substring(p)
            }
        }

        // --- normalize to the output grammar ^-?(0|[1-9][0-9]*)(\.[0-9]+)?$ ---
        var lead = 0
        while (lead < intPart.length - 1 && intPart[lead] == '0') lead++
        intPart = if (intPart.isEmpty()) "0" else intPart.substring(lead)
        if (intPart.isEmpty()) intPart = "0"

        val zeroMagnitude = intPart.all { it == '0' } && fracPart.all { it == '0' }
        val sign = if (negative && !zeroMagnitude) "-" else ""
        return if (fracPart.isEmpty()) "$sign$intPart" else "$sign$intPart.$fracPart"
    }

    private fun badDecimal(input: String): Nothing =
        fail(Reason.DECIMAL_GRAMMAR, "not a canonical decimal: ${quote(input)}")

    private fun quote(s: String): String {
        val sb = StringBuilder("\"")
        for (c in s) when (c) {
            '\n' -> sb.append("\\n")
            '\r' -> sb.append("\\r")
            '\t' -> sb.append("\\t")
            '"' -> sb.append("\\\"")
            '\\' -> sb.append("\\\\")
            else -> if (c.code < 0x20 || c.code > 0x7E) {
                sb.append("\\u").append(String.format("%04x", c.code))
            } else {
                sb.append(c)
            }
        }
        return sb.append('"').toString()
    }
}
