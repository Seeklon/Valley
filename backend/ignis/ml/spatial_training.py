"""Training-only objectives for sparse, observed FDS gas fields.

The production inference contract and historical checkpoints are unchanged.
Active and background errors are normalized separately, per variable/frame,
so adding unburned room cells cannot dilute the gradient of a measured hot spot.
"""

from __future__ import annotations

import torch
from torch.nn import functional as F

LOSS_VERSION = "observed-region-balanced-smoothl1-1"
LOCALIZATION_VERSION = "historical-regression-soft-tversky-1"


def region_balanced_loss(prediction, target, mask, active):
    """Return one loss per frame, with equal present regions and channels.

    Inputs are [batch, field, ...]. Missing values never act as zero labels.
    `active` is determined from *training targets* at fixed physical thresholds.
    Background errors remain in the objective to penalize false smoke/heat.
    A channel with only one observed region contributes that region's mean.
    """
    if prediction.shape != target.shape or mask.shape != target.shape or active.shape != target.shape:
        raise ValueError("Field targets, predictions and region masks must share their shape")
    if target.ndim < 3:
        raise ValueError("Expected batch, channel and spatial dimensions")
    mask, active = mask.bool(), active.bool() & mask.bool()
    safe = torch.where(mask, target, torch.zeros_like(target))
    errors = F.smooth_l1_loss(prediction, safe, reduction="none")
    dimensions = tuple(range(2, errors.ndim))
    regions, present = [], []
    for selected in (active, mask & ~active):
        count = selected.sum(dim=dimensions)
        numerator = torch.where(selected, errors, torch.zeros_like(errors)).sum(dim=dimensions)
        regions.append(numerator / count.clamp_min(1))
        present.append(count > 0)
    region_count = present[0].to(errors.dtype) + present[1].to(errors.dtype)
    channel_loss = (regions[0] + regions[1]) / region_count.clamp_min(1)
    channel_count = (region_count > 0).sum(dim=1)
    if torch.any(channel_count == 0).item():
        raise ValueError("Every training frame requires observed targets")
    return channel_loss.sum(dim=1) / channel_count


def support_loss(prediction, mask, active):
    """Soft support at fixed diagnostic thresholds, not a calibrated probability.

    Tversky weights FP=.7, FN=.3; empty positive regions use BCE only.
    Thresholds in asinh space are asinh(5/20) and asinh(1e-7/1e-6).
    Tau=threshold/8 keeps the ambient pseudo-probability small on sparse grids.
    No parameter is fitted on validation or test.
    """
    if prediction.shape != mask.shape or mask.shape != active.shape or prediction.shape[1] != 2:
        raise ValueError("Support objective requires two equally shaped gas fields and masks")
    mask, active = mask.bool(), active.bool() & mask.bool()
    dimensions = tuple(range(2, prediction.ndim))
    thresholds = torch.asinh(prediction.new_tensor([0.25, 0.1])).reshape(1, 2, *([1] * (prediction.ndim - 2)))
    logits = (prediction - thresholds) / (thresholds / 8)
    probabilities = torch.sigmoid(logits)
    y = active.to(prediction.dtype)
    observed = mask.to(prediction.dtype)
    tp = (probabilities * y).sum(dim=dimensions)
    fp = (probabilities * (observed - y)).sum(dim=dimensions)
    fn = ((1 - probabilities) * y).sum(dim=dimensions)
    positive = active.sum(dim=dimensions) > 0
    tversky = torch.where(positive, 1 - (tp + 1e-6) / (tp + 0.7 * fp + 0.3 * fn + 1e-6), 0.0)
    bce = F.binary_cross_entropy_with_logits(logits, y, reduction="none")
    count = mask.sum(dim=dimensions)
    bce = torch.where(mask, bce, 0.0).sum(dim=dimensions) / count.clamp_min(1)
    present = count > 0
    if torch.any(present.sum(dim=1) == 0).item():
        raise ValueError("Every training frame requires observed targets")
    return ((tversky + 0.1 * bce) * present).sum(dim=1) / present.sum(dim=1)
