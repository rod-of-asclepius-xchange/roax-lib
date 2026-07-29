use crate::error::{Error, Result};
use std::fmt;
use unicode_normalization::UnicodeNormalization;

/// One authoritative structured path segment.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum Segment {
    Key(String),
    Index(u32),
}

/// An authoritative path. Display strings are intentionally not parseable.
#[derive(Clone, Debug, Default, PartialEq, Eq, Hash)]
pub struct Path(Vec<Segment>);

impl Path {
    #[must_use]
    pub const fn new() -> Self {
        Self(Vec::new())
    }

    #[must_use]
    pub fn from_segments(segments: Vec<Segment>) -> Self {
        Self(segments)
    }

    #[must_use]
    pub fn segments(&self) -> &[Segment] {
        &self.0
    }

    #[must_use]
    pub fn into_segments(self) -> Vec<Segment> {
        self.0
    }

    #[must_use]
    pub fn with_key(&self, key: impl Into<String>) -> Self {
        let mut segments = self.0.clone();
        segments.push(Segment::Key(key.into()));
        Self(segments)
    }

    #[must_use]
    pub fn with_index(&self, index: u32) -> Self {
        let mut segments = self.0.clone();
        segments.push(Segment::Index(index));
        Self(segments)
    }

    /// Encode the authoritative structured path.
    pub fn encode(&self) -> Result<Vec<u8>> {
        let count = u32::try_from(self.0.len())
            .map_err(|_| Error::InvalidPath("more than 2^32-1 path segments".into()))?;
        let mut out = Vec::new();
        out.extend_from_slice(&count.to_be_bytes());

        for segment in &self.0 {
            match segment {
                Segment::Key(key) => {
                    let normalized: String = key.nfc().collect();
                    let bytes = normalized.as_bytes();
                    let length = u32::try_from(bytes.len()).map_err(|_| {
                        Error::InvalidPath("UTF-8 key is longer than 2^32-1 bytes".into())
                    })?;
                    out.push(0x01);
                    out.extend_from_slice(&length.to_be_bytes());
                    out.extend_from_slice(bytes);
                }
                Segment::Index(index) => {
                    out.push(0x02);
                    out.extend_from_slice(&index.to_be_bytes());
                }
            }
        }

        Ok(out)
    }

    /// Render a non-authoritative path for diagnostics and user interfaces.
    #[must_use]
    pub fn display(&self) -> String {
        let mut rendered = String::new();
        for segment in &self.0 {
            match segment {
                Segment::Key(key) => {
                    if !rendered.is_empty() {
                        rendered.push('.');
                    }
                    rendered.push_str(key);
                }
                Segment::Index(index) => {
                    rendered.push('[');
                    rendered.push_str(&index.to_string());
                    rendered.push(']');
                }
            }
        }
        rendered
    }

    #[must_use]
    pub fn normalized(&self) -> Self {
        Self(
            self.0
                .iter()
                .map(|segment| match segment {
                    Segment::Key(key) => Segment::Key(key.nfc().collect()),
                    Segment::Index(index) => Segment::Index(*index),
                })
                .collect(),
        )
    }
}

impl From<Vec<Segment>> for Path {
    fn from(value: Vec<Segment>) -> Self {
        Self::from_segments(value)
    }
}

impl fmt::Display for Path {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.display())
    }
}
