use crate::error::{Error, Result};
use crate::json::JsonValue;
use crate::type_map::TypeTag;
use base64::engine::general_purpose::STANDARD;
use base64::Engine;
use unicode_normalization::UnicodeNormalization;

const MAX_EXPANDED_DIGITS: usize = 1024;

enum IntegerMagnitude {
    Zero,
    Finite {
        significant_digits: Vec<u8>,
        trailing_zeros: usize,
    },
    BeyondAddressableRange,
}

/// Content-addressed blob carrier registered by ROAX-CANON/1.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BlobRef {
    pub byte_length: u64,
    pub digest: Vec<u8>,
}

/// Typed leaf value after schema binding and canonical number expansion.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum LeafValue {
    Null,
    Bool(bool),
    String(String),
    Integer(String),
    Decimal(String),
    Bytes(Vec<u8>),
    EmptyArray,
    EmptyObject,
    BlobRef(BlobRef),
}

impl LeafValue {
    /// Bind a parsed JSON value to a schema-selected tag.
    pub fn from_json(tag: TypeTag, value: &JsonValue) -> Result<Self> {
        match (tag, value) {
            (TypeTag::Null, JsonValue::Null) => Ok(Self::Null),
            (TypeTag::Bool, JsonValue::Bool(value)) => Ok(Self::Bool(*value)),
            (TypeTag::String, JsonValue::String(value)) => Ok(Self::String(value.clone())),
            (TypeTag::Integer, JsonValue::Number(literal)) => {
                Ok(Self::Integer(canonical_integer(literal)?))
            }
            (TypeTag::Decimal, JsonValue::Number(literal)) => {
                Ok(Self::Decimal(canonical_decimal(literal)?))
            }
            (TypeTag::Bytes, JsonValue::String(text)) => {
                Ok(Self::Bytes(decode_canonical_base64(text)?))
            }
            (TypeTag::EmptyArray, JsonValue::Array(values)) if values.is_empty() => {
                Ok(Self::EmptyArray)
            }
            (TypeTag::EmptyObject, JsonValue::Object(entries)) if entries.is_empty() => {
                Ok(Self::EmptyObject)
            }
            (TypeTag::BlobRef, _) => Err(Error::BlobRefNotSelectable),
            _ => Err(Error::TypeMismatch { tag }),
        }
    }

    #[must_use]
    pub const fn tag(&self) -> TypeTag {
        match self {
            Self::Null => TypeTag::Null,
            Self::Bool(_) => TypeTag::Bool,
            Self::String(_) => TypeTag::String,
            Self::Integer(_) => TypeTag::Integer,
            Self::Decimal(_) => TypeTag::Decimal,
            Self::Bytes(_) => TypeTag::Bytes,
            Self::EmptyArray => TypeTag::EmptyArray,
            Self::EmptyObject => TypeTag::EmptyObject,
            Self::BlobRef(_) => TypeTag::BlobRef,
        }
    }

    /// Encode the value bytes placed in the leaf preimage.
    pub fn encode(&self) -> Result<Vec<u8>> {
        match self {
            Self::Null | Self::EmptyArray | Self::EmptyObject => Ok(Vec::new()),
            Self::Bool(value) => Ok(vec![u8::from(*value)]),
            Self::String(value) => Ok(value.nfc().collect::<String>().into_bytes()),
            Self::Integer(value) => Ok(canonical_integer(value)?.into_bytes()),
            Self::Decimal(value) => Ok(canonical_decimal(value)?.into_bytes()),
            Self::Bytes(value) => Ok(value.clone()),
            Self::BlobRef(value) => {
                if value.digest.len() != 32 {
                    return Err(Error::InvalidValueCarrier);
                }
                let digest_length =
                    u32::try_from(value.digest.len()).map_err(|_| Error::InvalidValueCarrier)?;
                let mut encoded = Vec::with_capacity(12 + value.digest.len());
                encoded.extend_from_slice(&value.byte_length.to_be_bytes());
                encoded.extend_from_slice(&digest_length.to_be_bytes());
                encoded.extend_from_slice(&value.digest);
                Ok(encoded)
            }
        }
    }

    pub(crate) fn validate_disclosure_canonicality(&self) -> Result<()> {
        match self {
            Self::Integer(value) if canonical_integer(value)? != *value => {
                Err(Error::InvalidValueCarrier)
            }
            Self::Decimal(value) if canonical_decimal(value)? != *value => {
                Err(Error::InvalidValueCarrier)
            }
            Self::BlobRef(value) if value.digest.len() != 32 => Err(Error::InvalidValueCarrier),
            _ => Ok(()),
        }
    }

