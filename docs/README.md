# HeritageFlow engineering evidence

This directory contains the requirements-first design evidence for the LH6041
platform engineering project. The named customer is **Luoyang Heritage Cloud
Ltd.**, a fictional case-study SaaS operator. Guanlin, the Luoyang Ancient Tomb
Museum, and Wan'an Mountain are independent demonstration tenants; the project
does not claim that the real attractions share an operator or have agreed to a
deployment.

- `proposal.md`: problem, customer, user journey, and why-cloud argument.
- `non-functional-requirements.md`: measurable targets stated before cloud tests.
- `architecture.md`: system boundaries, cloud topology, and operational flow.
- `alicloud-roadmap.md`: incremental migration from the public preview to the
  managed Alibaba Cloud evaluation environment.
- `data-model.md`: DynamoDB keys, entities, access patterns, and invariants.
- `threat-model.md`: assets, trust boundaries, threats, and mitigations.
- `traceability.md`: requirement-to-implementation-to-evidence matrix.
- `adr/`: six architecture decision records.
- `diagrams/`: editable Mermaid sources and rendered SVG figures.

Targets marked **open** or **cloud evidence required** must not be presented as
achieved in the final paper until the corresponding experiment has been run.
