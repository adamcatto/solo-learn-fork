# Copyright 2022 solo-learn development team.

# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the
# Software, and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies
# or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
# PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
# FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
# OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import argparse
from typing import Any, Dict, List, Sequence

import torch
import torch.nn as nn
from solo.losses.vicreg import vicreg_loss_func
from solo.methods.base import BaseMethod


class VICReg(BaseMethod):
    def __init__(
        self,
        proj_output_dim: int,
        proj_hidden_dim: int,
        sim_loss_weight: float,
        var_loss_weight: float,
        cov_loss_weight: float,
        **kwargs
    ):
        """Implements VICReg (https://arxiv.org/abs/2105.04906)

        Args:
            proj_output_dim (int): number of dimensions of the projected features.
            proj_hidden_dim (int): number of neurons in the hidden layers of the projector.
            sim_loss_weight (float): weight of the invariance term.
            var_loss_weight (float): weight of the variance term.
            cov_loss_weight (float): weight of the covariance term.
        """

        super().__init__(**kwargs)

        self.sim_loss_weight = sim_loss_weight
        self.var_loss_weight = var_loss_weight
        self.cov_loss_weight = cov_loss_weight

        # projector
        self.projector = nn.Sequential(
            nn.Linear(self.features_dim, proj_hidden_dim),
            nn.BatchNorm1d(proj_hidden_dim),
            nn.ReLU(),
            nn.Linear(proj_hidden_dim, proj_hidden_dim),
            nn.BatchNorm1d(proj_hidden_dim),
            nn.ReLU(),
            nn.Linear(proj_hidden_dim, proj_output_dim),
        )

    @staticmethod
    def add_model_specific_args(parent_parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        parent_parser = super(VICReg, VICReg).add_model_specific_args(parent_parser)
        parser = parent_parser.add_argument_group("vicreg")

        # projector
        parser.add_argument("--proj_output_dim", type=int, default=2048)
        parser.add_argument("--proj_hidden_dim", type=int, default=2048)

        # parameters
        parser.add_argument("--sim_loss_weight", default=25, type=float)
        parser.add_argument("--var_loss_weight", default=25, type=float)
        parser.add_argument("--cov_loss_weight", default=1.0, type=float)
        return parent_parser

    @property
    def learnable_params(self) -> List[dict]:
        """Adds projector parameters to the parent's learnable parameters.

        Returns:
            List[dict]: list of learnable parameters.
        """

        extra_learnable_params = [{"params": self.projector.parameters()}]
        return super().learnable_params + extra_learnable_params

    def forward(self, X: torch.Tensor) -> Dict[str, Any]:
        """Performs the forward pass of the backbone and the projector.

        Args:
            X (torch.Tensor): a batch of images in the tensor format.

        Returns:
            Dict[str, Any]: a dict containing the outputs of the parent and the projected features.
        """

        out = super().forward(X)
        z = self.projector(out["feats"])
        out.update({"z": z})
        return out

    def training_step(self, batch: Sequence[Any], batch_idx: int) -> torch.Tensor:
        """Training step for VICReg reusing BaseMethod training step.

        Args:
            batch (Sequence[Any]): a batch of data in the format of [img_indexes, [X], Y], where
                [X] is a list of size num_crops containing batches of images.
            batch_idx (int): index of the batch.

        Returns:
            torch.Tensor: total loss composed of VICReg loss and classification loss.
        """

        out = super().training_step(batch, batch_idx)
        class_loss = out["loss"]
        z1, z2 = out["z"]

        # ------- vicreg loss -------
        vicreg_loss = vicreg_loss_func(
            z1,
            z2,
            sim_loss_weight=self.sim_loss_weight,
            var_loss_weight=self.var_loss_weight,
            cov_loss_weight=self.cov_loss_weight,
        )

        self.log("train_vicreg_loss", vicreg_loss, on_epoch=True, sync_dist=True)

        return vicreg_loss + class_loss

    def validation_step(self, batch, batch_idx):
        out = super().validation_step(batch, batch_idx)
        class_loss = out["loss"]
        z1, z2 = out["z"]

        # ------- vicreg loss -------
        vicreg_loss = vicreg_loss_func(
            z1,
            z2,
            sim_loss_weight=self.sim_loss_weight,
            var_loss_weight=self.var_loss_weight,
            cov_loss_weight=self.cov_loss_weight,
        )

        self.log("val_loss", vicreg_loss, on_epoch=True, sync_dist=True)

        return vicreg_loss + class_loss