    /// Build a disclosure carrier from a tag and optional JSON-compatible value.
    pub fn from_disclosure_carrier(tag: TypeTag, value: Option<&JsonValue>) -> Result<Self> {
        match tag {
            TypeTag::Null if value.is_none() => Ok(Self::Null),
            TypeTag::EmptyArray if value.is_none() => Ok(Self::EmptyArray),
            TypeTag::EmptyObject if value.is_none() => Ok(Self::EmptyObject),
            TypeTag::Bool => match value {
                Some(JsonValue::Bool(value)) => Ok(Self::Bool(*value)),
                _ => Err(Error::InvalidValueCarrier),
            },
            TypeTag::String => match value {
                Some(JsonValue::String(value)) => Ok(Self::String(value.clone())),
                _ => Err(Error::InvalidValueCarrier),
            },
            TypeTag::Integer => match value {
                Some(JsonValue::String(value)) => {
                    let canonical = canonical_integer(value)?;
                    if canonical == *value {
                        Ok(Self::Integer(canonical))
                    } else {
                        Err(Error::InvalidValueCarrier)
                    }
                }
                _ => Err(Error::InvalidValueCarrier),
            },
            TypeTag::Decimal => match value {
                Some(JsonValue::String(value)) => {
                    let canonical = canonical_decimal(value)?;
                    if canonical == *value {
                        Ok(Self::Decimal(canonical))
                    } else {
                        Err(Error::InvalidValueCarrier)
                    }
                }
                _ => Err(Error::InvalidValueCarrier),
            },
            TypeTag::Bytes => match value {
                Some(JsonValue::String(value)) => {
                    let bytes = hex::decode(value).map_err(|_| Error::InvalidValueCarrier)?;
                    if hex::encode(&bytes) == *value {
                        Ok(Self::Bytes(bytes))
                    } else {
                        Err(Error::InvalidValueCarrier)
                    }
                }
                _ => Err(Error::InvalidValueCarrier),
            },
            TypeTag::BlobRef => parse_blob_ref_carrier(value),
            _ => Err(Error::InvalidValueCarrier),
        }
    }

    /// Return the JSON-compatible carrier used in a disclosed leaf.
    #[must_use]
    pub fn disclosure_carrier(&self) -> Option<JsonValue> {
        match self {
            Self::Null | Self::EmptyArray | Self::EmptyObject => None,
            Self::Bool(value) => Some(JsonValue::Bool(*value)),
            Self::String(value) | Self::Integer(value) | Self::Decimal(value) => {
                Some(JsonValue::String(value.clone()))
            }
            Self::Bytes(value) => Some(JsonValue::String(hex::encode(value))),
            Self::BlobRef(value) => Some(JsonValue::Object(vec![
                (
                    "blobByteLength".into(),
                    JsonValue::String(value.byte_length.to_string()),
                ),
                (
                    "blobDigest".into(),
                    JsonValue::String(hex::encode(&value.digest)),
                ),
            ])),
        }
    }
}

fn parse_blob_ref_carrier(value: Option<&JsonValue>) -> Result<LeafValue> {
    let Some(JsonValue::Object(entries)) = value else {
        return Err(Error::InvalidValueCarrier);
    };
    let mut length = None;
    let mut digest = None;
    for (key, value) in entries {
        match (key.as_str(), value) {
            ("blobByteLength", JsonValue::String(text)) => {
                if canonical_unsigned_integer(text)? != *text {
                    return Err(Error::InvalidValueCarrier);
                }
                length = Some(
                    text.parse::<u64>()
                        .map_err(|_| Error::InvalidValueCarrier)?,
                );
            }
            ("blobDigest", JsonValue::String(text)) => {
                let bytes = hex::decode(text).map_err(|_| Error::InvalidValueCarrier)?;
                if bytes.len() != 32 || hex::encode(&bytes) != *text {
                    return Err(Error::InvalidValueCarrier);
                }
                digest = Some(bytes);
            }
            _ => return Err(Error::InvalidValueCarrier),
        }
    }
    Ok(LeafValue::BlobRef(BlobRef {
        byte_length: length.ok_or(Error::InvalidValueCarrier)?,
        digest: digest.ok_or(Error::InvalidValueCarrier)?,
    }))
}

