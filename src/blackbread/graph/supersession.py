import re
from collections.abc import Collection
from dataclasses import dataclass, field

from blackbread.ledger.catalog import EngagementAttested, EngagementAttestedV2
from blackbread.ledger.event import AgentEvent

_HEX = re.compile(r"^[0-9a-f]{64}$")


class SupersessionError(RuntimeError):
    pass


def select_supersession_head(
    event_hashes: Collection[str], superseded_hashes: Collection[str]
) -> str:
    tails = set(event_hashes) - set(superseded_hashes)
    if len(tails) != 1:
        raise SupersessionError("attestation lineage lacks one structural head")
    return tails.pop()


@dataclass(slots=True)
class AttestationChain:
    _sequences: dict[str, int] = field(default_factory=dict)
    _superseded: set[str] = field(default_factory=set)

    @property
    def head_hash(self) -> str | None:
        if not self._sequences:
            return None
        return select_supersession_head(self._sequences.keys(), self._superseded)

    def admit(
        self,
        event: AgentEvent,
        payload: EngagementAttested | EngagementAttestedV2,
    ) -> str | None:
        self._validate_source(event)
        if isinstance(payload, EngagementAttestedV2):
            predecessor = self._admit_v2(event, payload)
        else:
            self._admit_v1()
            predecessor = None
        self._sequences[event.event_hash] = event.sequence
        if predecessor is not None:
            self._superseded.add(predecessor)
        return predecessor

    def _validate_source(self, event: AgentEvent) -> None:
        if event.sequence < 1 or _HEX.fullmatch(event.event_hash) is None:
            raise SupersessionError("attestation source is invalid")
        if event.event_hash in self._sequences:
            raise SupersessionError("attestation event hash is already admitted")

    def _admit_v1(self) -> None:
        if self._sequences:
            raise SupersessionError("second v1 attestation is forbidden")

    def _admit_v2(
        self,
        event: AgentEvent,
        payload: EngagementAttestedV2,
    ) -> str:
        predecessor = payload.supersedes_event_hash
        if predecessor == event.event_hash:
            raise SupersessionError("attestation supersession cycle is forbidden")
        if not self._sequences:
            raise SupersessionError("v2 attestation requires an existing attestation")
        if predecessor not in self._sequences:
            raise SupersessionError("supersession predecessor is not an admitted attestation")
        if predecessor != self.head_hash:
            raise SupersessionError("predecessor is not the current supersession head")
        if event.sequence <= self._sequences[predecessor]:
            raise SupersessionError("attestation source sequence regressed")
        return predecessor
