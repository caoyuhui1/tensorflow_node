#!/usr/bin/env python
# -*- coding: utf-8 -*-

from model import StackedAutoEncoder
from inputlayer import OpenCVInputLayer

import tensorflow as tf

import numpy as np
import model.utils as utils
from os.path import join as pjoin

#utils.start_tensorboard()

print "recording summaries to " + utils.get_summary_dir()

models = []

for _ in xrange(4):
    models.append(StackedAutoEncoder(
        dims=[100],
        activations=['linear'], 
        noise='gaussian', 
        epoch=[10],
        loss='rmse',
        lr=0.007,
        batch_size=1
    ))

### Initialize Enqueue thread:
inputlayer = OpenCVInputLayer()

inputlayer.registerCallback([00,00,16,16], models[0].fit_single)
inputlayer.registerCallback([16,00,16,16], models[1].fit_single)
inputlayer.registerCallback([00,16,16,16], models[2].fit_single)
inputlayer.registerCallback([16,16,16,16], models[3].fit_single)

inputlayer.feedVideo("data/hand.m4v", frames=20)

for model in models:
    model.write_activation_summary()