/// Canonicalize an arbitrary-precision integer without parsing through a float.
pub fn canonical_integer(input: &str) -> Result<String> {
    let bytes = input.as_bytes();
    let (negative, digits) = if let Some(rest) = bytes.strip_prefix(b"-") {
        (true, rest)
    } else {
        (false, bytes)
    };
    if digits.is_empty()
        || !digits.iter().all(u8::is_ascii_digit)
        || (digits.len() > 1 && digits[0] == b'0')
    {
        return Err(Error::InvalidInteger);
    }
    if digits.len() > MAX_EXPANDED_DIGITS {
        return Err(Error::NumberExpansionLimit);
    }
    if negative && digits != b"0" {
        Ok(input.to_owned())
    } else {
        Ok(std::str::from_utf8(digits)
            .expect("ASCII digits are valid UTF-8")
            .to_owned())
    }
}

fn canonical_unsigned_integer(input: &str) -> Result<String> {
    let value = canonical_integer(input)?;
    if value.starts_with('-') {
        Err(Error::InvalidInteger)
    } else {
        Ok(value)
    }
}

/// Canonicalize an arbitrary-precision decimal while preserving fractional zeros.
pub fn canonical_decimal(input: &str) -> Result<String> {
    let bytes = input.as_bytes();
    let mut pos = 0;
    let negative = bytes.first() == Some(&b'-');
    if negative {
        pos += 1;
    }

    let integer_start = pos;
    match bytes.get(pos) {
        Some(b'0') => {
            pos += 1;
            if matches!(bytes.get(pos), Some(b'0'..=b'9')) {
                return Err(Error::InvalidDecimal);
            }
        }
        Some(b'1'..=b'9') => {
            pos += 1;
            while matches!(bytes.get(pos), Some(b'0'..=b'9')) {
                pos += 1;
            }
        }
        _ => return Err(Error::InvalidDecimal),
    }
    let integer_end = pos;

    let mut fraction_start = pos;
    let mut fraction_end = pos;
    if bytes.get(pos) == Some(&b'.') {
        pos += 1;
        fraction_start = pos;
        while matches!(bytes.get(pos), Some(b'0'..=b'9')) {
            pos += 1;
        }
        fraction_end = pos;
        if fraction_start == fraction_end {
            return Err(Error::InvalidDecimal);
        }
    }

    let mut exponent = 0_i64;
    if matches!(bytes.get(pos), Some(b'e' | b'E')) {
        pos += 1;
        let exponent_negative = bytes.get(pos) == Some(&b'-');
        if matches!(bytes.get(pos), Some(b'+' | b'-')) {
            pos += 1;
        }
        let exponent_start = pos;
        while matches!(bytes.get(pos), Some(b'0'..=b'9')) {
            pos += 1;
        }
        if exponent_start == pos {
            return Err(Error::InvalidDecimal);
        }
        let exponent_digits = &bytes[exponent_start..pos];
        let significant = exponent_digits
            .iter()
            .position(|byte| *byte != b'0')
            .map_or(&b""[..], |index| &exponent_digits[index..]);
        if significant.len() > 4 {
            return Err(Error::NumberExpansionLimit);
        }
        let magnitude = if significant.is_empty() {
            0_i64
        } else {
            std::str::from_utf8(significant)
                .expect("ASCII exponent digits are valid UTF-8")
                .parse::<i64>()
                .map_err(|_| Error::NumberExpansionLimit)?
        };
        exponent = if exponent_negative {
            -magnitude
        } else {
            magnitude
        };
    }

    if pos != bytes.len() {
        return Err(Error::InvalidDecimal);
    }

    let integer_digits = &bytes[integer_start..integer_end];
    let fraction_digits = &bytes[fraction_start..fraction_end];
    let mut digits = Vec::with_capacity(integer_digits.len() + fraction_digits.len());
    digits.extend_from_slice(integer_digits);
    digits.extend_from_slice(fraction_digits);

    let point = i64::try_from(integer_digits.len())
        .map_err(|_| Error::NumberExpansionLimit)?
        .checked_add(exponent)
        .ok_or(Error::NumberExpansionLimit)?;
    let digits_length = i64::try_from(digits.len()).map_err(|_| Error::NumberExpansionLimit)?;

    let expanded_digits = if point <= 0 {
        1_i64
            .checked_add(-point)
            .and_then(|count| count.checked_add(digits_length))
            .ok_or(Error::NumberExpansionLimit)?
    } else if point >= digits_length {
        point
    } else {
        digits_length
    };
    if expanded_digits > 1024_i64 {
        return Err(Error::NumberExpansionLimit);
    }

    let (raw_integer, fraction) = if point <= 0 {
        let zero_count = usize::try_from(-point).map_err(|_| Error::NumberExpansionLimit)?;
        let mut fraction = Vec::with_capacity(zero_count + digits.len());
        fraction.resize(zero_count, b'0');
        fraction.extend_from_slice(&digits);
        (vec![b'0'], fraction)
    } else if point >= digits_length {
        let zero_count =
            usize::try_from(point - digits_length).map_err(|_| Error::NumberExpansionLimit)?;
        let mut integer = digits.clone();
        integer.resize(integer.len() + zero_count, b'0');
        (integer, Vec::new())
    } else {
        let split = usize::try_from(point).map_err(|_| Error::NumberExpansionLimit)?;
        (digits[..split].to_vec(), digits[split..].to_vec())
    };

    let first_nonzero = raw_integer
        .iter()
        .position(|byte| *byte != b'0')
        .unwrap_or(raw_integer.len().saturating_sub(1));
    let integer = &raw_integer[first_nonzero..];
    let magnitude_is_zero = digits.iter().all(|byte| *byte == b'0');

    let mut out = String::new();
    if negative && !magnitude_is_zero {
        out.push('-');
    }
    out.push_str(std::str::from_utf8(integer).expect("ASCII digits are valid UTF-8"));
    if !fraction.is_empty() {
        out.push('.');
        out.push_str(std::str::from_utf8(&fraction).expect("ASCII digits are valid UTF-8"));
    }
    Ok(out)
}

