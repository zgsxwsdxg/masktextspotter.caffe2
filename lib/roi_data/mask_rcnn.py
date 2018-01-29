# Copyright (c) 2017-present, Facebook, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
##############################################################################

"""Construct minibatches for Mask R-CNN training. Handles the minibatch blobs
that are specific to Mask R-CNN. Other blobs that are generic to RPN or
Fast/er R-CNN are handled by their respecitive roi_data modules.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import logging
import numpy as np

from core.config import cfg
import utils.blob as blob_utils
import utils.boxes as box_utils
import utils.segms as segm_utils
from utils.char_mask import generate_char_maps, generate_char_maps_and_polygon_map

from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

DEBUG = False

def add_mask_rcnn_blobs(blobs, sampled_boxes, roidb, im_scale, batch_idx):
    """Add Mask R-CNN specific blobs to the input blob dictionary."""
    # Prepare the mask targets by associating one gt mask to each training roi
    # that has a fg (non-bg) class label.
    M = cfg.MRCNN.RESOLUTION
    polys_gt_inds = np.where(
        (roidb['gt_classes'] > 0) & (roidb['is_crowd'] == 0)
    )[0]
    polys_gt = [roidb['segms'][i] for i in polys_gt_inds]
    boxes_from_polys = segm_utils.polys_to_boxes(polys_gt)
    fg_inds = np.where(blobs['labels_int32'] > 0)[0]
    roi_has_mask = blobs['labels_int32'].copy()
    roi_has_mask[roi_has_mask > 0] = 1

    if fg_inds.shape[0] > 0:
        # Class labels for the foreground rois
        mask_class_labels = blobs['labels_int32'][fg_inds]
        masks = blob_utils.zeros((fg_inds.shape[0], M**2), int32=True)

        # Find overlap between all foreground rois and the bounding boxes
        # enclosing each segmentation
        rois_fg = sampled_boxes[fg_inds]
        overlaps_bbfg_bbpolys = box_utils.bbox_overlaps(
            rois_fg.astype(np.float32, copy=False),
            boxes_from_polys.astype(np.float32, copy=False)
        )
        # Map from each fg rois to the index of the mask with highest overlap
        # (measured by bbox overlap)
        fg_polys_inds = np.argmax(overlaps_bbfg_bbpolys, axis=1)

        # add fg targets
        for i in range(rois_fg.shape[0]):
            fg_polys_ind = fg_polys_inds[i]
            poly_gt = polys_gt[fg_polys_ind]
            roi_fg = rois_fg[i]
            # Rasterize the portion of the polygon mask within the given fg roi
            # to an M x M binary image
            mask = segm_utils.polys_to_mask_wrt_box(poly_gt, roi_fg, M)
            mask = np.array(mask > 0, dtype=np.int32)  # Ensure it's binary
            masks[i, :] = np.reshape(mask, M**2)
    else:  # If there are no fg masks (it does happen)
        # The network cannot handle empty blobs, so we must provide a mask
        # We simply take the first bg roi, given it an all -1's mask (ignore
        # label), and label it with class zero (bg).
        bg_inds = np.where(blobs['labels_int32'] == 0)[0]
        # rois_fg is actually one background roi, but that's ok because ...
        rois_fg = sampled_boxes[bg_inds[0]].reshape((1, -1))
        # We give it an -1's blob (ignore label)
        masks = -blob_utils.ones((1, M**2), int32=True)
        # We label it with class = 0 (background)
        mask_class_labels = blob_utils.zeros((1, ))
        # Mark that the first roi has a mask
        roi_has_mask[0] = 1

    if cfg.MRCNN.CLS_SPECIFIC_MASK:
        masks = _expand_to_class_specific_mask_targets(masks, mask_class_labels)

    # Scale rois_fg and format as (batch_idx, x1, y1, x2, y2)
    rois_fg *= im_scale
    repeated_batch_idx = batch_idx * blob_utils.ones((rois_fg.shape[0], 1))
    rois_fg = np.hstack((repeated_batch_idx, rois_fg))

    # Update blobs dict with Mask R-CNN blobs
    blobs['mask_rois'] = rois_fg
    blobs['roi_has_mask_int32'] = roi_has_mask
    blobs['masks_int32'] = masks

def add_charmask_rcnn_blobs(blobs, sampled_boxes, gt_boxes, gt_inds, roidb, im_scale, batch_idx):
    """Add Mask R-CNN specific blobs to the input blob dictionary."""
    # Prepare the mask targets by associating one gt mask to each training roi
    # that has a fg (non-bg) class label.
    is_e2e = cfg.MRCNN.IS_E2E
    M_HEIGHT = cfg.MRCNN.RESOLUTION_H
    M_WIDTH = cfg.MRCNN.RESOLUTION_W
    mask_rois_per_this_image = cfg.MRCNN.MASK_BATCH_SIZE_PER_IM
    polys_gt_inds = np.where(
        (roidb['gt_classes'] > 0) & (roidb['is_crowd'] == 0)
    )[0]
    polys_gt = [roidb['segms'][i] for i in polys_gt_inds]
    chars_gts = roidb['charboxes']
    boxes_from_polys = segm_utils.polys_to_boxes(polys_gt)
    if DEBUG:
        img_path = roidb['image']
        img = Image.open(img_path)

    if is_e2e:
        fg_inds = np.where(blobs['labels_int32'] > 0)[0]
        if fg_inds.size > 0:
            fg_inds = npr.choice(
                fg_inds, size=mask_rois_per_this_image, replace=False
            )
        roi_has_mask = np.ones((fg_inds.shape[0], ), dtype=np.int32)
        # roi_has_mask = blobs['labels_int32'].copy()
        # roi_has_mask[roi_has_mask > 0] = 1

        if fg_inds.shape[0] > 0:
            # Class labels for the foreground rois
            mask_class_labels = blobs['labels_int32'][fg_inds]
            masks = blob_utils.zeros((fg_inds.shape[0], 2, M_HEIGHT*M_WIDTH), int32=True)
            # mask_weights = blob_utils.zeros((fg_inds.shape[0], 2, M_HEIGHT*M_WIDTH), int32=True)

            # Find overlap between all foreground rois and the bounding boxes
            # enclosing each segmentation
            rois_fg = sampled_boxes[fg_inds]
            overlaps_bbfg_bbpolys = box_utils.bbox_overlaps(
                rois_fg.astype(np.float32, copy=False),
                boxes_from_polys.astype(np.float32, copy=False)
            )
            # Map from each fg rois to the index of the mask with highest overlap
            # (measured by bbox overlap)
            fg_polys_inds = np.argmax(overlaps_bbfg_bbpolys, axis=1)

            # add fg targets
            for i in range(rois_fg.shape[0]):
                fg_polys_ind = fg_polys_inds[i]
                poly_gt = polys_gt[fg_polys_ind]
                indexes_rec_rois_gt_chars = np.where(chars_gts[:, 9] == fg_polys_ind)
                chars_gt = chars_gts[indexes_rec_rois_gt_chars, :9]
                roi_fg = rois_fg[i]
                # Rasterize the portion of the polygon mask within the given fg roi
                # to an M_HEIGHT x M_WIDTH binary image
                mask = segm_utils.polys_to_mask_wrt_box_rec(chars_gt, poly_gt, roi_fg, M_HEIGHT, M_WIDTH)
                mask = np.array(mask, dtype=np.int32)  # Ensure it's binary
                # mask_weight = np.array(mask_weight, dtype=np.int32)  # Ensure it's binary
                masks[i, 0, :] = np.reshape(mask[0,:,:], M_HEIGHT*M_WIDTH)
                masks[i, 1, :] = np.reshape(mask[1,:,:], M_HEIGHT*M_WIDTH)
                # mask_weights[i, 0, :] = np.reshape(mask_weight[0,:,:], M_HEIGHT*M_WIDTH)
                # mask_weights[i, 1, :] = np.reshape(mask_weight[1,:,:], M_HEIGHT*M_WIDTH)
        else:  # If there are no fg masks (it does happen)
            # The network cannot handle empty blobs, so we must provide a mask
            # We simply take the first bg roi, given it an all -1's mask (ignore
            # label), and label it with class zero (bg).
            bg_inds = np.where(blobs['labels_int32'] == 0)[0]
            # rois_fg is actually one background roi, but that's ok because ...
            rois_fg = sampled_boxes[bg_inds[0]].reshape((1, -1))
            # We give it an -1's blob (ignore label)
            masks = -blob_utils.ones((1, 2, M_HEIGHT*M_WIDTH), int32=True)
            mask_weights = -blob_utils.ones((1, 2, M_HEIGHT*M_WIDTH), int32=True)
            # We label it with class = 0 (background)
            mask_class_labels = blob_utils.zeros((1, ))
            # Mark that the first roi has a mask
            roi_has_mask[0] = 1
    else:
        fg_inds = gt_inds
        roi_has_mask = np.ones((fg_inds.shape[0], ), dtype=np.int32)

        if fg_inds.shape[0] > 0:
            # Class labels for the foreground rois
            mask_class_labels = np.ones((fg_inds.shape[0], ), dtype=np.int32)
            masks = blob_utils.zeros((fg_inds.shape[0], 2, M_HEIGHT*M_WIDTH), int32=True)
            # mask_weights = blob_utils.zeros((fg_inds.shape[0], 2, M_HEIGHT*M_WIDTH), int32=True)

            rois_fg = gt_boxes
            # print(gt_boxes.shape[0])
            # add fg targets
            for i in range(rois_fg.shape[0]):
                fg_polys_ind = fg_inds[i]
                poly_gt = polys_gt[fg_polys_ind]
                indexes_rec_rois_gt_chars = np.where(chars_gts[:, 9] == fg_polys_ind)
                chars_gt = chars_gts[indexes_rec_rois_gt_chars, :9]
                roi_fg = rois_fg[i]
                # Rasterize the portion of the polygon mask within the given fg roi
                # to an M_HEIGHT x M_WIDTH binary image
                mask = segm_utils.polys_to_mask_wrt_box_rec(chars_gt, poly_gt, roi_fg, M_HEIGHT, M_WIDTH)
                if DEBUG:
                    draw = ImageDraw.Draw(img)
                    draw.rectangle([(roi_fg[0],roi_fg[1]), (roi_fg[2],roi_fg[3])])
                    img.save('./tests/image.jpg')
                    print(chars_gt)
                    _visu_global_map(mask[0,:,:].copy(), './tests/proposals_visu_global.jpg')
                    _visu_char_map(mask[1,:,:].copy(), './tests/proposals_visu_char.jpg')
                    raw_input()
                mask = np.array(mask, dtype=np.int32)  # Ensure it's binary
                # mask_weight = np.array(mask_weight, dtype=np.int32)  # Ensure it's binary
                masks[i, 0, :] = np.reshape(mask[0,:,:], M_HEIGHT*M_WIDTH)
                masks[i, 1, :] = np.reshape(mask[1,:,:], M_HEIGHT*M_WIDTH)
                # mask_weights[i, 0, :] = np.reshape(mask_weight[0,:,:], M_HEIGHT*M_WIDTH)
                # mask_weights[i, 1, :] = np.reshape(mask_weight[1,:,:], M_HEIGHT*M_WIDTH)
        else:  # If there are no fg masks (it does happen)
            # The network cannot handle empty blobs, so we must provide a mask
            # We simply take the first bg roi, given it an all -1's mask (ignore
            # label), and label it with class zero (bg).
            bg_inds = np.where(blobs['labels_int32'] == 0)[0]
            # rois_fg is actually one background roi, but that's ok because ...
            rois_fg = sampled_boxes[bg_inds[0]].reshape((1, -1))
            # We give it an -1's blob (ignore label)
            masks = -blob_utils.ones((1, 2, M_HEIGHT*M_WIDTH), int32=True)
            mask_weights = -blob_utils.ones((1, 2, M_HEIGHT*M_WIDTH), int32=True)
            # We label it with class = 0 (background)
            mask_class_labels = blob_utils.zeros((1, ))
            # Mark that the first roi has a mask
            roi_has_mask[0] = 1


    # Scale rois_fg and format as (batch_idx, x1, y1, x2, y2)
    rois_fg *= im_scale
    repeated_batch_idx = batch_idx * blob_utils.ones((rois_fg.shape[0], 1))
    rois_fg = np.hstack((repeated_batch_idx, rois_fg))

    # Update blobs dict with Mask R-CNN blobs
    blobs['mask_rois'] = rois_fg
    blobs['roi_has_mask_int32'] = roi_has_mask
    blobs['masks_global_int32'] = masks[:, 0, :]
    blobs['masks_char_int32'] = masks[:, 1, :].reshape((-1, M_HEIGHT, M_WIDTH))



def _expand_to_class_specific_mask_targets(masks, mask_class_labels):
    """Expand masks from shape (#masks, M ** 2) to (#masks, #classes * M ** 2)
    to encode class specific mask targets.
    """
    assert masks.shape[0] == mask_class_labels.shape[0]
    M = cfg.MRCNN.RESOLUTION

    # Target values of -1 are "don't care" / ignore labels
    mask_targets = -blob_utils.ones(
        (masks.shape[0], cfg.MODEL.NUM_CLASSES * M**2), int32=True
    )

    for i in range(masks.shape[0]):
        cls = int(mask_class_labels[i])
        start = M**2 * cls
        end = start + M**2
        # Ignore background instance
        # (only happens when there is no fg samples in an image)
        if cls > 0:
            mask_targets[i, start:end] = masks[i, :]

    return mask_targets

def _visu_global_map(mask, save_path):
    mask = mask*225
    mask = mask.astype('uint8')
    im = Image.fromarray(mask)
    im.save(save_path)

def _visu_char_map(char_mask, save_path):
    char_mask = char_mask*5
    char_mask = char_mask.astype('uint8')
    im = Image.fromarray(char_mask)
    im.save(save_path)