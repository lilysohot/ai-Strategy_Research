"""API route package for the投研 Agent web platform.

M1 ships only the run lifecycle (submit / SSE events / stop). Auth, sessions,
model configs, artifacts and usage land in M2/M3. Routes are deliberately
unguarded at M1 so the chain can be exercised end-to-end without a user account.
"""