/// Decode only the canonical RFC 4648 section 4 representation.
pub fn decode_canonical_base64(input: &str) -> Result<Vec<u8>> {
    if input.len() % 4 != 0
        || input.bytes().any(|byte| {
            !matches!(
                byte,
                b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'+' | b'/' | b'='
            )
        })
    {
        return Err(Error::InvalidBase64);
    }
    let decoded = STANDARD.decode(input).map_err(|_| Error::InvalidBase64)?;
    if STANDARD.encode(&decoded) != input {
        return Err(Error::InvalidBase64);
    }
    Ok(decoded)
}

pub(crate) fn parse_schema_nonnegative_u64(input: &str, maximum: u64) -> Option<u64> {
    match schema_nonnegative_integer_magnitude(input)? {
        IntegerMagnitude::Zero => Some(0),
        IntegerMagnitude::BeyondAddressableRange => None,
        IntegerMagnitude::Finite {
            significant_digits,
            trailing_zeros,
        } => {
            let mut value = 0_u64;
            for digit in significant_digits {
                value = value
                    .checked_mul(10)?
                    .checked_add(u64::from(digit - b'0'))?;
            }
            for _ in 0..trailing_zeros {
                value = value.checked_mul(10)?;
            }
            (value <= maximum).then_some(value)
        }
    }
}

pub(crate) fn is_schema_nonnegative_integer(input: &str) -> bool {
    schema_nonnegative_integer_magnitude(input).is_some()
}

