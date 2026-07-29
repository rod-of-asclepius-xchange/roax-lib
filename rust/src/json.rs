use crate::error::{Error, Result};
use std::collections::HashSet;
use std::fmt;

/// Literal-preserving JSON tree used for record data.
///
/// Numeric tokens remain their original source strings.
#[derive(Eq)]
pub enum JsonValue {
    Object(Vec<(String, Self)>),
    Array(Vec<Self>),
    String(String),
    Number(String),
    Bool(bool),
    Null,
}

impl PartialEq for JsonValue {
    fn eq(&self, other: &Self) -> bool {
        let mut pending = vec![(self, other)];
        while let Some((left, right)) = pending.pop() {
            match (left, right) {
                (Self::Object(left), Self::Object(right)) => {
                    if left.len() != right.len() {
                        return false;
                    }
                    for ((left_key, left_value), (right_key, right_value)) in left.iter().zip(right)
                    {
                        if left_key != right_key {
                            return false;
                        }
                        pending.push((left_value, right_value));
                    }
                }
                (Self::Array(left), Self::Array(right)) => {
                    if left.len() != right.len() {
                        return false;
                    }
                    pending.extend(left.iter().zip(right));
                }
                (Self::String(left), Self::String(right))
                | (Self::Number(left), Self::Number(right)) => {
                    if left != right {
                        return false;
                    }
                }
                (Self::Bool(left), Self::Bool(right)) => {
                    if left != right {
                        return false;
                    }
                }
                (Self::Null, Self::Null) => {}
                _ => return false,
            }
        }
        true
    }
}

impl fmt::Debug for JsonValue {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let mut pending = vec![DebugFrame::Value(self)];
        while let Some(frame) = pending.pop() {
            frame.write(f, &mut pending)?;
        }
        Ok(())
    }
}

