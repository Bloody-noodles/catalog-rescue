from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from api.auth import VerifiedIdentity
from database.models import AnalysisRun, Catalog, IdempotencyRecord, User


def resolve_user_for_write(session: Session, identity: VerifiedIdentity) -> User:
    """Resolve or create an OIDC user inside the caller's transaction."""
    dialect = session.get_bind().dialect.name
    values = {"issuer": identity.issuer, "subject": identity.subject}
    if identity.email:
        values["email"] = identity.email

    if dialect == "postgresql":
        statement = (
            postgresql_insert(User)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[User.issuer, User.subject])
            .returning(User.id)
        )
        session.execute(statement)
    elif dialect == "sqlite":
        statement = (
            sqlite_insert(User)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[User.issuer, User.subject])
            .returning(User.id)
        )
        session.execute(statement)
    else:
        user = session.scalar(
            select(User).where(
                User.issuer == identity.issuer,
                User.subject == identity.subject,
            )
        )
        if user is None:
            user = User(**values)
            session.add(user)
            session.flush()
        return user

    user = session.scalar(
        select(User).where(
            User.issuer == identity.issuer,
            User.subject == identity.subject,
        )
    )
    if user is None:
        raise RuntimeError("The authenticated user could not be resolved.")
    if identity.email and user.email != identity.email:
        user.email = identity.email
    return user


def get_existing_user_id(
    session: Session,
    identity: VerifiedIdentity,
) -> UUID | None:
    return session.scalar(
        select(User.id).where(
            User.issuer == identity.issuer,
            User.subject == identity.subject,
        )
    )


def persist_idempotency_record(
    session: Session,
    *,
    owner: User,
    catalog: Catalog,
    analysis: AnalysisRun,
    key: str,
    request_fingerprint: str,
) -> IdempotencyRecord:
    if catalog.owner_id != owner.id:
        raise ValueError("The idempotency owner must own the associated catalog.")
    if analysis.catalog_id != catalog.id:
        raise ValueError("The idempotency analysis must belong to the associated catalog.")

    record = IdempotencyRecord(
        owner_id=owner.id,
        key=key,
        request_fingerprint=request_fingerprint,
        analysis_id=analysis.id,
    )
    session.add(record)
    session.flush()
    return record
