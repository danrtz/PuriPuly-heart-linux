use std::collections::HashMap;

use crate::state::{OverlayPresentationCalibration, OverlayPresentationSnapshot};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum SpatialReanchorReason {
    InitialVisible,
    NewTurn,
    ModeEntered,
    PlacementCalibrationChanged,
}

impl SpatialReanchorReason {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::InitialVisible => "initial_visible",
            Self::NewTurn => "new_turn",
            Self::ModeEntered => "mode_entered",
            Self::PlacementCalibrationChanged => "placement_calibration_changed",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct PendingSpatialReanchor {
    pub(crate) reason: SpatialReanchorReason,
    pub(crate) requested_revision: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct SpatialDiagnostic(pub(crate) String);

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub(crate) struct SpatialReanchorPolicy {
    active: bool,
    seen_turn_ids: HashMap<String, Option<(String, u64, u64, u64)>>,
    pending_reanchor: Option<PendingSpatialReanchor>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct SpatialPolicyResult {
    pub(crate) diagnostics: Vec<SpatialDiagnostic>,
}

impl SpatialReanchorPolicy {
    pub(crate) fn from_initial_snapshot(
        snapshot: &OverlayPresentationSnapshot,
    ) -> (Self, SpatialPolicyResult) {
        if snapshot.calibration.anchor != "spatial_locked" {
            return (
                Self::default(),
                SpatialPolicyResult {
                    diagnostics: Vec::new(),
                },
            );
        }
        let drawable_turns = drawable_turn_ids(snapshot);
        let total_turns = drawable_turns.len();
        let seen_turn_ids = drawable_turns
            .into_iter()
            .take(64)
            .collect::<HashMap<_, _>>();
        let mut state = Self {
            active: true,
            seen_turn_ids,
            pending_reanchor: None,
        };
        let mut diagnostics = Vec::new();
        if total_turns > state.seen_turn_ids.len() {
            diagnostics.push(SpatialDiagnostic(format!(
                "spatial_turn_identity_capacity_reached retained={} rejected={}",
                state.seen_turn_ids.len(),
                total_turns - state.seen_turn_ids.len()
            )));
        }
        if !state.seen_turn_ids.is_empty() {
            state.request_reanchor(SpatialReanchorReason::InitialVisible, snapshot.revision);
        }
        (state, SpatialPolicyResult { diagnostics })
    }

    pub(crate) fn apply_snapshot_transition(
        &mut self,
        previous_calibration: &OverlayPresentationCalibration,
        snapshot: &OverlayPresentationSnapshot,
    ) -> SpatialPolicyResult {
        let mut diagnostics = Vec::new();
        let current_spatial = snapshot.calibration.anchor == "spatial_locked";
        match (self.active, current_spatial) {
            (false, false) => {}
            (false, true) => {
                self.active = true;
                let drawable_turns = drawable_turn_ids(snapshot);
                let total_turns = drawable_turns.len();
                self.seen_turn_ids = drawable_turns.into_iter().take(64).collect();
                if total_turns > self.seen_turn_ids.len() {
                    diagnostics.push(SpatialDiagnostic(format!(
                        "spatial_turn_identity_capacity_reached retained={} rejected={}",
                        self.seen_turn_ids.len(),
                        total_turns - self.seen_turn_ids.len()
                    )));
                }
                if !self.seen_turn_ids.is_empty() {
                    self.request_reanchor(SpatialReanchorReason::ModeEntered, snapshot.revision);
                }
            }
            (true, false) => {
                self.active = false;
                self.seen_turn_ids.clear();
                self.pending_reanchor = None;
            }
            (true, true) => {
                self.seen_turn_ids.retain(|block_id, semantic_identity| {
                    if snapshot
                        .blocks
                        .iter()
                        .any(|block| block.id == *block_id && is_drawable(block))
                    {
                        return true;
                    }
                    let Some((scope, generation, order, index)) = semantic_identity else {
                        return true;
                    };
                    !snapshot
                        .semantic_retirement_frontiers
                        .iter()
                        .any(|frontier| {
                            frontier.scope == *scope
                                && frontier.generation == *generation
                                && (*order, *index) <= (frontier.order, frontier.index)
                        })
                });
                let first_drawable =
                    self.seen_turn_ids.is_empty() && snapshot.blocks.iter().any(is_drawable);
                let mut unseen = 0usize;
                let mut admitted = 0usize;
                for block in snapshot.blocks.iter().filter(|block| is_drawable(block)) {
                    if let Some(cached_identity) = self.seen_turn_ids.get_mut(block.id.as_str()) {
                        if cached_identity.is_none() {
                            *cached_identity = semantic_identity(block);
                        }
                    } else {
                        unseen += 1;
                        if self.seen_turn_ids.len() < 64 {
                            self.seen_turn_ids
                                .insert(block.id.clone(), semantic_identity(block));
                            admitted += 1;
                        }
                    }
                }
                let has_new_turn = admitted > 0;
                if unseen > admitted {
                    diagnostics.push(SpatialDiagnostic(format!(
                        "spatial_turn_identity_capacity_reached retained={} rejected={}",
                        self.seen_turn_ids.len(),
                        unseen - admitted
                    )));
                }
                let placement_changed = previous_calibration.offset_x
                    != snapshot.calibration.offset_x
                    || previous_calibration.offset_y != snapshot.calibration.offset_y
                    || previous_calibration.distance != snapshot.calibration.distance;
                let reason = if placement_changed {
                    Some(SpatialReanchorReason::PlacementCalibrationChanged)
                } else if first_drawable {
                    Some(SpatialReanchorReason::InitialVisible)
                } else if has_new_turn {
                    Some(SpatialReanchorReason::NewTurn)
                } else {
                    None
                };
                if let Some(reason) = reason {
                    self.request_reanchor(reason, snapshot.revision);
                }
            }
        }
        SpatialPolicyResult { diagnostics }
    }

    fn request_reanchor(&mut self, reason: SpatialReanchorReason, revision: u64) {
        if self.pending_reanchor.is_some() {
            return;
        }
        self.pending_reanchor = Some(PendingSpatialReanchor {
            reason,
            requested_revision: revision,
        });
    }

    pub(crate) fn pending(&self) -> Option<PendingSpatialReanchor> {
        self.pending_reanchor
    }

    pub(crate) fn complete_pending(&mut self) -> Option<PendingSpatialReanchor> {
        self.pending_reanchor.take()
    }
}

fn is_drawable(block: &crate::state::OverlayPresentationBlock) -> bool {
    !block.primary_text.trim().is_empty()
        || (block.secondary_enabled && !block.secondary_text.trim().is_empty())
}

fn semantic_identity(
    block: &crate::state::OverlayPresentationBlock,
) -> Option<(String, u64, u64, u64)> {
    match (
        block.publication_scope.as_ref(),
        block.publication_generation,
        block.publication_order,
        block.publication_index,
    ) {
        (Some(scope), Some(generation), Some(order), Some(index)) => {
            Some((scope.clone(), generation, order, index))
        }
        _ => None,
    }
}

fn drawable_turn_ids(
    snapshot: &OverlayPresentationSnapshot,
) -> HashMap<String, Option<(String, u64, u64, u64)>> {
    snapshot
        .blocks
        .iter()
        .filter(|block| is_drawable(block))
        .map(|block| (block.id.clone(), semantic_identity(block)))
        .collect()
}
