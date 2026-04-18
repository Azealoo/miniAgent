# Cluster Slurm Runbooks

## Goal

Help translate analysis intent into practical cluster execution steps.

## Common planning fields

- job name
- CPUs
- memory
- GPUs if needed
- wall time
- environment activation
- command entrypoint
- output and error logs

## Default planning advice

- Prefer conservative memory requests over unrealistically small ones.
- Use separate log files for stdout and stderr.
- Keep environment activation explicit.
- Save scripts to a reproducible path when the user wants to rerun the job.

## Do not assume

- partition or qos unless the user or environment specifies it
- GPU need for all analysis tasks
- that a script should be submitted immediately

## Useful output structure

- run plan summary
- resource assumptions
- command block
- draft sbatch script
