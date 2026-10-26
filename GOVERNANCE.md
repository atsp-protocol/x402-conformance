# Governance

This is how I run x402-conformance. It states my position. A comment or a roadmap date is not a commitment. Binding work is a signed Proofline task.

## Maintainers

I maintain this repository: Ryan Gillespie, Optitransfer. I review proposals, and I merge to `main`.

Someone becomes a maintainer only when I say so in a signed decision and they are named in this section.

## Decisions

Proposals belong in issues and in Discussions. Work is binding only as a Proofline task signed by the owner key. I am the only person who signs with that key.

## Adding or changing a check

A check is admitted only when it meets the bar in [docs/ROADMAP.md](docs/ROADMAP.md#how-i-decide-what-goes-in) ("How I decide what goes in"). That bar applies to every proposal.

## Check ids

An id is never reused and never removed. A change of meaning gets a new id. A deprecated id stays in [docs/check-ids.json](docs/check-ids.json) with its original property text, and the deprecation is listed in [CHANGELOG.md](CHANGELOG.md).

`python3 tools/check_ids.py --since v1.6.0` writes the registry from the catalogue. `python3 tools/check_ids.py --check --since v1.6.0` fails when the registry is stale, when an id published at v1.6.0 is missing, or when that id's property changed without a deprecation entry.

## Neutrality

No implementation is treated differently. There is no paid tier. Results are never sold. The same disclosure rules apply to everyone.

The external run and the self-hosted run are two ways to execute the checks. Neither is a paid tier.

## Conflicts of interest

I am the licensor: Ryan Gillespie. Optitransfer is my company. I publish the results in the open. I do not sell them, and I do not take payment for a pass.

## Disclosure

Security reports follow [SECURITY.md](SECURITY.md). Those rules apply to every report, whoever sends it.

## Stewardship

I would move this project to a neutral home only by a signed decision. The licence would stay Apache-2.0, the check-id registry would come with it, and no implementation would be preferred as a condition of the move. I have not decided to move it.
