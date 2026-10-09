# Experiment evidence

Store sanitized raw experiment output and the CSV files used to generate paper
figures in this directory. Every measured run must record its UTC timestamp,
Git commit, container image or task-definition revision, environment, region,
and relevant service configuration.

Never store API keys, bearer tokens, visitor references, validation codes,
Terraform state, account identifiers, or unredacted cloud logs here. Use
`results/.local/` for disposable output that should not be committed.
