"""An in-memory mail world + tools, for the worked demo and tests.

Three tools: ``read_inbox`` and ``read_contacts`` (READ — they introduce untrusted content, so
their results may flow into no WRITE), and ``send_email`` (WRITE). The declassification policy
allows a WRITE carrying tainted data only when the recipient is the trusted requesting user —
a deterministic predicate over a USER_QUERY value, never over tainted text.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from reasoning_kernel.schemas.capability import Capability, CapabilitySet, EffectLevel
from reasoning_kernel.schemas.policy import RunContext, VerifierVerdict
from reasoning_kernel.schemas.registry import ToolSpec
from reasoning_kernel.schemas.values import TaintedValue
from reasoning_kernel.tools.registry import ToolRegistry

# --- capabilities -----------------------------------------------------------------
CAP_MAIL_READ = Capability(name="mail.read")
CAP_CONTACTS_READ = Capability(name="contacts.read")
CAP_MAIL_SEND = Capability(name="mail.send")

DEMO_GRANT = CapabilitySet(granted=frozenset({CAP_MAIL_READ, CAP_CONTACTS_READ, CAP_MAIL_SEND}))


# --- tool I/O schemas -------------------------------------------------------------
class EmailMessage(BaseModel):
    sender: str
    subject: str
    body: str


class Contact(BaseModel):
    name: str
    email: str


class ReadInboxIn(BaseModel):
    pass


class ReadInboxOut(BaseModel):
    latest: EmailMessage


class ReadContactsIn(BaseModel):
    pass


class ReadContactsOut(BaseModel):
    contacts: list[Contact]


class SendEmailIn(BaseModel):
    to: str
    body: str


class SendEmailOut(BaseModel):
    ok: bool
    message_id: str


class EmailSummary(BaseModel):
    """Q-LLM output schema — data only, no actions."""

    text: str


# --- the mutable world ------------------------------------------------------------
@dataclass
class MailWorld:
    inbox: list[EmailMessage]
    contacts: list[Contact]
    sent: list[SendEmailIn] = field(default_factory=list)


def build_registry(world: MailWorld) -> ToolRegistry:
    """Register the three demo tools against ``world``. READ tools taint their output."""

    def read_inbox(_inp: BaseModel) -> BaseModel:
        return ReadInboxOut(latest=world.inbox[-1])

    def read_contacts(_inp: BaseModel) -> BaseModel:
        return ReadContactsOut(contacts=list(world.contacts))

    def send_email(inp: BaseModel) -> BaseModel:
        assert isinstance(inp, SendEmailIn)
        world.sent.append(inp)
        return SendEmailOut(ok=True, message_id=f"msg-{len(world.sent)}")

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="read_inbox",
            input_schema=ReadInboxIn,
            output_schema=ReadInboxOut,
            required_caps=frozenset({CAP_MAIL_READ}),
            effect_level=EffectLevel.READ,
            result_readers=frozenset(),  # untrusted content: may flow into no WRITE
        ),
        read_inbox,
    )
    registry.register(
        ToolSpec(
            name="read_contacts",
            input_schema=ReadContactsIn,
            output_schema=ReadContactsOut,
            required_caps=frozenset({CAP_CONTACTS_READ}),
            effect_level=EffectLevel.READ,
            result_readers=frozenset(),
        ),
        read_contacts,
    )
    registry.register(
        ToolSpec(
            name="send_email",
            input_schema=SendEmailIn,
            output_schema=SendEmailOut,
            required_caps=frozenset({CAP_MAIL_SEND}),
            effect_level=EffectLevel.WRITE,
        ),
        send_email,
    )
    return registry


Q_SCHEMAS: dict[str, type[BaseModel]] = {"EmailSummary": EmailSummary}


class RecipientIsUserPolicy:
    """Declassify a tainted WRITE only when the recipient is the trusted requesting user."""

    def may_declassify(
        self,
        tool: ToolSpec,
        named_args: dict[str, TaintedValue],
        ctx: RunContext,
    ) -> VerifierVerdict:
        if tool.name != "send_email":
            return VerifierVerdict(allowed=False, reason="no declassification rule for this tool")
        recipient = named_args.get("to")
        if recipient is None:
            return VerifierVerdict(allowed=False, reason="missing recipient")
        # Compare against the trusted user only; the recipient itself must be untainted.
        if (
            not recipient.label.is_tainted
            and isinstance(recipient.value, str)
            and recipient.value == ctx.user
        ):
            return VerifierVerdict(allowed=True, reason="recipient is the trusted requesting user")
        return VerifierVerdict(
            allowed=False,
            reason="recipient is not the trusted user — tainted data may not leave",
        )
