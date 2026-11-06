# Production container release

This workflow publishes a release record and signed, digest-addressed container images. It does **not** deploy to production. Production deployment, production HTTPS configuration, readiness checks, backup/restore rehearsal and rollback remain separate operational gates.

## Release flow

1. A maintainer runs **Production image release** manually on `main` and supplies a new `vMAJOR.MINOR.PATCH` version. The workflow rejects runs from any branch or actor other than `MavroneBamboo`.
2. It requires a successful `push` CI run for the exact `main` commit. CI includes the staging deployment and `/health/ready` check, so an offline or failed staging runner prevents a release candidate.
3. BuildKit builds the application, reverse proxy and database-maintenance images from that exact commit. It publishes unique candidate tags with build provenance and SBOM metadata, then Trivy scans each digest. Fixable CRITICAL or HIGH vulnerabilities fail the workflow.
4. The workflow records the three immutable image digests, exports CycloneDX SBOMs, and checksums the release evidence.
5. The final job references the `production` environment. After its environment rules permit the job to proceed, Cosign uses GitHub OIDC to sign each exact digest and attest the corresponding CycloneDX SBOM. The job verifies all six signatures/attestations before creating a GitHub Release with the manifest, checksums and SBOMs. It does not rebuild or retag the images.

BuildKit provenance and SBOMs are attached at image build time; Cosign adds separately verifiable signatures and CycloneDX attestations. See [Docker Build attestations](https://docs.docker.com/build/metadata/attestations/) and [Sigstore container signing](https://docs.sigstore.dev/cosign/signing/signing_with_containers/).

## Repository setup

Before using the workflow:

- Keep the repository private and GHCR packages private. Ensure the repository `GITHUB_TOKEN` can create and write the three packages. Limit package read access to deployment operators and hosts that need the images.
- Create a GitHub Actions environment named `production`, restricted to the `main` branch. Configure required reviewers and prevent self-review when the repository plan supports those environment rules. GitHub currently restricts required-reviewer protection rules for private repositories to Enterprise plans; the workflow also restricts its dispatch actor to `MavroneBamboo` and checks that its source is `main`.
- Require pull-request review and passing CI for `main`. The release workflow itself must be reviewed through the same repository process before it is enabled.
- Protect `v*` release tags and releases against unauthorized updates/deletion, while allowing the intended release process to create a new tag. Do not create the version tag before running the workflow; the workflow checks that the version is unused and creates the release tag only after image signing succeeds.
- Ensure the release runner can reach GitHub, GHCR, Sigstore's signing and transparency services, and Trivy vulnerability feeds. No signing private key or application secret is stored in the repository.

No release version, package publication or production deployment is triggered by pull-request CI. Candidate images are pushed only after a maintainer manually starts the workflow and the exact `main` commit has passed CI and staging.

## Run and verify

From GitHub, open **Actions → Production image release → Run workflow**, select `main`, enter a new version such as `v1.0.0`, and start it as `MavroneBamboo`. Review candidate scan output and the `production` environment deployment record. The final summary lists exact `ghcr.io/...@sha256:...` references.

For an image listed in `release-manifest.json`, an operator can independently verify its signature and SBOM attestation with Cosign:

```sh
cosign verify \
  --certificate-identity 'https://github.com/MavroneBamboo/SPS-Student-Dashboard/.github/workflows/production-release.yml@refs/heads/main' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  ghcr.io/mavronebamboo/IMAGE@sha256:DIGEST

cosign verify-attestation --type cyclonedx \
  --certificate-identity 'https://github.com/MavroneBamboo/SPS-Student-Dashboard/.github/workflows/production-release.yml@refs/heads/main' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  ghcr.io/mavronebamboo/IMAGE@sha256:DIGEST
```

The image name and digest must come from the release manifest. Do not deploy a mutable tag in place of the digest. An air-gapped production host will need an approved process to import the image and its verification material; the current workflow does not solve offline transfer or key/trust-root distribution.

## Current limitations

- The production environment's required-reviewer enforcement depends on GitHub plan and repository visibility. For this private repository, configure and verify that protection before claiming a human approval pause; on plans without private-repository required reviewers, the `MavroneBamboo` dispatch-actor guard is the workflow's release-operator restriction.
- Release builds are Linux `amd64` only, matching the current staging/production host target.
- Trivy ignores unfixed vulnerabilities; a separate documented risk exception process is still needed for an unavoidable finding.
- This workflow publishes and verifies containers; it does not deploy, migrate a production database, seed production data, run production smoke tests, or perform rollback.
