---
library_name: peft
license: other
base_model: /root/rivermind-data/models/Qwen2.5-0.5B-Instruct/snapshots/master
tags:
- base_model:adapter:/root/rivermind-data/models/Qwen2.5-0.5B-Instruct/snapshots/master
- llama-factory
- lora
- transformers
pipeline_tag: text-generation
model-index:
- name: hak180_sft_lora
  results: []
---

<!-- This model card has been generated automatically according to the information the Trainer had access to. You
should probably proofread and complete it, then remove this comment. -->

# hak180_sft_lora

This model is a fine-tuned version of [/root/rivermind-data/models/Qwen2.5-0.5B-Instruct/snapshots/master](https://huggingface.co//root/rivermind-data/models/Qwen2.5-0.5B-Instruct/snapshots/master) on the hak180_sft dataset.

## Model description

More information needed

## Intended uses & limitations

More information needed

## Training and evaluation data

More information needed

## Training procedure

### Training hyperparameters

The following hyperparameters were used during training:
- learning_rate: 0.0001
- train_batch_size: 2
- eval_batch_size: 8
- seed: 42
- gradient_accumulation_steps: 4
- total_train_batch_size: 8
- optimizer: Use OptimizerNames.ADAMW_TORCH_FUSED with betas=(0.9,0.999) and epsilon=1e-08 and optimizer_args=No additional optimizer arguments
- lr_scheduler_type: cosine
- lr_scheduler_warmup_steps: 0.1
- num_epochs: 3.0

### Training results



### Framework versions

- PEFT 0.18.1
- Transformers 5.8.0
- Pytorch 2.11.0+cu128
- Datasets 4.0.0
- Tokenizers 0.22.2