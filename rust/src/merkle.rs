use crate::error::{Error, Result};
use sha2::{Digest, Sha256};

pub type Hash = [u8; 32];

/// RFC 9162 internal-node hash.
#[must_use]
pub fn node_hash(left: &Hash, right: &Hash) -> Hash {
    let mut hasher = Sha256::new();
    hasher.update([0x01]);
    hasher.update(left);
    hasher.update(right);
    hasher.finalize().into()
}

/// RFC 9162 Merkle Tree Hash over already-hashed, already-domain-separated leaves.
#[must_use]
pub fn merkle_tree_hash(leaves: &[Hash]) -> Hash {
    match leaves {
        [] => Sha256::digest([]).into(),
        [leaf] => *leaf,
        _ => {
            let split = largest_power_of_two_less_than(leaves.len());
            node_hash(
                &merkle_tree_hash(&leaves[..split]),
                &merkle_tree_hash(&leaves[split..]),
            )
        }
    }
}

/// Generate the root-ward RFC 9162 audit path for one leaf.
pub fn audit_path(leaves: &[Hash], index: usize) -> Result<Vec<Hash>> {
    if leaves.is_empty() || index >= leaves.len() {
        return Err(Error::InvalidLeafIndex);
    }
    Ok(audit_path_inner(leaves, index))
}

fn audit_path_inner(leaves: &[Hash], index: usize) -> Vec<Hash> {
    if leaves.len() == 1 {
        return Vec::new();
    }
    let split = largest_power_of_two_less_than(leaves.len());
    if index < split {
        let mut proof = audit_path_inner(&leaves[..split], index);
        proof.push(merkle_tree_hash(&leaves[split..]));
        proof
    } else {
        let mut proof = audit_path_inner(&leaves[split..], index - split);
        proof.push(merkle_tree_hash(&leaves[..split]));
        proof
    }
}

/// Fold an RFC 9162 inclusion proof over an already-hashed, untrusted value.
///
/// A successful fold is not ROAX disclosure verification.
/// Both the hash and tree size are caller inputs, so an internal node can pass
/// as a leaf under a forged size.
/// Use `verify_disclosed` for the protocol verification boundary.
#[must_use]
pub fn fold_inclusion_proof_untrusted(
    leaf: &Hash,
    index: u64,
    tree_size: u64,
    proof: &[Hash],
    expected_root: &Hash,
) -> bool {
    if tree_size == 0 || index >= tree_size {
        return false;
    }
    let mut proof_index = 0;
    let Some(root) = reconstruct_root(leaf, index, tree_size, proof, &mut proof_index) else {
        return false;
    };
    proof_index == proof.len() && root == *expected_root
}

fn reconstruct_root(
    leaf: &Hash,
    index: u64,
    tree_size: u64,
    proof: &[Hash],
    proof_index: &mut usize,
) -> Option<Hash> {
    if tree_size == 1 {
        return Some(*leaf);
    }
    let split = largest_power_of_two_less_than_u64(tree_size);
    if index < split {
        let left = reconstruct_root(leaf, index, split, proof, proof_index)?;
        let right = *proof.get(*proof_index)?;
        *proof_index += 1;
        Some(node_hash(&left, &right))
    } else {
        let right = reconstruct_root(leaf, index - split, tree_size - split, proof, proof_index)?;
        let left = *proof.get(*proof_index)?;
        *proof_index += 1;
        Some(node_hash(&left, &right))
    }
}

fn largest_power_of_two_less_than(value: usize) -> usize {
    debug_assert!(value > 1);
    if value.is_power_of_two() {
        value / 2
    } else {
        1_usize << (usize::BITS - 1 - value.leading_zeros())
    }
}

fn largest_power_of_two_less_than_u64(value: u64) -> u64 {
    debug_assert!(value > 1);
    if value.is_power_of_two() {
        value / 2
    } else {
        1_u64 << (u64::BITS - 1 - value.leading_zeros())
    }
}

#[cfg(test)]
mod tests {
    use super::{audit_path, fold_inclusion_proof_untrusted, merkle_tree_hash, Hash};

    #[test]
    fn every_generated_proof_verifies() {
        let leaves: Vec<Hash> = (0_u8..17)
            .map(|value| {
                let mut leaf = [0_u8; 32];
                leaf[0] = value;
                leaf
            })
            .collect();
        let root = merkle_tree_hash(&leaves);
        for index in 0..leaves.len() {
            let proof = audit_path(&leaves, index).unwrap();
            assert!(fold_inclusion_proof_untrusted(
                &leaves[index],
                index as u64,
                leaves.len() as u64,
                &proof,
                &root
            ));
        }
    }
}
