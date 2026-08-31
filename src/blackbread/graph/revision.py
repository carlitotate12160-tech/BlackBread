from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from blackbread.ledger.hashing import canonical_json, canonical_timestamp, sha256_hex

ScopeKind = Literal["root_domain", "exact_host", "exact_address", "cloud_tenant"]


@dataclass(frozen=True, slots=True)
class ScopeRevision:
    node_id: str
    scope_kind: ScopeKind
    canonical_value: str
    manifest_hash: str
    valid_from: datetime
    valid_until: datetime
    source_sequence: int
    source_event_hash: str
    source_schema_name: Literal["engagement.attested"]
    source_schema_version: int
    predecessor_attestation_event_hash: str | None
    revision_id: str = field(init=False)

    def __post_init__(self) -> None:
        identity = [
            [self.node_id, self.scope_kind, self.canonical_value],
            [
                self.manifest_hash,
                canonical_timestamp(self.valid_from),
                canonical_timestamp(self.valid_until),
            ],
            [self.source_sequence, self.source_event_hash],
            [
                self.source_schema_name,
                self.source_schema_version,
                self.predecessor_attestation_event_hash,
            ],
        ]
        revision_id = sha256_hex(
            "blackbread.graph.scope-root.revision\x00" + canonical_json(identity)
        )
        object.__setattr__(self, "revision_id", revision_id)