enum DebugFrame<'a> {
    Value(&'a JsonValue),
    Array(&'a [JsonValue], usize),
    Object(&'a [(String, JsonValue)], usize),
    Literal(&'static str),
}

impl<'a> DebugFrame<'a> {
    fn write(self, f: &mut fmt::Formatter<'_>, pending: &mut Vec<Self>) -> fmt::Result {
        match self {
            Self::Value(value) => Self::write_value(value, f, pending),
            Self::Array(values, index) => Self::write_array(values, index, f, pending),
            Self::Object(entries, index) => Self::write_object(entries, index, f, pending),
            Self::Literal(text) => f.write_str(text),
        }
    }

    fn write_value(
        value: &'a JsonValue,
        f: &mut fmt::Formatter<'_>,
        pending: &mut Vec<Self>,
    ) -> fmt::Result {
        match value {
            JsonValue::Object(entries) => {
                f.write_str("Object([")?;
                pending.push(Self::Object(entries, 0));
                Ok(())
            }
            JsonValue::Array(values) => {
                f.write_str("Array([")?;
                pending.push(Self::Array(values, 0));
                Ok(())
            }
            JsonValue::String(value) => write!(f, "String({value:?})"),
            JsonValue::Number(literal) => write!(f, "Number({literal:?})"),
            JsonValue::Bool(value) => write!(f, "Bool({value:?})"),
            JsonValue::Null => f.write_str("Null"),
        }
    }

    fn write_array(
        values: &'a [JsonValue],
        index: usize,
        f: &mut fmt::Formatter<'_>,
        pending: &mut Vec<Self>,
    ) -> fmt::Result {
        let Some(value) = values.get(index) else {
            return f.write_str("])");
        };
        if index != 0 {
            f.write_str(", ")?;
        }
        pending.push(Self::Array(values, index + 1));
        pending.push(Self::Value(value));
        Ok(())
    }

    fn write_object(
        entries: &'a [(String, JsonValue)],
        index: usize,
        f: &mut fmt::Formatter<'_>,
        pending: &mut Vec<Self>,
    ) -> fmt::Result {
        let Some((key, value)) = entries.get(index) else {
            return f.write_str("])");
        };
        if index != 0 {
            f.write_str(", ")?;
        }
        write!(f, "({key:?}, ")?;
        pending.push(Self::Object(entries, index + 1));
        pending.push(Self::Literal(")"));
        pending.push(Self::Value(value));
        Ok(())
    }
}

impl Clone for JsonValue {
    fn clone(&self) -> Self {
        let mut parents = Vec::new();
        let mut source = self;

        loop {
            let mut cloned = match source {
                Self::Object(entries) if !entries.is_empty() => {
                    parents.push(CloneParent::Object {
                        source: entries,
                        next_index: 1,
                        cloned: Vec::with_capacity(entries.len()),
                    });
                    source = &entries[0].1;
                    continue;
                }
                Self::Array(values) if !values.is_empty() => {
                    parents.push(CloneParent::Array {
                        source: values,
                        next_index: 1,
                        cloned: Vec::with_capacity(values.len()),
                    });
                    source = &values[0];
                    continue;
                }
                Self::Object(_) => Self::Object(Vec::new()),
                Self::Array(_) => Self::Array(Vec::new()),
                Self::String(value) => Self::String(value.clone()),
                Self::Number(literal) => Self::Number(literal.clone()),
                Self::Bool(value) => Self::Bool(*value),
                Self::Null => Self::Null,
            };

            loop {
                let Some(parent) = parents.last_mut() else {
                    return cloned;
                };
                if let Some(next_source) = parent.attach(cloned) {
                    source = next_source;
                    break;
                }
                cloned = parents
                    .pop()
                    .expect("the completed clone parent is present")
                    .finish();
            }
        }
    }
}

enum CloneParent<'a> {
    Object {
        source: &'a [(String, JsonValue)],
        next_index: usize,
        cloned: Vec<(String, JsonValue)>,
    },
    Array {
        source: &'a [JsonValue],
        next_index: usize,
        cloned: Vec<JsonValue>,
    },
}

impl<'a> CloneParent<'a> {
    fn attach(&mut self, value: JsonValue) -> Option<&'a JsonValue> {
        match self {
            Self::Object {
                source,
                next_index,
                cloned,
            } => {
                let key = source[cloned.len()].0.clone();
                cloned.push((key, value));
                let next = source.get(*next_index).map(|(_, value)| value);
                *next_index += usize::from(next.is_some());
                next
            }
            Self::Array {
                source,
                next_index,
                cloned,
            } => {
                cloned.push(value);
                let next = source.get(*next_index);
                *next_index += usize::from(next.is_some());
                next
            }
        }
    }

    fn finish(self) -> JsonValue {
        match self {
            Self::Object { cloned, .. } => JsonValue::Object(cloned),
            Self::Array { cloned, .. } => JsonValue::Array(cloned),
        }
    }
}

impl Drop for JsonValue {
    fn drop(&mut self) {
        let mut pending = Vec::new();
        take_nested_values(self, &mut pending);
        while let Some(mut value) = pending.pop() {
            take_nested_values(&mut value, &mut pending);
        }
    }
}

fn take_nested_values(value: &mut JsonValue, pending: &mut Vec<JsonValue>) {
    match value {
        JsonValue::Object(entries) => {
            for (_, child) in std::mem::take(entries) {
                pending.push(child);
            }
        }
        JsonValue::Array(values) => pending.extend(std::mem::take(values)),
        JsonValue::String(_) | JsonValue::Number(_) | JsonValue::Bool(_) | JsonValue::Null => {}
    }
}

impl JsonValue {
    /// Parse one strict UTF-8 JSON value while preserving every numeric token.
    ///
    /// # Errors
    ///
    /// Returns an error when the input is not UTF-8 or is not one strict JSON value.
    pub fn from_slice(input: &[u8]) -> Result<Self> {
        let text =
            std::str::from_utf8(input).map_err(|error| Error::InvalidUtf8(error.to_string()))?;
        Self::from_str(text)
    }

    /// Parse one strict JSON value while preserving every numeric token.
    ///
    /// # Errors
    ///
    /// Returns an error when the input is not one strict JSON value.
    #[allow(clippy::should_implement_trait)]
    pub fn from_str(input: &str) -> Result<Self> {
        let mut parser = Parser::new(input);
        let value = parser.parse_value()?;
        parser.skip_whitespace();
        if parser.pos != parser.bytes.len() {
            return Err(Error::TrailingJsonData);
        }
        value.validate()?;
        Ok(value)
    }

    /// Check invariants that public enum constructors cannot enforce.
    ///
    /// # Errors
    ///
    /// Returns [`Error::DuplicateKey`] for a repeated key in any object and
    /// [`Error::InvalidJson`] for a `Number` that is not one complete JSON number token.
    pub fn validate(&self) -> Result<()> {
        let mut pending = vec![self];
        while let Some(value) = pending.pop() {
            match value {
                Self::Object(entries) => {
                    let mut keys = HashSet::with_capacity(entries.len());
                    for (key, child) in entries {
                        if !keys.insert(key) {
                            return Err(Error::DuplicateKey { key: key.clone() });
                        }
                        pending.push(child);
                    }
                }
                Self::Array(values) => pending.extend(values),
                Self::Number(literal) => validate_number_literal(literal)?,
                Self::String(_) | Self::Bool(_) | Self::Null => {}
            }
        }
        Ok(())
    }

    /// Serialize without changing numeric literals.
    #[must_use]
    pub fn to_json_string(&self) -> String {
        let mut out = String::new();
        self.write_json(&mut out);
        out
    }

    fn write_json(&self, out: &mut String) {
        let mut pending = vec![WriteFrame::Value(self)];
        while let Some(frame) = pending.pop() {
            frame.write(out, &mut pending);
        }
    }

    #[must_use]
    pub fn as_object(&self) -> Option<&[(String, Self)]> {
        if let Self::Object(value) = self {
            Some(value)
        } else {
            None
        }
    }
}

enum WriteFrame<'a> {
    Value(&'a JsonValue),
    Array(&'a [JsonValue], usize),
    Object(&'a [(String, JsonValue)], usize),
}

impl<'a> WriteFrame<'a> {
    fn write(self, out: &mut String, pending: &mut Vec<Self>) {
        match self {
            Self::Value(value) => Self::write_value(value, out, pending),
            Self::Array(values, index) => Self::write_array(values, index, out, pending),
            Self::Object(entries, index) => Self::write_object(entries, index, out, pending),
        }
    }

    fn write_value(value: &'a JsonValue, out: &mut String, pending: &mut Vec<Self>) {
        match value {
            JsonValue::Object(entries) => {
                out.push('{');
                pending.push(Self::Object(entries, 0));
            }
            JsonValue::Array(values) => {
                out.push('[');
                pending.push(Self::Array(values, 0));
            }
            JsonValue::String(value) => write_string(value, out),
            JsonValue::Number(literal) => out.push_str(literal),
            JsonValue::Bool(value) => out.push_str(if *value { "true" } else { "false" }),
            JsonValue::Null => out.push_str("null"),
        }
    }

    fn write_array(
        values: &'a [JsonValue],
        index: usize,
        out: &mut String,
        pending: &mut Vec<Self>,
    ) {
        let Some(value) = values.get(index) else {
            out.push(']');
            return;
        };
        if index != 0 {
            out.push(',');
        }
        pending.push(Self::Array(values, index + 1));
        pending.push(Self::Value(value));
    }

    fn write_object(
        entries: &'a [(String, JsonValue)],
        index: usize,
        out: &mut String,
        pending: &mut Vec<Self>,
    ) {
        let Some((key, value)) = entries.get(index) else {
            out.push('}');
            return;
        };
        if index != 0 {
            out.push(',');
        }
        write_string(key, out);
        out.push(':');
        pending.push(Self::Object(entries, index + 1));
        pending.push(Self::Value(value));
    }
}

fn write_string(value: &str, out: &mut String) {
    out.push_str(&serde_json::to_string(value).expect("serializing a Rust string cannot fail"));
}

fn validate_number_literal(literal: &str) -> Result<()> {
    let mut parser = Parser::new(literal);
    parser.parse_number()?;
    if parser.pos == parser.bytes.len() {
        Ok(())
    } else {
        Err(parser.error("invalid trailing byte in number literal"))
    }
}

enum ContainerFrame {
    Object {
        entries: Vec<(String, JsonValue)>,
        keys: HashSet<String>,
        pending_key: String,
    },
    Array(Vec<JsonValue>),
}

impl ContainerFrame {
    fn into_value(self) -> JsonValue {
        match self {
            Self::Object { entries, .. } => JsonValue::Object(entries),
            Self::Array(values) => JsonValue::Array(values),
        }
    }
}

struct Parser<'a> {
    input: &'a str,
    bytes: &'a [u8],
    pos: usize,
}

impl<'a> Parser<'a> {
    const fn new(input: &'a str) -> Self {
        Self {
            input,
            bytes: input.as_bytes(),
            pos: 0,
        }
    }

    fn error(&self, message: impl Into<String>) -> Error {
        Error::InvalidJson {
            offset: self.pos,
            message: message.into(),
        }
    }

    fn skip_whitespace(&mut self) {
        while matches!(self.bytes.get(self.pos), Some(b' ' | b'\t' | b'\r' | b'\n')) {
            self.pos += 1;
        }
    }

    fn parse_value(&mut self) -> Result<JsonValue> {
        let mut containers = Vec::new();
        let mut completed = self.parse_value_start(&mut containers)?;
        loop {
            let Some(value) = completed.take() else {
                completed = self.parse_value_start(&mut containers)?;
                continue;
            };
            if containers.is_empty() {
                return Ok(value);
            }
            completed = self.attach_value(&mut containers, value)?;
        }
    }

    fn parse_value_start(
        &mut self,
        containers: &mut Vec<ContainerFrame>,
    ) -> Result<Option<JsonValue>> {
        self.skip_whitespace();
        match self.bytes.get(self.pos).copied() {
            Some(b'{') => self.start_object(containers),
            Some(b'[') => Ok(self.start_array(containers)),
            Some(b'"') => self.parse_string().map(JsonValue::String).map(Some),
            Some(b't') => {
                self.expect_keyword("true")?;
                Ok(Some(JsonValue::Bool(true)))
            }
            Some(b'f') => {
                self.expect_keyword("false")?;
                Ok(Some(JsonValue::Bool(false)))
            }
            Some(b'n') => {
                self.expect_keyword("null")?;
                Ok(Some(JsonValue::Null))
            }
            Some(b'-' | b'0'..=b'9') => self.parse_number().map(JsonValue::Number).map(Some),
            Some(_) => Err(self.error("unexpected token")),
            None => Err(self.error("unexpected end of input")),
        }
    }

    fn start_object(&mut self, containers: &mut Vec<ContainerFrame>) -> Result<Option<JsonValue>> {
        self.pos += 1;
        self.skip_whitespace();
        if self.consume(b'}') {
            return Ok(Some(JsonValue::Object(Vec::new())));
        }
        let mut keys = HashSet::new();
        let pending_key = self.parse_object_key(&mut keys)?;
        containers.push(ContainerFrame::Object {
            entries: Vec::new(),
            keys,
            pending_key,
        });
        Ok(None)
    }

    fn start_array(&mut self, containers: &mut Vec<ContainerFrame>) -> Option<JsonValue> {
        self.pos += 1;
        self.skip_whitespace();
        if self.consume(b']') {
            Some(JsonValue::Array(Vec::new()))
        } else {
            containers.push(ContainerFrame::Array(Vec::new()));
            None
        }
    }

    fn attach_value(
        &mut self,
        containers: &mut Vec<ContainerFrame>,
        value: JsonValue,
    ) -> Result<Option<JsonValue>> {
        let close = match containers
            .last_mut()
            .expect("a completed child must have a parent container")
        {
            ContainerFrame::Array(values) => {
                values.push(value);
                self.skip_whitespace();
                if self.consume(b']') {
                    true
                } else {
                    self.expect_byte(b',')?;
                    false
                }
            }
            ContainerFrame::Object {
                entries,
                keys,
                pending_key,
            } => {
                entries.push((std::mem::take(pending_key), value));
                self.skip_whitespace();
                if self.consume(b'}') {
                    true
                } else {
                    self.expect_byte(b',')?;
                    *pending_key = self.parse_object_key(keys)?;
                    false
                }
            }
        };

        if close {
            Ok(Some(
                containers
                    .pop()
                    .expect("the completed container is present")
                    .into_value(),
            ))
        } else {
            Ok(None)
        }
    }

    fn parse_object_key(&mut self, keys: &mut HashSet<String>) -> Result<String> {
        self.skip_whitespace();
        if self.bytes.get(self.pos) != Some(&b'"') {
            return Err(self.error("object key must be a string"));
        }
        let key = self.parse_string()?;
        if !keys.insert(key.clone()) {
            return Err(Error::DuplicateKey { key });
        }
        self.skip_whitespace();
        self.expect_byte(b':')?;
        Ok(key)
    }

    fn expect_keyword(&mut self, keyword: &str) -> Result<()> {
        if self.bytes.get(self.pos..self.pos + keyword.len()) == Some(keyword.as_bytes()) {
            self.pos += keyword.len();
            Ok(())
        } else {
            Err(self.error(format!("expected {keyword}")))
        }
    }

    fn parse_string(&mut self) -> Result<String> {
        self.expect_byte(b'"')?;
        let mut out = String::new();
        let mut chunk_start = self.pos;

        loop {
            let byte = *self
                .bytes
                .get(self.pos)
                .ok_or_else(|| self.error("unterminated string"))?;
            match byte {
                b'"' => {
                    out.push_str(&self.input[chunk_start..self.pos]);
                    self.pos += 1;
                    return Ok(out);
                }
                b'\\' => {
                    out.push_str(&self.input[chunk_start..self.pos]);
                    self.pos += 1;
                    let escape = *self
                        .bytes
                        .get(self.pos)
                        .ok_or_else(|| self.error("unterminated escape"))?;
                    self.pos += 1;
                    match escape {
                        b'"' => out.push('"'),
                        b'\\' => out.push('\\'),
                        b'/' => out.push('/'),
                        b'b' => out.push('\u{0008}'),
                        b'f' => out.push('\u{000c}'),
                        b'n' => out.push('\n'),
                        b'r' => out.push('\r'),
                        b't' => out.push('\t'),
                        b'u' => {
                            let first = self.parse_hex_quad()?;
                            if (0xd800..=0xdbff).contains(&first) {
                                if self.bytes.get(self.pos..self.pos + 2) != Some(b"\\u") {
                                    return Err(Error::UnpairedSurrogate);
                                }
                                self.pos += 2;
                                let second = self.parse_hex_quad()?;
                                if !(0xdc00..=0xdfff).contains(&second) {
                                    return Err(Error::UnpairedSurrogate);
                                }
                                let scalar = 0x1_0000
                                    + ((u32::from(first) - 0xd800) << 10)
                                    + (u32::from(second) - 0xdc00);
                                out.push(char::from_u32(scalar).ok_or(Error::UnpairedSurrogate)?);
                            } else if (0xdc00..=0xdfff).contains(&first) {
                                return Err(Error::UnpairedSurrogate);
                            } else {
                                out.push(
                                    char::from_u32(u32::from(first))
                                        .ok_or(Error::UnpairedSurrogate)?,
                                );
                            }
                        }
                        _ => return Err(self.error("invalid string escape")),
                    }
                    chunk_start = self.pos;
                }
                0x00..=0x1f => return Err(self.error("unescaped control character in string")),
                _ => {
                    let char_len = self.input[self.pos..]
                        .chars()
                        .next()
                        .expect("the input is valid UTF-8")
                        .len_utf8();
                    self.pos += char_len;
                }
            }
        }
    }

    fn parse_hex_quad(&mut self) -> Result<u16> {
        let end = self
            .pos
            .checked_add(4)
            .ok_or_else(|| self.error("Unicode escape overflow"))?;
        let bytes = self
            .bytes
            .get(self.pos..end)
            .ok_or_else(|| self.error("short Unicode escape"))?;
        let mut value = 0_u16;
        for byte in bytes {
            value = value
                .checked_mul(16)
                .expect("four hexadecimal digits fit in u16");
            value += match byte {
                b'0'..=b'9' => u16::from(byte - b'0'),
                b'a'..=b'f' => u16::from(byte - b'a' + 10),
                b'A'..=b'F' => u16::from(byte - b'A' + 10),
                _ => return Err(self.error("invalid Unicode escape")),
            };
        }
        self.pos = end;
        Ok(value)
    }

    fn parse_number(&mut self) -> Result<String> {
        let start = self.pos;
        self.consume(b'-');

        match self.bytes.get(self.pos).copied() {
            Some(b'0') => {
                self.pos += 1;
                if matches!(self.bytes.get(self.pos), Some(b'0'..=b'9')) {
                    return Err(self.error("leading zero in number"));
                }
            }
            Some(b'1'..=b'9') => {
                self.pos += 1;
                while matches!(self.bytes.get(self.pos), Some(b'0'..=b'9')) {
                    self.pos += 1;
                }
            }
            _ => return Err(self.error("invalid number integer part")),
        }

        if self.consume(b'.') {
            let fraction_start = self.pos;
            while matches!(self.bytes.get(self.pos), Some(b'0'..=b'9')) {
                self.pos += 1;
            }
            if self.pos == fraction_start {
                return Err(self.error("fraction requires a digit"));
            }
        }

        if matches!(self.bytes.get(self.pos), Some(b'e' | b'E')) {
            self.pos += 1;
            if matches!(self.bytes.get(self.pos), Some(b'+' | b'-')) {
                self.pos += 1;
            }
            let exponent_start = self.pos;
            while matches!(self.bytes.get(self.pos), Some(b'0'..=b'9')) {
                self.pos += 1;
            }
            if self.pos == exponent_start {
                return Err(self.error("exponent requires a digit"));
            }
        }

        Ok(self.input[start..self.pos].to_owned())
    }

    fn consume(&mut self, byte: u8) -> bool {
        if self.bytes.get(self.pos) == Some(&byte) {
            self.pos += 1;
            true
        } else {
            false
        }
    }

    fn expect_byte(&mut self, byte: u8) -> Result<()> {
        if self.consume(byte) {
            Ok(())
        } else {
            Err(self.error(format!("expected byte 0x{byte:02x}")))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::JsonValue;
    use crate::Error;

    const DEEP_ARRAY_NESTING: usize = 20_000;
    const DEEP_OBJECT_NESTING: usize = 10_000;

    #[test]
    fn debug_renders_every_variant() {
        let value = JsonValue::Object(vec![
            (
                "a".to_owned(),
                JsonValue::Array(vec![
                    JsonValue::Null,
                    JsonValue::Bool(true),
                    JsonValue::Number("1.0".to_owned()),
                ]),
            ),
            ("b".to_owned(), JsonValue::String("x\"y".to_owned())),
            ("c".to_owned(), JsonValue::Object(Vec::new())),
        ]);
        assert_eq!(
            format!("{value:?}"),
            r#"Object([("a", Array([Null, Bool(true), Number("1.0")])), ("b", String("x\"y")), ("c", Object([]))])"#
        );
    }

    #[test]
    fn deeply_nested_values_are_compared_and_formatted_iteratively() {
        let arrays = format!(
            "{}0{}",
            "[".repeat(DEEP_ARRAY_NESTING),
            "]".repeat(DEEP_ARRAY_NESTING)
        );
        let objects = format!(
            "{}null{}",
            "{\"key\":".repeat(DEEP_OBJECT_NESTING),
            "}".repeat(DEEP_OBJECT_NESTING)
        );
        for input in [arrays, objects] {
            let value = JsonValue::from_str(&input).expect("deep input must parse");
            let cloned = value.clone();
            assert!(value == cloned);
            assert!(!format!("{value:?}").is_empty());
            assert!(value != JsonValue::Null);
        }
    }

    #[test]
    fn deeply_nested_arrays_parse_serialize_and_drop_iteratively() {
        let input = format!(
            "{}0{}",
            "[".repeat(DEEP_ARRAY_NESTING),
            "]".repeat(DEEP_ARRAY_NESTING)
        );
        let value = JsonValue::from_str(&input).expect("deep arrays must parse");
        assert_eq!(value.to_json_string(), input);
        let cloned = value.clone();
        assert_eq!(cloned.to_json_string(), input);
        drop(cloned);
        drop(value);
    }

    #[test]
    fn deeply_nested_objects_parse_serialize_and_drop_iteratively() {
        let input = format!(
            "{}null{}",
            "{\"key\":".repeat(DEEP_OBJECT_NESTING),
            "}".repeat(DEEP_OBJECT_NESTING)
        );
        let value = JsonValue::from_str(&input).expect("deep objects must parse");
        assert_eq!(value.to_json_string(), input);
        let cloned = value.clone();
        assert_eq!(cloned.to_json_string(), input);
        drop(cloned);
        drop(value);
    }

    #[test]
    fn deeply_nested_partial_value_is_dropped_iteratively_after_an_error() {
        let input = format!(
            "{}0{}",
            "[".repeat(DEEP_ARRAY_NESTING),
            "]".repeat(DEEP_ARRAY_NESTING - 1)
        );
        assert!(matches!(
            JsonValue::from_str(&input),
            Err(Error::InvalidJson { .. })
        ));
    }

    #[test]
    fn duplicate_keys_are_compared_after_escape_decoding() {
        assert_eq!(
            JsonValue::from_str(r#"{"key":0,"\u006bey":1}"#),
            Err(Error::DuplicateKey {
                key: "key".to_owned(),
            })
        );
    }

    #[test]
    fn validate_rejects_duplicate_keys_in_constructed_trees() {
        let value = JsonValue::Array(vec![JsonValue::Object(vec![
            ("key".to_owned(), JsonValue::Null),
            ("key".to_owned(), JsonValue::Bool(true)),
        ])]);
        assert_eq!(
            value.validate(),
            Err(Error::DuplicateKey {
                key: "key".to_owned(),
            })
        );
    }

    #[test]
    fn validate_rejects_invalid_constructed_number_literals() {
        for literal in ["", "+1", "01", "1.", "1e", "1x", "NaN", " 1"] {
            let value = JsonValue::Number(literal.to_owned());
            assert!(
                matches!(value.validate(), Err(Error::InvalidJson { .. })),
                "{literal:?} must not be a JSON number token"
            );
        }
        for literal in ["0", "-0", "1.2300", "1e+09", "-12.5E-2"] {
            JsonValue::Number(literal.to_owned())
                .validate()
                .unwrap_or_else(|error| panic!("{literal:?} must be valid: {error}"));
        }
    }

    #[test]
    fn clone_preserves_constructed_values_without_reparsing_them() {
        let value = JsonValue::Object(vec![
            ("duplicate".to_owned(), JsonValue::Number("+1".to_owned())),
            ("duplicate".to_owned(), JsonValue::Array(Vec::new())),
        ]);
        let cloned = value.clone();
        assert_eq!(cloned, value);
    }

    #[test]
    fn surrogate_pairs_are_combined_and_unpaired_units_are_rejected() {
        assert_eq!(
            JsonValue::from_str(r#""\uD83D\uDE00""#),
            Ok(JsonValue::String("\u{1f600}".to_owned()))
        );
        for input in [r#""\uD800""#, r#""\uDC00""#, r#""\uD800\u0041""#] {
            assert_eq!(JsonValue::from_str(input), Err(Error::UnpairedSurrogate));
        }
    }
}
