# MyScoutee CI/CD manual

[Download the PDF](MyScoutee_CICD_Manual_EN.pdf) - MSC-CI-001, document version 1.0.0, released 2026-10-26.

The manual explains feature/master/release branches, manual gates, project and
runner configuration, dependencies, registries, infrastructure and retention.
It also documents the included **GitHub Actions conversion**, kept inactive
under each repository's `config/ci/github-actions.yml` and not separately tested.
Existing GitHub workflows retain their prior behavior.

Regenerate from the CI repository root with Python, ReportLab and DejaVu fonts:

```sh
python3 guides/publication/manuals/build-guide.py
```

The editable generator and logo are versioned here. No frontend copy is made.
Detailed references: [CI development guides](../../development/ci/MSC-129-plan.md).
