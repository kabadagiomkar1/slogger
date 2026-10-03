# Design interviews

For each decision, show the alternatives concretely before recommending one.
Use the same small example for both, explain what changes for the caller, and
separate shared requirements from the choice under discussion.

For example, source identity is required in either representation. The decision
is whether callers access it as `record["_id"]` or `result.origins[index]`.
Explain collisions, projection, navigation, and storage implications rather than
asking an abstract question about metadata placement.

Define unfamiliar terms before using them in a question. Testing-interface
approval means asking which library calls tests should exercise and what outcomes
they should verify. Do not ask users to approve internal test vocabulary.

When the user asks for clarification, explain the current decision without
advancing the interview. Carry accepted constraints forward instead of asking
for them again.
