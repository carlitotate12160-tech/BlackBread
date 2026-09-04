"""Canonical stability and sensitivity of the admission canonical parameter digest."""

from __future__ import annotations

from blackbread.conductor.contracts import ParameterEnvelope
from blackbread.ledger.hashing import HASH_HEX_LENGTH
from blackbread.policy.admission_contracts import parameter_digest
from tests.conductor._builders import make_proposal
from tests.policy._builders import manifest


def test_parameter_digest_is_lowercase_sha256_hex() -> None:
    digest = parameter_digest(make_proposal().parameter_envelope.canonical_parameters)
    assert len(digest) == HASH_HEX_LENGTH
    assert digest == digest.lower()
    int(digest, 16)


def test_parameter_digest_golden_vector() -> None:
    # Locks the domain separator and preimage shape. Regenerating this value requires an
    # intentional, versioned change to the digest domain, not an incidental refactor.
    canonical = '{"depth":1,"sources":["ct","dns"]}'
    assert parameter_digest(canonical) == (
        "b42993cb09384881d16ce42e0badb30b2534555f4e4fa491bc5a11969ad890a8"
    )
    assert make_proposal().parameter_envelope.canonical_parameters == canonical


def test_parameter_digest_is_stable_for_identical_parameters() -> None:
    left = parameter_digest(make_proposal().parameter_envelope.canonical_parameters)
    right = parameter_digest(make_proposal().parameter_envelope.canonical_parameters)
    assert left == right


def test_parameter_digest_changes_with_parameters() -> None:
    baseline = make_proposal()
    changed = make_proposal(
        parameter_envelope=ParameterEnvelope(
            input_schema_ref="PassiveAssetIntelligenceInput.v1",
            parameters={"depth": 2, "sources": ["ct"]},
        )
    )
    left = parameter_digest(baseline.parameter_envelope.canonical_parameters)
    right = parameter_digest(changed.parameter_envelope.canonical_parameters)
    assert left != right


def test_manifest_binds_the_canonical_parameter_digest() -> None:
    proposal = make_proposal()
    built = manifest(proposal)
    assert built.parameter_digest == parameter_digest(
        proposal.parameter_envelope.canonical_parameters
    )
