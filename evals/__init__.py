"""NAPCO Nucleus — evaluation harness.

Measures the requirement identifier (`agent.py --task verify_session`)
against labeled fixture cases. Lets you tell whether a prompt or model
change actually improved quality instead of guessing.

Usage:
    py -3 -m evals.run                     # run all cases in evals/cases/
    py -3 -m evals.run --case <name>       # run one case
    py -3 -m evals.run --no-replay         # skip the LLM identify step
                                           # and just score whatever sidecar
                                           # JSON is in data/requirements/
"""
