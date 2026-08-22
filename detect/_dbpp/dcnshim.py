"""The deformable convolution DB's ResNet wants, without their compiled ops.

DB's repo imports `assets.ops.dcn`, a CUDA extension you build yourself.
torchvision has had the same operator since 0.9 -- `deform_conv2d` takes the
offsets and the modulation mask directly -- so the shim is a module that holds
the weight and calls it.
"""
import math
import torch
import torch.nn as nn
from torchvision.ops import deform_conv2d

MODE = "stride"


class ModulatedDeformConv(nn.Module):
    def __init__(self, in_ch, out_ch, kernel_size=3, stride=1, padding=1,
                 dilation=1, deformable_groups=1, bias=False):
        super().__init__()
        self.stride, self.padding, self.dilation = stride, padding, dilation
        self.weight = nn.Parameter(
            torch.empty(out_ch, in_ch, kernel_size, kernel_size))
        self.bias = nn.Parameter(torch.zeros(out_ch)) if bias else None
        nn.init.kaiming_uniform_(self.weight, a=math.sqrt(5))

    def forward(self, x, offset, mask=None):
        # DB defines `conv2_offset` at stride 1 even when `conv2` strides, so
        # on the first block of layers 2-4 the offset map comes in at twice
        # the output size. One offset belongs to one OUTPUT position, so take
        # every stride-th: MODE decides which reading, because the CUDA op
        # they trained against is not obviously either.
        if self.stride != 1 and offset.shape[-1] != x.shape[-1] // self.stride:
            s = self.stride
            if MODE == "stride":
                offset = offset[:, :, ::s, ::s].contiguous()
                if mask is not None:
                    mask = mask[:, :, ::s, ::s].contiguous()
            else:
                oh, ow = x.shape[-2] // s, x.shape[-1] // s
                offset = offset[:, :, :oh, :ow].contiguous()
                if mask is not None:
                    mask = mask[:, :, :oh, :ow].contiguous()
        return deform_conv2d(x, offset, self.weight, self.bias,
                             stride=self.stride, padding=self.padding,
                             dilation=self.dilation, mask=mask)


DeformConv = ModulatedDeformConv