fn schema_nonnegative_integer_magnitude(input: &str) -> Option<IntegerMagnitude> {
    let bytes = input.as_bytes();
    let mut position = 0;
    let negative = bytes.first() == Some(&b'-');
    if negative {
        position += 1;
    }

    let integer_start = position;
    match bytes.get(position) {
        Some(b'0') => {
            position += 1;
            if matches!(bytes.get(position), Some(b'0'..=b'9')) {
                return None;
            }
        }
        Some(b'1'..=b'9') => {
            position += 1;
            while matches!(bytes.get(position), Some(b'0'..=b'9')) {
                position += 1;
            }
        }
        _ => return None,
    }
    let integer_end = position;

    let mut fraction_start = position;
    let mut fraction_end = position;
    if bytes.get(position) == Some(&b'.') {
        position += 1;
        fraction_start = position;
        while matches!(bytes.get(position), Some(b'0'..=b'9')) {
            position += 1;
        }
        fraction_end = position;
        if fraction_start == fraction_end {
            return None;
        }
    }

    let mut exponent_negative = false;
    let mut exponent_digits = &b""[..];
    if matches!(bytes.get(position), Some(b'e' | b'E')) {
        position += 1;
        exponent_negative = bytes.get(position) == Some(&b'-');
        if matches!(bytes.get(position), Some(b'+' | b'-')) {
            position += 1;
        }
        let start = position;
        while matches!(bytes.get(position), Some(b'0'..=b'9')) {
            position += 1;
        }
        if start == position {
            return None;
        }
        exponent_digits = &bytes[start..position];
    }
    if position != bytes.len() {
        return None;
    }

    let mut digits =
        Vec::with_capacity((integer_end - integer_start) + (fraction_end - fraction_start));
    digits.extend_from_slice(&bytes[integer_start..integer_end]);
    digits.extend_from_slice(&bytes[fraction_start..fraction_end]);
    let magnitude_is_zero = digits.iter().all(|digit| *digit == b'0');
    if magnitude_is_zero {
        return Some(IntegerMagnitude::Zero);
    }
    if negative {
        return None;
    }

    let exponent_digits = exponent_digits
        .iter()
        .position(|digit| *digit != b'0')
        .map_or(&b""[..], |first| &exponent_digits[first..]);
    let exponent = if exponent_digits.is_empty() {
        Some(0_i128)
    } else if exponent_digits.len() > 38 {
        None
    } else {
        let magnitude = std::str::from_utf8(exponent_digits)
            .ok()?
            .parse::<i128>()
            .ok()?;
        Some(if exponent_negative {
            -magnitude
        } else {
            magnitude
        })
    };
    let Some(exponent) = exponent else {
        return if exponent_negative {
            None
        } else {
            Some(IntegerMagnitude::BeyondAddressableRange)
        };
    };
    let fraction_length = i128::try_from(fraction_end - fraction_start).ok()?;
    let shift = exponent.checked_sub(fraction_length)?;
    let (kept_digits, trailing_zeros) = if shift >= 0 {
        let trailing_zeros = usize::try_from(shift).ok();
        let Some(trailing_zeros) = trailing_zeros else {
            return Some(IntegerMagnitude::BeyondAddressableRange);
        };
        (digits.as_slice(), trailing_zeros)
    } else {
        let removed = usize::try_from(-shift).ok()?;
        if removed > digits.len()
            || digits[digits.len() - removed..]
                .iter()
                .any(|digit| *digit != b'0')
        {
            return None;
        }
        (&digits[..digits.len() - removed], 0)
    };
    let first_nonzero = kept_digits
        .iter()
        .position(|digit| *digit != b'0')
        .unwrap_or(kept_digits.len());
    Some(IntegerMagnitude::Finite {
        significant_digits: kept_digits[first_nonzero..].to_vec(),
        trailing_zeros,
    })
}

#[cfg(test)]
mod tests {
    use super::{
        canonical_decimal, canonical_integer, decode_canonical_base64,
        is_schema_nonnegative_integer, parse_schema_nonnegative_u64,
    };

    #[test]
    fn decimal_examples_from_specification() {
        let cases = [
            ("1e2", "100"),
            ("1.0e2", "100"),
            ("1.00e1", "10.0"),
            ("1.5e-2", "0.015"),
            ("1e-3", "0.001"),
            ("0e5", "0"),
            ("0.010", "0.010"),
            ("-0.00", "0.00"),
        ];
        for (input, expected) in cases {
            assert_eq!(canonical_decimal(input).unwrap(), expected);
        }
    }

    #[test]
    fn integer_minus_zero_normalizes() {
        assert_eq!(canonical_integer("-0").unwrap(), "0");
    }

    #[test]
    fn base64_requires_canonical_padding_and_trailing_bits() {
        assert_eq!(decode_canonical_base64("Zg==").unwrap(), b"f");
        assert!(decode_canonical_base64("Zg").is_err());
        assert!(decode_canonical_base64("Zh==").is_err());
    }

    #[test]
    fn schema_integer_tokens_are_evaluated_without_floating_point() {
        for (literal, expected) in [
            ("6", Some(6)),
            ("6.0", Some(6)),
            ("6e0", Some(6)),
            ("10e-1", Some(1)),
            ("1.20e2", Some(120)),
            ("-0.0e999999999999999999999", Some(0)),
            ("12e-1", None),
            ("-1", None),
            ("18446744073709551616", None),
        ] {
            assert_eq!(
                parse_schema_nonnegative_u64(literal, u64::MAX),
                expected,
                "{literal}"
            );
        }
        assert!(is_schema_nonnegative_integer(
            "1e999999999999999999999999999"
        ));
        assert!(!is_schema_nonnegative_integer(
            "1e-999999999999999999999999999"
        ));
    }
}
